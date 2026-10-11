"""Build a pre-analysis context packet without prior-session judgment leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.prelock_read_policy import prelock_policy_manifest
from runtime.state_store import LOGIC_FILES


DATE_HEADING = re.compile(r"^##\s+20\d{2}-\d{2}-\d{2}")
PAGE_ID = re.compile(
    r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b",
    re.IGNORECASE,
)
MEMORY_REF = re.compile(r"`?(memory/[A-Za-z0-9_.\-/]+\.md)`?")
PROHIBITED_PRE_ANALYSIS_REFS = {"memory/MEMORY.md"}
MANDATORY_GUARDRAIL_NAMES = (
    "daily_runtime_contract",
    "automation_memory_policy",
    "token_policy",
    "memory_independent_report_no_user_reference",
    "memory_precise_numbers_no_fuzzy",
    "memory_stability_contract",
    "memory_report_evidence_time_lock",
    "golden_reasoning",
)
ALWAYS_READ_BYTE_BUDGET = 40 * 1024
AUTHORITY_READ_PLAN = {
    "always_read": MANDATORY_GUARDRAIL_NAMES,
    "workflow_entry": (
        "daily_sop",
    ),
    "source_validation": (
        "blockbeats_rules",
        "blockbeats_collector",
        "memory_blockbeats_important_only",
        "memory_browser_capture_toolset",
        "memory_five_sources_complete_or_halt",
    ),
    "analysis_orderflow": (
        "scoring_system",
        "orderflow",
        "orderflow_scoring",
    ),
    "analysis_chart_winrate": (
        "chart",
        "chart_scoring",
        "winrate",
        "thresholds",
        "trading_constitution",
        "maker_principles",
        "cannot_do",
    ),
    "analysis_agents": (
        "reasoning_depth",
        "scoring_contract",
    ),
    "risk_and_execution": (
        "risk",
        "entry_exit",
        "floating_defense",
        "maker_defense_memory",
        "leverage",
        "position_management",
        "state_gate",
    ),
    "render_publish_post_lock": (
        "memory_report_chinese_only_narrative",
        "memory_notion_publish_checklist",
        "memory_basemian_news_cards",
        "memory_push_report_to_ai_agent_plan",
        "memory_report_template_alignment",
        "review_principles",
        "execution_philosophy",
    ),
}


def authoritative_runtime_files(root: Path = ROOT) -> list[str]:
    files = list(LOGIC_FILES.values())
    missing = [relative for relative in files if not (root / relative).is_file()]
    if missing:
        raise ValueError(
            "missing authoritative runtime files: " + ", ".join(sorted(missing))
        )
    reference_sources = [
        ".agents/skills/daily-report/SKILL.md",
        "sessions/日报SOP.md",
        "AGENTS.md",
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authority_manifest(root: Path = ROOT) -> list[dict]:
    """Return content hashes for all runtime authority files.

    The context packet may be reused only while both the ledger hash and this
    manifest are unchanged. This prevents stale packets from carrying an old
    authority list after SOP/skill/memory edits.
    """
    authoritative_runtime_files(root)
    records = []
    for name, relative in LOGIC_FILES.items():
        path = root / relative
        records.append(
            {
                "name": name,
                "path": relative.replace("\\", "/"),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return records


def authority_sha256(manifest: list[dict]) -> str:
    return sha256_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def authority_read_plan() -> dict[str, list[str]]:
    plan = {}
    for phase, names in AUTHORITY_READ_PLAN.items():
        plan[phase] = [LOGIC_FILES[name].replace("\\", "/") for name in names]
    return plan


def authority_read_budget(root: Path = ROOT) -> dict:
    paths = authority_read_plan()["always_read"]
    records = [
        {"path": relative, "bytes": (root / relative).stat().st_size}
        for relative in paths
    ]
    total = sum(item["bytes"] for item in records)
    if total > ALWAYS_READ_BYTE_BUDGET:
        raise ValueError(
            f"always-read authority exceeds {ALWAYS_READ_BYTE_BUDGET} bytes: {total}"
        )
    return {"budget_bytes": ALWAYS_READ_BYTE_BUDGET, "total_bytes": total, "files": records}


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
    manifest = authority_manifest(root)
    manifest_hash = authority_sha256(manifest)
    payload = {
        "schema_version": "2.1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "slot": slot,
        "source": str(context_path.relative_to(root)).replace("\\", "/"),
        "source_sha256": sha256_text(text),
        "latest_block_sha256": sha256_text(latest),
        "operational_status": operational_status(latest),
        "authoritative_runtime_files": [item["path"] for item in manifest],
        "authority_manifest": manifest,
        "authority_sha256": manifest_hash,
        "authority_read_plan": authority_read_plan(),
        "authority_read_budget": authority_read_budget(root),
        "analysis_policy": {
            "workflow_depth": "full",
            "full_workflow_depth_confirmation_required": True,
            "minimum_host_reasoning_effort": "high",
            "use_highest_available_model": True,
            "full_analysis_recompute": True,
            "reuse_prior_features_scores_or_decisions": False,
            "prior_decision_access": "post_analysis_lock_only",
            "insufficient_reasoning_resources": "halt",
        },
        "read_policy": {
            "load_authority_digest_first": True,
            "load_full_context_log": False,
            "load_prior_decision_text": False,
            "load_all_authoritative_methodology": False,
            "expand_authority_by_phase": True,
            "load_complete_resolved_five_source_evidence": True,
            "load_complete_resolved_six_source_evidence": True,
            "mandatory_guardrails_always_read": (
                authority_read_plan()["always_read"]
            ),
            "prelock_safe_read_policy": prelock_policy_manifest(
                trading_date,
                slot,
                root=root,
            ),
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
            current_manifest = authority_manifest(root)
            current_authority_sha = authority_sha256(current_manifest)
        except (json.JSONDecodeError, OSError):
            payload = None
        if (
            isinstance(payload, dict)
            and payload.get("trading_date") == trading_date
            and payload.get("slot") == slot
            and payload.get("source_sha256")
            == sha256_text(context_path.read_text(encoding="utf-8"))
            and payload.get("authority_sha256") == current_authority_sha
            and payload.get("authority_manifest") == current_manifest
        ):
            return payload, target, True
    payload, target = build_context_pack(trading_date, slot, root=root)
    return payload, target, False


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a minimal daily-report context packet")
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    args = parser.parse_args()
    payload, target, reused = ensure_context_pack(args.date, args.slot)
    print(
        json.dumps(
            {
                "path": str(target),
                "context_pack_reused": reused,
                "operational_status": payload["operational_status"],
                "source_sha256": payload["source_sha256"],
                "authority_sha256": payload["authority_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
