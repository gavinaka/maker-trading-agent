"""Versioned, atomic state chain for the three daily decision sessions."""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.delta_engine import compare_snapshots, scan_source_snapshot
from runtime.dependency_graph import (
    active_post_lock_nodes,
    affected_nodes,
    required_analysis_nodes,
    required_post_lock_nodes,
)


ROOT = Path(__file__).resolve().parents[1]
_REASONING_READINESS_FROM = "2026-07-06"
_REASONING_READINESS_EXEMPT = ("2026-07-06", "morning")
_REPORT_PREFLIGHT_FROM = "2026-07-11"
LOGIC_FILES = {
    "daily_skill": ".agents/skills/daily-report/SKILL.md",
    "daily_sop": "sessions/日报SOP.md",
    "token_policy": "governance/token_policy.md",
    "daily_runtime_contract": "governance/daily_runtime_contract.md",
    "automation_memory_policy": "governance/automation_memory_policy.md",
    "golden_reasoning": "scoring/golden_report_reasoning_alignment.md",
    "blockbeats_rules": "data_sources/blockbeats_rules.md",
    "blockbeats_collector": "data_sources/collectors/blockbeats.md",
    "reasoning_depth": "scoring/reasoning_depth_checklist.md",
    "scoring_system": "scoring/scoring_system.md",
    "orderflow": "scoring/orderflow_methodology.md",
    "orderflow_scoring": "scoring/orderflow_scoring.md",
    "chart": "scoring/chart_methodology.md",
    "chart_scoring": "scoring/chart_scoring.md",
    "winrate": "scoring/winrate_methodology.md",
    "thresholds": "scoring/score_thresholds.md",
    "risk": "risk/risk_checklist.md",
    "entry_exit": "risk/entry_exit_rules.md",
    "floating_defense": "risk/floating_defense.md",
    "memory_basemian_news_cards": "memory/basemian-needs-news-cards.md",
    "memory_blockbeats_important_only": "memory/blockbeats-important-only.md",
    "memory_browser_capture_toolset": "memory/browser-capture-toolset.md",
    "maker_defense_memory": "memory/defense-layer2-vs-tp1-conflict.md",
    "memory_five_sources_complete_or_halt": "memory/five-sources-complete-or-halt.md",
    "memory_fundamentals_brief_core_priority": "memory/fundamentals-brief-core-priority.md",
    "memory_independent_report_no_user_reference": "memory/independent-report-no-user-reference.md",
    "memory_notion_publish_checklist": "memory/notion-publish-checklist.md",
    "memory_precise_numbers_no_fuzzy": "memory/precise-numbers-no-fuzzy.md",
    "memory_push_report_to_ai_agent_plan": "memory/push-report-to-ai-agent-plan.md",
    "memory_report_chinese_only_narrative": "memory/report-chinese-only-narrative.md",
    "memory_report_evidence_time_lock": "memory/report-evidence-time-lock.md",
    "memory_report_template_alignment": "memory/report-template-alignment.md",
    "memory_score70_must_place_maker": "memory/score70-must-place-maker.md",
    "memory_stability_contract": "memory/stability-contract.md",
    "memory_verify_once_sufficient_samples": "memory/verify-once-sufficient-samples.md",
    "leverage": "risk/leverage_rules.md",
    "position_management": "risk/position_management.md",
    "state_gate": "risk/state_gate.md",
    "trading_constitution": "constitution/trading_constitution.md",
    "maker_principles": "constitution/maker_principles.md",
    "cannot_do": "constitution/cannot_do_mapping.md",
    "review_principles": "constitution/review_principles.md",
    "execution_philosophy": "constitution/execution_philosophy.md",
    "news_agent": "agents/news_agent.md",
    "scoring_agent": "agents/scoring_agent.md",
    "risk_agent": "agents/risk_agent.md",
    "output_agent": "agents/output_agent.md",
    "review_agent": "agents/review_agent.md",
    "emotional_agent": "agents/emotional_agent.md",
    "footprint_agent": "agents/footprint_agent.md",
    "penalty_agent": "agents/penalty_agent.md",
}


def _reasoning_readiness_required(trading_date: str, slot: str) -> bool:
    return (trading_date, slot) != _REASONING_READINESS_EXEMPT and trading_date >= _REASONING_READINESS_FROM


def _report_preflight_required(trading_date: str) -> bool:
    return trading_date >= _REPORT_PREFLIGHT_FROM


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _report_preflight_binding_valid(
    trading_date: str,
    slot: str,
    validation: dict,
    directory: Path,
) -> bool:
    if not _report_preflight_required(trading_date):
        return True
    if not isinstance(validation, dict):
        return False
    preflight_path = (directory / f"report_preflight_{slot}.json").resolve()
    recorded_path = validation.get("report_preflight_manifest")
    expected_hash = validation.get("report_preflight_manifest_sha256")
    payload_hash = validation.get("payload_preview_sha256")
    return bool(
        validation.get("report_preflight_required") is True
        and validation.get("payload_derivation_pre_lock") is True
        and recorded_path
        and Path(str(recorded_path)).resolve() == preflight_path
        and preflight_path.is_file()
        and re.fullmatch(r"[0-9a-f]{64}", str(expected_hash or ""))
        and _file_sha256(preflight_path) == expected_hash
        and re.fullmatch(r"[0-9a-f]{64}", str(payload_hash or ""))
    )


SLOT_ORDER = {"morning": 1, "midday": 2, "evening": 3}
PRIOR_SLOT = {"midday": "morning", "evening": "midday"}
RESOLVED_STATE_KEYS = {
    "schema_version",
    "created_at",
    "trading_date",
    "slot",
    "state_version",
    "parent_version",
    "logic_version",
    "sources",
    "capture_manifest",
    "changed_sources",
    "source_affected_nodes",
    "invalidated_nodes",
    "post_lock_nodes",
    "recomputed_nodes",
    "analysis_policy",
    "collection_mode",
    "full_fallback_used",
    "fallback_reasons",
    "analysis_invalidation_reasons",
    "prior_state_skip",
    "notion_state",
    "commit_id",
    "report_sha256",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def logic_versions(root: Path = ROOT) -> dict[str, str]:
    return {name: file_hash(root / relative) for name, relative in LOGIC_FILES.items()}


def _validate_evidence_snapshot(
    directory: Path,
    slot: str,
    capture_manifest: dict,
) -> Path:
    snapshot = capture_manifest.get("evidence_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("evidence snapshot is missing from capture manifest")
    root_value = snapshot.get("root")
    if not isinstance(root_value, str) or not root_value.strip():
        raise ValueError("evidence snapshot root is missing")
    snapshot_root = (directory / root_value).resolve()
    allowed_root = (directory / "evidence" / slot).resolve()
    try:
        snapshot_root.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(
            f"evidence snapshot must be inside {allowed_root}"
        ) from exc
    if not snapshot_root.is_dir():
        raise ValueError(f"evidence snapshot directory is missing: {snapshot_root}")
    files = snapshot.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("evidence snapshot file list is empty")
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("evidence snapshot file entry must be an object")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError(f"invalid evidence snapshot path: {relative!r}")
        file_path = (snapshot_root / relative).resolve()
        try:
            file_path.relative_to(snapshot_root)
        except ValueError as exc:
            raise ValueError(f"evidence file escapes snapshot: {relative}") from exc
        if not file_path.is_file():
            raise ValueError(f"evidence file is missing: {relative}")
        if expected_hash != file_hash(file_path):
            raise ValueError(f"evidence file hash mismatch: {relative}")
    return snapshot_root


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def state_dir(trading_date: str, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date


def _delivery_manifest_exists(directory: Path, slot: str) -> bool:
    return (directory / f"delivery_{slot}.json").is_file()


def _prior_parent_for_reissue(directory: Path, slot: str) -> dict | None:
    prior = PRIOR_SLOT.get(slot)
    if prior is None:
        return None
    filename = "base.json" if prior == "morning" else f"resolved_{prior}.json"
    parent = load_json(directory / filename)
    if not parent or parent.get("slot") != prior:
        raise ValueError(f"cannot reissue {slot} without committed {prior} parent")
    return parent


def _capture_lease_recovery(
    *,
    trading_date: str,
    slot: str,
    workflow_lease_id: str | None,
    capture_workflow_lease_id: object,
    recovered_from_workflow_lease: dict | None,
) -> dict | None:
    if workflow_lease_id is None or capture_workflow_lease_id == workflow_lease_id:
        return None
    if not isinstance(capture_workflow_lease_id, str) or not re.fullmatch(
        r"[0-9a-f]{64}",
        capture_workflow_lease_id,
    ):
        return None
    if not isinstance(recovered_from_workflow_lease, dict):
        return None
    checks = {
        "date": recovered_from_workflow_lease.get("trading_date") == trading_date,
        "slot": recovered_from_workflow_lease.get("slot") == slot,
        "lease_id": (
            recovered_from_workflow_lease.get("lease_id")
            == capture_workflow_lease_id
        ),
        "status": recovered_from_workflow_lease.get("status")
        in {"abandoned", "recovered"},
        "active_lease": bool(re.fullmatch(r"[0-9a-f]{64}", workflow_lease_id)),
        "reason": len(
            str(recovered_from_workflow_lease.get("recovery_reason", "")).strip()
        )
        >= 8,
    }
    if not all(checks.values()):
        return None
    return {
        "kind": "recovered_capture_manifest_lease",
        "captured_workflow_lease_id": capture_workflow_lease_id,
        "active_workflow_lease_id": workflow_lease_id,
        "captured_lease_status": recovered_from_workflow_lease.get("status"),
        "captured_lease_closed_at": recovered_from_workflow_lease.get("closed_at"),
        "recovery_reason": recovered_from_workflow_lease.get("recovery_reason"),
    }


@contextmanager
def exclusive_lock(path: Path, *, stale_seconds: int = 1800):
    """Acquire a cross-process lock and never remove another owner's lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}:{uuid.uuid4().hex}"
    descriptor = None
    for attempt in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, token.encode("ascii"))
            os.fsync(descriptor)
            break
        except FileExistsError:
            age = time.time() - path.stat().st_mtime
            if attempt == 0 and age > stale_seconds:
                path.unlink(missing_ok=True)
                continue
            raise RuntimeError(f"session is already running: {path}")
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            if path.read_text(encoding="ascii") == token:
                path.unlink()
        except FileNotFoundError:
            pass


def session_locked(function):
    @functools.wraps(function)
    def wrapper(trading_date: str, slot: str, *args, **kwargs):
        root = kwargs.get("root", ROOT)
        with exclusive_lock(state_dir(trading_date, root) / ".session.lock"):
            return function(trading_date, slot, *args, **kwargs)

    return wrapper


@session_locked
def prepare_transition(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
    external_changes: set[str] | None = None,
    max_reasoning_confirmed: bool = False,
    full_recollection_performed: bool = False,
    replace_prepared_transition: bool = False,
    allow_same_slot_reissue: bool = False,
    capture_manifest_path: Path | None = None,
    workflow_lease_id: str | None = None,
    recovered_from_workflow_lease: dict | None = None,
    prior_state_skip_reason: str | None = None,
    pretrade_gate_contract: dict | None = None,
) -> tuple[dict, Path]:
    if slot not in SLOT_ORDER:
        raise ValueError(f"unsupported slot: {slot}")
    if not max_reasoning_confirmed:
        raise ValueError(
            "MAX reasoning must be confirmed before preparing analysis"
        )
    directory = state_dir(trading_date, root)
    parent = load_json(directory / "current.json")
    reissue = None
    if parent and parent.get("slot") == slot:
        if not allow_same_slot_reissue:
            raise ValueError(
                f"{slot} is already committed; pass explicit same-slot reissue "
                "authorization before delivery to replace it"
            )
        if _delivery_manifest_exists(directory, slot):
            raise ValueError(f"{slot} is already delivered; same-slot reissue blocked")
        reissue = {
            "kind": "same_slot_reissue_before_delivery",
            "previous_commit_id": parent.get("commit_id"),
            "previous_state_version": parent.get("state_version"),
            "previous_report_sha256": parent.get("report_sha256"),
            "previous_capture_manifest": parent.get("capture_manifest"),
        }
        parent = _prior_parent_for_reissue(directory, slot)
    current_logic = logic_versions(root)
    capture_name = (
        f"capture_{slot}_full.json"
        if slot == "morning" or full_recollection_performed
        else f"capture_{slot}.json"
    )
    capture_path = (
        capture_manifest_path.resolve()
        if capture_manifest_path is not None
        else directory / capture_name
    )
    if capture_manifest_path is not None:
        capture_root = (directory / "captures" / slot).resolve()
        try:
            capture_path.relative_to(capture_root)
        except ValueError as exc:
            raise ValueError(
                f"capture manifest must be inside {capture_root}"
            ) from exc
        capture_name = capture_path.relative_to(directory).as_posix()
    capture_manifest = load_json(capture_path)
    if capture_manifest is None:
        raise ValueError(f"capture manifest is missing: {capture_name}")
    manifest_mode = capture_manifest.get("mode")
    manifest_full_fallback = (
        manifest_mode == "conservative_delta"
        and capture_manifest.get("full_fallback_used") is True
        and capture_manifest.get("fallback_code") == 0
    )
    manifest_full = manifest_mode in {"full_base", "full_recollection"}
    full_recollection_performed = bool(
        slot != "morning" and (manifest_full or manifest_full_fallback)
    )
    allowed_modes = (
        {"full_base"}
        if slot == "morning"
        else {"conservative_delta", "full_recollection"}
    )
    capture_workflow_lease_id = capture_manifest.get("workflow_lease_id")
    capture_lease_recovery = _capture_lease_recovery(
        trading_date=trading_date,
        slot=slot,
        workflow_lease_id=workflow_lease_id,
        capture_workflow_lease_id=capture_workflow_lease_id,
        recovered_from_workflow_lease=recovered_from_workflow_lease,
    )
    capture_checks = {
        "date": capture_manifest.get("date") == trading_date,
        "slot": capture_manifest.get("slot") == slot,
        "success": capture_manifest.get("success") is True,
        "mode": manifest_mode in allowed_modes,
        "immutable_run_id": (
            capture_manifest_path is None
            or bool(re.fullmatch(r"[0-9a-f-]{16,64}", str(capture_manifest.get("run_id", ""))))
        ),
        "workflow_lease": (
            workflow_lease_id is None
            or (
                capture_manifest.get("workflow_lease_id") == workflow_lease_id
                and bool(re.fullmatch(r"[0-9a-f]{64}", workflow_lease_id))
            )
            or (
                allow_same_slot_reissue
                and reissue is not None
                and isinstance(capture_workflow_lease_id, str)
                and bool(
                    re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(capture_workflow_lease_id),
                    )
                )
            )
            or capture_lease_recovery is not None
        ),
    }
    failed_capture_checks = sorted(
        name for name, passed in capture_checks.items() if not passed
    )
    if failed_capture_checks:
        raise ValueError(
            "invalid capture manifest: " + ", ".join(failed_capture_checks)
        )
    evidence_root = _validate_evidence_snapshot(directory, slot, capture_manifest)
    if reissue is not None:
        reissue["reused_capture_workflow_lease_id"] = capture_manifest.get(
            "workflow_lease_id"
        )
        reissue["active_reissue_workflow_lease_id"] = workflow_lease_id
    snapshot = scan_source_snapshot(evidence_root)
    comparison = compare_snapshots(
        parent.get("sources") if parent else None,
        snapshot,
        slot=slot,
    )
    external_changes = external_changes or set()
    if external_changes:
        comparison["changed_sources"] = sorted(
            set(comparison["changed_sources"]) | external_changes
        )
        comparison["source_affected_nodes"] = sorted(
            set(comparison["source_affected_nodes"])
            | affected_nodes(external_changes)
        )

    if comparison["missing_required_sources"]:
        raise ValueError(
            "missing or incomplete required sources: "
            + ", ".join(comparison["missing_required_sources"])
        )
    if manifest_full_fallback:
        fallback = capture_manifest.get("fallback_manifest")
        if not isinstance(fallback, dict):
            raise ValueError("delta fallback is missing its immutable full manifest")
        fallback_path = (directory / str(fallback.get("path", ""))).resolve()
        fallback_root = (directory / "captures" / slot).resolve()
        try:
            fallback_path.relative_to(fallback_root)
        except ValueError as exc:
            raise ValueError("fallback manifest escapes its slot directory") from exc
        fallback_payload = load_json(fallback_path)
        fallback_allowed_lease_ids = {workflow_lease_id}
        if capture_lease_recovery is not None or (
            allow_same_slot_reissue and reissue is not None
        ):
            fallback_allowed_lease_ids.add(capture_workflow_lease_id)
        fallback_checks = {
            "exists": isinstance(fallback_payload, dict),
            "hash": (
                fallback_path.is_file()
                and fallback.get("sha256") == file_hash(fallback_path)
            ),
            "date": (
                isinstance(fallback_payload, dict)
                and fallback_payload.get("date") == trading_date
            ),
            "slot": (
                isinstance(fallback_payload, dict)
                and fallback_payload.get("slot") == slot
            ),
            "mode": (
                isinstance(fallback_payload, dict)
                and fallback_payload.get("mode") == "full_recollection"
            ),
            "lease": (
                isinstance(fallback_payload, dict)
                and fallback_payload.get("workflow_lease_id")
                in fallback_allowed_lease_ids
            ),
            "success": (
                isinstance(fallback_payload, dict)
                and fallback_payload.get("success") is True
            ),
        }
        failed_fallback = sorted(
            name for name, passed in fallback_checks.items() if not passed
        )
        if failed_fallback:
            raise ValueError(
                "invalid full fallback manifest: " + ", ".join(failed_fallback)
            )
    prior_state_skip = None
    if slot != "morning" and parent is None and prior_state_skip_reason:
        prior_state_skip = {
            "skipped_prior_slot": "morning" if slot == "midday" else "midday",
            "reason": prior_state_skip_reason.strip(),
        }
    if slot != "morning" and parent is None and not prior_state_skip:
        raise ValueError("no committed morning/base state")
    if parent and SLOT_ORDER[slot] <= SLOT_ORDER.get(parent.get("slot", ""), 0):
        raise ValueError("slot order is not strictly increasing")

    fallback_reasons = list(capture_manifest.get("fallback_reasons", []))
    logic_changed = bool(parent and parent.get("logic_version") != current_logic)
    analysis_invalidation_reasons = (
        ["logic version changed"] if logic_changed else []
    )

    invalidated = required_analysis_nodes(slot)
    transition = {
        "schema_version": "3.0",
        "created_at": now_iso(),
        "trading_date": trading_date,
        "slot": slot,
        "state_version": (parent.get("state_version", 0) + 1) if parent else 1,
        "parent_version": parent.get("state_version") if parent else None,
        "logic_version": current_logic,
        "sources": snapshot,
        "capture_manifest": {
            "path": capture_name,
            "sha256": file_hash(capture_path),
            "mode": capture_manifest.get("mode"),
            "completed_at": capture_manifest.get("completed_at"),
            "evidence_snapshot": capture_manifest.get("evidence_snapshot"),
        },
        "changed_sources": comparison["changed_sources"],
        "unchanged_sources": comparison["unchanged_sources"],
        "source_affected_nodes": comparison["source_affected_nodes"],
        "missing_required_sources": comparison["missing_required_sources"],
        "invalidated_nodes": sorted(invalidated),
        "post_lock_nodes": sorted(required_post_lock_nodes(slot)),
        "analysis_policy": {
            "reasoning_effort": "max",
            "max_reasoning_confirmed": True,
            "use_highest_available_model": True,
            "full_analysis_recompute": True,
            "prior_decision_access": "post_analysis_lock_only",
            "reuse_prior_analysis": False,
            "insufficient_reasoning_resources": "halt",
        },
        "collection_mode": (
            "full_base"
            if slot == "morning"
            else "full_recollection"
            if full_recollection_performed
            else "incremental"
        ),
        "full_fallback_used": bool(full_recollection_performed and slot != "morning"),
        "fallback_reasons": fallback_reasons,
        "analysis_invalidation_reasons": analysis_invalidation_reasons,
        "prior_state_skip": prior_state_skip,
    }
    if reissue:
        transition["reissue"] = reissue
    if capture_lease_recovery is not None:
        transition["capture_lease_recovery"] = capture_lease_recovery
    if pretrade_gate_contract is not None:
        transition["pretrade_gate_contract"] = copy.deepcopy(
            pretrade_gate_contract
        )
    target = directory / f"transition_{slot}.json"
    existing = load_json(target)
    if existing and not replace_prepared_transition:
        comparable = (
            existing.get("logic_version") == transition["logic_version"]
            and existing.get("sources") == transition["sources"]
            and existing.get("capture_manifest") == transition["capture_manifest"]
            and existing.get("parent_version") == transition["parent_version"]
            and existing.get("analysis_policy") == transition["analysis_policy"]
            and existing.get("pretrade_gate_contract")
            == transition.get("pretrade_gate_contract")
        )
        if comparable:
            existing_recovery = existing.get("capture_lease_recovery")
            if existing_recovery == capture_lease_recovery:
                reused = copy.deepcopy(existing)
                reused["idempotent_reuse"] = True
                return reused, target
            if capture_lease_recovery is not None:
                rebound = copy.deepcopy(existing)
                rebound["capture_lease_recovery"] = capture_lease_recovery
                rebound.pop("idempotent_reuse", None)
                atomic_json_write(target, rebound)
                refreshed = copy.deepcopy(rebound)
                refreshed["recovery_binding_refreshed"] = True
                return refreshed, target
        raise ValueError(
            "a different transition is already prepared; use explicit replacement "
            "after verifying that no analysis is in progress"
        )
    atomic_json_write(target, transition)
    return transition, target


@session_locked
def commit_transition(
    trading_date: str,
    slot: str,
    updates: dict[str, Any],
    analysis_lock: dict[str, Any],
    commit_id: str,
    *,
    root: Path = ROOT,
    allow_same_slot_reissue: bool = False,
) -> tuple[dict, Path]:
    if not re.fullmatch(r"[0-9a-f]{64}", commit_id):
        raise ValueError("commit_id must be a lowercase SHA-256 hex digest")
    directory = state_dir(trading_date, root)
    parent = load_json(directory / "current.json") or {}
    filename = "base.json" if slot == "morning" else f"resolved_{slot}.json"
    target = directory / filename
    transition = load_json(directory / f"transition_{slot}.json")
    if transition is None:
        raise ValueError(f"transition for {slot} has not been prepared")
    if parent.get("slot") == slot:
        if parent.get("commit_id") == commit_id and target.is_file():
            duplicate = copy.deepcopy(parent)
            duplicate["idempotent_reuse"] = True
            return duplicate, target
        if not allow_same_slot_reissue or not transition.get("reissue"):
            raise ValueError(f"{slot} is already committed with a different result")
        if _delivery_manifest_exists(directory, slot):
            raise ValueError(f"{slot} is already delivered; same-slot reissue blocked")
    missing_sources = transition.get("missing_required_sources", [])
    if missing_sources:
        raise ValueError(
            "commit blocked by missing required sources: "
            + ", ".join(sorted(missing_sources))
        )
    analysis_policy = transition.get("analysis_policy", {})
    if (
        analysis_policy.get("reasoning_effort") != "max"
        or not analysis_policy.get("max_reasoning_confirmed")
    ):
        raise ValueError("commit blocked without confirmed MAX reasoning")
    required = set(transition["invalidated_nodes"])
    completed = set(analysis_lock.get("completed_nodes", []))
    missing = sorted(required - completed)
    if missing:
        raise ValueError("analysis lock missing completed nodes: " + ", ".join(missing))
    unexpected_nodes = sorted(completed - required)
    if unexpected_nodes:
        raise ValueError(
            "analysis lock contains unexpected nodes: " + ", ".join(unexpected_nodes)
        )
    required_post_lock = active_post_lock_nodes(transition.get("post_lock_nodes", []))
    completed_post_lock = set(analysis_lock.get("post_lock_completed_nodes", []))
    missing_post_lock = sorted(required_post_lock - completed_post_lock)
    unexpected_post_lock = sorted(completed_post_lock - required_post_lock)
    if missing_post_lock or unexpected_post_lock:
        raise ValueError(
            "post-lock completion mismatch: "
            f"missing={missing_post_lock}, unexpected={unexpected_post_lock}"
        )
    lock_checks = {
        "trading_date": analysis_lock.get("trading_date") == trading_date,
        "slot": analysis_lock.get("slot") == slot,
        "max_reasoning": analysis_lock.get("max_reasoning_confirmed") is True,
        "five_sources": analysis_lock.get("five_source_validation_passed") is True,
        "full_analysis": analysis_lock.get("full_analysis_confirmed") is True,
        "no_prior_judgment": analysis_lock.get("prior_judgment_read_before_lock") is False,
        "max_through_analysis": (
            analysis_lock.get("max_through_analysis_confirmed") is True
        ),
        "max_through_post_lock": (
            analysis_lock.get("max_through_post_lock_confirmed") is True
        ),
        "commit_id": analysis_lock.get("commit_id") == commit_id,
        "report_sha256": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(analysis_lock.get("report_sha256", "")))
        ),
    }
    validation = analysis_lock.get("analysis_validation", {})
    reasoning_ready = (
        not _reasoning_readiness_required(trading_date, slot)
        or (
            isinstance(validation, dict)
            and validation.get("reasoning_readiness_pre_md") is True
            and validation.get("reasoning_readiness_policy")
            == "pre_md_reasoning_depth_certified_no_posthoc_rationale"
        )
    )
    lock_checks["analysis_validation"] = (
        isinstance(validation, dict)
        and validation.get("lint_passed") is True
        and validation.get("report_state_validated") is True
        and validation.get("report_state_omissions") == []
        and validation.get("source_coverage_validated") is True
        and validation.get("position_coupling_absent") is True
        and reasoning_ready
        and _report_preflight_binding_valid(
            trading_date,
            slot,
            validation,
            directory,
        )
    )
    failed_checks = sorted(name for name, passed in lock_checks.items() if not passed)
    if failed_checks:
        raise ValueError("invalid analysis lock: " + ", ".join(failed_checks))

    updates = copy.deepcopy(updates)
    allowed_updates = {"notion_state", "analysis_archive", "decision"}
    unexpected_updates = sorted(set(updates) - allowed_updates)
    if unexpected_updates:
        raise ValueError("unsupported state updates: " + ", ".join(unexpected_updates))
    decision = updates.pop("decision", None)
    analysis_archive = updates.pop("analysis_archive", None)
    if not isinstance(analysis_archive, dict) or not analysis_archive:
        raise ValueError("analysis archive is empty")
    if not isinstance(decision, dict) or not decision:
        raise ValueError("decision archive is empty")
    notion_state = updates.pop("notion_state", None)
    if not isinstance(notion_state, dict) or not notion_state:
        raise ValueError("notion factual state is empty")
    resolved = {"notion_state": notion_state}
    resolved.update(
        {
            "schema_version": transition["schema_version"],
            "created_at": now_iso(),
            "trading_date": trading_date,
            "slot": slot,
            "state_version": transition["state_version"],
            "parent_version": transition["parent_version"],
            "logic_version": transition["logic_version"],
            "sources": transition["sources"],
            "capture_manifest": transition["capture_manifest"],
            "changed_sources": transition["changed_sources"],
            "source_affected_nodes": transition.get("source_affected_nodes", []),
            "invalidated_nodes": transition["invalidated_nodes"],
            "post_lock_nodes": transition.get("post_lock_nodes", []),
            "recomputed_nodes": sorted(completed),
            "analysis_policy": transition["analysis_policy"],
            "collection_mode": transition["collection_mode"],
            "full_fallback_used": transition["full_fallback_used"],
            "fallback_reasons": transition["fallback_reasons"],
            "analysis_invalidation_reasons": transition.get(
                "analysis_invalidation_reasons", []
            ),
            "prior_state_skip": transition.get("prior_state_skip"),
            "commit_id": commit_id,
            "report_sha256": analysis_lock["report_sha256"],
        }
    )
    unexpected_state = sorted(set(resolved) - RESOLVED_STATE_KEYS)
    missing_state = sorted(RESOLVED_STATE_KEYS - set(resolved))
    if unexpected_state or missing_state:
        raise ValueError(
            "resolved state allowlist violation: "
            f"unexpected={unexpected_state}, missing={missing_state}"
        )
    atomic_json_write(target, resolved)
    atomic_json_write(directory / "current.json", resolved)
    if analysis_archive is not None:
        atomic_json_write(
            directory / f"analysis_{slot}.json",
            {
                "schema_version": "2.0",
                "created_at": now_iso(),
                "trading_date": trading_date,
                "slot": slot,
                "state_version": transition["state_version"],
                "reuse_policy": "post_analysis_audit_only",
                "analysis_archive": analysis_archive,
            },
        )
    if decision is not None:
        atomic_json_write(
            directory / f"decision_{slot}.json",
            {
                "schema_version": "2.0",
                "created_at": now_iso(),
                "trading_date": trading_date,
                "slot": slot,
                "state_version": transition["state_version"],
                "reuse_policy": "post_analysis_lock_only",
                "decision": decision,
            },
        )
    return resolved, target
