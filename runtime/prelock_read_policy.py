"""Safe pre-lock read policy for daily-report execution.

This module defines the mechanical boundary for files that may be read before
the analysis lock exists. It is intentionally stricter than normal repository
maintenance: daily-report analysis should use committed authority and the
current slot's immutable evidence, not repository-wide search.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLOTS = {"morning", "midday", "evening"}
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
LEASE_ID_RE = re.compile(r"^[0-9a-f]{64}$")

SAFE_RG_EXCLUDES = (
    "sessions/**",
    "outputs/**",
    "runtime_state/**",
    "reviews/**",
    "memory/MEMORY.md",
)

AUTHORITY_EXACT = {
    ".agents/skills/daily-report/SKILL.md",
    ".claude/skills/daily-report/SKILL.md",
    "AGENTS.md",
    "CLAUDE.md",
    "sessions/日报SOP.md",
}

AUTHORITY_MARKDOWN_PREFIXES = (
    "agents/",
    "constitution/",
    "data_sources/",
    "execution/",
    "governance/",
    "memory/",
    "risk/",
    "scoring/",
    "templates/",
)


class PrelockReadViolation(RuntimeError):
    """Raised when a pre-lock read would expose prior judgment artifacts."""


def _as_relative(path: Path | str, *, root: Path = ROOT) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PrelockReadViolation(
            f"pre-lock read escapes repository root: {path}"
        ) from exc


def _is_current_runtime_file(relative: str, trading_date: str, slot: str) -> bool:
    current_prefix = f"runtime_state/{trading_date}/"
    if not relative.startswith(current_prefix):
        return False
    suffix = relative.removeprefix(current_prefix)
    allowed_exact = {
        f"context_{slot}.json",
        f"transition_{slot}.json",
        f"golden_reasoning_{slot}.json",
        f"prelock_guard_{slot}.json",
        f"reasoning_work_{slot}.md",
        f"reasoning_readiness_{slot}.json",
        f"decision_input_{slot}.json",
        f"decision_contract_{slot}.json",
        "pretrade_gate.json",
        "usage.jsonl",
    }
    if suffix in allowed_exact:
        return True
    if suffix.startswith(f"authority_phase_{slot}_") and suffix.endswith(".md"):
        return True
    allowed_prefixes = (
        f"captures/{slot}/",
        f"evidence/{slot}/",
    )
    return suffix.startswith(allowed_prefixes)


def classify_prelock_read(
    path: Path | str,
    *,
    trading_date: str,
    slot: str,
    root: Path = ROOT,
) -> dict:
    """Classify whether a path is safe before the analysis lock.

    The return value is JSON-serializable so it can be embedded into context and
    guard manifests.
    """
    if not DATE_RE.fullmatch(trading_date):
        raise ValueError(f"invalid trading date: {trading_date}")
    if slot not in SLOTS:
        raise ValueError(f"invalid slot: {slot}")
    relative = _as_relative(path, root=root)
    parts = relative.split("/")

    if relative in {"sessions/context_log.md", "memory/MEMORY.md"}:
        return {
            "path": relative,
            "allowed": False,
            "reason": "prior_aggregate_context_forbidden_before_analysis_lock",
        }
    if relative.startswith("sessions/archive/"):
        return {
            "path": relative,
            "allowed": False,
            "reason": "archived_context_forbidden_before_analysis_lock",
        }
    if relative.startswith("reviews/"):
        return {
            "path": relative,
            "allowed": False,
            "reason": "review_history_forbidden_before_analysis_lock",
        }
    if relative.startswith("runtime_state/") and "/.prelock_quarantine/" in relative:
        return {
            "path": relative,
            "allowed": False,
            "reason": "prelock_quarantine_forbidden_before_analysis_lock",
        }
    if relative.startswith("outputs/"):
        current_report = f"outputs/{trading_date}_{slot}_combined.md"
        if relative == current_report:
            return {
                "path": relative,
                "allowed": True,
                "reason": "current_slot_report_artifact",
            }
        if relative.endswith(".py"):
            return {
                "path": relative,
                "allowed": True,
                "reason": "deterministic_output_tool_source",
            }
        return {
            "path": relative,
            "allowed": False,
            "reason": "prior_or_generated_output_forbidden_before_analysis_lock",
        }
    if relative.startswith("runtime_state/"):
        if relative == "runtime_state/workflow_lease.json":
            return {
                "path": relative,
                "allowed": True,
                "reason": "active_workflow_lease_metadata",
            }
        if len(parts) == 3 and parts[1] == "workflow_leases":
            stem = parts[2].removesuffix(".json")
            expected_prefix = f"{trading_date}_{slot}_"
            lease_id = stem.removeprefix(expected_prefix)
            if stem.startswith(expected_prefix) and LEASE_ID_RE.fullmatch(lease_id):
                return {
                    "path": relative,
                    "allowed": True,
                    "reason": "same_slot_archived_workflow_lease_metadata",
                }
        if _is_current_runtime_file(relative, trading_date, slot):
            return {
                "path": relative,
                "allowed": True,
                "reason": "current_slot_runtime_artifact",
            }
        return {
            "path": relative,
            "allowed": False,
            "reason": "runtime_state_not_in_current_slot_allowlist",
        }
    if relative in AUTHORITY_EXACT:
        return {"path": relative, "allowed": True, "reason": "daily_report_authority"}
    if relative.startswith(".agents/"):
        return {"path": relative, "allowed": True, "reason": "codex_authority"}
    if any(relative.startswith(prefix) for prefix in AUTHORITY_MARKDOWN_PREFIXES):
        if relative == "memory/MEMORY.md":
            return {
                "path": relative,
                "allowed": False,
                "reason": "aggregate_memory_forbidden_before_analysis_lock",
            }
        if relative.endswith(".md"):
            return {
                "path": relative,
                "allowed": True,
                "reason": "phase_authority_markdown",
            }
    return {
        "path": relative,
        "allowed": False,
        "reason": "not_in_prelock_allowlist",
    }


def assert_prelock_read_allowed(
    path: Path | str,
    *,
    trading_date: str,
    slot: str,
    root: Path = ROOT,
) -> str:
    classification = classify_prelock_read(
        path,
        trading_date=trading_date,
        slot=slot,
        root=root,
    )
    if not classification["allowed"]:
        raise PrelockReadViolation(
            "pre-lock read blocked: "
            f"{classification['path']} ({classification['reason']})"
        )
    return str(classification["path"])


def prelock_rg_exclude_args() -> list[str]:
    args: list[str] = []
    for pattern in SAFE_RG_EXCLUDES:
        args.extend(["-g", f"!{pattern}"])
    return args


def prelock_policy_manifest(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict:
    if not DATE_RE.fullmatch(trading_date):
        raise ValueError(f"invalid trading date: {trading_date}")
    if slot not in SLOTS:
        raise ValueError(f"invalid slot: {slot}")
    return {
        "schema_version": "1.0",
        "trading_date": trading_date,
        "slot": slot,
        "policy": "pre_analysis_safe_read_allowlist",
        "default_action": "deny",
        "safe_rg_excludes": list(SAFE_RG_EXCLUDES),
        "allowed_authority_exact": sorted(AUTHORITY_EXACT),
        "allowed_authority_markdown_prefixes": list(AUTHORITY_MARKDOWN_PREFIXES),
        "allowed_current_runtime": [
            f"runtime_state/{trading_date}/context_{slot}.json",
            f"runtime_state/{trading_date}/transition_{slot}.json",
            f"runtime_state/{trading_date}/golden_reasoning_{slot}.json",
            f"runtime_state/{trading_date}/prelock_guard_{slot}.json",
            f"runtime_state/{trading_date}/reasoning_work_{slot}.md",
            f"runtime_state/{trading_date}/reasoning_readiness_{slot}.json",
            f"runtime_state/{trading_date}/pretrade_gate.json",
            f"runtime_state/{trading_date}/authority_phase_{slot}_<phase>.md",
            f"runtime_state/{trading_date}/captures/{slot}/**",
            f"runtime_state/{trading_date}/evidence/{slot}/**",
        ],
        "forbidden_prior_judgment_paths": [
            "sessions/context_log.md",
            "sessions/archive/**",
            "memory/MEMORY.md",
            "outputs/** except deterministic .py tools and current slot combined.md",
            "runtime_state/** except current slot allowlist and workflow lease metadata",
            "runtime_state/**/.prelock_quarantine/**",
            "reviews/**",
        ],
        "root": str(root),
    }
