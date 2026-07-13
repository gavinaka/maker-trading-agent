"""Fail closed when a production automation memory contains trading judgment."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


PROHIBITED = {
    "direction": r"多头|空头|偏多|偏空|观望|做多|做空|long\b|short\b|direction",
    "score": r"总分|盘口分|盘面分|评分\s*[:：=]?\s*\d|score\s*[:=]",
    "probability": r"胜率|执行概率|win\s*rate|probability\s*[:=]",
    "levels": r"支撑|压力|阻力|入场|止损|止盈|撤单|\bsupport\b|\bresistance\b|\bentry\b|\bstop\s*loss\b|\btake\s*profit\b",
    "position": r"仓位|持仓|挂单|订单|盈亏|\bposition\b|\border\b|\bpnl\b",
}
AUTOMATION_SCOPES = ("morning", "midday", "evening", "weekly", "monthly")


def memory_path(automation_id: str, codex_home: Path | None = None) -> Path:
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return home / "automations" / automation_id / "memory.md"


def inspect_memory(path: Path) -> dict:
    if not path.is_file():
        return {"status": "clean", "path": str(path), "exists": False, "violations": []}
    text = path.read_text(encoding="utf-8")
    violations = [name for name, pattern in PROHIBITED.items() if re.search(pattern, text, re.I)]
    return {
        "status": "blocked" if violations else "clean",
        "path": str(path),
        "exists": True,
        "sha256": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--automation-id", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--slot",
        required=True,
        choices=AUTOMATION_SCOPES,
    )
    args = parser.parse_args()
    result = inspect_memory(memory_path(args.automation_id))
    result.update({"trading_date": args.date, "slot": args.slot})
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
