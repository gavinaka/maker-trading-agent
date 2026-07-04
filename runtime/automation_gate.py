"""Atomic idempotency gate for recurring local Codex automations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_DIR = ROOT / "runtime_state" / "automation_gate"
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

EXIT_DONE = 10
EXIT_IN_PROGRESS = 11


def now() -> datetime:
    return datetime.now().astimezone()


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def validate_key(value: str) -> str:
    if not KEY_RE.fullmatch(value):
        raise ValueError("key must contain only letters, digits, dot, underscore, or hyphen")
    return value


def paths(key: str) -> tuple[Path, Path]:
    return GATE_DIR / f"{key}.lock.json", GATE_DIR / f"{key}.done.json"


def load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def external_done(path: Path | None, required_flags: list[str]) -> bool:
    if path is None or not path.is_file():
        return False
    if not required_flags:
        return True
    payload = load_json(path)
    return bool(payload) and all(payload.get(flag) is True for flag in required_flags)


def claim(args: argparse.Namespace) -> int:
    key = validate_key(args.key)
    lock_path, done_path = paths(key)
    external_path = Path(args.done_file).resolve() if args.done_file else None

    if done_path.is_file() or external_done(external_path, args.require_json_flag):
        print(json.dumps({"status": "done", "key": key}, ensure_ascii=False))
        return EXIT_DONE

    GATE_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    payload = {
        "key": key,
        "token": token,
        "claimed_at": now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
    }

    for attempt in range(2):
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            existing = load_json(lock_path) or {}
            claimed_at = existing.get("claimed_at")
            try:
                claimed = datetime.fromisoformat(claimed_at)
            except (TypeError, ValueError):
                claimed = datetime.fromtimestamp(
                    lock_path.stat().st_mtime,
                    tz=now().tzinfo,
                )
            if now() - claimed <= timedelta(minutes=args.stale_minutes):
                print(
                    json.dumps(
                        {
                            "status": "in_progress",
                            "key": key,
                            "claimed_at": claimed.isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                    )
                )
                return EXIT_IN_PROGRESS
            if attempt == 0:
                lock_path.unlink(missing_ok=True)
                continue
            raise
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(json.dumps({"status": "claimed", "key": key, "token": token}))
            return 0

    raise RuntimeError("could not claim automation gate")


def assert_owner(lock_path: Path, token: str) -> dict:
    payload = load_json(lock_path)
    if not payload:
        raise ValueError("automation lock is missing or invalid")
    if payload.get("token") != token:
        raise ValueError("automation lock token does not match")
    return payload


def complete(args: argparse.Namespace) -> int:
    key = validate_key(args.key)
    lock_path, done_path = paths(key)
    lock = assert_owner(lock_path, args.token)
    payload = {
        "key": key,
        "completed_at": now().isoformat(timespec="seconds"),
        "claimed_at": lock["claimed_at"],
        "artifact": args.artifact,
    }
    atomic_json_write(done_path, payload)
    lock_path.unlink()
    print(json.dumps({"status": "completed", "key": key}, ensure_ascii=False))
    return 0


def release(args: argparse.Namespace) -> int:
    key = validate_key(args.key)
    lock_path, _ = paths(key)
    assert_owner(lock_path, args.token)
    lock_path.unlink()
    print(json.dumps({"status": "released", "key": key}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    claim_parser = commands.add_parser("claim")
    claim_parser.add_argument("--key", required=True)
    claim_parser.add_argument("--stale-minutes", type=int, default=240)
    claim_parser.add_argument("--done-file")
    claim_parser.add_argument(
        "--require-json-flag",
        action="append",
        default=[],
    )

    complete_parser = commands.add_parser("complete")
    complete_parser.add_argument("--key", required=True)
    complete_parser.add_argument("--token", required=True)
    complete_parser.add_argument("--artifact")

    release_parser = commands.add_parser("release")
    release_parser.add_argument("--key", required=True)
    release_parser.add_argument("--token", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "claim":
        return claim(args)
    if args.command == "complete":
        return complete(args)
    return release(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
