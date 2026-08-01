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

# v3 separates immutable section labels from their full report text.  The
# combined Markdown remains the only textual truth; this is a deterministic
# presentation projection, not a second writing surface.
DAILY_VISUAL_PAYLOAD_TYPES_31 = (
    "quote",
    "heading_2",
    "callout",
    "heading_3",
    "paragraph",
    "heading_3",
    "paragraph",
    "paragraph",
    "heading_3",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "heading_3",
    "paragraph",
    "heading_3",
    "paragraph",
    "heading_3",
    "callout",
    "divider",
    "heading_2",
    "paragraph",
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
DAILY_VISUAL_PAYLOAD_TYPES_32 = DAILY_VISUAL_PAYLOAD_TYPES_31 + ("paragraph",)
DAILY_VISUAL_PAYLOAD_TYPES_BY_SLOT = {
    "morning": DAILY_VISUAL_PAYLOAD_TYPES_31,
    "midday": DAILY_VISUAL_PAYLOAD_TYPES_31,
    "evening": DAILY_VISUAL_PAYLOAD_TYPES_32,
}

# v4 is the user-approved delivery grammar distilled from the hand-written
# Notion reports.  It keeps conclusions inline with their labels, removes the
# system-style opening summary/callouts/divider, and keeps the complete audit
# trail in combined.md / Word appendix rather than exposing it as UI chrome.
DAILY_MANUAL_GOLD_TYPES_23 = (
    "heading_2",  # 不能做：...
    "heading_3",  # 基本面：...
    "heading_3",  # 技术面
    "paragraph",  # 盘口（合约）：
    "paragraph",  # 盘口读数
    "heading_3",  # 解读：...
    "paragraph",  # 盘面：
    "paragraph",  # 日线级别：
    "paragraph",  # 小时级别：
    "heading_3",  # 趋势确认：...
    "heading_3",  # 日内支撑/压力
    "heading_3",  # 策略
    "paragraph",  # 策略正文
    "heading_2",  # BTC（策略/候选/观察/被拒候选审计）：...
    "paragraph",
    "paragraph",
    "paragraph",
    "heading_3",  # 防守计划
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
)
DAILY_MANUAL_GOLD_TYPES_24 = DAILY_MANUAL_GOLD_TYPES_23 + ("paragraph",)
DAILY_MANUAL_GOLD_TYPES_BY_SLOT = {
    "morning": DAILY_MANUAL_GOLD_TYPES_23,
    "midday": DAILY_MANUAL_GOLD_TYPES_23,
    "evening": DAILY_MANUAL_GOLD_TYPES_24,
}

DAILY_MANUAL_GOLD_PREFIXES = {
    0: ("不能做：",),
    1: ("基本面：",),
    2: ("技术面",),
    3: ("盘口",),
    5: ("解读：",),
    6: ("盘面",),
    7: ("日线级别：",),
    8: ("小时级别：",),
    9: ("趋势确认：",),
    10: ("日内支撑：",),
    11: ("策略",),
    13: (
        "BTC（策略）：",
        "BTC（候选策略）：",
        "BTC（无方向观察）：",
        "BTC（方向观察）：",
        "BTC（被拒候选审计）：",
    ),
    18: ("第一层：",),
    19: ("第二层：",),
    20: ("注意事项：",),
    21: ("取消", "⚠️取消"),
}

DAILY_VISUAL_LABELS = {
    1: "不能做",
    3: "基本面",
    5: "技术面",
    8: "解读",
    13: "趋势确认",
    15: "日内支撑/压力",
    17: "策略",
    20: "Maker 计划",
    25: "防守计划",
}

# v3 renders immutable section names as their own blocks, but the following
# report-derived bodies still carry canonical prefixes.  Keeping this mapping
# beside the block-type/label contract prevents the preflight and publisher
# from maintaining separate, drifting assumptions.
DAILY_VISUAL_BODY_PREFIXES = {
    2: ("不能做：",),
    4: ("基本面：",),
    6: ("盘口",),
    9: ("解读：",),
    10: ("盘面",),
    11: ("日线级别：",),
    12: ("小时级别：",),
    14: ("趋势确认：",),
    16: ("日内支撑：",),
    21: (
        "BTC（策略）：",
        "BTC（候选策略）：",
        "BTC（无方向观察）：",
        "BTC（方向观察）：",
        "BTC（被拒候选审计）：",
    ),
    26: ("第一层：",),
    27: ("第二层：",),
    28: ("注意事项：",),
    29: ("取消", "⚠️取消"),
    # Morning/midday end at block 30 with the continuity boundary. Evening
    # inserts one additional "核心：" body at block 30 and moves that same
    # boundary to the final block 31. The final-block validator still requires
    # FINAL_TEXT_PREFIXES, so accepting 核心 here cannot weaken the boundary.
    30: ("核心：", "独立边界", "持仓校准"),
}

DAILY_VISUAL_LIMITS = {
    "heading_max_chars": 12,
    "quote_warn_chars": 140,
    "quote_max_chars": 1800,
    "body_warn_chars": 180,
    # Hard limits protect the Notion rich_text API boundary, not prose length.
    # Presentation density thresholds remain warnings so producers never have
    # an incentive to weaken analysis to make a visual gate pass.
    "body_max_chars": 1800,
    "long_body_threshold_chars": 120,
    "long_body_warn_count": 3,
    "total_text_warn_chars": 1800,
    "total_text_max_chars": 12000,
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
    "BTC（候选策略）：",
    "BTC（无方向观察）：",
    "BTC（方向观察）：",
    "BTC（被拒候选审计）：",
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
