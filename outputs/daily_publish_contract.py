# -*- coding: utf-8 -*-
"""Shared contract for daily report Notion publishing.

This module intentionally contains no trading logic.  It defines the mechanical
delivery shape that all daily Notion payload builders and validators must share.
"""

from __future__ import annotations


DAILY_PAYLOAD_TYPES_25 = (
    "quote",
    "heading_2",
    "heading_3",
    "heading_3",
    "paragraph",
    "paragraph",
    "heading_3",
    "paragraph",
    "paragraph",
    "paragraph",
    "heading_3",
    "heading_3",
    "heading_3",
    "paragraph",
    "divider",
    "heading_2",
    "paragraph",
    "paragraph",
    "paragraph",
    "heading_3",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
)
DAILY_PAYLOAD_TYPES_26 = DAILY_PAYLOAD_TYPES_25 + ("paragraph",)
DAILY_PAYLOAD_TYPES_BY_SLOT = {
    "morning": DAILY_PAYLOAD_TYPES_25,
    "midday": DAILY_PAYLOAD_TYPES_25,
    "evening": DAILY_PAYLOAD_TYPES_26,
}

DAILY_PAYLOAD_TEXT_PREFIXES = {
    1: "不能做：",
    2: "基本面",
    3: "技术面",
    6: "解读",
    10: "趋势确认",
    11: "日内支撑",
    12: "策略",
    15: "BTC",
    19: "防守计划",
}

CRITICAL_REPORT_TEXT_PREFIXES = (
    "不能做：",
    "BTC（策略）：",
    "反弹空：",
    "高空：",
    "低空：",
    "做空：",
    "低多：",
    "反弹多：",
    "高多：",
    "做多：",
    "止盈：",
    "止损：",
    "第一层：",
    "第二层：",
    "注意事项：",
    "取消价",
    "⚠️取消价",
    "核心：",
    "独立边界",
    "持仓校准",
)
FINAL_TEXT_PREFIXES = ("独立边界", "持仓校准")

REQUIRED_SOURCE_LABELS = {
    "blockbeats",
    "coinglass",
    "exocharts",
    "fedwatch",
    "farside_btc_etf",
    "tradingview_1d",
    "tradingview_4h",
    "tradingview_1h",
    "tradingview_15m",
}
SOURCE_LABEL_FILES = {
    "blockbeats": {"blockbeats.png", "blockbeats.json"},
    "coinglass": {"coinglass.png"},
    "exocharts": {"exocharts.png"},
    "fedwatch": {"fedwatch.png", "fedwatch.json"},
    "farside_btc_etf": {"farside_btc_etf.png", "farside_btc_etf.json"},
    "tradingview_1d": {"tradingview_btc_1d.png"},
    "tradingview_4h": {"tradingview_btc_4h.png"},
    "tradingview_1h": {"tradingview_btc_1h.png"},
    "tradingview_15m": {"tradingview_btc_15m.png"},
}

SOURCE_SPEC_FILENAMES = {
    "blockbeats": "blockbeats.json",
    "coinglass": "coinglass.png",
    "exocharts": "exocharts.png",
    "fedwatch": "fedwatch.png",
    "farside_btc_etf": "farside_btc_etf.json",
    "tradingview_1d": "tradingview_btc_1d.png",
    "tradingview_4h": "tradingview_btc_4h.png",
    "tradingview_1h": "tradingview_btc_1h.png",
    "tradingview_15m": "tradingview_btc_15m.png",
}
SOURCE_SPEC_POLICY = {
    "blockbeats": {"max_age_minutes": 1440, "same_local_day": True},
    "coinglass": {"max_age_minutes": 240},
    "exocharts": {"max_age_minutes": 240},
    "fedwatch": {"max_age_minutes": 1440, "same_local_day": True},
    "farside_btc_etf": {"max_age_minutes": 1440, "same_local_day": True},
    "tradingview_1d": {"max_age_minutes": 240},
    "tradingview_4h": {"max_age_minutes": 240},
    "tradingview_1h": {"max_age_minutes": 240},
    "tradingview_15m": {"max_age_minutes": 240},
}

SLOT_TITLE_META = {
    "morning": {"emoji": "🌅", "label": "早间日报", "score_time": "11:00"},
    "midday": {"emoji": "🌇", "label": "午间日报", "score_time": "15:30"},
    "evening": {"emoji": "🌙", "label": "晚间日报", "score_time": "20:00"},
}
