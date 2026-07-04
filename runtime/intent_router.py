"""Deterministic daily-report intent routing for this isolated workspace."""

from __future__ import annotations

import argparse
import json
import re


SESSION_REPORT = re.compile(
    r"^\s*(?:请|帮我|现在|立即|今天|给我|请给我|我要|我需要)?\s*"
    r"(?:写|出|跑|生成|开始|执行)?\s*"
    r"(?P<report>早报|早间日报|午报|午间日报|晚报|晚间日报)"
)
GENERIC_DAILY_REPORT = re.compile(
    r"^\s*(?:请|帮我|现在|立即|今天|给我|请给我|我要|我需要)?\s*"
    r"(?:(?:写|出|跑|生成|开始|执行)\s*)?日报\s*$"
)
NEGATED = re.compile(r"^\s*(?:不要|别|无需|不用|禁止|停止|取消)")
META_SUFFIX = re.compile(r"(?:是什么|怎么|如何|规则|路由|测试|检查|解释)")


def classify_intent(text: str) -> str:
    """Return this workspace's only report workflow, or no match."""
    stripped = text.strip()
    if NEGATED.search(stripped):
        return "none"
    session = SESSION_REPORT.search(stripped)
    if session and not META_SUFFIX.search(stripped[session.end() :]):
        return "daily-report"
    if GENERIC_DAILY_REPORT.search(stripped):
        return "daily-report"
    return "none"


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Trading-System report intent")
    parser.add_argument("text")
    args = parser.parse_args()
    print(json.dumps({"intent": classify_intent(args.text)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
