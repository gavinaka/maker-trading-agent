"""Cross-process mutex between report production and authority maintenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORDINATION_STALE_SECONDS = 120
RECOVERY_COOLDOWN_SECONDS = 300


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def maintenance_lock_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / "authority_maintenance.lock.json"


def coordination_lock_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / ".authority_mutex.coordination.lock"


def audit_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / "authority_maintenance_audit.jsonl"


def recovery_request_path(root: Path = ROOT) -> Path:
    return root / "runtime_state" / "authority_maintenance_recovery_request.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now().astimezone()


def load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


@contextmanager
def coordination_guard(root: Path = ROOT):
    """Serialize production starts and maintenance claims on one filesystem."""
    path = coordination_lock_path(root)
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
            age = datetime.now().timestamp() - path.stat().st_mtime
            if attempt == 0 and age > COORDINATION_STALE_SECONDS:
                path.unlink(missing_ok=True)
                continue
            raise RuntimeError("authority mutex coordination is already in progress")
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


def active_production(root: Path = ROOT) -> dict:
    lease_path = root / "runtime_state" / "workflow_lease.json"
    gate_dir = root / "runtime_state" / "automation_gate"
    gates = []
    if gate_dir.is_dir():
        gates = sorted(path.name for path in gate_dir.glob("*.lock.json"))
    lease = load_json(lease_path)
    return {
        "workflow_lease": lease if lease and lease.get("status") == "active" else None,
        "automation_gate_locks": gates,
    }


def append_audit(payload: dict, *, root: Path = ROOT) -> None:
    target = audit_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


@contextmanager
def production_start_guard(root: Path = ROOT):
    """Block Gate/Lease creation while a maintenance window is active."""
    with coordination_guard(root):
        maintenance = load_json(maintenance_lock_path(root))
        if maintenance:
            raise RuntimeError(
                "authority maintenance mutex is active: "
                f"owner={maintenance.get('owner')} reason={maintenance.get('reason')}"
            )
        yield


def claim_maintenance(
    reason: str,
    *,
    owner: str = "Technical expert",
    root: Path = ROOT,
) -> dict:
    if len(reason.strip()) < 8:
        raise ValueError("maintenance reason must be explicit")
    if not owner.strip():
        raise ValueError("maintenance owner is required")
    target = maintenance_lock_path(root)
    with coordination_guard(root):
        if target.exists():
            existing = load_json(target) or {}
            raise RuntimeError(
                "authority maintenance mutex is already active: "
                f"owner={existing.get('owner')} reason={existing.get('reason')}"
            )
        production = active_production(root)
        if production["workflow_lease"] or production["automation_gate_locks"]:
            raise RuntimeError(
                "cannot start authority maintenance while report production is active"
            )
        payload = {
            "schema_version": "1.0",
            "status": "active",
            "token": uuid.uuid4().hex,
            "owner": owner.strip(),
            "reason": reason.strip(),
            "claimed_at": now_iso(),
            "pid": os.getpid(),
        }
        recovery_request_path(root).unlink(missing_ok=True)
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        append_audit(
            {
                "event": "claim",
                "owner": payload["owner"],
                "reason": payload["reason"],
                "claimed_at": payload["claimed_at"],
                "pid": payload["pid"],
            },
            root=root,
        )
        return payload


def release_maintenance(token: str, *, root: Path = ROOT) -> dict:
    target = maintenance_lock_path(root)
    with coordination_guard(root):
        payload = load_json(target)
        if not payload:
            raise RuntimeError("authority maintenance mutex is missing or invalid")
        if payload.get("token") != token:
            raise RuntimeError("authority maintenance mutex token does not match")
        released = dict(payload)
        released.pop("token", None)
        released["status"] = "released"
        released["released_at"] = now_iso()
        target.unlink()
        recovery_request_path(root).unlink(missing_ok=True)
        append_audit(
            {
                "event": "release",
                "owner": released["owner"],
                "reason": released["reason"],
                "claimed_at": released["claimed_at"],
                "released_at": released["released_at"],
            },
            root=root,
        )
        return released


def request_maintenance_recovery(
    reason: str,
    *,
    owner: str = "Technical expert",
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict:
    """Create a hash-bound recovery challenge without clearing the live lock."""
    if len(reason.strip()) < 8:
        raise ValueError("maintenance recovery reason must be explicit")
    if not owner.strip():
        raise ValueError("maintenance recovery owner is required")
    target = maintenance_lock_path(root)
    request_target = recovery_request_path(root)
    with coordination_guard(root):
        payload = load_json(target)
        if not payload:
            raise RuntimeError("authority maintenance mutex is missing or invalid")
        production = active_production(root)
        if production["workflow_lease"] or production["automation_gate_locks"]:
            raise RuntimeError(
                "cannot recover authority maintenance while report production is active"
            )
        lock_sha256 = _sha256_file(target)
        existing = load_json(request_target)
        if existing and existing.get("lock_sha256") == lock_sha256:
            return existing
        if request_target.exists():
            raise RuntimeError(
                "stale maintenance recovery request does not match the active lock"
            )
        requested_at = _now(now)
        request = {
            "schema_version": "1.0",
            "status": "cooldown",
            "challenge": uuid.uuid4().hex,
            "lock_sha256": lock_sha256,
            "requested_at": requested_at.isoformat(timespec="seconds"),
            "not_before": (
                requested_at + timedelta(seconds=RECOVERY_COOLDOWN_SECONDS)
            ).isoformat(timespec="seconds"),
            "requested_by": owner.strip(),
            "reason": reason.strip(),
        }
        descriptor = os.open(request_target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(request, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        append_audit(
            {
                "event": "recover_requested",
                "lock_sha256": request["lock_sha256"],
                "requested_at": request["requested_at"],
                "not_before": request["not_before"],
                "requested_by": request["requested_by"],
                "reason": request["reason"],
            },
            root=root,
        )
        return request


def recover_maintenance(
    *,
    challenge: str,
    expected_lock_sha256: str,
    confirm_orphaned: bool,
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict:
    """Clear only the exact lock after a five-minute orphan recovery cooldown."""
    if not confirm_orphaned:
        raise ValueError("maintenance recovery requires explicit orphan confirmation")
    target = maintenance_lock_path(root)
    request_target = recovery_request_path(root)
    with coordination_guard(root):
        payload = load_json(target)
        request = load_json(request_target)
        if not payload or not request:
            raise RuntimeError("maintenance lock or recovery request is missing")
        actual_lock_sha256 = _sha256_file(target)
        checks = {
            "challenge": request.get("challenge") == challenge,
            "expected_lock": request.get("lock_sha256") == expected_lock_sha256,
            "unchanged_lock": actual_lock_sha256 == expected_lock_sha256,
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            raise RuntimeError("maintenance recovery challenge mismatch: " + ", ".join(failed))
        if _now(now) < datetime.fromisoformat(str(request["not_before"])):
            raise RuntimeError("maintenance recovery cooldown is still active")
        production = active_production(root)
        if production["workflow_lease"] or production["automation_gate_locks"]:
            raise RuntimeError("cannot recover maintenance while report production is active")
        recovered = dict(payload)
        recovered.pop("token", None)
        recovered["status"] = "recovered"
        recovered["recovered_at"] = _now(now).isoformat(timespec="seconds")
        recovered["recovered_by"] = request["requested_by"]
        recovered["recovery_reason"] = request["reason"]
        target.unlink()
        request_target.unlink()
        append_audit(
            {
                "event": "recover",
                "lock_sha256": actual_lock_sha256,
                "claimed_at": recovered.get("claimed_at"),
                "recovered_at": recovered["recovered_at"],
                "recovered_by": recovered["recovered_by"],
                "recovery_reason": recovered["recovery_reason"],
            },
            root=root,
        )
        return recovered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    claim = commands.add_parser("claim")
    claim.add_argument("--reason", required=True)
    claim.add_argument("--owner", default="Technical expert")
    release = commands.add_parser("release")
    release.add_argument("--token", required=True)
    request_recovery = commands.add_parser("request-recovery")
    request_recovery.add_argument("--reason", required=True)
    request_recovery.add_argument("--owner", default="Technical expert")
    recover = commands.add_parser("recover")
    recover.add_argument("--challenge", required=True)
    recover.add_argument("--expected-lock-sha256", required=True)
    recover.add_argument("--confirm-orphaned", action="store_true", required=True)
    commands.add_parser("status")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "claim":
        payload = claim_maintenance(args.reason, owner=args.owner)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "release":
        payload = release_maintenance(args.token)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "request-recovery":
        payload = request_maintenance_recovery(args.reason, owner=args.owner)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "recover":
        payload = recover_maintenance(
            challenge=args.challenge,
            expected_lock_sha256=args.expected_lock_sha256,
            confirm_orphaned=args.confirm_orphaned,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(
        json.dumps(
            {
                "maintenance": load_json(maintenance_lock_path()),
                "recovery_request": load_json(recovery_request_path()),
                "production": active_production(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
