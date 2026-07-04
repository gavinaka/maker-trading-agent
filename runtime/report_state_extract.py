"""Archive completed analysis after the session result has been locked.

The archive is audit-only and must never be loaded as the next session's
pre-analysis context. Decision output is split by state_store at commit time.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_SOURCE_MARKERS = {
    "blockbeats": re.compile(r"BlockBeats|律动", re.I),
    "coinglass": re.compile(r"Coinglass", re.I),
    "exocharts": re.compile(r"Exocharts", re.I),
    "fedwatch": re.compile(r"FedWatch|CME", re.I),
    "tradingview": re.compile(r"TradingView", re.I),
}

POSITION_COUPLING_PATTERNS = [
    re.compile(r"持仓校准"),
    re.compile(r"(?:主账户|Maker账户|双账户).{0,18}(?:无持仓|空仓|已平仓|未开仓|已成交|持仓)"),
    re.compile(r"(?:已有|当前|实际).{0,18}(?:持仓|空单|多单).{0,24}(?:阻断|禁止|不挂|新增|补仓|风控门|观望)"),
    re.compile(r"方向相反.{0,12}持仓"),
    re.compile(r"风控门阻断新增"),
    re.compile(r"先补齐风控"),
]


def _match(pattern: str, text: str, default=None, flags: int = 0):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else default


def _number(pattern: str, text: str) -> float | None:
    value = _match(pattern, text)
    if value is None:
        return None
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def extract_report_state(text: str) -> dict:
    orderflow_line = _match(
        r"盘口（合约）：\s*\n([^\n]+)",
        text,
        "",
    )
    maker_section = _match(
        r"## ② Maker 计划\s*\n(.*?)(?=\n## ③|\Z)",
        text,
        "",
        re.S,
    )
    strategy = _match(
        r"\n策略：\s*\n(.*?)(?=\n## ②|\Z)",
        text,
        "",
        re.S,
    )
    return {
        "notion_state": {
            "gate_summary": _match(r"门禁(?:沿用)?[^：\n]*：([^\n]+)", text, ""),
        },
        "analysis_archive": {
            "reuse_policy": "post_analysis_audit_only",
            "features": {
                "fundamentals": {
                    "summary": _match(r"基本面：([^\n]+)", text, ""),
                },
                "orderflow": {
                    "cvd": _match(r"CVD(上升|下降|横盘)", orderflow_line),
                    "price": _match(r"价格(上升|下降|横盘)", orderflow_line),
                    "funding_trend": _match(
                        r"资金费率(上升|下降|横盘)", orderflow_line
                    ),
                    "funding_sign": _match(
                        r"（(为正值|为负值|接近0值)）", orderflow_line
                    ),
                    "oi": _match(r"持仓(上升|下降|横盘)", orderflow_line),
                    "raw": orderflow_line,
                },
                "trend_regime": {
                    "summary": _match(r"趋势确认：([^\n]+)", text, ""),
                },
                "liquidity": {
                    "support": _match(r"日内支撑：([^\s　]+)", text, ""),
                    "resistance": _match(r"日内压力：([^\s　]+)", text, ""),
                },
                "chart_1d": {
                    "summary": _match(r"日线级别[　 ]*([^\n]+)", text, ""),
                },
                "chart_1h": {
                    "summary": _match(r"小时级别[　 ]*([^\n]+)", text, ""),
                },
            },
            "scores": {
                "orderflow": _number(
                    r"盘口(?:\*\*)?\s*[：:]?\s*([0-9.]+)\s*[／/]\s*70",
                    text,
                ),
                "chart": {
                    "total": _number(
                        r"盘面(?:\*\*)?\s*[：:]?\s*([0-9.]+)\s*[／/]\s*30",
                        text,
                    ),
                },
                "total": _number(r"总分(?:\*\*)?\s*[：:]?\s*([0-9.]+)", text),
                "winrate": _number(
                    r"胜率(?:自估)?(?:\*\*)?\s*[：:]?\s*([0-9.]+)%",
                    text,
                ),
            },
            "risk_state": {
                "summary": _match(
                    r"(?:\*\*)?风险(?:验算)?(?:\*\*)?\s*[：:]([^\n]+)",
                    text,
                    "",
                ),
            },
        },
        "decision": {
            "cannot_do": _match(r"不能做：([^\n]+)", text, ""),
            "main_account": {"strategy": strategy},
            "maker": {"raw": maker_section},
        },
    }


def validate_report_state(text: str, payload: dict | None = None) -> list[str]:
    """Return structural omissions that make a full-analysis lock invalid."""
    payload = payload or extract_report_state(text)
    archive = payload["analysis_archive"]
    features = archive["features"]
    scores = archive["scores"]
    decision = payload["decision"]
    missing: list[str] = []

    required_values = {
        "gate_summary": payload["notion_state"].get("gate_summary"),
        "fundamentals": features["fundamentals"].get("summary"),
        "orderflow_raw": features["orderflow"].get("raw"),
        "orderflow_cvd": features["orderflow"].get("cvd"),
        "orderflow_price": features["orderflow"].get("price"),
        "orderflow_funding": features["orderflow"].get("funding_trend"),
        "orderflow_oi": features["orderflow"].get("oi"),
        "trend_regime": features["trend_regime"].get("summary"),
        "support": features["liquidity"].get("support"),
        "resistance": features["liquidity"].get("resistance"),
        "chart_1d": features["chart_1d"].get("summary"),
        "chart_1h": features["chart_1h"].get("summary"),
        "score_orderflow": scores.get("orderflow"),
        "score_chart": scores["chart"].get("total"),
        "score_total": scores.get("total"),
        "score_winrate": scores.get("winrate"),
        "risk": archive["risk_state"].get("summary"),
        "cannot_do": decision.get("cannot_do"),
        "main_account": decision["main_account"].get("strategy"),
        "maker": decision["maker"].get("raw"),
    }
    for name, value in required_values.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(name)
    for source, marker in REQUIRED_SOURCE_MARKERS.items():
        if not marker.search(text):
            missing.append(f"source_evidence:{source}")
    for line_number, line in enumerate(text.splitlines(), 1):
        if any(pattern.search(line) for pattern in POSITION_COUPLING_PATTERNS):
            missing.append(f"position_coupling:line_{line_number}")
    return sorted(missing)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive locked analysis from a combined report"
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = extract_report_state(args.report.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(args.output)
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
