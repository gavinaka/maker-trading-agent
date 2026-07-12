"""Bind the actual Codex thread model and reasoning effort before analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.state_store import atomic_json_write


ROOT = Path(__file__).resolve().parents[1]


def required(trading_date: str, slot: str) -> bool:
    return (trading_date, {"morning": 0, "midday": 1, "evening": 2}[slot]) >= (
        "2026-07-12", 1
    )


def locate_session(thread_id: str, codex_home: Path | None = None) -> Path:
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    roots = (home / "sessions", home / "archived_sessions")
    matches = []
    for root in roots:
        if root.exists():
            matches.extend(root.rglob(f"*{thread_id}*.jsonl"))
    unique = sorted({path.resolve() for path in matches})
    if len(unique) != 1:
        raise ValueError(f"expected one session JSONL for thread {thread_id}, got {len(unique)}")
    return unique[0]


def extract_latest_settings(path: Path, *, expected_root: Path = ROOT) -> dict[str, Any]:
    session_id = None
    session_cwd = None
    latest = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = item.get("payload") or {}
        if item.get("type") == "session_meta":
            session_id = payload.get("id") or session_id
            session_cwd = payload.get("cwd") or session_cwd
        if item.get("type") == "turn_context":
            model = payload.get("model")
            effort = payload.get("effort") or payload.get("reasoning_effort")
            if model and effort:
                latest = {
                    "model": str(model),
                    "reasoning_effort": str(effort),
                    "turn_id": payload.get("turn_id"),
                    "source": "session_jsonl_turn_context",
                    "source_line": line_number,
                }
            session_cwd = payload.get("cwd") or session_cwd
        if item.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
            settings = payload.get("thread_settings") or {}
            model = settings.get("model")
            effort = settings.get("reasoning_effort")
            if model and effort:
                latest = {
                    "model": str(model),
                    "reasoning_effort": str(effort),
                    "turn_id": None,
                    "source": "session_jsonl_thread_settings",
                    "source_line": line_number,
                }
    if session_cwd is None or Path(session_cwd).resolve() != expected_root.resolve():
        raise ValueError(f"session cwd does not match Trading-System: {session_cwd}")
    if latest is None:
        raise ValueError("session JSONL does not expose model and reasoning effort")
    latest.update({"thread_id": session_id, "session_cwd": session_cwd})
    return latest


def _manifest_hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_manifest(
    trading_date: str,
    slot: str,
    *,
    session_jsonl: Path,
    required_effort: str = "max",
    root: Path = ROOT,
) -> dict[str, Any]:
    settings = extract_latest_settings(session_jsonl, expected_root=root)
    if settings["reasoning_effort"] != required_effort:
        raise ValueError(
            "actual host reasoning effort is not the required maximum: "
            f"actual={settings['reasoning_effort']} required={required_effort}"
        )
    payload: dict[str, Any] = {
        "schema_version": "codex-host-capability-v1",
        "status": "verified",
        "trading_date": trading_date,
        "slot": slot,
        "observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "required_effort": required_effort,
        **settings,
    }
    payload["manifest_sha256"] = _manifest_hash(payload)
    return payload


def manifest_path(trading_date: str, slot: str, *, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date / f"host_capability_{slot}.json"


def validate_manifest(
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
        payload.get("schema_version") != "codex-host-capability-v1"
        or payload.get("status") != "verified"
        or payload.get("trading_date") != trading_date
        or payload.get("slot") != slot
        or payload.get("required_effort") != "max"
        or payload.get("reasoning_effort") != "max"
        or not payload.get("model")
        or payload.get("manifest_sha256") != _manifest_hash(payload)
    ):
        raise ValueError("host capability manifest is invalid or does not prove MAX")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--session-jsonl", type=Path)
    parser.add_argument("--required-effort", default="max", choices=("max",))
    args = parser.parse_args()
    if not args.thread_id and args.session_jsonl is None:
        raise SystemExit("CODEX_THREAD_ID or --session-jsonl is required")
    source = args.session_jsonl or locate_session(args.thread_id)
    payload = build_manifest(
        args.date, args.slot, session_jsonl=source,
        required_effort=args.required_effort, root=ROOT
    )
    target = manifest_path(args.date, args.slot)
    atomic_json_write(target, payload)
    print(json.dumps({"status": "VERIFIED", "path": str(target), "model": payload["model"], "reasoning_effort": payload["reasoning_effort"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
