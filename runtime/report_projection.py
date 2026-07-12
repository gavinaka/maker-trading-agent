"""Verify that certified reasoning survives into the human-facing report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from outputs.daily_payload_builder import parse_daily_text_contract
from runtime.reasoning_contract import validate_reasoning_contract_file


ROOT = Path(__file__).resolve().parents[1]


def _appendix(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line.strip() == "## ③ 后附":
            return "\n".join(lines[index + 1 :]).strip()
    raise ValueError("report projection requires ## ③ 后附")


def _visible_sections(lines: list[str], trading_date: str, slot: str) -> dict[str, str]:
    contract = parse_daily_text_contract(lines, trading_date, slot)
    return {
        "opening_quote": contract["opening_quote"],
        "cannot_do": contract["cannot_do"],
        "fundamentals": contract["fundamentals"],
        "orderflow": "\n".join((contract["orderflow_label"], contract["orderflow_text"])),
        "interpretation": contract["interpretation"],
        "daily_line": contract["daily_line"],
        "hourly_line": contract["hourly_line"],
        "trend_confirmation": contract["trend_confirmation"],
        "support_resistance": contract["support_resistance"],
        "strategy": contract["strategy"],
        "maker": "\n".join(contract["maker_main"]),
        "defense": "\n".join(contract["defense"]),
    }


def validate_report_projection(
    report_path: Path,
    reasoning_contract_path: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    report = report_path.resolve()
    report.relative_to(root.resolve())
    reasoning = validate_reasoning_contract_file(
        reasoning_contract_path, trading_date, slot, root=root
    )
    lines = report.read_text(encoding="utf-8").splitlines()
    visible = _visible_sections(lines, trading_date, slot)
    appendix = _appendix(lines)
    checked = []
    for item in (reasoning.get("report_projection") or {}).get("items", []):
        text = str(item["text"])
        if item["surface"] == "visible":
            actual = visible[item["section"]]
        else:
            actual = appendix
        if actual.count(text) != 1:
            raise ValueError(
                "report semantic projection missing or duplicated: "
                f"{item['id']} surface={item['surface']} section={item['section']}"
            )
        checked.append(item["id"])
    if not checked:
        raise ValueError("report semantic projection has no certified items")
    return {
        "status": "passed",
        "schema_version": "report-semantic-projection-v1",
        "reasoning_contract_sha256": reasoning["contract_sha256"],
        "checked_item_count": len(checked),
        "checked_item_ids": checked,
    }
