"""Immutable per-stage attempt storage and a small mutable checkpoint pointer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .effort_policy import REQUESTED_EFFORT, REQUESTED_MODEL
from .methodology import canonical_sha256, sha256_file


STAGES = ("evidence", "reasoning", "decision", "report", "delivery")
STAGE_DEPENDENCY = {
    "evidence": None,
    "reasoning": "evidence",
    "decision": "reasoning",
    "report": "decision",
    "delivery": "report",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _seal_checkpoint(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed.pop("checkpoint_sha256", None)
    sealed["checkpoint_sha256"] = canonical_sha256(sealed)
    return sealed


def _seal_named_hash(payload: dict[str, Any], field: str) -> dict[str, Any]:
    sealed = dict(payload)
    sealed.pop(field, None)
    sealed[field] = canonical_sha256(sealed)
    return sealed


def _safe_name(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError(f"invalid {label}: {value}")
    return value


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return ctypes.windll.kernel32.GetLastError() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                process, ctypes.byref(exit_code)
            ):
                return True
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ArtifactStore:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.state_root = self.repo_root / "runtime_state_vnext"

    def slot_root(self, trading_date: str, slot: str) -> Path:
        date_root = self.date_root(trading_date)
        if slot not in {"morning", "midday", "evening"}:
            raise ValueError(f"invalid slot: {slot}")
        return date_root / slot

    def date_root(self, trading_date: str) -> Path:
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", trading_date):
            raise ValueError(f"invalid trading date: {trading_date}")
        try:
            datetime.strptime(trading_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"invalid trading date: {trading_date}") from exc
        return self.state_root / trading_date

    def run_root(self, trading_date: str, slot: str, run_id: str) -> Path:
        _safe_name(run_id, "run id")
        return self.slot_root(trading_date, slot) / run_id

    def create_run(
        self,
        trading_date: str,
        slot: str,
        *,
        methodology_manifest: dict[str, Any],
        requested_model: str = REQUESTED_MODEL,
        requested_effort: str = REQUESTED_EFFORT,
        run_mode: str,
        authorization_ref: str,
        run_id: str | None = None,
        allow_shadow_repeat: bool = False,
    ) -> dict[str, Any]:
        if requested_model != REQUESTED_MODEL or requested_effort != REQUESTED_EFFORT:
            raise ValueError(
                "vNext run requests must use gpt-5.6-sol with xhigh reasoning effort"
            )
        if run_mode not in {"shadow", "production"}:
            raise ValueError("vNext run_mode must be shadow or production")
        authorization_value = authorization_ref.strip()
        if not authorization_value:
            raise ValueError("vNext run mode requires an explicit authorization reference")
        authorization_ref_sha256 = hashlib.sha256(
            authorization_value.encode("utf-8")
        ).hexdigest()
        if allow_shadow_repeat and run_mode != "shadow":
            raise ValueError("allow_shadow_repeat is only valid for shadow runs")
        run_id = run_id or f"run-{uuid.uuid4().hex}"
        if not re.fullmatch(r"run-[A-Za-z0-9_.-]{4,80}", run_id):
            raise ValueError("vNext run id must use the run- prefix and 4..80 safe characters")
        root = self.run_root(trading_date, slot, run_id)
        current_path = self.slot_root(trading_date, slot) / "current.json"
        supersedes_run_id: str | None = None
        if current_path.exists():
            try:
                current = json.loads(current_path.read_text(encoding="utf-8"))
                current_run_id = str(current.get("run_id", "")).strip()
                current_root = self.run_root(trading_date, slot, current_run_id)
                current_run = self.load_run(current_root)
                current_checkpoint = self.load_checkpoint(current_root)
            except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "this vNext date/slot current pointer is invalid; manual review is required"
                ) from exc
            retired_replacement = (
                current_run.get("run_id") != current_run_id
                or current_checkpoint.get("run_id") != current_run_id
            )
            if retired_replacement:
                raise RuntimeError(
                    "this vNext date/slot current pointer is invalid; manual review is required"
                )
            current_status = current_checkpoint.get("status")
            valid_retired = (
                current_status == "retired"
                and (current_root / "retirement.json").is_file()
            )
            valid_shadow_repeat = (
                allow_shadow_repeat
                and run_mode == "shadow"
                and current_status == "shadow_complete"
                and current_checkpoint.get("completion_mode") == "shadow"
                and current_checkpoint.get("notion_published") is False
            )
            if not (valid_retired or valid_shadow_repeat):
                raise RuntimeError(
                    "this vNext date/slot already has a run; resume or explicitly retire it"
                )
            supersedes_run_id = current_run_id
        created_at = now_iso()
        active_path = self.state_root / "active_run.json"
        active = _seal_named_hash({
            "schema_version": "active-run-vnext-v1",
            "run_id": run_id,
            "trading_date": trading_date,
            "slot": slot,
            "run_mode": run_mode,
            "claimed_at": created_at,
            "lifecycle": "initializing",
            "initializer_pid": os.getpid(),
        }, "active_sha256")
        try:
            _exclusive_json(active_path, active)
        except FileExistsError as exc:
            if not self._reconcile_terminal_active_run(active_path):
                raise RuntimeError(
                    "another vNext report run is active; resume it instead of starting a second run"
                ) from exc
            try:
                _exclusive_json(active_path, active)
            except FileExistsError as retry_exc:
                raise RuntimeError(
                    "another vNext report run claimed the active position during recovery"
                ) from retry_exc
        try:
            root.mkdir(parents=True, exist_ok=False)
            run = {
                "schema_version": "daily-run-vnext-v2",
                "run_id": run_id,
                "trading_date": trading_date,
                "slot": slot,
                "run_mode": run_mode,
                "authorization_kind": (
                    "explicit_shadow_test_approval"
                    if run_mode == "shadow"
                    else "explicit_production_cutover_approval"
                ),
                "authorization_ref_sha256": authorization_ref_sha256,
                "created_at": created_at,
                "requested_model": requested_model,
                "requested_effort": requested_effort,
                "host_capability_required": True,
                "methodology_sha256": methodology_manifest["manifest_sha256"],
            }
            if supersedes_run_id is not None:
                run["supersedes_run_id"] = supersedes_run_id
                run["supersedes_terminal_status"] = current_checkpoint.get("status")
                if current_checkpoint.get("status") == "shadow_complete":
                    run["shadow_repeat"] = True
            _exclusive_json(root / "run.json", _seal_named_hash(run, "run_sha256"))
            _exclusive_json(root / "methodology_manifest.json", methodology_manifest)
            checkpoint = {
                "schema_version": "daily-checkpoint-vnext-v1",
                "run_id": run_id,
                "trading_date": trading_date,
                "slot": slot,
                "updated_at": created_at,
                "status": "running",
                "completed": {},
                "next_stage": "evidence",
            }
            _exclusive_json(root / "checkpoint.json", _seal_checkpoint(checkpoint))
            self._append_event(
                root,
                {
                    "event": "run_created",
                    "at": created_at,
                    "supersedes_run_id": supersedes_run_id,
                },
            )
            running_active = {
                "schema_version": "active-run-vnext-v1",
                "run_id": run_id,
                "trading_date": trading_date,
                "slot": slot,
                "run_mode": run_mode,
                "claimed_at": created_at,
                "lifecycle": "running",
                "initializer_pid": os.getpid(),
                "initialized_at": now_iso(),
            }
            self._replace_initializing_active(
                active_path,
                run_id,
                _seal_named_hash(running_active, "active_sha256"),
            )
            _atomic_json(
                current_path,
                {"run_id": run_id, "updated_at": created_at},
            )
        except Exception:
            self._release_active_if_owned(active_path, run_id)
            raise
        return run

    def _replace_initializing_active(
        self,
        active_path: Path,
        run_id: str,
        running_active: dict[str, Any],
    ) -> None:
        try:
            current = json.loads(active_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("vNext initialization lease disappeared or changed") from exc
        recorded_hash = current.get("active_sha256")
        clean = dict(current)
        clean.pop("active_sha256", None)
        if (
            current.get("schema_version") != "active-run-vnext-v1"
            or current.get("run_id") != run_id
            or current.get("lifecycle") != "initializing"
            or current.get("initializer_pid") != os.getpid()
            or recorded_hash != canonical_sha256(clean)
        ):
            raise RuntimeError("vNext initialization lease ownership changed")
        _atomic_json(active_path, running_active)

    def _reconcile_terminal_active_run(self, active_path: Path) -> bool:
        """Release only a sealed terminal lease left by a post-checkpoint crash."""

        try:
            observed = json.loads(active_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "existing vNext active-run lease is unreadable; manual review is required"
            ) from exc
        recorded_hash = observed.get("active_sha256")
        clean = dict(observed)
        clean.pop("active_sha256", None)
        if (
            observed.get("schema_version") != "active-run-vnext-v1"
            or recorded_hash != canonical_sha256(clean)
        ):
            raise RuntimeError(
                "existing vNext active-run lease is invalid; manual review is required"
            )
        lifecycle = observed.get("lifecycle")
        if lifecycle == "initializing":
            try:
                initializer_pid = int(observed.get("initializer_pid"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "existing vNext initialization lease owner is invalid"
                ) from exc
            if _pid_is_alive(initializer_pid):
                return False
            orphan = self.state_root / (
                "active_run.orphan-init-"
                f"{str(observed.get('run_id', 'unknown'))[:48]}-"
                f"{now_iso().replace(':', '').replace('+', '_')}.json"
            )
            try:
                os.replace(active_path, orphan)
            except FileNotFoundError:
                return True
            return True
        if lifecycle != "running":
            raise RuntimeError(
                "existing vNext active-run lifecycle is invalid; manual review is required"
            )
        try:
            old_root = self.run_root(
                str(observed.get("trading_date", "")),
                str(observed.get("slot", "")),
                str(observed.get("run_id", "")),
            )
        except ValueError as exc:
            raise RuntimeError(
                "existing vNext active-run lease path is invalid; manual review is required"
            ) from exc
        with self.controller_lock(old_root):
            try:
                current = json.loads(active_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                return True
            if current != observed:
                return False
            run = self.load_run(old_root)
            checkpoint = self.load_checkpoint(old_root)
            identity = (
                run.get("run_id"),
                run.get("trading_date"),
                run.get("slot"),
                run.get("run_mode"),
            )
            if identity != (
                observed.get("run_id"),
                observed.get("trading_date"),
                observed.get("slot"),
                observed.get("run_mode"),
            ):
                raise RuntimeError(
                    "terminal active-run identity differs from sealed run metadata"
                )
            if checkpoint.get("status") not in {"complete", "shadow_complete", "retired"}:
                return False
            self._recover_or_block_open_attempts(old_root)
            self._emit_terminal_sample_outcome_best_effort(old_root)
            self._append_event(
                old_root,
                {
                    "event": "terminal_active_run_reconciled",
                    "terminal_status": checkpoint.get("status"),
                },
            )
            self._release_active_if_owned(active_path, str(run["run_id"]))
        return not active_path.exists()

    @staticmethod
    def _release_active_if_owned(active_path: Path, run_id: str) -> None:
        try:
            active = json.loads(active_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if active.get("run_id") == run_id:
            active_path.unlink(missing_ok=True)

    def _emit_terminal_sample_outcome_best_effort(self, run_root: Path) -> None:
        """Emit an audit-only outcome without adding a production failure path."""

        target = run_root / "sample_outcome.json"
        existed = target.exists()
        try:
            from .sample_outcome import write_sample_outcome

            payload = write_sample_outcome(repo_root=self.repo_root, run_root=run_root)
        except Exception as exc:  # observer failures must never block terminal sealing
            try:
                self._append_event(
                    run_root,
                    {
                        "event": "sample_outcome_observer_failed",
                        "error_type": type(exc).__name__,
                    },
                )
            except Exception:
                pass
            return
        if not existed:
            try:
                self._append_event(
                    run_root,
                    {
                        "event": "sample_outcome_emitted",
                        "sample_outcome_sha256": payload["sample_outcome_sha256"],
                    },
                )
            except Exception:
                pass

    def _assert_active(self, run_root: Path) -> dict[str, Any]:
        run = self.load_run(run_root)
        path = self.state_root / "active_run.json"
        try:
            active = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise RuntimeError("vNext active-run lease is missing or invalid") from exc
        recorded_hash = active.get("active_sha256")
        clean = dict(active)
        clean.pop("active_sha256", None)
        if (
            active.get("schema_version") != "active-run-vnext-v1"
            or active.get("lifecycle") != "running"
            or recorded_hash != canonical_sha256(clean)
        ):
            raise RuntimeError("vNext active-run lease hash is invalid")
        expected = (
            run["run_id"],
            run["trading_date"],
            run["slot"],
            run.get("run_mode"),
        )
        actual = (
            active.get("run_id"),
            active.get("trading_date"),
            active.get("slot"),
            active.get("run_mode"),
        )
        if actual != expected:
            raise RuntimeError("vNext active-run lease belongs to another run")
        return active

    def load_run(self, run_root: Path) -> dict[str, Any]:
        try:
            payload = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("vNext run metadata is missing or invalid") from exc
        recorded_hash = payload.get("run_sha256")
        clean = dict(payload)
        clean.pop("run_sha256", None)
        schema_version = payload.get("schema_version")
        if schema_version not in {"daily-run-vnext-v1", "daily-run-vnext-v2"}:
            raise RuntimeError("vNext run metadata schema is invalid")
        if recorded_hash != canonical_sha256(clean):
            raise RuntimeError("vNext run metadata hash is invalid")
        if schema_version == "daily-run-vnext-v2":
            run_mode = payload.get("run_mode")
            expected_authorization_kind = (
                "explicit_shadow_test_approval"
                if run_mode == "shadow"
                else "explicit_production_cutover_approval"
                if run_mode == "production"
                else None
            )
            if (
                expected_authorization_kind is None
                or payload.get("authorization_kind") != expected_authorization_kind
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(payload.get("authorization_ref_sha256", "")),
                )
            ):
                raise RuntimeError("vNext run mode authorization binding is invalid")
        expected_root = self.run_root(
            str(payload.get("trading_date", "")).strip(),
            str(payload.get("slot", "")).strip(),
            str(payload.get("run_id", "")).strip(),
        ).resolve()
        if run_root.resolve() != expected_root:
            raise RuntimeError("vNext run metadata path binding is invalid")
        return payload

    def record_pretrade_gate(self, run_root: Path, **kwargs: Any) -> dict[str, Any]:
        from .pretrade_gate import (
            build_pretrade_gate_contract,
            validate_pretrade_gate_contract,
        )

        run = self.load_run(run_root)
        if (
            run.get("schema_version") != "daily-run-vnext-v2"
            or run.get("run_mode") != "production"
        ):
            raise ValueError("only a sealed production run may record a pretrade gate")
        trading_date = str(run["trading_date"])
        target = self.date_root(trading_date) / "pretrade_gate.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            validate_pretrade_gate_contract(existing, trading_date=trading_date)
            requested = build_pretrade_gate_contract(
                trading_date,
                recorded_at=existing.get("recorded_at"),
                **kwargs,
            )
            if existing != requested:
                raise ValueError("same-day vNext pretrade gate is immutable")
            return existing
        payload = build_pretrade_gate_contract(trading_date, **kwargs)
        _exclusive_json(target, payload)
        return payload

    def load_pretrade_gate(self, run_root: Path) -> dict[str, Any]:
        from .pretrade_gate import validate_pretrade_gate_contract

        run = self.load_run(run_root)
        if (
            run.get("schema_version") != "daily-run-vnext-v2"
            or run.get("run_mode") != "production"
        ):
            raise ValueError("shadow and legacy runs must not load a pretrade gate")
        trading_date = str(run["trading_date"])
        target = self.date_root(trading_date) / "pretrade_gate.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        return validate_pretrade_gate_contract(payload, trading_date=trading_date)

    @contextmanager
    def controller_lock(self, run_root: Path) -> Iterator[None]:
        path = run_root / ".controller.lock"
        lock_id = uuid.uuid4().hex
        lock_payload = {
            "schema_version": "controller-lock-vnext-v1",
            "lock_id": lock_id,
            "pid": os.getpid(),
            "claimed_at": now_iso(),
        }
        descriptor: int | None = None
        recovered_orphan: str | None = None
        for _ in range(3):
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(
                        descriptor,
                        (json.dumps(lock_payload, sort_keys=True) + "\n").encode("utf-8"),
                    )
                    os.fsync(descriptor)
                except Exception:
                    os.close(descriptor)
                    descriptor = None
                    path.unlink(missing_ok=True)
                    raise
                break
            except FileExistsError:
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    existing_pid = int(existing.get("pid"))
                    existing_lock_id = str(existing.get("lock_id", ""))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        "controller lock is invalid; manual review is required"
                    ) from exc
                if (
                    existing.get("schema_version") != "controller-lock-vnext-v1"
                    or not existing_lock_id
                    or _pid_is_alive(existing_pid)
                ):
                    raise RuntimeError("another controller process is active")
                orphan = run_root / (
                    f".controller.lock.orphan-{now_iso().replace(':', '').replace('+', '_')}-"
                    f"{existing_lock_id[:12]}.json"
                )
                try:
                    os.replace(path, orphan)
                    recovered_orphan = orphan.name
                except FileNotFoundError:
                    continue
        if descriptor is None:
            raise RuntimeError("controller lock could not be acquired")
        try:
            if recovered_orphan:
                self._append_event(
                    run_root,
                    {
                        "event": "controller_lock_orphan_recovered",
                        "orphan_record": recovered_orphan,
                    },
                )
            yield
        finally:
            os.close(descriptor)
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                current = {}
            if current.get("lock_id") == lock_id:
                path.unlink(missing_ok=True)

    def _append_event(self, run_root: Path, payload: dict[str, Any]) -> None:
        record = dict(payload)
        record.setdefault("at", now_iso())
        with (run_root / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def load_checkpoint(self, run_root: Path) -> dict[str, Any]:
        payload = json.loads((run_root / "checkpoint.json").read_text(encoding="utf-8"))
        recorded_hash = payload.get("checkpoint_sha256")
        clean = dict(payload)
        clean.pop("checkpoint_sha256", None)
        if (
            payload.get("schema_version") != "daily-checkpoint-vnext-v1"
            or recorded_hash != canonical_sha256(clean)
        ):
            raise ValueError("invalid vNext checkpoint")
        return payload

    def _next_attempt(self, run_root: Path, stage: str) -> tuple[int, Path]:
        if stage not in STAGES:
            raise ValueError(f"invalid stage: {stage}")
        directory = run_root / stage
        numbers = []
        if directory.is_dir():
            for child in directory.iterdir():
                match = re.fullmatch(r"attempt-(\d{3})", child.name)
                if child.is_dir() and match:
                    numbers.append(int(match.group(1)))
        number = max(numbers, default=0) + 1
        target = directory / f"attempt-{number:03d}"
        return number, target

    @staticmethod
    def _attempt_number(path: Path) -> int:
        match = re.fullmatch(r"attempt-(\d{3})", path.name)
        if not path.is_dir() or match is None:
            raise ValueError(f"invalid stage attempt directory: {path.name}")
        return int(match.group(1))

    def _load_attempt_record(
        self,
        attempt_root: Path,
        *,
        stage: str,
        attempt: int,
    ) -> dict[str, Any]:
        try:
            payload = json.loads((attempt_root / "attempt.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("stage attempt record is missing or invalid; manual review is required") from exc
        recorded_hash = payload.get("attempt_sha256")
        clean = dict(payload)
        clean.pop("attempt_sha256", None)
        if (
            payload.get("schema_version") != "stage-attempt-vnext-v1"
            or payload.get("stage") != stage
            or payload.get("attempt") != attempt
            or payload.get("status") != "running"
            or recorded_hash != canonical_sha256(clean)
        ):
            raise RuntimeError("stage attempt record changed; manual review is required")
        return payload

    def load_open_attempt_record(
        self,
        run_root: Path,
        stage: str,
        attempt: int,
    ) -> dict[str, Any]:
        """Return the hash-verified record for the caller-owned open attempt.

        Stage validators use the sealed ``started_at`` as an upper time bound.
        Exposing it through the artifact store keeps that binding on the same
        integrity path as attempt completion instead of rereading JSON ad hoc.
        """

        attempt_root = self._assert_open_attempt_owner(run_root, stage, attempt)
        return self._load_attempt_record(
            attempt_root,
            stage=stage,
            attempt=attempt,
        )

    @staticmethod
    def _attempt_has_terminal_record(attempt_root: Path) -> bool:
        terminals = [
            attempt_root / "manifest.json",
            attempt_root / "failure.json",
            attempt_root / "orphaned.json",
        ]
        existing = [path for path in terminals if path.exists()]
        if len(existing) > 1:
            raise RuntimeError("stage attempt has conflicting terminal records")
        return bool(existing)

    def _recover_or_block_open_attempts(self, run_root: Path) -> None:
        for stage in STAGES:
            stage_root = run_root / stage
            if not stage_root.is_dir():
                continue
            for attempt_root in sorted(stage_root.glob("attempt-*")):
                attempt = self._attempt_number(attempt_root)
                if self._attempt_has_terminal_record(attempt_root):
                    continue
                record = self._load_attempt_record(
                    attempt_root,
                    stage=stage,
                    attempt=attempt,
                )
                try:
                    owner_pid = int(record.get("owner_pid"))
                    owner_thread_id = int(record.get("owner_thread_id"))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "stage attempt owner is invalid; manual review is required"
                    ) from exc
                owner_alive = _pid_is_alive(owner_pid)
                if owner_alive:
                    raise RuntimeError(
                        f"stage attempt is already active: {stage}/attempt-{attempt:03d}"
                    )
                orphan = {
                    "schema_version": "stage-orphan-vnext-v1",
                    "stage": stage,
                    "attempt": attempt,
                    "owner_pid": owner_pid,
                    "owner_thread_id": owner_thread_id,
                    "recovered_at": now_iso(),
                    "reason": "owner process or execution context is no longer active",
                    "attempt_record_sha256": sha256_file(attempt_root / "attempt.json"),
                }
                _exclusive_json(
                    attempt_root / "orphaned.json",
                    _seal_named_hash(orphan, "orphan_sha256"),
                )
                self._append_event(
                    run_root,
                    {
                        "event": "stage_attempt_orphan_recovered",
                        "stage": stage,
                        "attempt": attempt,
                    },
                )

    def _assert_open_attempt_owner(
        self,
        run_root: Path,
        stage: str,
        attempt: int,
    ) -> Path:
        attempt_root = run_root / stage / f"attempt-{attempt:03d}"
        if self._attempt_has_terminal_record(attempt_root):
            raise RuntimeError("stage attempt is already terminal")
        record = self._load_attempt_record(
            attempt_root,
            stage=stage,
            attempt=attempt,
        )
        if (
            record.get("owner_pid") != os.getpid()
            or record.get("owner_thread_id") != threading.get_ident()
        ):
            raise RuntimeError("stage attempt can only be completed by its owner")
        return attempt_root

    def _validate_output_records(
        self,
        attempt_root: Path,
        outputs: dict[str, dict[str, Any]],
    ) -> None:
        if not outputs:
            raise ValueError("completed stage requires at least one output")
        for name, record in outputs.items():
            _safe_name(name, "output name")
            if not isinstance(record, dict):
                raise ValueError(f"stage output record is invalid: {name}")
            target = (self.repo_root / str(record.get("path", ""))).resolve()
            try:
                target.relative_to(attempt_root.resolve())
            except ValueError as exc:
                raise ValueError(f"stage output escapes its attempt: {name}") from exc
            if (
                not target.is_file()
                or sha256_file(target) != record.get("sha256")
                or target.stat().st_size != record.get("bytes")
            ):
                raise ValueError(f"stage output record does not match bytes: {name}")

    def begin_attempt(self, run_root: Path, stage: str) -> tuple[int, Path]:
        with self.controller_lock(run_root):
            self._assert_active(run_root)
            self._recover_or_block_open_attempts(run_root)
            checkpoint = self.load_checkpoint(run_root)
            if checkpoint.get("status") in {"complete", "shadow_complete"}:
                raise RuntimeError("vNext run is already complete")
            if checkpoint.get("status") == "needs_review":
                raise RuntimeError("manual review authorization is required before retry")
            if checkpoint.get("next_stage") != stage:
                raise RuntimeError(
                    f"vNext state expects {checkpoint.get('next_stage')}, not {stage}"
                )
            dependency = STAGE_DEPENDENCY[stage]
            if dependency and dependency not in checkpoint.get("completed", {}):
                raise ValueError(f"stage {stage} requires completed {dependency}")
            number, target = self._next_attempt(run_root, stage)
            target.mkdir(parents=True, exist_ok=False)
            attempt = {
                "schema_version": "stage-attempt-vnext-v1",
                "stage": stage,
                "attempt": number,
                "status": "running",
                "started_at": now_iso(),
                "owner_pid": os.getpid(),
                "owner_thread_id": threading.get_ident(),
                "input_bindings": dict(checkpoint.get("completed", {})),
            }
            _exclusive_json(
                target / "attempt.json",
                _seal_named_hash(attempt, "attempt_sha256"),
            )
            self._append_event(run_root, {"event": "stage_started", "stage": stage, "attempt": number})
            return number, target

    def resume_after_manual_review(
        self,
        run_root: Path,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        with self.controller_lock(run_root):
            self._assert_active(run_root)
            checkpoint = self.load_checkpoint(run_root)
            if checkpoint.get("status") != "needs_review":
                raise RuntimeError("run is not waiting for manual review")
            retry_stage = authorization["retry_stage"]
            last_failure = checkpoint.get("last_failure") or {}
            if retry_stage not in STAGES or retry_stage != last_failure.get("stage"):
                raise ValueError("manual review retry_stage must match the failed stage")
            review_root = run_root / "manual_reviews"
            review_root.mkdir(parents=True, exist_ok=True)
            number = len(list(review_root.glob("review-*.json"))) + 1
            target = review_root / f"review-{number:03d}.json"
            _exclusive_json(target, authorization)
            checkpoint.update(
                {
                    "updated_at": now_iso(),
                    "status": "running",
                    "next_stage": retry_stage,
                    "last_manual_review": {
                        "path": target.relative_to(self.repo_root).as_posix(),
                        "manifest_sha256": sha256_file(target),
                    },
                }
            )
            _atomic_json(run_root / "checkpoint.json", _seal_checkpoint(checkpoint))
            self._append_event(
                run_root,
                {
                    "event": "manual_review_authorized",
                    "retry_stage": retry_stage,
                    "review": number,
                },
            )
        return authorization

    def retire_run(
        self,
        run_root: Path,
        authorization: dict[str, Any],
    ) -> dict[str, Any]:
        with self.controller_lock(run_root):
            self._assert_active(run_root)
            # Retirement is an explicit operator decision, but it must not race
            # a live stage owner.  Dead owners are sealed as orphan evidence;
            # a live owner keeps exclusive authority until it exits.
            self._recover_or_block_open_attempts(run_root)
            checkpoint = self.load_checkpoint(run_root)
            if checkpoint.get("status") in {"complete", "shadow_complete", "retired"}:
                raise RuntimeError("completed or retired run cannot be retired again")
            target = run_root / "retirement.json"
            _exclusive_json(target, authorization)
            checkpoint.update(
                {
                    "updated_at": now_iso(),
                    "status": "retired",
                    "next_stage": None,
                    "retirement": {
                        "path": target.relative_to(self.repo_root).as_posix(),
                        "sha256": sha256_file(target),
                    },
                }
            )
            _atomic_json(run_root / "checkpoint.json", _seal_checkpoint(checkpoint))
            self._append_event(
                run_root,
                {
                    "event": "run_retired",
                    "authorization_sha256": authorization["manifest_sha256"],
                },
            )
            self._emit_terminal_sample_outcome_best_effort(run_root)
            active_path = self.state_root / "active_run.json"
            self._assert_active(run_root)
            self._release_active_if_owned(active_path, str(checkpoint["run_id"]))
        return authorization

    def write_payload(self, attempt_root: Path, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
        _safe_name(filename, "artifact filename")
        target = attempt_root / filename
        _exclusive_json(target, payload)
        return {
            "path": target.relative_to(self.repo_root).as_posix(),
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
        }

    def write_text(self, attempt_root: Path, filename: str, text: str) -> dict[str, Any]:
        _safe_name(filename, "artifact filename")
        target = attempt_root / filename
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {
            "path": target.relative_to(self.repo_root).as_posix(),
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
        }

    def complete_attempt(
        self,
        run_root: Path,
        stage: str,
        attempt: int,
        outputs: dict[str, dict[str, Any]],
        *,
        gate: dict[str, Any],
        terminal_status: str = "complete",
        terminal_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.controller_lock(run_root):
            self._assert_active(run_root)
            checkpoint = self.load_checkpoint(run_root)
            if checkpoint.get("next_stage") != stage:
                raise RuntimeError(
                    f"checkpoint expects {checkpoint.get('next_stage')}, not completion of {stage}"
                )
            attempt_root = self._assert_open_attempt_owner(run_root, stage, attempt)
            self._validate_output_records(attempt_root, outputs)
            stage_index = STAGES.index(stage)
            next_stage = STAGES[stage_index + 1] if stage_index + 1 < len(STAGES) else None
            if terminal_status not in {"complete", "shadow_complete"}:
                raise ValueError("terminal status must be complete or shadow_complete")
            if next_stage is not None and terminal_status != "complete":
                raise ValueError("shadow_complete is only valid for the final stage")
            if terminal_metadata is not None:
                if next_stage is not None:
                    raise ValueError("terminal metadata is only valid for the final stage")
                if not isinstance(terminal_metadata, dict):
                    raise ValueError("terminal metadata must be an object")
                allowed_terminal_metadata = {"completion_mode", "notion_published"}
                if set(terminal_metadata) - allowed_terminal_metadata:
                    raise ValueError("terminal metadata contains unsupported checkpoint fields")
            if terminal_status == "shadow_complete" and terminal_metadata != {
                "completion_mode": "shadow",
                "notion_published": False,
            }:
                raise ValueError("shadow_complete requires explicit shadow completion metadata")
            manifest = {
                "schema_version": "stage-manifest-vnext-v1",
                "stage": stage,
                "attempt": attempt,
                "status": "passed",
                "completed_at": now_iso(),
                "outputs": outputs,
                "gate": gate,
            }
            manifest["manifest_sha256"] = canonical_sha256(manifest)
            _exclusive_json(attempt_root / "manifest.json", manifest)
            completed = dict(checkpoint.get("completed", {}))
            for later in STAGES[stage_index + 1 :]:
                completed.pop(later, None)
            completed[stage] = {
                "attempt": attempt,
                "manifest_path": (attempt_root / "manifest.json").relative_to(self.repo_root).as_posix(),
                "manifest_sha256": sha256_file(attempt_root / "manifest.json"),
                "outputs": outputs,
            }
            checkpoint.update(
                {
                    "updated_at": now_iso(),
                    "status": terminal_status if next_stage is None else "running",
                    "completed": completed,
                    "next_stage": next_stage,
                }
            )
            if next_stage is None and terminal_metadata:
                checkpoint.update(terminal_metadata)
            _atomic_json(run_root / "checkpoint.json", _seal_checkpoint(checkpoint))
            event = {"event": "stage_passed", "stage": stage, "attempt": attempt}
            if next_stage is None:
                event["terminal_status"] = terminal_status
            self._append_event(run_root, event)
            if next_stage is None:
                self._emit_terminal_sample_outcome_best_effort(run_root)
                active_path = self.state_root / "active_run.json"
                self._assert_active(run_root)
                self._release_active_if_owned(active_path, str(checkpoint["run_id"]))
        return manifest

    def fail_attempt(
        self,
        run_root: Path,
        stage: str,
        attempt: int,
        *,
        failure_class: str,
        retryable: bool,
        retry_scope: str,
        defects: list[dict[str, Any]],
        needs_manual_review: bool = False,
    ) -> dict[str, Any]:
        with self.controller_lock(run_root):
            self._assert_active(run_root)
            checkpoint = self.load_checkpoint(run_root)
            if checkpoint.get("next_stage") != stage:
                raise RuntimeError(
                    f"checkpoint expects {checkpoint.get('next_stage')}, not failure of {stage}"
                )
            attempt_root = self._assert_open_attempt_owner(run_root, stage, attempt)
            failure = {
                "schema_version": "stage-failure-vnext-v1",
                "stage": stage,
                "attempt": attempt,
                "status": "failed",
                "failed_at": now_iso(),
                "failure_class": failure_class,
                "retryable": retryable,
                "retry_scope": retry_scope,
                "needs_manual_review": needs_manual_review,
                "defects": defects,
            }
            failure["failure_sha256"] = canonical_sha256(failure)
            _exclusive_json(attempt_root / "failure.json", failure)
            checkpoint.update(
                {
                    "updated_at": now_iso(),
                    "status": "needs_review" if needs_manual_review else "retryable_failure",
                    "next_stage": None if needs_manual_review else retry_scope,
                    "last_failure": {
                        "stage": stage,
                        "attempt": attempt,
                        "path": (attempt_root / "failure.json").relative_to(self.repo_root).as_posix(),
                    },
                }
            )
            _atomic_json(run_root / "checkpoint.json", _seal_checkpoint(checkpoint))
            self._append_event(run_root, {"event": "stage_failed", "stage": stage, "attempt": attempt, "failure_class": failure_class})
        return failure

    def load_stage_output_record(
        self,
        run_root: Path,
        stage: str,
        output_name: str,
    ) -> dict[str, Any]:
        checkpoint = self.load_checkpoint(run_root)
        completed = checkpoint.get("completed", {}).get(stage)
        if not isinstance(completed, dict):
            raise ValueError(f"stage is not complete: {stage}")
        manifest_path = (self.repo_root / str(completed.get("manifest_path", ""))).resolve()
        manifest_path.relative_to(run_root.resolve())
        if (
            not manifest_path.is_file()
            or sha256_file(manifest_path) != completed.get("manifest_sha256")
        ):
            raise ValueError(f"stage manifest changed: {stage}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != "stage-manifest-vnext-v1"
            or manifest.get("stage") != stage
            or manifest.get("status") != "passed"
            or manifest.get("manifest_sha256") != canonical_sha256(manifest)
            or manifest.get("outputs") != completed.get("outputs")
        ):
            raise ValueError(f"stage manifest is invalid: {stage}")
        output = (completed.get("outputs") or {}).get(output_name)
        if not isinstance(output, dict):
            raise ValueError(f"stage output is missing: {stage}.{output_name}")
        target = (self.repo_root / output["path"]).resolve()
        target.relative_to(self.repo_root)
        if not target.is_file() or sha256_file(target) != output.get("sha256"):
            raise ValueError(f"stage output changed: {stage}.{output_name}")
        if target.stat().st_size != output.get("bytes"):
            raise ValueError(f"stage output size changed: {stage}.{output_name}")
        return dict(output)

    def load_stage_payload(self, run_root: Path, stage: str, output_name: str) -> dict[str, Any]:
        output = self.load_stage_output_record(run_root, stage, output_name)
        target = (self.repo_root / output["path"]).resolve()
        return json.loads(target.read_text(encoding="utf-8"))

    def attempt_count(self, run_root: Path, stage: str) -> int:
        directory = run_root / stage
        return len([path for path in directory.glob("attempt-*") if path.is_dir()]) if directory.is_dir() else 0

    def failure_count(
        self,
        run_root: Path,
        stage: str,
        *,
        failure_class: str | None = None,
    ) -> int:
        directory = run_root / stage
        if not directory.is_dir():
            return 0
        count = 0
        for path in directory.glob("attempt-*/failure.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise RuntimeError("stage failure record is unreadable; manual review is required")
            attempt = self._attempt_number(path.parent)
            recorded_hash = payload.get("failure_sha256")
            clean = dict(payload)
            clean.pop("failure_sha256", None)
            if (
                payload.get("schema_version") != "stage-failure-vnext-v1"
                or payload.get("stage") != stage
                or payload.get("attempt") != attempt
                or payload.get("status") != "failed"
                or recorded_hash != canonical_sha256(clean)
            ):
                raise RuntimeError("stage failure record is invalid; manual review is required")
            if failure_class is None or payload.get("failure_class") == failure_class:
                count += 1
        return count

    def safe_status(self, run_root: Path) -> dict[str, Any]:
        run = self.load_run(run_root)
        checkpoint = self.load_checkpoint(run_root)
        return {
            "run_id": checkpoint["run_id"],
            "trading_date": checkpoint["trading_date"],
            "slot": checkpoint["slot"],
            "run_mode": (
                run.get("run_mode")
                if run.get("schema_version") == "daily-run-vnext-v2"
                else "legacy_unknown"
            ),
            "status": checkpoint["status"],
            "completed_stages": [stage for stage in STAGES if stage in checkpoint.get("completed", {})],
            "next_stage": checkpoint.get("next_stage"),
            "attempt_counts": {stage: self.attempt_count(run_root, stage) for stage in STAGES},
        }
