"""Import real Codex host token/tool metrics for one production automation thread."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.state_store import atomic_json_write


def locate_session(thread_id: str, codex_home: Path | None = None) -> Path:
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    matches = list((home / "sessions").rglob(f"*{thread_id}*.jsonl"))
    if len(matches) != 1:
        raise ValueError(f"expected one session JSONL for thread {thread_id}, got {len(matches)}")
    return matches[0]


def summarize_session(path: Path, *, expected_root: Path = ROOT) -> dict:
    totals = {
        "model_turns": 0, "input_tokens": 0, "cached_input_tokens": 0,
        "output_tokens": 0, "reasoning_output_tokens": 0,
        "tool_calls": 0, "context_compactions": 0,
    }
    thread_id = None
    session_cwd = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "session_meta" and session_cwd is None:
            payload = item.get("payload") or {}
            thread_id = payload.get("id")
            session_cwd = payload.get("cwd")
        if item.get("type") == "event_msg":
            payload = item.get("payload") or {}
            if payload.get("type") == "token_count":
                usage = ((payload.get("info") or {}).get("last_token_usage") or {})
                if usage:
                    totals["model_turns"] += 1
                    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
                        totals[key] += int(usage.get(key) or 0)
            elif payload.get("type") == "context_compacted":
                totals["context_compactions"] += 1
        if item.get("type") == "response_item":
            payload = item.get("payload") or {}
            if payload.get("type") in {"function_call", "custom_tool_call", "mcp_tool_call"}:
                totals["tool_calls"] += 1
    if session_cwd is None or Path(session_cwd).resolve() != expected_root.resolve():
        raise ValueError(f"session cwd does not match Trading-System: {session_cwd}")
    totals["uncached_input_tokens"] = totals["input_tokens"] - totals["cached_input_tokens"]
    totals.update({
        "schema_version": "codex-host-usage-v1", "thread_id": thread_id,
        "session_jsonl": str(path), "session_cwd": session_cwd,
        "targets": {"model_turns_max": 80, "uncached_input_tokens_max": 800000},
    })
    totals["target_status"] = {
        "model_turns": "pass" if totals["model_turns"] <= 80 else "over",
        "uncached_input_tokens": "pass" if totals["uncached_input_tokens"] <= 800000 else "over",
    }
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--session-jsonl", type=Path)
    args = parser.parse_args()
    if not args.thread_id and not args.session_jsonl:
        raise SystemExit("CODEX_THREAD_ID or --session-jsonl is required")
    path = args.session_jsonl or locate_session(args.thread_id)
    payload = summarize_session(path)
    payload.update({"trading_date": args.date, "slot": args.slot})
    target = ROOT / "runtime_state" / args.date / f"host_usage_{args.slot}.json"
    atomic_json_write(target, payload)
    print(json.dumps({"status": "IMPORTED", "path": str(target), **payload["target_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
