"""Freeze independent reasoning before prior-plan continuity is read."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.host_capability import validate_manifest as validate_host_capability_manifest
from runtime.reasoning_readiness import validate_reasoning_readiness_manifest
from runtime.state_store import atomic_json_write


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_INPUTS = {
    "capture_manifest",
    "transition",
    "host_capability",
    "golden_reasoning_manifest",
    "reasoning_contract",
    "adversarial_review",
    "decision_contract",
}
INDEPENDENCE_BOUNDARY = "prior_plan_and_actual_position_not_read_before_this_lock"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return {
        "path": resolved.relative_to(root.resolve()).as_posix(),
        "sha256": _sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _manifest_hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def manifest_path(trading_date: str, slot: str, *, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date / f"reasoning_lock_{slot}.json"


def write_reasoning_lock(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    target = manifest_path(trading_date, slot, root=root)
    if target.is_file():
        return validate_reasoning_lock(
            target, trading_date, slot, root=root
        ), target
    readiness, readiness_path = validate_reasoning_readiness_manifest(
        trading_date, slot, root=root
    )
    if not readiness or readiness_path is None:
        raise ValueError("reasoning lock requires certified reasoning readiness")
    records: dict[str, dict[str, Any]] = {}
    for key in sorted(REQUIRED_INPUTS):
        record = readiness.get(key) or {}
        path = root / str(record.get("path", ""))
        if record != _file_record(path, root):
            raise ValueError(f"reasoning lock input changed: {key}")
        records[key] = record
    host_path = root / records["host_capability"]["path"]
    host = validate_host_capability_manifest(
        host_path, trading_date, slot, root=root
    )
    if host.get("reasoning_effort") != "max":
        raise ValueError("independent reasoning lock requires exact max effort")
    payload: dict[str, Any] = {
        "schema_version": "independent-reasoning-lock-v1",
        "status": "locked",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "slot": slot,
        "independence_boundary": INDEPENDENCE_BOUNDARY,
        "actual_model": host["model"],
        "actual_reasoning_effort": host["reasoning_effort"],
        "reasoning_readiness": _file_record(readiness_path, root),
        "inputs": records,
    }
    payload["manifest_sha256"] = _manifest_hash(payload)
    atomic_json_write(target, payload)
    return payload, target


def validate_reasoning_lock(
    path: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved = path.resolve()
    resolved.relative_to((root / "runtime_state" / trading_date).resolve())
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "independent-reasoning-lock-v1"
        or payload.get("status") != "locked"
        or payload.get("trading_date") != trading_date
        or payload.get("slot") != slot
        or payload.get("independence_boundary") != INDEPENDENCE_BOUNDARY
        or payload.get("actual_reasoning_effort") != "max"
        or payload.get("manifest_sha256") != _manifest_hash(payload)
    ):
        raise ValueError("independent reasoning lock is invalid")
    readiness = payload.get("reasoning_readiness") or {}
    readiness_path = root / str(readiness.get("path", ""))
    if readiness != _file_record(readiness_path, root):
        raise ValueError("reasoning readiness changed after independent lock")
    validate_reasoning_readiness_manifest(trading_date, slot, root=root)
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != REQUIRED_INPUTS:
        raise ValueError("independent reasoning lock input set is incomplete")
    for key, record in inputs.items():
        path_value = root / str((record or {}).get("path", ""))
        if record != _file_record(path_value, root):
            raise ValueError(f"independent reasoning lock input changed: {key}")
    return payload
