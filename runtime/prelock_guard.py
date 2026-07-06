"""Temporarily hide prior-judgment artifacts before the analysis lock.

The daily-report workflow requires the model/operator to avoid prior decisions
until the current report hash is locked. This module turns that rule into a
filesystem guard for the high-risk local artifacts that caused prior drift.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SLOT_ORDER = ("morning", "midday", "evening")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _safe_relative(path: Path, root: Path) -> str:
    resolved = path.resolve()
    base = root.resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError as exc:
        raise ValueError(f"guard target escapes repository root: {path}") from exc


def _previous_date(trading_date: str) -> str:
    return (date.fromisoformat(trading_date) - timedelta(days=1)).isoformat()


def _prior_slot_pairs(trading_date: str, slot: str) -> list[tuple[str, str]]:
    if slot not in SLOT_ORDER:
        raise ValueError(f"unsupported slot: {slot}")
    pairs: list[tuple[str, str]] = [(_previous_date(trading_date), "evening")]
    for prior_slot in SLOT_ORDER[: SLOT_ORDER.index(slot)]:
        pairs.append((trading_date, prior_slot))
    return pairs


def _candidate_paths_for_pair(root: Path, trading_date: str, slot: str) -> Iterable[Path]:
    runtime = root / "runtime_state" / trading_date
    outputs = root / "outputs"
    yield runtime / f"analysis_{slot}.json"
    yield runtime / f"decision_{slot}.json"
    yield outputs / f"{trading_date}_{slot}_combined.md"
    yield outputs / f"{trading_date}_{slot}_publish_payload.json"
    yield outputs / f"{trading_date}_{slot}_render.docx"


def prelock_guard_targets(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> list[Path]:
    """Return existing files that must be hidden before independent analysis."""
    targets: list[Path] = []
    seen: set[str] = set()
    context_log = root / "sessions" / "context_log.md"
    if context_log.is_file():
        relative = _safe_relative(context_log, root)
        targets.append(context_log)
        seen.add(relative)
    for pair_date, pair_slot in _prior_slot_pairs(trading_date, slot):
        for path in _candidate_paths_for_pair(root, pair_date, pair_slot):
            if not path.is_file():
                continue
            relative = _safe_relative(path, root)
            if relative in seen:
                continue
            targets.append(path)
            seen.add(relative)
    return targets


def guard_manifest_path(trading_date: str, slot: str, *, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date / f"prelock_guard_{slot}.json"


def _quarantine_path(root: Path, trading_date: str, slot: str, relative: str) -> Path:
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
    safe_name = relative.replace("/", "__").replace("\\", "__").replace(":", "_")
    return (
        root
        / "runtime_state"
        / trading_date
        / ".prelock_quarantine"
        / slot
        / f"{digest}_{safe_name}"
    )


def activate_prelock_guard(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> tuple[dict, Path]:
    """Move prior-judgment artifacts into a slot-local quarantine.

    The operation is idempotent while a guard is active. A restored manifest is
    replaced on the next prepare run for the same slot.
    """
    manifest_path = guard_manifest_path(trading_date, slot, root=root)
    existing = load_json(manifest_path)
    if existing and existing.get("status") == "active":
        return existing, manifest_path

    entries = []
    for target in prelock_guard_targets(trading_date, slot, root=root):
        relative = _safe_relative(target, root)
        quarantine = _quarantine_path(root, trading_date, slot, relative)
        if quarantine.exists():
            raise RuntimeError(f"pre-lock quarantine collision: {quarantine}")
        original_sha256 = sha256_file(target)
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        target.replace(quarantine)
        entries.append(
            {
                "original_path": relative,
                "quarantine_path": _safe_relative(quarantine, root),
                "sha256": original_sha256,
                "bytes": quarantine.stat().st_size,
            }
        )

    payload = {
        "schema_version": "1.0",
        "status": "active",
        "created_at": now_iso(),
        "trading_date": trading_date,
        "slot": slot,
        "policy": "pre_analysis_prior_judgment_files_quarantined_until_lock",
        "entries": entries,
    }
    atomic_json_write(manifest_path, payload)
    return payload, manifest_path


def restore_prelock_guard(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
    reason: str = "post_lock_or_session_close",
) -> tuple[dict | None, Path]:
    manifest_path = guard_manifest_path(trading_date, slot, root=root)
    payload = load_json(manifest_path)
    if not payload or payload.get("status") != "active":
        return payload, manifest_path

    for entry in payload.get("entries", []):
        if not isinstance(entry, dict):
            raise ValueError("pre-lock guard entry must be an object")
        original = (root / str(entry["original_path"])).resolve()
        quarantine = (root / str(entry["quarantine_path"])).resolve()
        _safe_relative(original, root)
        _safe_relative(quarantine, root)
        if not quarantine.is_file():
            raise RuntimeError(f"pre-lock quarantine file is missing: {quarantine}")
        if sha256_file(quarantine) != entry.get("sha256"):
            raise RuntimeError(
                f"pre-lock quarantine hash mismatch: {entry['original_path']}"
            )
        if original.exists():
            raise RuntimeError(
                f"cannot restore pre-lock artifact over existing file: {original}"
            )
        original.parent.mkdir(parents=True, exist_ok=True)
        quarantine.replace(original)

    payload["status"] = "restored"
    payload["restored_at"] = now_iso()
    payload["restore_reason"] = reason
    atomic_json_write(manifest_path, payload)
    return payload, manifest_path


def restore_all_active_prelock_guards(
    *,
    root: Path = ROOT,
    reason: str = "session_recovery",
) -> list[Path]:
    restored: list[Path] = []
    runtime_root = root / "runtime_state"
    if not runtime_root.is_dir():
        return restored
    for manifest_path in runtime_root.glob("*/prelock_guard_*.json"):
        payload = load_json(manifest_path)
        if not payload or payload.get("status") != "active":
            continue
        trading_date = str(payload.get("trading_date"))
        slot = str(payload.get("slot"))
        restore_prelock_guard(trading_date, slot, root=root, reason=reason)
        restored.append(manifest_path)
    return restored


def assert_no_active_prelock_guard(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> None:
    payload = load_json(guard_manifest_path(trading_date, slot, root=root))
    if payload and payload.get("status") == "active":
        raise RuntimeError(
            "pre-lock guard is still active; run lock-analysis successfully "
            "or abandon/recover the session before downstream steps"
        )
