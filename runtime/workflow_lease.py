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
import uuid
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLOTS = ("morning", "midday", "evening")
PRIOR_SLOT = {"midday": "morning", "evening": "midday"}
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def active_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / "workflow_lease.json"


def audit_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / "workflow_lease_audit.jsonl"


def lease_id(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
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
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


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
    target = directory / (
        f"{payload['trading_date']}_{payload['slot']}_{payload['lease_id']}.json"
    )
    if target.exists():
        existing = load_json(target)
        if existing != payload:
            raise RuntimeError(f"lease archive collision: {target}")
        return target
    _atomic_create(target, payload)
    return target


def _prior_delivery_complete(trading_date: str, slot: str, root: Path) -> bool:
    prior = PRIOR_SLOT.get(slot)
    if prior is None:
        return True
    target = (
        root
        / "runtime_state"
        / trading_date
        / f"delivery_{prior}.json"
    )
    delivery = load_json(target)
    required = (
        "frozen_verifier_pass",
        "unique_page_pass",
        "word_visual_qa_pass",
        "context_log_recorded",
    )
    return bool(
        delivery
        and delivery.get("trading_date") == trading_date
        and delivery.get("slot") == prior
        and all(delivery.get(flag) is True for flag in required)
    )


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
    target = (
        root
        / "runtime_state"
        / trading_date
        / f"delivery_{slot}.json"
    )
    delivery = load_json(target)
    required = (
        "frozen_verifier_pass",
        "unique_page_pass",
        "word_visual_qa_pass",
        "context_log_recorded",
    )
    if (
        delivery
        and delivery.get("trading_date") == trading_date
        and delivery.get("slot") == slot
        and all(delivery.get(flag) is True for flag in required)
    ):
        raise RuntimeError(
            f"{trading_date} {slot} is already delivered; duplicate workflow blocked"
        )


def begin_lease(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
    skip_prior_delivery_reason: str | None = None,
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
    _atomic_create(target, payload)
    _append_audit(
        root,
        {
            "event": "begin",
            "at": payload["started_at"],
            "trading_date": trading_date,
            "slot": slot,
            "lease_id": payload["lease_id"],
        },
    )
    return payload


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
    root: Path = ROOT,
) -> dict:
    if len(reason.strip()) < 8:
        raise ValueError("recovery reason must be explicit")
    existing = load_json(active_path(root))
    if not existing:
        raise RuntimeError("no active workflow lease to recover")
    _close_lease(
        existing["token"],
        status="recovered",
        reason=reason.strip(),
        root=root,
    )
    return begin_lease(
        trading_date,
        slot,
        root=root,
        skip_prior_delivery_reason=skip_prior_delivery_reason,
    )
