"""Build a pre-analysis context packet without prior-session judgment leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from runtime.state_store import LOGIC_FILES


ROOT = Path(__file__).resolve().parents[1]
DATE_HEADING = re.compile(r"^##\s+20\d{2}-\d{2}-\d{2}")
PAGE_ID = re.compile(
    r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b",
    re.IGNORECASE,
)
MEMORY_REF = re.compile(r"`?(memory/[A-Za-z0-9_.\-/]+\.md)`?")
PROHIBITED_PRE_ANALYSIS_REFS = {"memory/MEMORY.md"}


def authoritative_runtime_files(root: Path = ROOT) -> list[str]:
    files = list(LOGIC_FILES.values())
    missing = [relative for relative in files if not (root / relative).is_file()]
    if missing:
        raise ValueError(
            "missing authoritative runtime files: " + ", ".join(sorted(missing))
        )
    reference_sources = [
        ".claude/skills/daily-report/SKILL.md",
        "sessions/日报SOP.md",
        "AGENTS.md",
        "CLAUDE.md",
    ]
    refs: set[str] = set()
    for relative in reference_sources:
        path = root / relative
        if not path.is_file():
            continue
        refs.update(MEMORY_REF.findall(path.read_text(encoding="utf-8")))
    checked_refs = refs - PROHIBITED_PRE_ANALYSIS_REFS
    missing_refs = sorted(ref for ref in checked_refs if not (root / ref).is_file())
    if missing_refs:
        raise ValueError(
            "missing referenced memory files: " + ", ".join(missing_refs)
        )
    unversioned_refs = sorted(ref for ref in checked_refs if ref not in files)
    if unversioned_refs:
        raise ValueError(
            "referenced memory files are not in LOGIC_FILES: "
            + ", ".join(unversioned_refs)
        )
    return files


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def latest_context_block(text: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if DATE_HEADING.match(line)), None)
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if DATE_HEADING.match(lines[i]):
            end = i
            break
    block = "\n".join(lines[start:end]).strip()
    return block


def operational_status(block: str) -> dict:
    """Extract delivery continuity only; never copy analysis or decisions."""
    final_lines = [
        line
        for line in block.splitlines()
        if "最终唯一存活页" in line or "最终存活页" in line
    ]
    final_text = "\n".join(final_lines)
    return {
        "final_page_ids": sorted(set(PAGE_ID.findall(final_text))),
        "published": bool(final_lines),
        "frozen_verifier_pass": any(
            "冻结" in line and "PASS" in line for line in final_lines
        ),
        "word_visual_qa_pass": any(
            "Word" in line
            and (
                "视觉" in line
                or "逐页检查" in line
                or "逐页确认" in line
            )
            and "未宣称" not in line
            for line in block.splitlines()
        ),
    }


def build_context_pack(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> tuple[dict, Path]:
    context_path = root / "sessions" / "context_log.md"
    text = context_path.read_text(encoding="utf-8")
    latest = latest_context_block(text)
    payload = {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "slot": slot,
        "source": str(context_path.relative_to(root)).replace("\\", "/"),
        "source_sha256": sha256_text(text),
        "latest_block_sha256": sha256_text(latest),
        "operational_status": operational_status(latest),
        "authoritative_runtime_files": authoritative_runtime_files(root),
        "analysis_policy": {
            "reasoning_effort": "max",
            "max_reasoning_confirmation_required": True,
            "use_highest_available_model": True,
            "full_analysis_recompute": True,
            "reuse_prior_features_scores_or_decisions": False,
            "prior_decision_access": "post_analysis_lock_only",
            "insufficient_reasoning_resources": "halt",
        },
        "read_policy": {
            "load_full_context_log": False,
            "load_prior_decision_text": False,
            "load_all_authoritative_methodology": True,
            "load_complete_resolved_five_source_evidence": True,
        },
    }

    target = root / "runtime_state" / trading_date / f"context_{slot}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return payload, target


def ensure_context_pack(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> tuple[dict, Path, bool]:
    """Reuse an unchanged pre-analysis packet instead of rebuilding it."""
    target = root / "runtime_state" / trading_date / f"context_{slot}.json"
    context_path = root / "sessions" / "context_log.md"
    if target.is_file() and context_path.is_file():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = None
        if (
            isinstance(payload, dict)
            and payload.get("trading_date") == trading_date
            and payload.get("slot") == slot
            and payload.get("source_sha256")
            == sha256_text(context_path.read_text(encoding="utf-8"))
        ):
            return payload, target, True
    payload, target = build_context_pack(trading_date, slot, root=root)
    return payload, target, False


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a minimal daily-report context packet")
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    args = parser.parse_args()
    payload, target = build_context_pack(args.date, args.slot)
    print(
        json.dumps(
            {
                "path": str(target),
                "operational_status": payload["operational_status"],
                "source_sha256": payload["source_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
