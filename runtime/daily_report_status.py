"""Read-only status entrypoint for recurring report automations.

This script is intentionally conservative.  It never claims or releases gates,
never starts workflow leases, and never repairs partial artifacts.  Its only job
is to give Codex automations a stable first-step JSON decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from runtime.workflow_lease import _delivery_complete
    from runtime.pretrade_gate import (
        manifest_path as pretrade_gate_path,
        pretrade_gate_required,
        validate_pretrade_gate_contract,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from runtime.workflow_lease import _delivery_complete
    from runtime.pretrade_gate import (
        manifest_path as pretrade_gate_path,
        pretrade_gate_required,
        validate_pretrade_gate_contract,
    )


ROOT = Path(__file__).resolve().parents[1]
SLOTS = ("morning", "midday", "evening")
PRIOR_SLOT = {"midday": "morning", "evening": "midday"}
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
DEFAULT_STALE_MINUTES = 240


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_trading_date(value: str) -> date:
    if not DATE_RE.fullmatch(value):
        raise ValueError(f"invalid date: {value}")
    return date.fromisoformat(value)


def gate_paths(root: Path, key: str) -> tuple[Path, Path]:
    directory = root / "runtime_state" / "automation_gate"
    return directory / f"{key}.lock.json", directory / f"{key}.done.json"


def active_lease(root: Path) -> dict[str, Any] | None:
    payload = load_json(root / "runtime_state" / "workflow_lease.json")
    if payload and payload.get("status") == "active":
        return payload
    return None


def gate_status(root: Path, key: str) -> dict[str, Any]:
    lock_path, done_path = gate_paths(root, key)
    lock = load_json(lock_path)
    done = load_json(done_path)
    result: dict[str, Any] = {
        "key": key,
        "lock_path": relative_path(lock_path, root),
        "done_path": relative_path(done_path, root),
        "locked": lock_path.is_file(),
        "done": done_path.is_file(),
        "lock": lock,
        "done_record": done,
    }
    if lock_path.is_file():
        claimed_at = parse_claim_time(lock, lock_path)
        age_minutes = (datetime.now().astimezone() - claimed_at).total_seconds() / 60
        result["claimed_at"] = claimed_at.isoformat(timespec="seconds")
        result["age_minutes"] = round(age_minutes, 2)
        result["stale"] = age_minutes > DEFAULT_STALE_MINUTES
    return result


def parse_claim_time(lock: dict[str, Any] | None, lock_path: Path) -> datetime:
    value = lock.get("claimed_at") if isinstance(lock, dict) else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                return parsed
            return parsed.astimezone()
        except ValueError:
            pass
    return datetime.fromtimestamp(lock_path.stat().st_mtime).astimezone()


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def daily_artifacts(root: Path, trading_date: str, slot: str) -> dict[str, Any]:
    state = root / "runtime_state" / trading_date
    outputs = root / "outputs"
    capture_dir = state / "captures" / slot
    evidence_dir = state / "evidence" / slot
    delivery_path = state / f"delivery_{slot}.json"
    current = load_json(state / "current.json")
    exists = {
        "state_dir": state.is_dir(),
        "capture_dir": capture_dir.is_dir(),
        "evidence_dir": evidence_dir.is_dir(),
        "transition": (state / f"transition_{slot}.json").is_file(),
        "prelock_guard": (state / f"prelock_guard_{slot}.json").is_file(),
        "reasoning_work": (state / f"reasoning_work_{slot}.md").is_file(),
        "reasoning_readiness": (state / f"reasoning_readiness_{slot}.json").is_file(),
        "report_preflight": (state / f"report_preflight_{slot}.json").is_file(),
        "analysis_lock": (state / f"analysis_lock_{slot}.json").is_file(),
        "analysis": (state / f"analysis_{slot}.json").is_file(),
        "decision": (state / f"decision_{slot}.json").is_file(),
        "resolved_state": (state / ("base.json" if slot == "morning" else f"resolved_{slot}.json")).is_file(),
        "current_for_slot": bool(current) and current.get("slot") == slot,
        "combined_markdown": (outputs / f"{trading_date}_{slot}_combined.md").is_file(),
        "render_manifest": (state / f"render_{slot}.json").is_file(),
        "word_qa_manifest": (state / f"word_qa_{slot}.json").is_file(),
        "publish_manifest": (state / f"publish_{slot}.json").is_file(),
        "delivery_manifest": delivery_path.is_file(),
        "retention_cleanup": (state / f"retention_cleanup_{slot}.json").is_file(),
        "pretrade_gate_contract": (state / "pretrade_gate.json").is_file(),
    }
    partial_keys = [
        key
        for key, present in exists.items()
        if present and key not in {"state_dir", "pretrade_gate_contract"}
    ]
    return {
        "state_dir": relative_path(state, root),
        "delivery_path": relative_path(delivery_path, root),
        "exists": exists,
        "partial_keys": partial_keys,
        "has_partial_work": bool(partial_keys),
    }


def daily_status(root: Path, trading_date: str, slot: str) -> dict[str, Any]:
    if slot not in SLOTS:
        raise ValueError(f"unsupported slot: {slot}")
    parse_trading_date(trading_date)

    key = f"daily-{trading_date}-{slot}"
    gate = gate_status(root, key)
    lease = active_lease(root)
    artifacts = daily_artifacts(root, trading_date, slot)
    delivery_complete = _delivery_complete(trading_date, slot, root)
    prior = PRIOR_SLOT.get(slot)
    prior_delivery_complete = (
        True if prior is None else _delivery_complete(trading_date, prior, root)
    )
    gate_contract_required = pretrade_gate_required(trading_date, slot)
    gate_contract_valid = not gate_contract_required
    gate_contract_error = None
    if gate_contract_required:
        try:
            validate_pretrade_gate_contract(trading_date, slot, root=root)
            gate_contract_valid = True
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            gate_contract_error = type(exc).__name__

    state = "ready_to_claim"
    reasons: list[str] = []
    missing: list[str] = []

    if delivery_complete and gate["done"] and gate_contract_valid:
        state = "complete"
    elif delivery_complete and not gate["done"]:
        state = "manual_review_required"
        reasons.append("delivery_complete_but_automation_gate_not_done")
    elif lease is not None:
        state = "blocked_by_other_active_lease"
        reasons.append("active_workflow_lease_exists")
    elif gate["locked"]:
        state = "orphaned_automation_gate"
        reasons.append("automation_gate_lock_exists_without_complete_delivery")
    elif not prior_delivery_complete:
        state = "manual_review_required"
        missing.append(f"complete_prior_delivery:{prior}")
    elif slot != "morning" and gate_contract_required and not gate_contract_valid:
        state = "manual_review_required"
        reasons.append("same_day_pretrade_gate_contract_missing_or_invalid")
        missing.append("runtime_state/<date>/pretrade_gate.json")
    elif artifacts["has_partial_work"]:
        state = "manual_review_required"
        reasons.append("partial_daily_artifacts_exist_without_complete_delivery")
        if gate_contract_required and not gate_contract_valid:
            reasons.append("same_day_pretrade_gate_contract_missing_or_invalid")

    return {
        "schema_version": "1.0",
        "kind": "daily",
        "date": trading_date,
        "slot": slot,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "next_action": {
            "state": state,
            "gate_key": key,
            "reasons": reasons,
            "missing": missing,
        },
        "gate": gate,
        "workflow_lease": {
            "active": lease is not None,
            "payload": redact_lease(lease),
            "same_target": bool(
                lease
                and lease.get("trading_date") == trading_date
                and lease.get("slot") == slot
            ),
        },
        "prior_delivery": {
            "slot": prior,
            "complete": prior_delivery_complete,
        },
        "pretrade_gate_contract": {
            "required": gate_contract_required,
            "valid": gate_contract_valid,
            "path": relative_path(pretrade_gate_path(trading_date, root=root), root),
            "error_type": gate_contract_error,
        },
        "delivery": {
            "complete": delivery_complete,
            "path": artifacts["delivery_path"],
        },
        "artifacts": artifacts,
    }


def redact_lease(lease: dict[str, Any] | None) -> dict[str, Any] | None:
    if lease is None:
        return None
    redacted = dict(lease)
    redacted.pop("token", None)
    return redacted


def weekly_key(target: date) -> tuple[str, str]:
    iso = target.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    return f"weekly-{label}", label


def monthly_key(target: date) -> tuple[str, str]:
    label = f"{target.year:04d}-{target.month:02d}"
    return f"monthly-{label}", label


def review_artifact(root: Path, kind: str, label: str) -> dict[str, Any]:
    suffix = "weekly" if kind == "weekly" else "monthly"
    path = root / "reviews" / f"{label}_{suffix}.md"
    exists = path.is_file()
    size = path.stat().st_size if exists else 0
    return {
        "path": relative_path(path, root),
        "exists": {"review_markdown": exists},
        "size_bytes": size,
        "non_empty": exists and size > 0,
    }


def periodic_status(root: Path, kind: str, trading_date: str) -> dict[str, Any]:
    target = parse_trading_date(trading_date)
    if kind == "weekly":
        key, label = weekly_key(target)
    elif kind == "monthly":
        key, label = monthly_key(target)
    else:
        raise ValueError(f"unsupported kind: {kind}")

    gate = gate_status(root, key)
    lease = active_lease(root)
    artifact = review_artifact(root, kind, label)
    state = "ready_to_claim"
    reasons: list[str] = []

    if gate["done"]:
        state = "complete"
    elif lease is not None:
        state = "in_progress_or_stale_gate"
        reasons.append("active_daily_workflow_lease_exists")
    elif gate["locked"]:
        state = "in_progress_or_stale_gate"
        reasons.append("automation_gate_lock_exists")
    elif kind == "monthly" and artifact["exists"]["review_markdown"]:
        state = "existing_artifact_needs_verification"
        reasons.append("monthly_artifact_exists_without_done_gate")

    return {
        "schema_version": "1.0",
        "kind": kind,
        "date": trading_date,
        "period": label,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "next_action": {
            "state": state,
            "gate_key": key,
            "reasons": reasons,
            "missing": [],
        },
        "gate": gate,
        "workflow_lease": {
            "active": lease is not None,
            "payload": redact_lease(lease),
        },
        "artifacts": artifact,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=("daily", "weekly", "monthly"))
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", choices=SLOTS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = ROOT
    if args.kind == "daily":
        if not args.slot:
            raise ValueError("--slot is required for --kind daily")
        payload = daily_status(root, args.date, args.slot)
    else:
        if args.slot:
            raise ValueError("--slot is only valid for --kind daily")
        payload = periodic_status(root, args.kind, args.date)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
