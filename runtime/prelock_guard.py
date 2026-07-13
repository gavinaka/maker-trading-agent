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

from runtime.prelock_read_policy import prelock_policy_manifest


ROOT = Path(__file__).resolve().parents[1]
SLOT_ORDER = ("morning", "midday", "evening")
PYTHON_CACHE_SUFFIXES = {".pyc", ".pyo"}


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


def _is_python_cache_artifact(path: Path | str) -> bool:
    candidate = Path(path)
    return "__pycache__" in candidate.parts or candidate.suffix.lower() in PYTHON_CACHE_SUFFIXES


def _is_current_slot_generated_output(relative: str, trading_date: str, slot: str) -> bool:
    return relative in {
        f"outputs/{trading_date}_{slot}_cards.json",
        f"outputs/{trading_date}_{slot}_combined.md",
        f"outputs/{trading_date}_{slot}_publish_payload.json",
        f"outputs/{trading_date}_{slot}_render.docx",
    }


def _is_current_slot_recovery_artifact(
    relative: str,
    trading_date: str,
    slot: str,
) -> bool:
    """Return artifacts that may survive pre-lock only for certified recovery.

    These files are created after the current slot's independent reasoning has
    already been certified.  They remain hidden during every ordinary prepare;
    the caller must explicitly opt in after validating the existing readiness
    manifest against the requested immutable capture.
    """
    if _is_current_slot_reasoning_recovery_artifact(relative, trading_date, slot):
        return True
    return _is_current_slot_draft_recovery_artifact(relative, trading_date, slot)


def _is_current_slot_reasoning_recovery_artifact(
    relative: str, trading_date: str, slot: str
) -> bool:
    return relative in {
        f"runtime_state/{trading_date}/reasoning_input_{slot}.json",
        f"runtime_state/{trading_date}/reasoning_contract_{slot}.json",
        f"runtime_state/{trading_date}/adversarial_review_input_{slot}.json",
        f"runtime_state/{trading_date}/adversarial_review_{slot}.json",
        f"runtime_state/{trading_date}/decision_input_{slot}.json",
        f"runtime_state/{trading_date}/decision_contract_{slot}.json",
    }


def _is_current_slot_draft_recovery_artifact(
    relative: str, trading_date: str, slot: str
) -> bool:
    if relative in {
        f"outputs/{trading_date}_{slot}_cards.json",
        f"outputs/{trading_date}_{slot}_combined.md",
    }:
        return True
    return (
        relative.startswith(f"outputs/blockbeats/{trading_date}_{slot}_")
        and relative.lower().endswith(".png")
    )


def _is_current_slot_generated_runtime_state(
    relative: str,
    trading_date: str,
    slot: str,
) -> bool:
    resolved_state = "base.json" if slot == "morning" else f"resolved_{slot}.json"
    return relative in {
        f"runtime_state/{trading_date}/reasoning_readiness_{slot}.json",
        f"runtime_state/{trading_date}/reasoning_lock_{slot}.json",
        f"runtime_state/{trading_date}/analysis_lock_{slot}.json",
        f"runtime_state/{trading_date}/analysis_{slot}.json",
        f"runtime_state/{trading_date}/decision_{slot}.json",
        f"runtime_state/{trading_date}/{resolved_state}",
        f"runtime_state/{trading_date}/current.json",
        f"runtime_state/{trading_date}/delivery_{slot}.json",
        f"runtime_state/{trading_date}/publish_{slot}.json",
        f"runtime_state/{trading_date}/publish_payload_{slot}.json",
        f"runtime_state/{trading_date}/report_preflight_{slot}.json",
        f"runtime_state/{trading_date}/render_{slot}.json",
        f"runtime_state/{trading_date}/word_qa_{slot}.json",
    }


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


def _prelock_broad_prior_judgment_paths(root: Path) -> Iterable[Path]:
    sessions_archive = root / "sessions" / "archive"
    if sessions_archive.is_dir():
        yield from (path for path in sessions_archive.rglob("*") if path.is_file())

    memory_aggregate = root / "memory" / "MEMORY.md"
    if memory_aggregate.is_file():
        yield memory_aggregate

    reviews = root / "reviews"
    if reviews.is_dir():
        yield from (path for path in reviews.rglob("*") if path.is_file())

    outputs = root / "outputs"
    if outputs.is_dir():
        for path in outputs.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".py":
                continue
            if _is_python_cache_artifact(path):
                continue
            yield path

    runtime_root = root / "runtime_state"
    if runtime_root.is_dir():
        prior_state_patterns = (
            "analysis_*.json",
            "decision_*.json",
            "context_*.json",
            "base.json",
            "current.json",
            "resolved_*.json",
            "delivery_*.json",
            "publish_*.json",
            "render_*.json",
            "word_qa_*.json",
            "evening_independent_review.json",
            "notion_*.json",
            "publish_payload_*.json",
            "report_preflight_*.json",
        )
        for date_dir in runtime_root.iterdir():
            if not date_dir.is_dir() or date_dir.name.startswith("."):
                continue
            for pattern in prior_state_patterns:
                yield from date_dir.glob(pattern)


def prelock_guard_targets(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
    preserve_certified_recovery_artifacts: bool = False,
    preserve_certified_draft_artifacts: bool = False,
) -> list[Path]:
    """Return existing files that must be hidden before independent analysis."""
    targets: list[Path] = []
    seen: set[str] = set()

    # Recovery rebinds the transition to a new workflow lease. The previous
    # readiness and independent lock therefore bind stale hashes even when the
    # certified reasoning inputs themselves are safe to reuse.
    for name in (
        f"reasoning_readiness_{slot}.json",
        f"reasoning_lock_{slot}.json",
    ):
        path = root / "runtime_state" / trading_date / name
        if path.is_file():
            relative = _safe_relative(path, root)
            targets.append(path)
            seen.add(relative)
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
    for path in _prelock_broad_prior_judgment_paths(root):
        relative = _safe_relative(path, root)
        if relative in seen:
            continue
        current_runtime_allowed = {
            f"runtime_state/{trading_date}/context_{slot}.json",
            f"runtime_state/{trading_date}/transition_{slot}.json",
            f"runtime_state/{trading_date}/golden_reasoning_{slot}.json",
            f"runtime_state/{trading_date}/prelock_guard_{slot}.json",
            f"runtime_state/{trading_date}/pretrade_gate.json",
            f"runtime_state/{trading_date}/usage.jsonl",
        }
        if relative in current_runtime_allowed:
            continue
        if preserve_certified_recovery_artifacts and _is_current_slot_reasoning_recovery_artifact(
            relative, trading_date, slot
        ):
            continue
        if preserve_certified_draft_artifacts and _is_current_slot_draft_recovery_artifact(
            relative, trading_date, slot
        ):
            continue
        if relative.startswith(
            f"runtime_state/{trading_date}/captures/{slot}/"
        ) or relative.startswith(f"runtime_state/{trading_date}/evidence/{slot}/"):
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
    preserve_certified_recovery_artifacts: bool = False,
    preserve_certified_draft_artifacts: bool = False,
    discard_stale_generated_on_abandon: bool = False,
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
    for target in prelock_guard_targets(
        trading_date,
        slot,
        root=root,
        preserve_certified_recovery_artifacts=(
            preserve_certified_recovery_artifacts
        ),
        preserve_certified_draft_artifacts=preserve_certified_draft_artifacts,
    ):
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
        "certified_recovery_artifacts_preserved": bool(
            preserve_certified_recovery_artifacts
        ),
        "certified_draft_artifacts_preserved": bool(
            preserve_certified_draft_artifacts
        ),
        "discard_stale_generated_on_abandon": bool(
            discard_stale_generated_on_abandon
        ),
        "safe_read_policy": prelock_policy_manifest(
            trading_date,
            slot,
            root=root,
        ),
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

    superseded_current_outputs: list[str] = []
    for entry in payload.get("entries", []):
        if not isinstance(entry, dict):
            raise ValueError("pre-lock guard entry must be an object")
        original_relative = str(entry["original_path"])
        original = (root / original_relative).resolve()
        quarantine = (root / str(entry["quarantine_path"])).resolve()
        _safe_relative(original, root)
        _safe_relative(quarantine, root)
        superseded_current_artifact = (
            (
                reason in {"analysis_lock_success", "reasoning_lock_success"}
                or (
                    reason == "abandon-session"
                    and payload.get("discard_stale_generated_on_abandon") is True
                )
            )
            and (
                _is_current_slot_generated_output(original_relative, trading_date, slot)
                or _is_current_slot_recovery_artifact(
                    original_relative,
                    trading_date,
                    slot,
                )
                or _is_current_slot_generated_runtime_state(
                    original_relative,
                    trading_date,
                    slot,
                )
            )
        )
        if not quarantine.is_file():
            if superseded_current_artifact:
                superseded_current_outputs.append(original_relative)
                continue
            if original.is_file() and sha256_file(original) == entry.get("sha256"):
                continue
            raise RuntimeError(f"pre-lock quarantine file is missing: {quarantine}")
        if sha256_file(quarantine) != entry.get("sha256"):
            raise RuntimeError(
                f"pre-lock quarantine hash mismatch: {entry['original_path']}"
            )
        if superseded_current_artifact:
            quarantine.unlink()
            superseded_current_outputs.append(original_relative)
            continue
        if original.exists():
            if original.is_file() and sha256_file(original) == entry.get("sha256"):
                quarantine.unlink()
                continue
            if _is_python_cache_artifact(entry["original_path"]) and original.is_file():
                original.unlink()
            else:
                raise RuntimeError(
                    f"cannot restore pre-lock artifact over existing file: {original}"
                )
        original.parent.mkdir(parents=True, exist_ok=True)
        quarantine.replace(original)

    payload["status"] = "restored"
    payload["restored_at"] = now_iso()
    payload["restore_reason"] = reason
    if superseded_current_outputs:
        payload["superseded_current_outputs"] = superseded_current_outputs
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
            "pre-lock guard is still active; run lock-reasoning successfully "
            "or abandon/recover the session before downstream steps"
        )
