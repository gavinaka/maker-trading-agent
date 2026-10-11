"""Verify that the Maker delivery fork has not changed its trading kernel."""

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from typing import Any


class KernelLockError(RuntimeError):
    """The local Maker fork no longer matches its approved kernel boundary."""


def _run_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise KernelLockError("maker_kernel_git_unavailable") from exc
    return completed.stdout.strip()


def _git_file_sha256(root: Path, revision: str, relative_path: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "show", f"{revision}:{relative_path}"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise KernelLockError("maker_kernel_git_unavailable") from exc
    return hashlib.sha256(completed.stdout).hexdigest()


def _lock_payload(root: Path) -> dict[str, Any]:
    path = root / "KERNEL_LOCK.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KernelLockError("maker_kernel_lock_invalid") from exc
    expected = {
        "schema_version",
        "source_agent",
        "source_commit",
        "source_worktree_uncommitted_changes_included",
        "delivery_contract",
        "prohibited_delivery_formats",
        "allowed_user_delivery",
        "approved_kernel_integrity_patch",
        "delivery_adapter_paths",
    }
    patch = payload.get("approved_kernel_integrity_patch")
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schema_version") != "maker-trading-agent-kernel-lock-v3"
        or payload.get("source_agent") != "Trading-System-vNext"
        or payload.get("source_worktree_uncommitted_changes_included") is not False
        or payload.get("allowed_user_delivery") != ["telegram_sendMessage"]
        or not isinstance(payload.get("source_commit"), str)
        or len(payload["source_commit"]) != 40
        or not isinstance(payload.get("delivery_adapter_paths"), list)
        or not all(isinstance(path, str) and path for path in payload["delivery_adapter_paths"])
        or not isinstance(patch, dict)
        or set(patch) != {"path", "baseline_sha256", "patched_sha256", "rationale"}
        or patch.get("path") != "runtime_vnext/validation/decision.py"
        or patch.get("rationale") != "directional_thesis_only_does_not_imply_submitted_candidate"
        or not all(
            isinstance(patch.get(key), str) and len(patch[key]) == 64
            for key in ("baseline_sha256", "patched_sha256")
        )
    ):
        raise KernelLockError("maker_kernel_lock_invalid")
    return payload


def assert_kernel_lock(root: Path) -> dict[str, Any]:
    """Fail closed if tracked runtime code escaped the delivery-adapter allowlist.

    The check deliberately compares against the sealed vNext commit in this
    repository only.  It never writes to or depends on a sibling worktree.
    """

    resolved = root.resolve()
    payload = _lock_payload(resolved)
    source_commit = str(payload["source_commit"])
    merge_base = _run_git(resolved, "merge-base", "HEAD", source_commit)
    if merge_base != source_commit:
        raise KernelLockError("maker_kernel_baseline_not_ancestor")

    changed = _run_git(resolved, "diff", "--name-only", source_commit, "--", "runtime_vnext")
    patch = payload["approved_kernel_integrity_patch"]
    approved_patch_path = str(patch["path"])
    if _git_file_sha256(resolved, source_commit, approved_patch_path) != patch[
        "baseline_sha256"
    ]:
        raise KernelLockError("maker_kernel_integrity_patch_baseline_mismatch")
    allowed = set(payload["delivery_adapter_paths"]) | {approved_patch_path}
    changed_paths = {line.replace("\\", "/") for line in changed.splitlines() if line.strip()}
    forbidden = sorted(changed_paths - allowed)
    if forbidden:
        raise KernelLockError("maker_kernel_tracked_file_changed")
    if approved_patch_path in changed_paths:
        actual = hashlib.sha256((resolved / approved_patch_path).read_bytes()).hexdigest()
        if actual != patch["patched_sha256"]:
            raise KernelLockError("maker_kernel_integrity_patch_hash_mismatch")

    untracked = _run_git(
        resolved,
        "ls-files",
        "--others",
        "--exclude-standard",
        "runtime_vnext",
    )
    untracked_paths = {line.replace("\\", "/") for line in untracked.splitlines() if line.strip()}
    if sorted(untracked_paths - allowed):
        raise KernelLockError("maker_kernel_untracked_file_changed")
    return payload


__all__ = ["KernelLockError", "assert_kernel_lock"]
