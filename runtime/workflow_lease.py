"""Persistent, auditable lease for one complete daily-report workflow.

The lease spans begin-session through successful delivery.  It is global to the
repository, so two slots (or two dates) cannot overlap.  A lease is never
silently expired: interruption requires an explicit abandon or recover action
with an audit reason.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from runtime.authority_mutex import production_start_guard


ROOT = Path(__file__).resolve().parents[1]
SLOTS = ("morning", "midday", "evening")
PRIOR_SLOT = {"midday": "morning", "evening": "midday"}
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
PAGE_ID_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.I,
)
DELIVERY_REQUIRED_FLAGS = (
    "frozen_verifier_pass",
    "unique_page_pass",
    "word_visual_qa_pass",
    "context_log_recorded",
)
DELIVERY_MINIMUM_EVIDENCE_BINDINGS = (
    "report_sha256",
    "docx_path",
    "docx_sha256",
    "render_manifest",
    "render_manifest_sha256",
    "word_qa_manifest",
    "word_qa_manifest_sha256",
    "publish_manifest",
    "publish_manifest_sha256",
    "published_at",
)
DELIVERY_OPTIONAL_EVIDENCE_BINDINGS = (
    "context_log_block_sha256",
    "source_binding",
)


def _notion_visual_flag_matches(delivery: dict, evidence: dict) -> bool:
    """Require the explicit flag for v3 while preserving historical v2 records."""
    expected = evidence.get("notion_visual_contract_pass")
    if expected is True:
        return delivery.get("notion_visual_contract_pass") is True
    return "notion_visual_contract_pass" not in delivery


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def active_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / "workflow_lease.json"


def audit_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / "workflow_lease_audit.jsonl"


def lease_id(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def load_json(path: Path) -> dict | None:
    for attempt in range(8):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            break
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            if attempt == 7:
                raise
            time.sleep(0.01 * (attempt + 1))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _validate_identity(trading_date: str, slot: str) -> None:
    if not DATE_RE.fullmatch(trading_date):
        raise ValueError(f"invalid trading date: {trading_date}")
    if slot not in SLOTS:
        raise ValueError(f"unsupported slot: {slot}")


def _atomic_create(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _append_audit(root: Path, payload: dict) -> None:
    target = audit_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _archive(root: Path, payload: dict) -> Path:
    directory = root / "runtime_state" / "workflow_leases"
    directory.mkdir(parents=True, exist_ok=True)
    target = _archive_file(
        root,
        payload["trading_date"],
        payload["slot"],
        payload["lease_id"],
    )
    if target.exists():
        existing = load_json(target)
        if existing != payload:
            raise RuntimeError(f"lease archive collision: {target}")
        return target
    _atomic_create(target, payload)
    return target


def _archive_file(root: Path, trading_date: str, slot: str, lease_id_value: str) -> Path:
    return (
        root
        / "runtime_state"
        / "workflow_leases"
        / f"{trading_date}_{slot}_{lease_id_value}.json"
    )


def _assert_lease_id(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
        raise ValueError(f"invalid workflow lease id: {value}")


def _load_recoverable_archived_lease(
    trading_date: str,
    slot: str,
    lease_id_value: str,
    root: Path,
) -> dict:
    _validate_identity(trading_date, slot)
    _assert_lease_id(lease_id_value)
    archived = load_json(_archive_file(root, trading_date, slot, lease_id_value))
    if not archived:
        raise RuntimeError(
            "archived workflow lease not found for recovery: "
            f"{trading_date} {slot} lease_id={lease_id_value}"
        )
    checks = {
        "date": archived.get("trading_date") == trading_date,
        "slot": archived.get("slot") == slot,
        "lease_id": archived.get("lease_id") == lease_id_value,
        "closed": archived.get("status") in {"abandoned", "recovered"},
        "token_removed": "token" not in archived,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(
            "archived workflow lease is not recoverable: " + ", ".join(failed)
        )
    return archived


def _recovered_from_payload(archived: dict, recovery_reason: str) -> dict:
    return {
        "trading_date": archived["trading_date"],
        "slot": archived["slot"],
        "lease_id": archived["lease_id"],
        "status": archived["status"],
        "closed_at": archived.get("closed_at"),
        "close_reason": archived.get("reason"),
        "recovery_reason": recovery_reason.strip(),
    }


def _delivery_path(trading_date: str, slot: str, root: Path) -> Path:
    return root / "runtime_state" / trading_date / f"delivery_{slot}.json"


def _resolved_state_path(trading_date: str, slot: str, root: Path) -> Path:
    filename = "base.json" if slot == "morning" else f"resolved_{slot}.json"
    return root / "runtime_state" / trading_date / filename


def _delivery_state(trading_date: str, slot: str, commit_id: str, root: Path) -> dict | None:
    current = load_json(root / "runtime_state" / trading_date / "current.json")
    if (
        current
        and current.get("slot") == slot
        and current.get("commit_id") == commit_id
    ):
        return current
    resolved = load_json(_resolved_state_path(trading_date, slot, root))
    if (
        resolved
        and resolved.get("slot") == slot
        and resolved.get("commit_id") == commit_id
    ):
        return resolved
    return None


def _delivery_evidence_matches(recorded: object, actual: dict) -> bool:
    if not isinstance(recorded, dict):
        return False
    required_match = all(
        recorded.get(key) == actual.get(key)
        for key in DELIVERY_MINIMUM_EVIDENCE_BINDINGS
    )
    if not required_match:
        return False
    return all(
        key not in recorded or recorded.get(key) == actual.get(key)
        for key in DELIVERY_OPTIONAL_EVIDENCE_BINDINGS
    )


def _delivery_recorded(trading_date: str, slot: str, root: Path) -> bool:
    delivery = load_json(_delivery_path(trading_date, slot, root))
    if not delivery:
        return False
    evidence = delivery.get("evidence")
    if not isinstance(evidence, dict):
        return False
    page_id = str(delivery.get("page_id", ""))
    checks = {
        "schema_version": delivery.get("schema_version") == "2.0",
        "date": delivery.get("trading_date") == trading_date,
        "slot": delivery.get("slot") == slot,
        "commit_id": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(delivery.get("commit_id", "")))
        ),
        "workflow_lease_id": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(delivery.get("workflow_lease_id", "")))
        ),
        "page_id": bool(PAGE_ID_RE.fullmatch(page_id)),
        "flags": all(delivery.get(flag) is True for flag in DELIVERY_REQUIRED_FLAGS),
        "notion_visual_contract": _notion_visual_flag_matches(delivery, evidence),
        "published_at": bool(delivery.get("published_at"))
        and delivery.get("published_at") == evidence.get("published_at"),
        "minimum_evidence": all(
            evidence.get(key)
            for key in DELIVERY_MINIMUM_EVIDENCE_BINDINGS
            if key != "published_at"
        ),
    }
    return all(checks.values())


def _delivery_complete(trading_date: str, slot: str, root: Path) -> bool:
    from runtime.pretrade_gate import (
        pretrade_gate_required,
        validate_pretrade_gate_contract,
    )

    if pretrade_gate_required(trading_date, slot):
        try:
            validate_pretrade_gate_contract(trading_date, slot, root=root)
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return False
    delivery = load_json(_delivery_path(trading_date, slot, root))
    if not delivery:
        return False
    page_id = str(delivery.get("page_id", ""))
    checks = {
        "schema_version": delivery.get("schema_version") == "2.0",
        "date": delivery.get("trading_date") == trading_date,
        "slot": delivery.get("slot") == slot,
        "commit_id": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(delivery.get("commit_id", "")))
        ),
        "workflow_lease_id": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(delivery.get("workflow_lease_id", "")))
        ),
        "page_id": bool(PAGE_ID_RE.fullmatch(page_id)),
        "flags": all(delivery.get(flag) is True for flag in DELIVERY_REQUIRED_FLAGS),
        "published_at": bool(delivery.get("published_at")),
    }
    if any(not passed for passed in checks.values()):
        return False

    state = _delivery_state(trading_date, slot, delivery["commit_id"], root)
    if not state:
        return False

    try:
        from runtime.delivery_evidence import validate_delivery_evidence

        evidence = validate_delivery_evidence(
            trading_date,
            slot,
            page_id,
            current=state,
            root=root,
        )
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, json.JSONDecodeError):
        return False

    return (
        delivery.get("published_at") == evidence.get("published_at")
        and _notion_visual_flag_matches(delivery, evidence)
        and _delivery_evidence_matches(delivery.get("evidence"), evidence)
    )


def _prior_delivery_complete(trading_date: str, slot: str, root: Path) -> bool:
    prior = PRIOR_SLOT.get(slot)
    if prior is None:
        return True
    return _delivery_complete(trading_date, prior, root)


def _record_prior_delivery_skip(
    trading_date: str,
    slot: str,
    reason: str,
    root: Path,
) -> dict:
    prior = PRIOR_SLOT.get(slot)
    if prior is None:
        raise ValueError(f"{slot} has no prior slot to skip")
    if len(reason.strip()) < 8:
        raise ValueError("prior delivery skip reason must be explicit")
    payload = {
        "schema_version": "1.0",
        "created_at": now_iso(),
        "trading_date": trading_date,
        "slot": slot,
        "skipped_prior_slot": prior,
        "reason": reason.strip(),
    }
    target = (
        root
        / "runtime_state"
        / trading_date
        / f"prior_delivery_skip_{slot}.json"
    )
    existing = load_json(target)
    if existing:
        if (
            existing.get("trading_date") != trading_date
            or existing.get("slot") != slot
            or existing.get("skipped_prior_slot") != prior
        ):
            raise RuntimeError(f"prior delivery skip collision: {target}")
        return existing
    _atomic_create(target, payload)
    _append_audit(
        root,
        {
            "event": "prior_delivery_skipped",
            "at": payload["created_at"],
            "trading_date": trading_date,
            "slot": slot,
            "skipped_prior_slot": prior,
            "reason": payload["reason"],
        },
    )
    return payload


def _assert_prior_delivery(
    trading_date: str,
    slot: str,
    root: Path,
    *,
    skip_reason: str | None = None,
) -> dict | None:
    if _prior_delivery_complete(trading_date, slot, root):
        return None
    if skip_reason:
        return _record_prior_delivery_skip(trading_date, slot, skip_reason, root)
    prior = PRIOR_SLOT.get(slot)
    raise RuntimeError(
        f"{slot} cannot begin before {prior} has a complete delivery manifest"
    )


def _assert_not_already_delivered(trading_date: str, slot: str, root: Path) -> None:
    if _delivery_recorded(trading_date, slot, root):
        raise RuntimeError(
            f"{trading_date} {slot} is already delivered; duplicate workflow blocked"
        )


def _begin_lease_under_mutex(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
    skip_prior_delivery_reason: str | None = None,
    recovered_from_workflow_lease: dict | None = None,
) -> dict:
    _validate_identity(trading_date, slot)
    _assert_not_already_delivered(trading_date, slot, root)
    prior_delivery_skip = _assert_prior_delivery(
        trading_date,
        slot,
        root,
        skip_reason=skip_prior_delivery_reason,
    )
    target = active_path(root)
    existing = load_json(target)
    if existing:
        raise RuntimeError(
            "another workflow lease is active: "
            f"{existing.get('trading_date')} {existing.get('slot')} "
            f"lease_id={existing.get('lease_id')}; explicitly abandon or recover it"
        )
    token = uuid.uuid4().hex
    payload = {
        "schema_version": "1.0",
        "status": "active",
        "trading_date": trading_date,
        "slot": slot,
        "token": token,
        "lease_id": lease_id(token),
        "started_at": now_iso(),
        "owner_pid": os.getpid(),
    }
    if prior_delivery_skip:
        payload["prior_delivery_skip"] = {
            "skipped_prior_slot": prior_delivery_skip["skipped_prior_slot"],
            "reason": prior_delivery_skip["reason"],
        }
    if recovered_from_workflow_lease is not None:
        payload["recovered_from_workflow_lease"] = recovered_from_workflow_lease
    _atomic_create(target, payload)
    audit_payload = {
        "event": "begin",
        "at": payload["started_at"],
        "trading_date": trading_date,
        "slot": slot,
        "lease_id": payload["lease_id"],
    }
    if recovered_from_workflow_lease is not None:
        audit_payload["recovered_from_workflow_lease_id"] = (
            recovered_from_workflow_lease["lease_id"]
        )
    _append_audit(root, audit_payload)
    return payload


def begin_lease(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
    skip_prior_delivery_reason: str | None = None,
    recovered_from_workflow_lease: dict | None = None,
) -> dict:
    with production_start_guard(root):
        return _begin_lease_under_mutex(
            trading_date,
            slot,
            root=root,
            skip_prior_delivery_reason=skip_prior_delivery_reason,
            recovered_from_workflow_lease=recovered_from_workflow_lease,
        )


def assert_lease(
    trading_date: str,
    slot: str,
    token: str,
    *,
    root: Path = ROOT,
) -> dict:
    _validate_identity(trading_date, slot)
    payload = load_json(active_path(root))
    checks = {
        "active": bool(payload) and payload.get("status") == "active",
        "date": bool(payload) and payload.get("trading_date") == trading_date,
        "slot": bool(payload) and payload.get("slot") == slot,
        "token": bool(payload) and payload.get("token") == token,
        "lease_id": bool(payload) and payload.get("lease_id") == lease_id(token),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError("workflow lease validation failed: " + ", ".join(failed))
    return payload


def _close_lease(
    token: str,
    *,
    status: str,
    reason: str,
    root: Path,
) -> dict:
    target = active_path(root)
    payload = load_json(target)
    if not payload or payload.get("token") != token:
        raise RuntimeError("workflow lease owner mismatch")
    closed = dict(payload)
    closed.pop("token", None)
    closed["status"] = status
    closed["closed_at"] = now_iso()
    closed["reason"] = reason
    _archive(root, closed)
    _append_audit(
        root,
        {
            "event": status,
            "at": closed["closed_at"],
            "trading_date": closed["trading_date"],
            "slot": closed["slot"],
            "lease_id": closed["lease_id"],
            "reason": reason,
        },
    )
    current = load_json(target)
    if not current or current.get("token") != token:
        raise RuntimeError("workflow lease changed while closing")
    target.unlink()
    return closed


def complete_lease(token: str, *, artifact: str, root: Path = ROOT) -> dict:
    return _close_lease(
        token,
        status="delivered",
        reason=f"delivery manifest: {artifact}",
        root=root,
    )


def abandon_lease(token: str, *, reason: str, root: Path = ROOT) -> dict:
    if len(reason.strip()) < 8:
        raise ValueError("abandon reason must be explicit")
    return _close_lease(token, status="abandoned", reason=reason.strip(), root=root)


def recover_lease(
    trading_date: str,
    slot: str,
    *,
    reason: str,
    skip_prior_delivery_reason: str | None = None,
    from_lease_id: str | None = None,
    root: Path = ROOT,
) -> dict:
    if len(reason.strip()) < 8:
        raise ValueError("recovery reason must be explicit")
    existing = load_json(active_path(root))
    if existing:
        if from_lease_id is not None and existing.get("lease_id") != from_lease_id:
            raise RuntimeError("active workflow lease does not match --from-lease-id")
        archived = _close_lease(
            existing["token"],
            status="recovered",
            reason=reason.strip(),
            root=root,
        )
    elif from_lease_id is not None:
        archived = _load_recoverable_archived_lease(
            trading_date,
            slot,
            from_lease_id,
            root,
        )
        _append_audit(
            root,
            {
                "event": "recover_archived",
                "at": now_iso(),
                "trading_date": trading_date,
                "slot": slot,
                "lease_id": archived["lease_id"],
                "reason": reason.strip(),
            },
        )
    else:
        raise RuntimeError("no active workflow lease to recover")
    return begin_lease(
        trading_date,
        slot,
        root=root,
        skip_prior_delivery_reason=skip_prior_delivery_reason,
        recovered_from_workflow_lease=_recovered_from_payload(
            archived,
            reason,
        ),
    )
