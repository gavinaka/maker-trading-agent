"""Append-only execution telemetry for the daily-report workflow.

The model host does not always expose token counts. Missing counts are recorded
as null instead of being guessed, so the log remains an auditable truth source.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.state_store import exclusive_lock


ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _optional_non_negative(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError("token and call counts must be non-negative")
    return parsed


def append_usage(
    *,
    trading_date: str,
    slot: str,
    phase: str,
    status: str,
    event_id: str | None = None,
    duration_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    tool_calls: int | None = None,
    retries: int = 0,
    full_fallbacks: int = 0,
    details: dict[str, Any] | None = None,
    root: Path = ROOT,
) -> Path:
    if slot not in {"morning", "midday", "evening"}:
        raise ValueError(f"unsupported slot: {slot}")
    if status not in {"started", "success", "failed", "blocked"}:
        raise ValueError(f"unsupported status: {status}")

    record = {
        "event_id": event_id or uuid.uuid4().hex,
        "timestamp": _now_iso(),
        "trading_date": trading_date,
        "slot": slot,
        "phase": phase,
        "status": status,
        "duration_ms": _optional_non_negative(duration_ms),
        "input_tokens": _optional_non_negative(input_tokens),
        "output_tokens": _optional_non_negative(output_tokens),
        "tool_calls": _optional_non_negative(tool_calls),
        "retries": _optional_non_negative(retries) or 0,
        "full_fallbacks": _optional_non_negative(full_fallbacks) or 0,
        "details": details or {},
    }

    target = root / "runtime_state" / trading_date / "usage.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with exclusive_lock(target.with_suffix(".lock")):
        if target.is_file():
            for existing_line in target.read_text(encoding="utf-8").splitlines():
                try:
                    existing = json.loads(existing_line)
                except json.JSONDecodeError:
                    continue
                if existing.get("event_id") == record["event_id"]:
                    return target
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Append daily-report execution telemetry")
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--phase", required=True)
    parser.add_argument("--status", required=True, choices=("started", "success", "failed", "blocked"))
    parser.add_argument("--event-id")
    parser.add_argument("--duration-ms", type=int)
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--tool-calls", type=int)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--full-fallbacks", type=int, default=0)
    parser.add_argument("--details-json", default="{}")
    args = parser.parse_args()

    details = json.loads(args.details_json)
    if not isinstance(details, dict):
        raise SystemExit("--details-json must decode to an object")
    target = append_usage(
        trading_date=args.date,
        slot=args.slot,
        phase=args.phase,
        status=args.status,
        event_id=args.event_id,
        duration_ms=args.duration_ms,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        tool_calls=args.tool_calls,
        retries=args.retries,
        full_fallbacks=args.full_fallbacks,
        details=details,
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
