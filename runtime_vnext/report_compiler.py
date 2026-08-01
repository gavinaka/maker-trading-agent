"""Compile certified structured analysis into every human-facing report surface."""

from __future__ import annotations

import copy
import subprocess
import sys
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from outputs.daily_payload_builder import parse_daily_text_contract
from outputs.report_structure_gate import assert_combined_structure, expected_title

from .domain_ir.registry import (
    EXECUTION_AUTHORIZATION_FIELDS,
    REGISTRY,
    SHADOW_CONTINUITY_FIELDS,
)
from .gates import (
    REQUIRED_SOURCES,
    decision_model_sha256,
    maker_fill_scenarios,
    reasoning_model_sha256,
)
from .methodology import canonical_sha256, load_scoring_policy, sha256_file
from .plan_semantics import (
    DIRECTIONAL_THESIS_ONLY,
    FAILURE_ORDER,
    MAKER_SEMANTIC_STATES,
    NON_DIRECTIONAL_OBSERVATION,
    QUALIFIED_CANDIDATE,
    REJECTED_SUBMITTED_CANDIDATE,
    classify_maker_semantic_state,
)
from .reasoning_submission import load_reasoning_submission_contract


DIRECTION_CN = {
    "long": "计划做多",
    "short": "计划做空",
    "observe": "观望",
    "blocked": "门禁阻断",
}

REPORT_MODEL_SCHEMA_VERSION = REGISTRY.report_model_schema_version
ORDERFLOW_SCORE_MAX = 60
CHART_SCORE_MAX = 30
SHADOW_CONTINUITY_SCHEMA_VERSION = REGISTRY.shadow_continuity_schema_version

AUDIT_DIRECTION_CN = {
    "long": "偏多",
    "short": "偏空",
    "neutral": "中性",
    "observe": "观望",
    "blocked": "阻断",
}

SOURCE_ROLE_CN = {
    "BlockBeats": "重要事件事实与影响层级",
    "Coinglass": "同一 pivot 的价格、CVD、OI 主判，资金费率修正与清算图辅助",
    "Exocharts": "足迹对盘口主判的确认、削弱或反证",
    "FedWatch": "宏观概率变化与事件窗口",
    "Farside": "现货 ETF 资金流确认",
    "TradingView": "多周期结构、用户手绘成交量分布与机会质量",
}

_TYPED_SCALAR = object()
_FEDWATCH_NUMERIC_MAP = object()
_OMIT_TYPED_VALUE = object()
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_PROVIDER_CODE_PATTERN = re.compile(r"^[a-z0-9_]{1,120}$")
_MACHINE_ENUM_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")

_RATE_EXPECTATION_PROVIDER_CONTRACTS = {
    "cme_fedwatch_ui": {
        "display_name": "CME FedWatch（官方主源）",
        "selection_mode": "cme_primary",
        "series_ticker": None,
        "acquisition_channel": "rendered_official_ui",
        "method_class": "cme_target_rate_probability",
        "method_equivalence": "canonical",
        "sample_source_class": "cme_canonical",
        "quote_basis_code": "cme_rendered_probability_table_v1",
        "normalization_method_code": "identity_cme_distribution_v1",
        "fallback_reason_code": "none",
        "observation_only": False,
        "method_disclosure": "CME目标利率概率口径",
    },
    "kalshi_public_market_data_api": {
        "display_name": "Kalshi KXFEDDECISION（Plan C 备用观察源）",
        "selection_mode": "kalshi_plan_c_fallback",
        "series_ticker": "KXFEDDECISION",
        "acquisition_channel": "public_market_data_api",
        "method_class": "independent_event_contract_market",
        "method_equivalence": "non_equivalent",
        "sample_source_class": "kalshi_plan_c_observation",
        "quote_basis_code": "kalshi_yes_bid_ask_midpoint_dollars_v1",
        "normalization_method_code": "kalshi_bounded_simplex_other_unlisted_v1",
        "observation_only": True,
        "method_disclosure": "独立事件合约市场口径，非CME等价，仅作observation",
    },
}

_ZONE_AUDIT_SCHEMA = {
    "lower_bound": _TYPED_SCALAR,
    "upper_bound": _TYPED_SCALAR,
    "timeframe": _TYPED_SCALAR,
    "role": _TYPED_SCALAR,
}

SOURCE_METRIC_AUDIT_SCHEMA = {
    "BlockBeats": {
        "tier": _TYPED_SCALAR,
        "event_window_hours": _TYPED_SCALAR,
        "selected_event_count": _TYPED_SCALAR,
        "selected_event_sha256": [_TYPED_SCALAR],
    },
    "Coinglass": {
        "pivot": {
            "timeframe": _TYPED_SCALAR,
            "start_price": _TYPED_SCALAR,
            "end_price": _TYPED_SCALAR,
            "dominant_leg": _TYPED_SCALAR,
            "trendline_status": _TYPED_SCALAR,
            "anchor_reset": _TYPED_SCALAR,
        },
        "price_direction": _TYPED_SCALAR,
        "cvd_direction": _TYPED_SCALAR,
        "oi_direction": _TYPED_SCALAR,
        "funding_direction": _TYPED_SCALAR,
        "funding_sign": _TYPED_SCALAR,
        "combination_id": _TYPED_SCALAR,
        "effect_divergence": {
            "cvd_break": _TYPED_SCALAR,
            "price_confirmation": _TYPED_SCALAR,
            "interpretation": _TYPED_SCALAR,
        },
        "price_break_status": _TYPED_SCALAR,
        "oi_price_context": _TYPED_SCALAR,
        "main_triad_direction": _TYPED_SCALAR,
        "funding_effect": _TYPED_SCALAR,
        "final_direction": _TYPED_SCALAR,
        "funding_single_variable_flip": _TYPED_SCALAR,
        "liquidation_map": {
            "role": _TYPED_SCALAR,
            "threshold": _TYPED_SCALAR,
            "captured_timeframes": [_TYPED_SCALAR],
            "current_price": _TYPED_SCALAR,
            "levels": [{
                "side": _TYPED_SCALAR,
                "price": _TYPED_SCALAR,
                "timeframe": _TYPED_SCALAR,
                "strength": _TYPED_SCALAR,
            }],
        },
    },
    "Exocharts": {
        "capture_profile": {
            "exchange": _TYPED_SCALAR,
            "symbol": _TYPED_SCALAR,
            "timeframe": _TYPED_SCALAR,
            "tick_multiplier": _TYPED_SCALAR,
            "cluster_type": _TYPED_SCALAR,
            "text_type": _TYPED_SCALAR,
            "candle_type": _TYPED_SCALAR,
            "fpbs_enabled": _TYPED_SCALAR,
            "vwap_enabled": _TYPED_SCALAR,
        },
        "ohlc": {
            "open": _TYPED_SCALAR,
            "high": _TYPED_SCALAR,
            "low": _TYPED_SCALAR,
            "close": _TYPED_SCALAR,
        },
        "poc": _TYPED_SCALAR,
        "delta": _TYPED_SCALAR,
        "cvd": _TYPED_SCALAR,
        "volume": _TYPED_SCALAR,
        "cross_check_result": _TYPED_SCALAR,
    },
    "FedWatch": {
        "data_as_of": _TYPED_SCALAR,
        "next_fomc_date": _TYPED_SCALAR,
        "current_probabilities": _FEDWATCH_NUMERIC_MAP,
        "change_1d": _FEDWATCH_NUMERIC_MAP,
        "change_1w": _FEDWATCH_NUMERIC_MAP,
        "change_1m": _FEDWATCH_NUMERIC_MAP,
    },
    "Farside": {
        "latest_complete_date": _TYPED_SCALAR,
        "latest_total_usd_m": _TYPED_SCALAR,
        "flow_direction": _TYPED_SCALAR,
    },
    "TradingView": {
        "timeframes": {
            timeframe: {
                "price": _TYPED_SCALAR,
                "sma20": _TYPED_SCALAR,
                "structure": _TYPED_SCALAR,
            }
            for timeframe in ("1d", "4h", "1h", "15m")
        },
        "volume_profile": {
            "source_mode": _TYPED_SCALAR,
            "status": _TYPED_SCALAR,
            "platform_indicator_state": _TYPED_SCALAR,
            "platform_vrvp_used": _TYPED_SCALAR,
            "automated_values_used": _TYPED_SCALAR,
            "zones": [_ZONE_AUDIT_SCHEMA],
        },
        "chart_basis": {
            "support_levels": [_TYPED_SCALAR],
            "resistance_levels": [_TYPED_SCALAR],
            "structure_zones": [_ZONE_AUDIT_SCHEMA],
            "volume_price_state": _TYPED_SCALAR,
            "fibonacci_levels": [_TYPED_SCALAR],
            "trendline_status": _TYPED_SCALAR,
        },
        "chart_component_scores": {
            key: _TYPED_SCALAR
            for key in (
                "chart.support_resistance",
                "chart.liquidity_hunt",
                "chart.sma20_interaction",
                "chart.volume_price",
                "chart.fibonacci_trendline",
            )
        },
        "chart_scoring_basis": {
            "included_timeframes": [_TYPED_SCALAR],
            "excluded_timeframes": [_TYPED_SCALAR],
            "fifteen_minute_role": _TYPED_SCALAR,
        },
    },
}

MAIN_PLAN_AUDIT_FIELDS = {
    "direction",
    "claim_id",
    "plan_state",
    "action",
    "exchange",
    "instrument",
    "position_notional_usdt",
    "leverage",
    "entry_mode",
    "entry_zone_basis",
    "entries",
    "entry_allocations_pct",
    "stop_basis",
    "stop",
    "tp1",
    "final_take_profit",
    "tp1_close_pct",
    "counter_claim_id",
    "invalidation_claim_id",
    "scenario_ids",
}

CLAIM_TYPE_CN = {
    "cannot_do": "禁止事项",
    "chart_interpretation": "多周期盘面判断",
    "etf_confirmation": "ETF 资金流确认",
    "fundamental_context": "基本面背景",
    "fundamental_event_realization": "基本面逐事件价格归因观察",
    "fundamental_price_realization": "基本面价格归因观察",
    "liquidation_confirmation": "清算图辅助确认",
    "liquidity_hunt": "流动性猎杀概率",
    "main_account_thesis": "主账户判断",
    "maker_thesis": "Maker 判断",
    "market_regime": "市场阶段",
    "orderflow_interpretation": "同锚盘口判断",
    "strongest_counterevidence": "最强反证",
    "invalidation_path": "失效路径",
}

ACCOUNT_CN = {
    "shared": "共享证据层",
    "main": "主账户",
    "maker": "Maker",
}

SCENARIO_TYPE_CN = {
    "base": "基准情景",
    "counter": "反证情景",
    "invalidation": "失效情景",
}

CHART_COMPONENT_CN = {
    "chart.support_resistance": "支撑与压力",
    "chart.liquidity_hunt": "流动性猎杀机会",
    "chart.sma20_interaction": "SMA20 互动",
    "chart.volume_price": "量价关系",
    "chart.fibonacci_trendline": "斐波那契与趋势线",
}

METRIC_LABEL_CN = {
    "impact_tier": "影响层级",
    "tier": "事件层级",
    "event_window_hours": "事件窗口（小时）",
    "selected_event_count": "入选重要事件数",
    "realization_state": "价格归因观察枚举",
    "pivot": "同锚点",
    "pivot_id": "同锚点编号",
    "timeframe": "周期",
    "subject": "标的",
    "price": "价格变化",
    "price_direction": "价格方向",
    "cvd": "累积成交量差（CVD）",
    "cvd_direction": "CVD 方向",
    "oi": "未平仓量（OI）",
    "oi_direction": "OI 方向",
    "funding": "资金费率",
    "funding_direction": "资金费率变化",
    "funding_sign": "资金费率正负",
    "combination_id": "四维组合编号",
    "effect_divergence": "效应背离",
    "price_break_status": "价格突破状态",
    "oi_price_context": "OI 与价格关系",
    "main_triad_direction": "价格、CVD、OI 三项主判",
    "main_triad_rationale": "三项主判依据",
    "funding_effect": "资金费率修正作用",
    "final_direction": "盘口最终方向",
    "funding_single_variable_flip": "资金费率是否单变量翻向",
    "liquidation_map": "清算图辅助结论",
    "footprint": "足迹结论",
    "ohlc": "足迹时间窗与 OHLC",
    "poc": "成交量分布控制点（POC）",
    "delta": "主动成交差（Delta）",
    "volume": "成交量",
    "cross_check_result": "足迹交叉验证结果",
    "macro_context": "宏观背景",
    "data_as_of": "数据截至时间",
    "next_fomc_date": "下次 FOMC 日期",
    "current_probabilities": "当前概率结构",
    "change_1d": "较 1 日变化",
    "change_1w": "较 1 周变化",
    "change_1m": "较 1 月变化",
    "total_usd_m": "ETF 总净流量（百万美元）",
    "latest_complete_date": "最近完整交易日",
    "latest_total_usd_m": "最近完整日总净流量（百万美元）",
    "flow_direction": "ETF 流向",
    "price_relation": "ETF 流量与价格关系",
    "timeframes": "多周期覆盖",
    "volume_profile": "成交量分布",
    "source_mode": "成交量分布来源模式",
    "status": "成交量分布证据状态",
    "platform_indicator_state": "平台内置 VRVP 状态",
    "platform_vrvp_used": "是否使用平台内置 VRVP",
    "automated_values_used": "是否使用自动数值",
    "zones": "用户手绘价格区域",
    "lower_bound": "区域下沿",
    "upper_bound": "区域上沿",
    "role": "区域用途",
    "reason": "证据状态原因",
    "structure": "结构状态",
    "sma20": "SMA20 关系",
    "vrvp": "用户手绘成交量分布关键位置",
}

TYPED_FIELD_LABEL_CN = {
    "timeframes.1d.structure": "1D结构",
    "timeframes.4h.structure": "4H结构",
    "timeframes.1h.structure": "1H结构",
    "timeframes.15m.structure": "15m结构",
    "flow_direction": "ETF流向",
    "final_direction": "盘口最终方向",
    "pivot.anchor_reset": "盘口是否重置新锚",
    "cross_check_result": "足迹交叉核验",
    "realization_state": "基本面价格归因观察",
    "price_relation": "ETF与同锚价格关系",
}

METRIC_VALUE_CN = {
    "true": "是",
    "false": "否",
    "up": "上升",
    "down": "下降",
    "flat": "横向",
    "range": "震荡",
    "positive": "正值",
    "negative": "负值",
    "near_zero": "接近零",
    "higher_high": "CVD 创新高",
    "lower_low": "CVD 创新低",
    "none": "未出现",
    "ambiguous": "不明确",
    "confirmed": "已确认",
    "not_confirmed": "未确认",
    "bearish": "偏空",
    "bullish": "偏多",
    "neutral": "中性",
    "mixed": "混合",
    "strengthen": "增强",
    "weaken": "削弱",
    "confirm": "确认",
    "contradict": "反证",
    "realized": "已兑现",
    "partially_realized": "部分兑现",
    "not_realized": "未兑现",
    "conflicted": "存在冲突",
    "new_high_or_breakout": "创新高或突破",
    "stalled_no_new_high": "上涨停滞且未创新高",
    "new_low_or_breakdown": "创新低或下破",
    "not_applicable": "不适用",
    "intact": "保持有效",
    "broken": "已破坏",
    "new_long_expansion": "新增多头扩张",
    "new_short_expansion": "新增空头扩张",
    "short_cover_squeeze": "空头回补挤压",
    "profit_taking_plus_spot_supply": "止盈叠加现货供给",
    "long_liquidation": "多头清算",
    "position_reduction": "持仓收缩",
    "unclear": "不清晰",
    "outflow": "净流出",
    "inflow": "净流入",
    "no_change_dominant": "维持利率概率占优",
    "stable": "稳定",
    "slightly_higher": "小幅上升",
    "higher": "上升",
    "readable": "用户手绘区域可读",
    "insufficient": "用户手绘区域证据不足",
    "user_drawn_manual_only": "仅用户手绘",
    "hidden": "已隐藏",
    "absent": "不存在",
    "visible": "仍可见（污染）",
    "unknown": "状态未知（污染）",
    "value_area": "手绘价值区域",
    "poc_zone": "手绘 POC 区域",
    "hvn_zone": "手绘高量区域",
    "lvn_zone": "手绘低量区域",
    "verified": "已核验",
    "same 1H window": "同一 1 小时时间窗",
    "price and CVD aligned while OI fell": "价格与 CVD 同向、OI 下降",
    "daily resistance intact": "日线压力结构仍有效",
    "1H below SMA20": "1 小时价格位于 SMA20 下方",
}

VISIBLE_ENUM_CN_BY_DOMAIN = {
    "tradingview.chart_basis.volume_price_state": {
        "confirm": "确认",
        "weaken": "削弱",
        "neutral": "中性",
        "conflicted": "存在冲突",
        "not_available": "不可用",
    },
    "tradingview.chart_basis.trendline_status": {
        "intact": "保持有效",
        "broken": "已破坏",
        "ambiguous": "不明确",
        "not_available": "不可用",
    },
    "maker.entry_type": {
        "left": "左侧",
        "right": "右侧",
        "not_applicable": "不适用",
    },
}

SOURCE_BOUNDARY_CN = {
    "BlockBeats": "只定义当期事件背景与影响层级；v1价格归因未绑定逐事件价格窗口，只作观察记录，不能直接给出BTC方向、置信度调整或账户触发。",
    "Coinglass": "先在同一 1H pivot 下由价格、CVD、OI 形成主体主判；资金费率只修正强度，不得单变量翻向；清算图仅辅助印证手绘位置概率，不承担盘口方向。",
    "Exocharts": "固定日线足迹配置只对 Coinglass 主判作确认、削弱或反证；不得另起方向或单方翻向。",
    "FedWatch": "只定义宏观概率环境与事件窗口，不担任 Maker 方向盘。",
    "Farside": "ETF 流量只能确认或削弱现货承接，禁止单变量翻向。",
    "TradingView": "负责多周期结构、SMA20、用户手绘成交量分布区域和机会质量；平台内置VRVP与自动数值禁止使用，手绘区域不可读时只把该维度记为证据不足，盘面分数不代替盘口方向。",
}

ORDERFLOW_DIRECTION_METHOD_CN = (
    "盘口方向先由同一锚点（pivot）下的价格、CVD 与 OI 形成主体主判；"
    "资金费率只修正强度，Exocharts 只作确认、削弱或反证，二者都不得单变量翻向。"
)

SOURCE_DECISION_CLAIMS = {
    "BlockBeats": ("fundamental_context", "fundamental_price_realization"),
    "Coinglass": ("orderflow_interpretation", "liquidation_confirmation"),
    "Exocharts": ("orderflow_interpretation",),
    "FedWatch": ("fundamental_context",),
    "Farside": ("etf_confirmation",),
    "TradingView": ("chart_interpretation", "liquidity_hunt"),
}

REASONING_PROOF_LABELS = {
    "orderflow_anchor": "同锚盘口四维",
    "footprint_cross_check": "足迹交叉验证",
    "multi_timeframe_structure": "多周期结构与位置",
    "july_additions": "7 月增量逻辑",
    "fundamental_and_etf_realization": "基本面、宏观与 ETF 兑现",
    "main_account_closure": "主账户独立闭环",
    "maker_account_closure": "Maker 独立闭环",
    "account_separation": "主账户与 Maker 分离",
    "score_and_winrate": "评分与计划时置信度落值",
    "risk_and_scenarios": "风险与情景闭环",
}

APPENDIX_SEMANTIC_OWNERSHIP = {
    "full_scenario_tree": "appendix_risk_and_scenarios_only",
    "current_counterevidence": "typed_current_basis_only",
    "current_invalidation_basis": "typed_current_basis_only",
    "future_counter_trigger": "counter_scenario_condition_from_bound_trigger_logic_only",
    "future_invalidation_trigger": "invalidation_scenario_condition_from_bound_trigger_logic_only",
    "free_control_conclusion_or_invalidation": "upstream_audit_only_never_projectable",
}

CONSTRUCTIBILITY_REASON_CN = {
    "constructible": "候选结构与执行语义完整",
    "non_directional_thesis": "Maker 当前为无方向观察结论，不适用入场区、名义仓位或风险候选",
    "no_certified_entry_zone": "当前没有认证的 TradingView 入场区间",
    "entry_zone_binding_invalid": "候选入场区未绑定首选认证区域",
    "entry_zone_role_invalid": "候选方向与认证结构区的支撑/压力角色冲突",
    "maker_order_marketable": "候选限价位于会立即成交或穿越现价的一侧，不满足静置 Maker 语义",
    "entry_semantics_invalid": "方向、现价、触达方向或入场类型不构成同一闭合语义",
    "cannot_do_conflict": "候选执行方式与本轮 Maker 不能做结论冲突",
    "order_lifecycle_invalid": "候选订单没有同时满足可成交路径与成交前撤单路径",
    "structural_stop_invalid": "候选初始止损未绑定本轮认证结构与推理阶段预先密封的外扩缓冲",
    "risk_math_invalid": "候选区间的风险数学未满足全部成交组合要求",
    "defense_trigger_invalid": "候选防守触发价未通过完整分档情景的确定性计算",
}

THRESHOLD_INELIGIBLE_CN = "评分与计划时置信度未同时达到候选门槛"

REJECTED_RISK_RECALCULATION_STATES = {
    "not_applicable": "qualified_plan_uses_primary_risk_scenarios",
    "not_submitted": "candidate_risk_input_absent",
    "recalculated": "deterministic_recalculation_succeeded",
    "not_recalculable": "candidate_risk_input_failed_recalculation",
}

SIGNAL_TYPE_CN = {
    "etf_confirmation": "ETF 资金流确认",
    "fundamental_price_realization": "基本面价格归因观察",
}

SIGNAL_DISPOSITION_CN = {
    "adjusted": "已进入置信度调整",
    "no_adjustment": "不追加置信度调整",
}

NO_ADJUSTMENT_REASON_CN = {
    "neutral_signal": "类型化信号为中性",
    "reviewed_no_independent_incremental_effect": "已复核，本轮未形成独立增量影响",
    "event_price_attribution_unavailable": (
        "逐事件价格窗口与方向归因尚未建立，当前只作观察记录"
    ),
}

ADJUSTMENT_REASON_CN = {
    "etf_confirm": "ETF现货确认",
    "etf_weaken": "ETF现货削弱",
    "fundamental_confirm": "基本面价格兑现确认",
    "fundamental_weaken": "基本面价格兑现削弱",
    "maker_counter_current": "Maker当前最强反证残余",
}

SCENARIO_DETAIL_MARKERS = (
    "**主账户基准情景**：触发条件为",
    "**主账户反证情景**：触发条件为",
    "**主账户失效情景**：触发条件为",
    "**Maker基准情景**：触发条件为",
    "**Maker反证情景**：触发条件为",
    "**Maker失效情景**：触发条件为",
)

PRESENTATION_CONTRACT_PATH = "governance/vnext_report_presentation_contract.json"
PRESENTATION_CONTRACT_SCHEMA_VERSION = "vnext-report-presentation-contract-v11"
TIMEFRAME_DISPLAY_SCHEMA_VERSION = REGISTRY.timeframe_display_schema_version
TIMEFRAME_DISPLAY_CODES = frozenset({"1d", "4h", "1h", "15m", "3d", "48h", "24h"})
TRADINGVIEW_TIMEFRAME_CODES = ("1d", "4h", "1h", "15m")


def _validated_timeframe_display_contract(
    presentation_contract: dict[str, Any],
) -> dict[str, Any]:
    if (
        presentation_contract.get("schema_version")
        != PRESENTATION_CONTRACT_SCHEMA_VERSION
        or "four_timeframe_tokens" in presentation_contract
    ):
        raise ValueError("vNext report presentation contract has stale timeframe authority")
    value = presentation_contract.get("timeframe_display_contract")
    if not isinstance(value, dict):
        raise ValueError("vNext report presentation contract lacks timeframe display authority")
    mapping = value.get("canonical_by_code")
    order = value.get("tradingview_projection_order")
    if (
        value.get("schema_version") != TIMEFRAME_DISPLAY_SCHEMA_VERSION
        or not isinstance(mapping, dict)
        or set(mapping) != TIMEFRAME_DISPLAY_CODES
        or any(
            not isinstance(code, str)
            or not isinstance(label, str)
            or not label
            or label != label.strip()
            for code, label in mapping.items()
        )
        or len(set(mapping.values())) != len(mapping)
        or tuple(order or ()) != TRADINGVIEW_TIMEFRAME_CODES
    ):
        raise ValueError("vNext timeframe display contract is invalid")
    return {
        "schema_version": TIMEFRAME_DISPLAY_SCHEMA_VERSION,
        "canonical_by_code": dict(mapping),
        "tradingview_projection_order": list(order),
    }


def _timeframe_display_label(timeframe_contract: dict[str, Any], code: Any) -> str:
    if not isinstance(code, str):
        raise ValueError("timeframe code must be a canonical string")
    mapping = timeframe_contract["canonical_by_code"]
    if code not in mapping:
        raise ValueError(f"unsupported canonical timeframe code: {code!r}")
    return str(mapping[code])


def _default_timeframe_display_contract() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    return _validated_timeframe_display_contract(load_presentation_contract(root))


def _contains_exact_timeframe_label(text: str, label: str) -> bool:
    return re.search(
        rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])",
        text,
    ) is not None


def _maker_semantic_state(maker: dict[str, Any]) -> str:
    sealed_state = maker.get("semantic_state")
    if sealed_state is not None:
        if sealed_state not in {
            QUALIFIED_CANDIDATE,
            REJECTED_SUBMITTED_CANDIDATE,
            DIRECTIONAL_THESIS_ONLY,
            NON_DIRECTIONAL_OBSERVATION,
        }:
            raise ValueError("Maker semantic_state is outside the closed vocabulary")
        return str(sealed_state)
    constructibility = (
        maker.get("plan_constructibility")
        if isinstance(maker.get("plan_constructibility"), dict)
        else {}
    )
    lifecycle = (
        maker.get("order_lifecycle")
        if isinstance(maker.get("order_lifecycle"), dict)
        else {}
    )
    reach_basis = (
        maker.get("entry_reach_probability_basis")
        if isinstance(maker.get("entry_reach_probability_basis"), dict)
        else {}
    )
    return classify_maker_semantic_state(
        plan_state=maker.get("plan_state"),
        direction=maker.get("direction"),
        plan_constructible=maker.get("plan_constructible"),
        threshold_eligible=maker.get("threshold_eligible"),
        risk_plan=maker.get("risk_plan"),
        defense_plan=maker.get("defense_plan"),
        position_notional_usdt=maker.get("position_notional_usdt"),
        entry_type=maker.get("entry_type"),
        order_lifecycle_state=lifecycle.get("state"),
        entry_reach_probability_applicability=reach_basis.get("applicability"),
        constructibility_reason=constructibility.get("primary_reason_code"),
    )


def _maker_plan_is_qualified(maker: dict[str, Any]) -> bool:
    return _maker_semantic_state(maker) == QUALIFIED_CANDIDATE


def _maker_plan_summary(maker: dict[str, Any]) -> str:
    semantic_state = _maker_semantic_state(maker)
    if semantic_state == QUALIFIED_CANDIDATE:
        return DIRECTION_CN.get(str(maker.get("direction")), "候选计划成立")
    if semantic_state == REJECTED_SUBMITTED_CANDIDATE:
        return "本轮已提交候选未通过认证，只保留不可执行审计"
    if semantic_state == DIRECTIONAL_THESIS_ONLY:
        return "本轮只保留方向判断，未提交候选计划"
    if semantic_state == NON_DIRECTIONAL_OBSERVATION:
        return "本轮为无方向观察结论，不存在候选计划"
    raise ValueError("Maker semantic state is unavailable")


def _constructibility_reason_texts(value: Any) -> list[str]:
    """Project every certified failure in authority order without fallback text."""

    if not isinstance(value, dict):
        raise ValueError("plan_constructibility must be an object")
    primary = str(value.get("primary_reason_code") or "")
    raw_codes = value.get("failure_codes")
    if not isinstance(raw_codes, list):
        raise ValueError("plan_constructibility.failure_codes must be an array")
    codes = [str(item) for item in raw_codes]
    if len(codes) != len(set(codes)):
        raise ValueError("plan_constructibility.failure_codes contains duplicates")
    unknown = [code for code in codes if code not in CONSTRUCTIBILITY_REASON_CN]
    if unknown:
        raise ValueError(
            "unknown plan constructibility failure code(s): " + ", ".join(unknown)
        )
    expected_order = [code for code in FAILURE_ORDER if code in set(codes)]
    if codes != expected_order:
        raise ValueError("plan_constructibility.failure_codes is outside authority order")
    if codes:
        if primary != codes[0]:
            raise ValueError(
                "plan_constructibility.primary_reason_code must equal the first failure"
            )
        return [CONSTRUCTIBILITY_REASON_CN[code] for code in codes]
    if primary != "constructible":
        raise ValueError(
            "an empty plan_constructibility.failure_codes requires constructible primary"
        )
    return [CONSTRUCTIBILITY_REASON_CN["constructible"]]


def _maker_plan_reason_texts(maker: dict[str, Any]) -> list[str]:
    constructibility = maker.get("plan_constructibility")
    texts = _constructibility_reason_texts(constructibility)
    failure_codes = (
        constructibility.get("failure_codes")
        if isinstance(constructibility, dict)
        else None
    )
    reasons = texts if isinstance(failure_codes, list) and failure_codes else []
    if maker.get("threshold_eligible") is False:
        reasons.append(THRESHOLD_INELIGIBLE_CN)
    return reasons or texts


def _strip_clause_terminal(value: Any) -> str:
    return str(value or "").strip().rstrip("。；;")


def _join_clauses(*values: Any) -> str:
    return "；".join(
        text for text in (_strip_clause_terminal(value) for value in values) if text
    )


def _owner_field_display(owner_label: str, field_label: str) -> str:
    owner_compact = re.sub(r"\s+", "", owner_label)
    field_compact = re.sub(r"\s+", "", field_label)
    if owner_compact == field_compact:
        return owner_label
    return f"{owner_label}{field_label}"


def _structural_stop_projection(
    basis: Any,
    *,
    direction: str,
    account: str,
    policy: dict[str, Any],
    invalidation_claim: dict[str, Any],
    buffer_policy: dict[str, Any],
    timeframe_contract: dict[str, Any] | None = None,
) -> str:
    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    typed = _typed_stop_basis(basis, policy=policy)
    timeframe = str(typed.get("timeframe", "")).lower()
    allowed_timeframes = {
        str(value).lower() for value in policy.get("allowed_timeframes") or []
    }
    if not allowed_timeframes or timeframe not in allowed_timeframes:
        raise ValueError(f"{account} stop basis uses an uncertified timeframe")
    anchor = Decimal(str(typed["anchor_price"]))
    buffer_value = Decimal(str(typed["outward_buffer_price"]))
    derived = Decimal(str(typed["derived_stop"]))
    if buffer_value <= 0 or typed.get("buffer_backsolved_from_risk") is not False:
        raise ValueError("structural stop buffer must be a positive typed distance, never risk-backsolved")
    required_buffer_fields = set(buffer_policy.get("required_fields") or [])
    sealed_buffer = (
        invalidation_claim.get("structural_noise_buffer")
        if isinstance(invalidation_claim, dict)
        else None
    )
    if (
        not required_buffer_fields
        or not isinstance(sealed_buffer, dict)
        or set(sealed_buffer) != required_buffer_fields
        or sealed_buffer.get("schema_version") != buffer_policy.get("schema_version")
        or sealed_buffer.get("method_code") != buffer_policy.get("method_code")
        or sealed_buffer.get("risk_budget_input_used") is not False
        or buffer_policy.get("risk_budget_input_used") is not False
        or buffer_policy.get("compiler_may_infer") is not False
        or str(invalidation_claim.get("id") or "")
        != str(typed.get("buffer_claim_id") or "")
    ):
        raise ValueError(
            "structural stop buffer lacks its exact reasoning-stage invalidation owner"
        )
    owner_value_field = str(policy.get("buffer_value_owner_claim_field") or "")
    owner_observation_field = str(
        policy.get("buffer_observation_owner_claim_field") or ""
    )
    owner_timeframe_field = str(
        policy.get("buffer_timeframe_owner_claim_field") or ""
    )
    owner_status_field = str(policy.get("buffer_status_owner_claim_field") or "")
    owner_anchor_kind_field = str(
        policy.get("buffer_anchor_kind_owner_claim_field") or ""
    )
    owner_anchor_source_field_field = str(
        policy.get("buffer_anchor_source_field_owner_claim_field") or ""
    )
    owner_anchor_price_field = str(
        policy.get("buffer_anchor_price_owner_claim_field") or ""
    )
    owner_noise_boundary_field = str(
        policy.get("buffer_noise_outer_boundary_owner_claim_field") or ""
    )
    if not all(
        (
            owner_value_field,
            owner_observation_field,
            owner_timeframe_field,
            owner_status_field,
            owner_anchor_kind_field,
            owner_anchor_source_field_field,
            owner_anchor_price_field,
            owner_noise_boundary_field,
        )
    ):
        raise ValueError("structural stop policy lacks reasoning-stage buffer owners")
    owner_distance = _nested_typed_value(invalidation_claim, owner_value_field)
    owner_observation = _nested_typed_value(
        invalidation_claim, owner_observation_field
    )
    owner_timeframe = _nested_typed_value(invalidation_claim, owner_timeframe_field)
    owner_status = _nested_typed_value(invalidation_claim, owner_status_field)
    owner_anchor_kind = _nested_typed_value(
        invalidation_claim, owner_anchor_kind_field
    )
    owner_anchor_source_field = _nested_typed_value(
        invalidation_claim, owner_anchor_source_field_field
    )
    owner_anchor_price = _nested_typed_value(
        invalidation_claim, owner_anchor_price_field
    )
    owner_noise_boundary = _nested_typed_value(
        invalidation_claim, owner_noise_boundary_field
    )
    if (
        isinstance(owner_distance, bool)
        or not isinstance(owner_distance, (int, float, Decimal))
        or Decimal(str(owner_distance)) != buffer_value
        or str(owner_observation) != str(typed.get("observation_id") or "")
        or str(owner_timeframe).lower() != timeframe
        or owner_status != "certified"
        or str(owner_anchor_kind) != str(typed.get("anchor_kind") or "")
        or str(owner_anchor_source_field)
        != str(typed.get("anchor_source_field") or "")
        or Decimal(str(owner_anchor_price)) != anchor
    ):
        raise ValueError(
            "structural stop buffer differs from the reasoning-stage observation, timeframe or price distance"
        )
    expected = anchor + buffer_value if direction == "short" else anchor - buffer_value
    if derived != expected:
        raise ValueError("structural stop final price differs from anchor plus directional buffer")
    noise_boundary = Decimal(str(owner_noise_boundary))
    if not (
        (direction == "short" and derived > noise_boundary >= anchor)
        or (direction == "long" and derived < noise_boundary <= anchor)
    ):
        raise ValueError(
            "structural stop does not remain strictly outside its certified visible noise envelope"
        )
    anchor_kind_code = str(typed.get("anchor_kind"))
    allowed_anchor_kinds = set(policy.get("allowed_anchor_kinds") or [])
    if not allowed_anchor_kinds or anchor_kind_code not in allowed_anchor_kinds:
        raise ValueError(f"{account} stop basis uses an uncertified anchor_kind")
    anchor_source_field = str(typed.get("anchor_source_field"))
    allowed_anchor_source_fields = list(policy.get("allowed_anchor_source_fields") or [])
    source_field_allowed = any(
        re.fullmatch(
            re.escape(str(pattern)).replace(r"\[\*\]", r"\[\d+\]"),
            anchor_source_field,
        )
        for pattern in allowed_anchor_source_fields
    )
    if (
        not allowed_anchor_source_fields
        or not source_field_allowed
    ):
        raise ValueError(f"{account} stop basis uses an uncertified anchor_source_field")
    anchor_kind = {
        "manual_profile_upper_outer_boundary": "用户手绘区上沿",
        "manual_profile_lower_outer_boundary": "用户手绘区下沿",
        "structure_zone_outer_boundary": "多周期结构区外沿",
    }[anchor_kind_code]
    operator = "+" if direction == "short" else "−"
    account_text = "主账户" if account == "main" else "Maker"
    return (
        f"{account_text}{_timeframe_display_label(timeframe_contract, timeframe)}结构锚={_plain_number(anchor)}（{anchor_kind}），"
        f"可见噪声外边界={_plain_number(noise_boundary)}；"
        f"外扩缓冲={_plain_number(buffer_value)}（当前运行证据绑定噪声距离，非固定阈值、非风险倒推），"
        f"计算={_plain_number(anchor)}{operator}{_plain_number(buffer_value)}="
        f"{_plain_number(derived)}"
    )


def _main_plan_projection(
    main: dict[str, Any],
    *,
    stop_policy: dict[str, Any] | None = None,
    invalidation_claim: dict[str, Any] | None = None,
    buffer_policy: dict[str, Any] | None = None,
    timeframe_contract: dict[str, Any] | None = None,
    run_mode: str = "production",
) -> str:
    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    if main.get("plan_state") == "observe":
        return "本轮主账户只保留独立判断与反证，不生成仓位、入场、止损或止盈价格"
    entries = main.get("entries") if isinstance(main.get("entries"), list) else []
    allocations = (
        main.get("entry_allocations_pct")
        if isinstance(main.get("entry_allocations_pct"), list)
        else []
    )
    ladder = "、".join(
        f"{_plain_number(entry)}({ _plain_number(allocation) }%)"
        for entry, allocation in zip(entries, allocations)
    )
    if not ladder:
        ladder = "无认证分档"
    if stop_policy is None:
        risk_policy = load_scoring_policy().get("risk_execution") or {}
        stop_policy = dict(risk_policy.get("main_initial_stop_policy") or {})
        buffer_policy = dict(
            risk_policy.get("structural_noise_buffer_judgment") or {}
        )
    if not isinstance(invalidation_claim, dict) or not isinstance(buffer_policy, dict):
        raise ValueError("main plan projection requires its sealed invalidation buffer owner")
    plan_prefix = "影子候选" if run_mode == "shadow" else "计划"
    return (
        f"{main.get('exchange', '未提供')} {main.get('instrument', '未提供')}；"
        f"{plan_prefix}持仓{_plain_number(main.get('position_notional_usdt', 0))} USDT；"
        f"{plan_prefix}杠杆{_plain_number(main.get('leverage', 0))}x；"
        f"{plan_prefix}分档入场{ladder}；候选止损{_plain_number(main.get('stop', 0))}；"
        f"{_structural_stop_projection(main.get('stop_basis'), direction=str(main.get('direction')), account='main', policy=stop_policy, invalidation_claim=invalidation_claim, buffer_policy=buffer_policy, timeframe_contract=timeframe_contract)}；"
        f"TP1={_plain_number(main.get('tp1', 0))}并减仓{_plain_number(main.get('tp1_close_pct', 0))}%；"
        f"终局止盈={_plain_number(main.get('final_take_profit', 0))}"
    )


def _execution_action_text(action: Any) -> str:
    return {
        "not_attempted": "未尝试真实执行",
        "place_order": "具备资格并挂出条件订单",
        "observe": "具备执行环境但本轮仅观望、不挂单",
        "blocked": "真实执行资格被阻断",
    }.get(str(action), "执行状态未认证")


def _execution_authorization_text(
    *,
    run_mode: str,
    authorization: dict[str, Any],
    execution_action: Any,
    semantic_state: str,
) -> str:
    if run_mode == "shadow":
        prefix = {
            QUALIFIED_CANDIDATE: "影子候选计划",
            REJECTED_SUBMITTED_CANDIDATE: "影子被拒候选审计状态",
            DIRECTIONAL_THESIS_ONLY: "影子方向观察状态",
            NON_DIRECTIONAL_OBSERVATION: "影子无方向观察状态",
        }.get(semantic_state)
        if prefix is None:
            raise ValueError("shadow authorization lacks a closed Maker semantic state")
        return (
            f"{prefix}；未读取个人持仓/订单状态；"
            "未创建、撤销或挂出真实订单"
        )
    allowed = authorization.get("live_execution_allowed") is True
    eligibility = "当前具备真实执行资格" if allowed else "当前不具备真实执行资格"
    return f"计划结论与执行资格独立认证；{eligibility}；{_execution_action_text(execution_action)}"


def _four_timeframe_line(
    reasoning: dict[str, Any],
    *,
    timeframe_contract: dict[str, Any] | None = None,
) -> str:
    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    observations = _observation_index(reasoning)
    metrics = (observations.get("TradingView") or {}).get("metrics") or {}
    timeframes = metrics.get("timeframes") if isinstance(metrics, dict) else {}
    if not isinstance(timeframes, dict):
        raise ValueError("TradingView certified metrics lack timeframes")
    parts: list[str] = []
    for key in timeframe_contract["tradingview_projection_order"]:
        label = _timeframe_display_label(timeframe_contract, key)
        item = timeframes.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"TradingView certified metrics lack {label}")
        price = item.get("price")
        sma20 = item.get("sma20")
        structure = _metric_value(item.get("structure", "未提供"))
        if price is None or (key != "15m" and sma20 is None):
            raise ValueError(f"TradingView {label} lacks price or SMA20")
        sma20_text = (
            _plain_number(sma20)
            if sma20 is not None
            else "未采集（15m非必需）"
        )
        parts.append(
            f"{label}价格{_plain_number(price)}、SMA20 {sma20_text}、结构{structure}"
        )
    return "；".join(parts)


def _main_authorization_text(*, plan_state: Any, run_mode: str) -> str:
    """Project the main-account authorization without changing its plan state."""

    observing = plan_state == "observe"
    if run_mode == "shadow":
        if observing:
            return (
                "影子主账户观察状态；未读取或改变真实持仓，"
                "未生成计划且未尝试任何真实执行。"
            )
        return "影子候选主账户计划；未读取或改变真实持仓，未尝试任何真实执行。"
    if observing:
        return "主账户观察状态；不生成或执行计划，后续须重新认证并另获生产授权。"
    return "主账户执行状态只以本轮认证决策与生产运行授权为准。"


def _canonical_market_frontstage(
    reasoning: dict[str, Any],
    *,
    maker: dict[str, Any],
    main: dict[str, Any],
    run_mode: str,
    fedwatch_outcome_pattern: re.Pattern[str],
    rate_expectation_provider: dict[str, Any],
) -> dict[str, str]:
    """Project load-bearing market and account values from typed owners only."""

    observations = _observation_index(reasoning)
    blockbeats = (observations.get("BlockBeats") or {}).get("metrics") or {}
    fedwatch = (observations.get("FedWatch") or {}).get("metrics") or {}
    farside = (observations.get("Farside") or {}).get("metrics") or {}
    coinglass = (observations.get("Coinglass") or {}).get("metrics") or {}
    exocharts = (observations.get("Exocharts") or {}).get("metrics") or {}
    tradingview = (observations.get("TradingView") or {}).get("metrics") or {}
    pivot = coinglass.get("pivot") if isinstance(coinglass.get("pivot"), dict) else {}
    frames = tradingview.get("timeframes") if isinstance(tradingview.get("timeframes"), dict) else {}
    daily = frames.get("1d") if isinstance(frames.get("1d"), dict) else {}
    hourly = frames.get("1h") if isinstance(frames.get("1h"), dict) else {}
    chart_basis = tradingview.get("chart_basis") if isinstance(tradingview.get("chart_basis"), dict) else {}
    supports = chart_basis.get("support_levels") if isinstance(chart_basis.get("support_levels"), list) else []
    resistances = chart_basis.get("resistance_levels") if isinstance(chart_basis.get("resistance_levels"), list) else []
    support_text = "、".join(_plain_number(value) for value in supports) or "未提供"
    resistance_text = "、".join(_plain_number(value) for value in resistances) or "未提供"
    direction_text = {
        "long": "做多",
        "short": "做空",
        "neutral": "中性观察",
        "observe": "观察",
        "blocked": "阻断",
    }
    main_direction = direction_text.get(str(main.get("direction")), "中性观察")
    maker_direction = direction_text.get(str(maker.get("direction")), "观察")
    realization_claim = _claim_by_type(
        reasoning, "fundamental_price_realization"
    )
    etf_claim = _claim_by_type(reasoning, "etf_confirmation")
    realization_text = {
        "realized": "观察枚举为已兑现",
        "partially_realized": "观察枚举为部分兑现",
        "not_realized": "观察枚举为未兑现",
        "conflicted": "观察枚举为价格实现冲突",
    }.get(str(realization_claim.get("realization_state")), "未认证")
    etf_relation_text = {
        "confirm": "确认",
        "weaken": "削弱",
        "neutral": "中性",
    }.get(str(etf_claim.get("price_relation")), "未认证")
    fed_probability_text = _fedwatch_map_text(
        fedwatch.get("current_probabilities"),
        outcome_pattern=fedwatch_outcome_pattern,
        signed_delta=False,
    )
    cannot_text = {
        "做多": "禁止 Maker 做多",
        "追多": "禁止 Maker 在右侧追多",
        "做空": "禁止 Maker 做空",
        "追空": "禁止 Maker 在右侧追空",
        "追多空": "禁止 Maker 在右侧追多或追空",
    }.get(str(maker.get("cannot_do_code")), "Maker 不能做结论未认证")
    if main.get("plan_state") == "observe":
        strategy_text = (
            f"主账户保留{main_direction}中线判断，但本轮计划状态为观察；"
            "不执行计划、不生成仓位、入场、止损或止盈。Maker结论不得改写主账户。"
        )
    else:
        main_plan_verb = "形成" if run_mode == "shadow" else "执行"
        strategy_text = (
            f"主账户按基本面、盘面、盘口的独立优先级{main_plan_verb}{main_direction}中线计划；"
            "Maker结论不得改写主账户。"
        )
    main_authorization = _main_authorization_text(
        plan_state=main.get("plan_state"),
        run_mode=run_mode,
    )
    return {
        "opening_quote": "以下结论只投影当前时段已认证的六源事实、跨源判断与两套独立账户闭环。",
        "fundamentals": (
            f"BlockBeats事件窗{_plain_number(blockbeats.get('event_window_hours', 0))}小时、"
            f"入选重要事件{_plain_number(blockbeats.get('selected_event_count', 0))}条；"
            f"价格归因{realization_text}，但v1未绑定逐事件价格窗口，"
            "只作观察且不参与置信度调整或账户触发。"
            f"{rate_expectation_provider['display_name']}当前概率={fed_probability_text}；"
            f"{rate_expectation_provider['method_disclosure']}，仅定义宏观背景。"
            f"Farside最新完整日{farside.get('latest_complete_date', '未提供')}净流量"
            f"{_plain_number(farside.get('latest_total_usd_m', 0))}百万美元，"
            f"与同锚价格关系={etf_relation_text}。"
            "基本面、宏观与ETF只参与各自规定的确认层级，均不得单变量决定账户方向或下单。"
        ),
        "orderflow_label": (
            f"价格、CVD、OI三项主判为{_metric_value(coinglass.get('main_triad_direction', '未提供'))}；"
            "资金费率只修正强弱"
        ),
        "orderflow_text": (
            f"同一1H锚点{_plain_number(pivot.get('start_price', 0))}→{_plain_number(pivot.get('end_price', 0))}；"
            f"价格{_metric_value(coinglass.get('price_direction', '未提供'))}、"
            f"CVD{_metric_value(coinglass.get('cvd_direction', '未提供'))}、"
            f"OI{_metric_value(coinglass.get('oi_direction', '未提供'))}共同形成"
            f"{_metric_value(coinglass.get('main_triad_direction', '未提供'))}主判；"
            f"资金费率仅作{_metric_value(coinglass.get('funding_effect', '未提供'))}修正；"
            f"Exocharts足迹为{_metric_value(exocharts.get('cross_check_result', '未提供'))}，不得单独翻向。"
        ),
        "interpretation": (
            f"Maker结构化方向为{maker_direction}；主账户结构化方向为{main_direction}；"
            "两者分别保留自身最强反证和失效路径，不互相推导。"
        ),
        "chart_label": "盘面只评价机会质量，不承担方向主判",
        "daily_line": (
            f"1D价格{_plain_number(daily.get('price', 0))}；SMA20={_plain_number(daily.get('sma20', 0))}；"
            f"结构={_metric_value(daily.get('structure', '未提供'))}。"
        ),
        "hourly_line": (
            f"1H价格{_plain_number(hourly.get('price', 0))}；SMA20={_plain_number(hourly.get('sma20', 0))}；"
            f"结构={_metric_value(hourly.get('structure', '未提供'))}。"
        ),
        "trend_confirmation": (
            f"主账户{main_direction}、Maker{maker_direction}；"
            "账户方向来自各自认证闭环，TradingView多周期结构只承担盘面与位置判断。"
        ),
        "support_resistance": f"认证支撑={support_text}；认证压力={resistance_text}。",
        "strategy": strategy_text,
        "main_authorization": main_authorization,
        "cannot_do": cannot_text,
        "independent_boundary": (
            "主账户与Maker分别由自身类型化判断、最强反证、失效路径和情景树闭环；"
            "二者只在分析结束后并列展示，不互相引用、推导或强制同向。"
        ),
    }


def _validate_manual_profile_projection(
    reasoning: dict[str, Any],
    frontstage: dict[str, str],
) -> None:
    observations = _observation_index(reasoning)
    metrics = (observations.get("TradingView") or {}).get("metrics") or {}
    profile = metrics.get("volume_profile") if isinstance(metrics, dict) else {}
    if not isinstance(profile, dict) or profile.get("status") != "insufficient":
        return
    liquidity = _claim_by_type(reasoning, "liquidity_hunt")
    conclusion = str(liquidity.get("conclusion") or "")
    if "证据不足" not in conclusion or not re.search(r"不推断|不替代|不生成", conclusion):
        raise ValueError(
            "insufficient user-drawn profile must disclose the no-inference boundary"
        )
    profile_text = "\n".join(
        str(frontstage.get(name) or "")
        for name in ("hourly_line", "support_resistance")
    )
    if re.search(
        r"(?:VRVP|VAH|VAL|HVN|LVN|价值区|POC)[^。；\n]{0,28}\d{4,}",
        profile_text,
        re.I,
    ):
        raise ValueError(
            "insufficient user-drawn profile cannot project POC/VAH/VAL/HVN/LVN locations"
        )


def _prefixed(value: str, prefix: str) -> str:
    value = value.strip()
    return value if value.startswith(prefix) else prefix + value


def _sentence(value: Any) -> str:
    """Return one readable sentence without adding duplicate punctuation."""

    text = str(value).strip()
    return text if text.endswith(("。", "！", "？", ".", "!", "?", "；", ";")) else text + "。"


def _claim_by_type(
    reasoning: dict[str, Any],
    claim_type: str,
    *,
    account: str | None = None,
) -> dict[str, Any]:
    matches = [
        claim
        for claim in reasoning.get("claims", [])
        if isinstance(claim, dict)
        and claim.get("claim_type") == claim_type
        and (account is None or claim.get("account") == account)
    ]
    if len(matches) != 1:
        suffix = f"/{account}" if account else ""
        raise ValueError(f"expected one certified claim: {claim_type}{suffix}")
    return matches[0]


_LIQUIDATION_FACT_MARKER = re.compile(r"清算(?:图|带|区|位|磁吸|密集|热力)")
def _human_observation_fact(
    observation: dict[str, Any],
    *,
    timeframe_contract: dict[str, Any] | None = None,
) -> str:
    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    """Project a certified observation fact without inventing market meaning.

    Coinglass liquidation levels are only interpretable with their captured
    window.  The window is already certified in structured metrics, so the
    presentation layer may append a missing label deterministically.  Existing
    labels are preserved without duplication.
    """

    fact = str(observation.get("fact", "")).strip()
    if observation.get("source") != "Coinglass" or not _LIQUIDATION_FACT_MARKER.search(fact):
        return fact
    metrics = observation.get("metrics")
    heatmap = metrics.get("liquidation_map") if isinstance(metrics, dict) else None
    captured = heatmap.get("captured_timeframes") if isinstance(heatmap, dict) else None
    if not isinstance(captured, list):
        return fact
    labels = [
        _timeframe_display_label(timeframe_contract, value)
        for value in captured
    ]
    missing = [
        label
        for label in labels
        if not _contains_exact_timeframe_label(fact, label)
    ]
    if not missing:
        return fact
    return f"{fact.rstrip('。；;')}；清算图周期：{'、'.join(missing)}。"


def _fedwatch_outcome_pattern(scoring_policy: dict[str, Any]) -> re.Pattern[str]:
    pattern_text = str(
        (scoring_policy.get("gold_methodology") or {}).get(
            "fedwatch_outcome_key_pattern",
            "",
        )
    )
    try:
        pattern = re.compile(pattern_text)
    except re.error as exc:
        raise ValueError("invalid FedWatch outcome-key policy") from exc
    if not pattern_text:
        raise ValueError("missing FedWatch outcome-key policy")
    return pattern


def _rate_expectation_provider_projection(
    evidence: dict[str, Any],
    *,
    provider_contract: dict[str, Any],
) -> dict[str, Any]:
    """Project the sealed provider identity without trusting display prose."""

    sources = evidence.get("sources")
    fedwatch = sources.get("FedWatch") if isinstance(sources, dict) else None
    meta = fedwatch.get("meta") if isinstance(fedwatch, dict) else None
    if not isinstance(meta, dict):
        raise ValueError("FedWatch evidence lacks sealed provider metadata")
    if evidence.get("schema_version") == "evidence-snapshot-v1":
        if meta:
            raise ValueError("legacy evidence cannot assert rate-expectation provider metadata")
        return {
            "provider_id": "unknown",
            "display_name": "利率预期来源未绑定（旧版只读证据）",
            "selection_mode": "legacy_unbound",
            "series_ticker": None,
            "acquisition_channel": "unknown",
            "method_class": "unknown",
            "method_equivalence": "unknown",
            "sample_source_class": "unknown",
            "quote_basis_code": "unknown",
            "normalization_method_code": "unknown",
            "fallback_reason_code": "unknown",
            "provenance_sha256": None,
            "observation_only": True,
            "method_disclosure": "旧版证据未密封实际provider与方法口径，仅作observation",
        }
    if evidence.get("schema_version") != "evidence-snapshot-v2":
        raise ValueError("unsupported evidence schema for rate-expectation provider projection")
    provider_id = str(meta.get("provider_id") or "")
    contract = _RATE_EXPECTATION_PROVIDER_CONTRACTS.get(provider_id)
    if contract is None:
        raise ValueError("FedWatch evidence has an unsupported provider_id")
    required_fields = {
        "provider_id",
        "selection_mode",
        "series_ticker",
        "acquisition_channel",
        "method_class",
        "method_equivalence",
        "sample_source_class",
        "quote_basis_code",
        "normalization_method_code",
        "fallback_reason_code",
        "provenance_sha256",
    }
    missing = sorted(required_fields - set(meta))
    if missing:
        raise ValueError(
            "FedWatch evidence provider metadata is incomplete: " + ", ".join(missing)
        )
    for field in (
        "selection_mode",
        "series_ticker",
        "acquisition_channel",
        "method_class",
        "method_equivalence",
        "sample_source_class",
        "quote_basis_code",
        "normalization_method_code",
    ):
        if meta.get(field) != contract[field]:
            raise ValueError(f"FedWatch evidence provider metadata conflicts at {field}")
    fallback_reason = str(meta.get("fallback_reason_code") or "")
    if provider_id == "cme_fedwatch_ui":
        if fallback_reason != "none":
            raise ValueError("CME primary evidence cannot carry a fallback reason")
    else:
        cme_contract = provider_contract.get("cme")
        eligible_codes = (
            cme_contract.get("eligible_fallback_codes")
            if isinstance(cme_contract, dict)
            else None
        )
        if (
            not isinstance(eligible_codes, list)
            or not eligible_codes
            or any(
                not isinstance(code, str)
                or _SAFE_PROVIDER_CODE_PATTERN.fullmatch(code) is None
                for code in eligible_codes
            )
            or len(eligible_codes) != len(set(eligible_codes))
            or fallback_reason not in eligible_codes
        ):
            raise ValueError(
                "Kalshi Plan C evidence lacks a closed eligible fallback reason code"
            )
    provenance_sha256 = str(meta.get("provenance_sha256") or "")
    if _SHA256_PATTERN.fullmatch(provenance_sha256) is None:
        raise ValueError("FedWatch evidence provider provenance SHA-256 is invalid")
    return {
        "provider_id": provider_id,
        "display_name": contract["display_name"],
        "selection_mode": contract["selection_mode"],
        "series_ticker": contract["series_ticker"],
        "acquisition_channel": contract["acquisition_channel"],
        "method_class": contract["method_class"],
        "method_equivalence": contract["method_equivalence"],
        "sample_source_class": contract["sample_source_class"],
        "quote_basis_code": contract["quote_basis_code"],
        "normalization_method_code": contract["normalization_method_code"],
        "fallback_reason_code": fallback_reason,
        "provenance_sha256": provenance_sha256,
        "observation_only": contract["observation_only"],
        "method_disclosure": contract["method_disclosure"],
    }


def _project_fedwatch_numeric_map(
    value: Any,
    *,
    outcome_pattern: re.Pattern[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("FedWatch probability map must be a typed object")
    projected: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if outcome_pattern.fullmatch(key) is None or isinstance(raw_value, bool):
            raise ValueError("uncertified FedWatch outcome key or value")
        try:
            number = Decimal(str(raw_value))
        except (ArithmeticError, ValueError):
            raise ValueError("FedWatch probability value must be numeric")
        if not number.is_finite():
            raise ValueError("FedWatch probability value must be finite")
        projected[key] = copy.deepcopy(raw_value)
    return projected


def _project_typed_metric(
    value: Any,
    schema: Any,
    *,
    fedwatch_outcome_pattern: re.Pattern[str],
) -> Any:
    if schema is _TYPED_SCALAR:
        return (
            _OMIT_TYPED_VALUE
            if isinstance(value, (dict, list))
            else copy.deepcopy(value)
        )
    if schema is _FEDWATCH_NUMERIC_MAP:
        return _project_fedwatch_numeric_map(
            value,
            outcome_pattern=fedwatch_outcome_pattern,
        )
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            return {}
        projected: dict[str, Any] = {}
        for key, child_schema in schema.items():
            if key not in value:
                continue
            child = _project_typed_metric(
                value[key],
                child_schema,
                fedwatch_outcome_pattern=fedwatch_outcome_pattern,
            )
            if child is not _OMIT_TYPED_VALUE:
                projected[key] = child
        return projected
    if isinstance(schema, list) and len(schema) == 1:
        if not isinstance(value, list):
            return []
        projected_items = [
            _project_typed_metric(
                item,
                schema[0],
                fedwatch_outcome_pattern=fedwatch_outcome_pattern,
            )
            for item in value
        ]
        return [item for item in projected_items if item is not _OMIT_TYPED_VALUE]
    raise ValueError("unsupported typed metric projection schema")


def _fedwatch_outcome_label(key: str) -> str:
    if key == "hold":
        return "维持利率"
    if key == "other_unlisted":
        return "其他未列出结果"
    tail = re.fullmatch(r"(cut|hike)_gt_([1-9][0-9]*)bp", key)
    if tail is not None:
        action = "降息" if tail.group(1) == "cut" else "加息"
        return f"{action}超过{tail.group(2)}bp"
    match = re.fullmatch(r"(cut|hike)_([1-9][0-9]*)bp", key)
    if match is None:
        raise ValueError("uncertified FedWatch outcome key")
    action = "降息" if match.group(1) == "cut" else "加息"
    return f"{action}{match.group(2)}bp"


def _fedwatch_outcome_sort_key(key: str) -> tuple[int, int]:
    if key == "hold":
        return (2, 0)
    if key == "other_unlisted":
        return (5, 0)
    tail = re.fullmatch(r"(cut|hike)_gt_([1-9][0-9]*)bp", key)
    if tail is not None:
        basis_points = int(tail.group(2))
        return (0, -basis_points) if tail.group(1) == "cut" else (4, basis_points)
    match = re.fullmatch(r"(cut|hike)_([1-9][0-9]*)bp", key)
    if match is None:
        raise ValueError("uncertified FedWatch outcome key")
    basis_points = int(match.group(2))
    return (1, -basis_points) if match.group(1) == "cut" else (3, basis_points)


def _fedwatch_map_text(
    value: Any,
    *,
    outcome_pattern: re.Pattern[str],
    signed_delta: bool,
) -> str:
    projected = _project_fedwatch_numeric_map(
        value,
        outcome_pattern=outcome_pattern,
    )
    parts: list[str] = []
    for key in sorted(projected, key=_fedwatch_outcome_sort_key):
        raw_value = projected[key]
        numeric = Decimal(str(raw_value))
        rendered = _plain_number(raw_value)
        if signed_delta and numeric > 0:
            rendered = "+" + rendered
        unit = "个百分点" if signed_delta else "%"
        parts.append(f"{_fedwatch_outcome_label(key)}={rendered}{unit}")
    return "、".join(parts) or "未提供"


def _manual_profile_status_basis(profile: dict[str, Any]) -> str:
    """Explain the certified manual-profile state without trusting raw prose."""

    status = str(profile.get("status") or "")
    platform_state = str(profile.get("platform_indicator_state") or "")
    if status == "readable":
        if platform_state == "hidden":
            return "平台内置相关指标已隐藏，用户手绘区间已认证可读"
        if platform_state == "absent":
            return "平台内置相关指标不存在，用户手绘区间已认证可读"
        raise ValueError("readable manual profile has uncertified platform state")
    if status == "insufficient":
        if platform_state == "visible":
            return "平台内置相关指标仍可见，用户手绘证据维度不得认证并按0分处理"
        if platform_state == "unknown":
            return "平台指标状态未经认证，用户手绘证据维度不得认证并按0分处理"
        if platform_state == "hidden":
            return "平台内置相关指标已隐藏，但用户手绘区域未形成可读认证区间，该维度按0分处理"
        if platform_state == "absent":
            return "平台内置相关指标不存在，但用户手绘区域未形成可读认证区间，该维度按0分处理"
        raise ValueError("insufficient manual profile has uncertified platform state")
    raise ValueError("uncertified manual profile status")


def _source_facts(
    reasoning: dict[str, Any],
    *,
    fedwatch_outcome_pattern: re.Pattern[str],
    timeframe_contract: dict[str, Any] | None = None,
    rate_expectation_provider: dict[str, Any] | None = None,
    blockbeats_events: list[dict[str, Any]] | None = None,
    fundamental_event_projections: list[dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """Return deterministic facts reconstructed from certified typed metrics."""

    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()

    explanations = _source_explanations(
        reasoning,
        fedwatch_outcome_pattern=fedwatch_outcome_pattern,
        timeframe_contract=timeframe_contract,
        rate_expectation_provider=rate_expectation_provider,
        blockbeats_events=blockbeats_events,
        fundamental_event_projections=fundamental_event_projections,
    )
    return {
        source: [str((explanations.get(source) or {}).get("fact", "")).strip()]
        if str((explanations.get(source) or {}).get("fact", "")).strip()
        else []
        for source in REQUIRED_SOURCES
    }


def _source_metrics(
    reasoning: dict[str, Any],
    *,
    fedwatch_outcome_pattern: re.Pattern[str],
) -> dict[str, dict[str, Any]]:
    """Rebuild the typed metric audit from closed per-source schemas."""

    metrics = {source: {} for source in REQUIRED_SOURCES}
    seen_sources: set[str] = set()
    for observation in reasoning.get("observations", []):
        if not isinstance(observation, dict):
            continue
        source = str(observation.get("source", ""))
        values = observation.get("metrics")
        if source not in metrics:
            continue
        if source in seen_sources:
            raise ValueError(f"duplicate certified observation source: {source}")
        seen_sources.add(source)
        if not isinstance(values, dict):
            raise ValueError(f"certified source metrics must be an object: {source}")
        projected = _project_typed_metric(
            values,
            SOURCE_METRIC_AUDIT_SCHEMA[source],
            fedwatch_outcome_pattern=fedwatch_outcome_pattern,
        )
        metrics[source] = projected if isinstance(projected, dict) else {}
    missing_sources = set(REQUIRED_SOURCES) - seen_sources
    if missing_sources:
        raise ValueError(
            "canonical source-metric projection is missing: "
            + ", ".join(sorted(missing_sources))
        )
    return metrics


def _typed_entry_zone_basis(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return {}
    return {
        key: copy.deepcopy(value.get(key))
        for key in ("observation_id", "zone_kind", "zone_index")
        if key in value
    }


def _typed_stop_basis(
    value: Any,
    *,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("structural stop basis must be an object")
    required_fields = tuple(policy.get("required_stop_basis_fields") or [])
    if not required_fields:
        raise ValueError("structural stop policy lacks required_stop_basis_fields")
    missing = [field for field in required_fields if field not in value]
    if missing:
        raise ValueError("structural stop basis is incomplete: " + ", ".join(missing))
    return {field: copy.deepcopy(value[field]) for field in required_fields}


def _typed_main_plan(
    main: dict[str, Any],
    *,
    stop_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    projected = {
        key: copy.deepcopy(main.get(key))
        for key in MAIN_PLAN_AUDIT_FIELDS
        if key in main
    }
    if "entry_zone_basis" in projected:
        projected["entry_zone_basis"] = _typed_entry_zone_basis(
            main.get("entry_zone_basis")
        )
    if main.get("plan_state") != "observe":
        if stop_policy is None:
            stop_policy = dict(
                (load_scoring_policy().get("risk_execution") or {}).get(
                    "main_initial_stop_policy"
                )
                or {}
            )
        projected["stop_basis"] = _typed_stop_basis(
            main.get("stop_basis"), policy=stop_policy
        )
    return projected


def _typed_plan_constructibility(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    projected = {
        key: copy.deepcopy(value.get(key))
        for key in ("status", "primary_reason_code", "failure_codes", "claim_ids")
        if key in value
    }
    if "entry_zone_basis" in value:
        projected["entry_zone_basis"] = _typed_entry_zone_basis(
            value.get("entry_zone_basis")
        )
    return projected


def _typed_entry_reach_probability_basis(maker: dict[str, Any]) -> dict[str, Any]:
    basis = (
        maker.get("entry_reach_probability_basis")
        if isinstance(maker.get("entry_reach_probability_basis"), dict)
        else {}
    )
    projected = {"claim_ids": list(basis.get("claim_ids") or [])}
    required_fields = (
        "applicability",
        "reference_source",
        "reference_timeframe",
        "reference_price",
        "reference_entry",
        "entry_distance",
        "reach_direction",
    )
    missing = [field for field in required_fields if field not in basis]
    if missing:
        raise ValueError(
            "entry reach probability basis is incomplete: "
            + ", ".join(missing)
        )
    projected.update(
        {field: copy.deepcopy(basis[field]) for field in required_fields}
    )
    return projected


def _typed_entry_reach_probability_projection(
    maker: dict[str, Any],
) -> dict[str, Any]:
    basis = _typed_entry_reach_probability_basis(maker)
    applicability = str(basis.get("applicability") or "")
    value = maker.get("entry_reach_probability")
    reference_price = basis.get("reference_price")
    if (
        basis.get("reference_source") != "TradingView"
        or basis.get("reference_timeframe") != "1h"
        or not isinstance(reference_price, (int, float, Decimal))
        or isinstance(reference_price, bool)
        or reference_price <= 0
    ):
        raise ValueError(
            "entry reach probability requires a positive certified TradingView 1h reference price"
        )
    geometry_values = (
        basis.get("reference_entry"),
        basis.get("entry_distance"),
        basis.get("reach_direction"),
    )
    if applicability == "applicable":
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 100
            or any(item is None or item == "" for item in geometry_values)
        ):
            raise ValueError(
                "applicable entry reach probability requires a 0..100 integer and complete reach geometry"
            )
        return {
            "applicability": "applicable",
            "value_pct": value,
            "reason_code": None,
        }
    if applicability == "not_applicable_no_certified_entry_geometry":
        if value is not None or any(
            item is not None and item != "" for item in geometry_values
        ):
            raise ValueError(
                "non-applicable entry reach probability must be null with empty entry reach geometry"
            )
        return {
            "applicability": applicability,
            "value_pct": None,
            "reason_code": "no_certified_entry_geometry",
        }
    raise ValueError("entry reach probability applicability is outside the closed vocabulary")


def _entry_reach_probability_display(projection: dict[str, Any]) -> str:
    if projection.get("applicability") == "applicable":
        return f"{projection.get('value_pct')}%"
    if (
        projection.get("applicability")
        == "not_applicable_no_certified_entry_geometry"
        and projection.get("value_pct") is None
        and projection.get("reason_code") == "no_certified_entry_geometry"
    ):
        return "不适用（本轮无认证入场几何，无法定义触达对象）"
    raise ValueError("entry reach probability projection is internally inconsistent")


def _typed_order_lifecycle(maker: dict[str, Any]) -> dict[str, Any]:
    lifecycle = (
        maker.get("order_lifecycle")
        if isinstance(maker.get("order_lifecycle"), dict)
        else {}
    )
    required_fields = {
        "schema_version",
        "state",
        "legal_fill_path_exists",
        "legal_cancel_path_exists",
        "fill_probability",
        "fill_probability_applicability",
        "reason_code",
    }
    if set(lifecycle) != required_fields:
        raise ValueError("order lifecycle differs from the closed typed schema")
    if lifecycle.get("schema_version") != "maker-order-lifecycle-v1":
        raise ValueError("order lifecycle schema version is unsupported")
    if lifecycle.get("fill_probability") is not None:
        raise ValueError("order lifecycle may not fabricate an actual fill probability")
    expected = {
        "fillable": (True, True, "not_estimated_lifecycle_only"),
        "cancel_blocks_all_entries": (
            False,
            True,
            "not_applicable_no_legal_fill_path",
        ),
        "entry_before_cancel": (
            True,
            False,
            "not_applicable_invalid_prefill_cancel",
        ),
        "invalid_geometry": (False, False, "not_applicable_invalid_geometry"),
        "not_applicable_no_candidate_geometry": (
            False,
            False,
            "not_applicable_no_candidate_geometry",
        ),
    }
    state = str(lifecycle.get("state") or "")
    if state not in expected:
        raise ValueError("order lifecycle state is outside the closed vocabulary")
    fill_path, cancel_path, probability_applicability = expected[state]
    if (
        lifecycle.get("legal_fill_path_exists") is not fill_path
        or lifecycle.get("legal_cancel_path_exists") is not cancel_path
        or lifecycle.get("fill_probability_applicability")
        != probability_applicability
        or lifecycle.get("reason_code") != state
    ):
        raise ValueError("order lifecycle projection is internally inconsistent")
    return copy.deepcopy(lifecycle)


def _order_lifecycle_display(lifecycle: dict[str, Any]) -> str:
    lifecycle = _typed_order_lifecycle({"order_lifecycle": lifecycle})
    state = str(lifecycle.get("state") or "")
    expected = {
        "fillable": (True, True, "存在合法入场路径；撤单位于反方向分支。实际成交概率未估计"),
        "cancel_blocks_all_entries": (False, True, "撤单价会先于所有入场档触发，订单没有可成交路径"),
        "entry_before_cancel": (True, False, "至少一档会先成交后才触及撤单价，不属于成交前撤单"),
        "invalid_geometry": (False, False, "价格几何冲突，无法形成合法订单生命周期"),
        "not_applicable_no_candidate_geometry": (False, False, "无完整候选价格几何，订单生命周期不适用"),
    }
    if state not in expected:
        raise ValueError("order lifecycle state is outside the closed vocabulary")
    fill_path, cancel_path, text = expected[state]
    if (
        lifecycle.get("legal_fill_path_exists") is not fill_path
        or lifecycle.get("legal_cancel_path_exists") is not cancel_path
        or lifecycle.get("reason_code") != state
    ):
        raise ValueError("order lifecycle projection is internally inconsistent")
    return text


def _typed_risk_plan(
    maker: dict[str, Any],
    *,
    stop_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk = maker.get("risk_plan") if isinstance(maker.get("risk_plan"), dict) else {}
    if not risk:
        return {}
    required_fields = (
        "entries",
        "entry_allocations_pct",
        "stop_basis",
        "stop",
        "tp1",
        "tp2",
        "tp1_close_pct",
        "tp2_close_pct",
        "leverage",
        "cancel_before_fill",
    )
    missing = [field for field in required_fields if field not in risk]
    if missing:
        raise ValueError("candidate risk plan is incomplete: " + ", ".join(missing))
    projected = {field: copy.deepcopy(risk[field]) for field in required_fields}
    if stop_policy is None:
        stop_policy = dict(
            (load_scoring_policy().get("risk_execution") or {}).get(
                "maker_initial_stop_policy"
            )
            or {}
        )
    if maker.get("plan_constructible") is True:
        projected["stop_basis"] = _typed_stop_basis(
            risk.get("stop_basis"), policy=stop_policy
        )
    else:
        raw_stop_basis = risk.get("stop_basis")
        projected["stop_basis"] = (
            {
                field: copy.deepcopy(raw_stop_basis.get(field))
                for field in stop_policy.get("required_stop_basis_fields") or []
                if isinstance(raw_stop_basis, dict) and field in raw_stop_basis
            }
            if isinstance(raw_stop_basis, dict)
            else {}
        )
        projected["candidate_status"] = "rejected_not_executable"
    return projected


def _typed_defense_plan(maker: dict[str, Any]) -> dict[str, Any]:
    defense = (
        maker.get("defense_plan")
        if isinstance(maker.get("defense_plan"), dict)
        else {}
    )
    if not defense:
        return {}
    required_fields = (
        "mode",
        "prefill_anchor",
        "trigger_scenarios",
        "postfill_recalculation",
        "first_stop_rule",
        "second_action",
    )
    missing = [field for field in required_fields if field not in defense]
    if missing:
        raise ValueError(
            "candidate defense plan is incomplete: " + ", ".join(missing)
        )
    if maker.get("plan_constructible") is not True:
        projected = {
            field: copy.deepcopy(defense[field]) for field in required_fields
        }
        projected["candidate_status"] = "rejected_not_executable"
        return projected
    prefill = defense.get("prefill_anchor")
    trigger_scenarios = defense.get("trigger_scenarios")
    postfill = defense.get("postfill_recalculation")
    if not isinstance(prefill, dict):
        raise ValueError("constructible defense plan prefill_anchor must be an object")
    if not isinstance(trigger_scenarios, list) or not trigger_scenarios:
        raise ValueError("constructible defense plan trigger_scenarios must be non-empty")
    if not isinstance(postfill, dict):
        raise ValueError("constructible defense plan postfill_recalculation must be an object")
    prefill_fields = (
        "kind",
        "weighted_fill",
        "is_actual_fill",
        "is_single_entry",
    )
    trigger_fields = (
        "risk_scenario_id",
        "filled_level_indexes",
        "weighted_fill",
        "first_trigger_price_raw",
        "second_trigger_price_raw",
        "rounding_rule",
        "rounding_step",
        "first_trigger_price",
        "second_trigger_price",
    )
    postfill_fields = ("required", "anchor", "replace_prefill_projection")
    missing_prefill = [field for field in prefill_fields if field not in prefill]
    missing_postfill = [field for field in postfill_fields if field not in postfill]
    if missing_prefill or missing_postfill:
        raise ValueError(
            "constructible defense plan nested fields are incomplete: "
            + ", ".join(missing_prefill + missing_postfill)
        )
    projected_scenarios: list[dict[str, Any]] = []
    for index, scenario in enumerate(trigger_scenarios):
        if not isinstance(scenario, dict):
            raise ValueError(f"constructible defense trigger scenario {index} is invalid")
        missing_trigger = [field for field in trigger_fields if field not in scenario]
        if missing_trigger:
            raise ValueError(
                f"constructible defense trigger scenario {index} is incomplete: "
                + ", ".join(missing_trigger)
            )
        projected_scenarios.append(
            {field: copy.deepcopy(scenario[field]) for field in trigger_fields}
        )
    return {
        "mode": copy.deepcopy(defense["mode"]),
        "prefill_anchor": {
            field: copy.deepcopy(prefill[field]) for field in prefill_fields
        },
        "trigger_scenarios": projected_scenarios,
        "postfill_recalculation": {
            field: copy.deepcopy(postfill[field]) for field in postfill_fields
        },
        "first_stop_rule": copy.deepcopy(defense["first_stop_rule"]),
        "second_action": copy.deepcopy(defense["second_action"]),
    }


def _typed_continuity_contract(continuity: dict[str, Any]) -> dict[str, Any]:
    if continuity.get("schema_version") == SHADOW_CONTINUITY_SCHEMA_VERSION:
        return {
            key: copy.deepcopy(continuity.get(key))
            for key in SHADOW_CONTINUITY_FIELDS
            if key in continuity
        }
    prior = continuity.get("prior_plan") if isinstance(continuity.get("prior_plan"), dict) else {}
    current = continuity.get("current_plan") if isinstance(continuity.get("current_plan"), dict) else {}
    return {
        "schema_version": continuity.get("schema_version"),
        "reasoning_sha256": continuity.get("reasoning_sha256"),
        "prior_plan": {
            key: copy.deepcopy(prior.get(key))
            for key in (
                "source_kind",
                "source_sha256",
                "observed_at",
                "status",
                "executed_pct",
                "executable_order_count_before",
                "daily_trade_count_before",
            )
            if key in prior
        },
        "current_plan": {
            key: copy.deepcopy(current.get(key))
            for key in (
                "action",
                "old_order_cancelled",
                "new_order_created",
                "executable_order_count_after",
                "executed_pct",
                "daily_trade_count_after",
                "valid_until",
                "independent_analysis_changed_after_lock",
            )
            if key in current
        },
    }


def _reference_labels(reasoning: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for observation in reasoning.get("observations", []):
        if isinstance(observation, dict) and observation.get("id"):
            source = str(observation.get("source", "未知来源"))
            labels[str(observation["id"])] = f"{source} 证据"
    for claim in reasoning.get("claims", []):
        if isinstance(claim, dict) and claim.get("id"):
            claim_type = str(claim.get("claim_type", ""))
            labels[str(claim["id"])] = CLAIM_TYPE_CN.get(claim_type, "补充判断")
    return labels


def _claim_audit(reasoning: dict[str, Any]) -> list[dict[str, Any]]:
    labels = _reference_labels(reasoning)
    projected: list[dict[str, Any]] = []
    for claim in reasoning.get("claims", []):
        if not isinstance(claim, dict):
            continue
        item = copy.deepcopy(claim)
        item["support_labels"] = [
            labels.get(str(value), "认证证据")
            for value in claim.get("support_ids") or []
        ]
        item["counter_labels"] = [
            labels.get(str(value), "认证反证")
            for value in claim.get("counter_ids") or []
        ]
        item["invalidation_label"] = labels.get(
            str(claim.get("invalidation_id", "")),
            "无独立失效节点",
        )
        projected.append(item)
    return projected


def _scenario_audit(
    reasoning: dict[str, Any],
    *,
    account_controls: dict[str, dict[str, Any]],
    scenario_ownership: dict[str, Any],
    presentation_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project all visible scenario language from typed owners and closed codes."""

    projection = _scenario_projection_policy(presentation_contract)
    if (
        scenario_ownership.get("schema_version")
        != REGISTRY.scenario_ownership_schema_version
        or scenario_ownership.get("producer_free_prose_allowed") is not False
        or scenario_ownership.get("execution_lifecycle_owner")
        != "decision_and_continuity"
        or scenario_ownership.get("transition_code_by_type")
        != projection["transition_code_by_type"]
    ):
        raise ValueError("scenario ownership policy is invalid")
    expected_items = {
        (str(item["account"]), str(item["scenario_type"])): item
        for item in scenario_ownership.get("items", [])
        if isinstance(item, dict)
    }
    claims = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    methodology = reasoning.get("methodology")
    methodology_scenarios = (
        methodology.get("scenario_tree")
        if isinstance(methodology, dict)
        and isinstance(methodology.get("scenario_tree"), list)
        else []
    )
    methodology_by_key = {
        (str(item.get("account")), str(item.get("kind"))): item
        for item in methodology_scenarios
        if isinstance(item, dict)
    }
    projected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in reasoning.get("scenario_tree", []):
        if not isinstance(raw, dict) or set(raw) != {
            "id",
            "account",
            "scenario_type",
            "owner_claim_id",
        }:
            raise ValueError("scenario does not use the exact typed ownership fields")
        if not all(_canonical_closed_string(value) for value in raw.values()):
            raise ValueError("scenario ownership identifiers are not canonical")
        account = str(raw["account"])
        scenario_type = str(raw["scenario_type"])
        owner_claim_id = str(raw["owner_claim_id"])
        key = (account, scenario_type)
        expected = expected_items.get(key)
        owner_claim = claims.get(owner_claim_id)
        if (
            expected is None
            or key in seen
            or raw["id"] != expected.get("id")
            or not isinstance(owner_claim, dict)
            or owner_claim.get("account") != account
            or owner_claim.get("claim_type") != expected.get("owner_claim_type")
        ):
            raise ValueError("scenario typed owner does not match its exact matrix row")
        seen.add(key)
        transition_code = str(
            projection["transition_code_by_type"].get(scenario_type) or ""
        )
        methodology_item = methodology_by_key.get(key)
        if (
            not isinstance(methodology_item, dict)
            or methodology_item.get("claim_id") != owner_claim_id
            or methodology_item.get("action") != transition_code
        ):
            raise ValueError(
                "methodology scenario owner or transition code drifted from the top-level scenario"
            )
        if scenario_type == "base":
            direction = str(owner_claim.get("direction") or "")
            condition = str(
                (
                    projection["base_condition_by_account_direction"].get(
                        account
                    )
                    or {}
                ).get(direction)
                or ""
            )
        else:
            control = (account_controls.get(account) or {}).get(scenario_type)
            if (
                not isinstance(control, dict)
                or control.get("claim_id") != owner_claim_id
            ):
                raise ValueError("scenario lacks its same-account typed control")
            condition = str(control.get("condition") or "")
        visible = (
            projection["projection_by_account_and_transition_code"].get(account)
            or {}
        ).get(transition_code)
        if (
            not condition
            or not isinstance(visible, dict)
            or set(visible) != {"expected_path", "action"}
        ):
            raise ValueError("scenario deterministic presentation mapping is incomplete")
        projected.append(
            {
                "id": raw["id"],
                "account": account,
                "scenario_type": scenario_type,
                "owner_claim_id": owner_claim_id,
                "transition_code": transition_code,
                "condition": condition,
                "expected_path": str(visible["expected_path"]),
                "action": str(visible["action"]),
            }
        )
    if seen != set(expected_items):
        raise ValueError("scenario typed ownership matrix is incomplete")
    _validate_scenario_projection(
        projected,
        claims=list(claims.values()),
        account_controls=account_controls,
        presentation_contract=presentation_contract,
    )
    return projected


def _scenario_projection_policy(
    presentation_contract: dict[str, Any],
) -> dict[str, Any]:
    projection = presentation_contract.get("scenario_projection_contract")
    expected_fields = {
        "schema_version",
        "ownership_schema_version",
        "producer_free_prose_projectable",
        "condition_owner_by_type",
        "transition_code_by_type",
        "base_condition_by_account_direction",
        "projection_by_account_and_transition_code",
        "canonical_audit_field_order",
        "execution_lifecycle_owner",
    }
    transition_codes = {
        "base": "retain_certified_assessment",
        "counter": "reassess_on_typed_counter",
        "invalidation": "invalidate_and_recollect_evidence",
    }
    if (
        not isinstance(projection, dict)
        or set(projection) != expected_fields
        or projection.get("schema_version")
        != REGISTRY.scenario_projection_schema_version
        or projection.get("ownership_schema_version")
        != REGISTRY.scenario_ownership_schema_version
        or projection.get("producer_free_prose_projectable") is not False
        or projection.get("condition_owner_by_type")
        != {
            "base": "bound_owner_claim.typed_state",
            "counter": "bound_owner_claim.trigger_logic",
            "invalidation": "bound_owner_claim.trigger_logic",
        }
        or projection.get("transition_code_by_type") != transition_codes
        or projection.get("canonical_audit_field_order")
        != [
            "id",
            "account",
            "scenario_type",
            "owner_claim_id",
            "transition_code",
            "condition",
            "expected_path",
            "action",
        ]
        or projection.get("execution_lifecycle_owner")
        != "decision_and_continuity"
    ):
        raise ValueError("scenario presentation contract is invalid")
    base_conditions = projection.get("base_condition_by_account_direction")
    if (
        not isinstance(base_conditions, dict)
        or set(base_conditions) != {"main", "maker"}
        or set(base_conditions.get("main") or {}) != {"long", "short", "neutral"}
        or set(base_conditions.get("maker") or {})
        != {"long", "short", "observe"}
        or not all(
            isinstance(value, str) and bool(value)
            for account in base_conditions.values()
            for value in account.values()
        )
    ):
        raise ValueError("scenario base-condition projection is invalid")
    visible = projection.get("projection_by_account_and_transition_code")
    if not isinstance(visible, dict) or set(visible) != {"main", "maker"}:
        raise ValueError("scenario transition projection is invalid")
    for account in ("main", "maker"):
        rows = visible.get(account)
        if (
            not isinstance(rows, dict)
            or set(rows) != set(transition_codes.values())
            or any(
                not isinstance(row, dict)
                or set(row) != {"expected_path", "action"}
                or not all(isinstance(value, str) and bool(value) for value in row.values())
                for row in rows.values()
            )
        ):
            raise ValueError("scenario transition projection is invalid")
    return projection


def _validate_scenario_projection(
    scenarios: list[dict[str, Any]],
    *,
    claims: list[dict[str, Any]],
    account_controls: dict[str, dict[str, Any]],
    presentation_contract: dict[str, Any],
) -> None:
    """Validate canonical scenario output by exact structural reconstruction."""

    projection = _scenario_projection_policy(presentation_contract)
    fields = set(projection["canonical_audit_field_order"])
    claim_index = {
        str(item.get("id")): item
        for item in claims
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    owner_type_by_key = {
        ("main", "base"): "main_account_thesis",
        ("main", "counter"): "strongest_counterevidence",
        ("main", "invalidation"): "invalidation_path",
        ("maker", "base"): "maker_thesis",
        ("maker", "counter"): "strongest_counterevidence",
        ("maker", "invalidation"): "invalidation_path",
    }
    seen: set[tuple[str, str]] = set()
    for item in scenarios:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("canonical scenario field set is invalid")
        account = str(item.get("account") or "")
        scenario_type = str(item.get("scenario_type") or "")
        key = (account, scenario_type)
        owner = claim_index.get(str(item.get("owner_claim_id") or ""))
        transition_code = projection["transition_code_by_type"].get(scenario_type)
        if (
            key not in owner_type_by_key
            or key in seen
            or item.get("id") != f"scenario_{account}_{scenario_type}"
            or not isinstance(owner, dict)
            or owner.get("account") != account
            or owner.get("claim_type") != owner_type_by_key[key]
            or item.get("transition_code") != transition_code
        ):
            raise ValueError("canonical scenario typed provenance is invalid")
        seen.add(key)
        if scenario_type == "base":
            expected_condition = (
                projection["base_condition_by_account_direction"]
                .get(account, {})
                .get(str(owner.get("direction") or ""))
            )
        else:
            control = (account_controls.get(account) or {}).get(scenario_type)
            if (
                not isinstance(control, dict)
                or control.get("claim_id") != item.get("owner_claim_id")
            ):
                raise ValueError("canonical scenario control owner is invalid")
            expected_condition = control.get("condition")
        visible = (
            projection["projection_by_account_and_transition_code"]
            .get(account, {})
            .get(transition_code)
        )
        if (
            not isinstance(visible, dict)
            or item.get("condition") != expected_condition
            or item.get("expected_path") != visible.get("expected_path")
            or item.get("action") != visible.get("action")
        ):
            raise ValueError("canonical scenario projection drifted from typed owners")
    if seen != set(owner_type_by_key):
        raise ValueError("canonical scenario matrix is incomplete")


def _claim_index(reasoning: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for item in reasoning.get("claims", []):
        if not isinstance(item, dict) or not item.get("claim_type"):
            continue
        claim_type = str(item["claim_type"])
        account = str(item.get("account", ""))
        result[f"{claim_type}:{account}"] = item
        counts[claim_type] = counts.get(claim_type, 0) + 1
    for item in reasoning.get("claims", []):
        if not isinstance(item, dict) or not item.get("claim_type"):
            continue
        claim_type = str(item["claim_type"])
        if counts.get(claim_type) == 1:
            result[claim_type] = item
    return result


def _observation_index(reasoning: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in reasoning.get("observations", []):
        if not isinstance(item, dict) or not item.get("source"):
            continue
        source = str(item["source"])
        if source in result:
            raise ValueError(f"duplicate certified observation source: {source}")
        result[source] = item
    return result


def _nested_typed_value(owner: dict[str, Any], field: str) -> Any:
    current: Any = owner
    for token in field.split("."):
        if not isinstance(current, dict) or token not in current:
            raise ValueError(f"typed current-basis field is missing: {field}")
        current = current[token]
    return current


def _typed_domain_contains(allowed_values: Any, value: Any) -> bool:
    """Match closed JSON values without bool/int coercion or hashability assumptions."""

    return any(
        type(value) is type(allowed) and value == allowed
        for allowed in allowed_values
    )


def _canonical_closed_string(value: Any) -> bool:
    """Require an exact, non-empty string for closed-schema identifiers."""

    return isinstance(value, str) and bool(value) and value == value.strip()


def _typed_domain_intersection(left: list[Any], right: list[Any]) -> list[Any]:
    """Intersect JSON-domain values without bool/int coercion or hashing."""

    return [value for value in left if _typed_domain_contains(right, value)]


def _typed_current_basis(
    reasoning: dict[str, Any],
    claim: dict[str, Any],
) -> dict[str, Any]:
    basis = claim.get("current_basis")
    if not isinstance(basis, dict) or set(basis) != {"mode", "clauses"}:
        raise ValueError("counter or invalidation claim lacks the closed current_basis")
    raw_mode = basis.get("mode")
    if not _canonical_closed_string(raw_mode):
        raise ValueError("current_basis mode is not a canonical closed string")
    mode = raw_mode
    if mode not in {"all", "any"}:
        raise ValueError("current_basis mode is outside the closed vocabulary")
    clauses = basis.get("clauses")
    if not isinstance(clauses, list) or len(clauses) < 1:
        raise ValueError("current_basis requires at least one typed clause")
    observations = {
        str(item.get("id")): item
        for item in reasoning.get("observations", [])
        if isinstance(item, dict) and item.get("id")
    }
    claims = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    projected_clauses: list[dict[str, Any]] = []
    rendered: list[str] = []
    for index, clause in enumerate(clauses):
        if not isinstance(clause, dict) or set(clause) != {
            "owner_type",
            "owner_id",
            "field",
            "operator",
            "value",
        }:
            raise ValueError(f"current_basis clause {index} differs from the closed schema")
        raw_owner_type = clause.get("owner_type")
        raw_owner_id = clause.get("owner_id")
        raw_field = clause.get("field")
        raw_operator = clause.get("operator")
        if not all(
            _canonical_closed_string(value)
            for value in (raw_owner_type, raw_owner_id, raw_field, raw_operator)
        ):
            raise ValueError("current_basis identifiers are not canonical")
        owner_type = raw_owner_type
        owner_id = raw_owner_id
        field = raw_field
        if raw_operator != "equals":
            raise ValueError("current_basis only supports equals")
        if owner_type == "observation":
            owner = observations.get(owner_id)
            if not isinstance(owner, dict):
                raise ValueError("current_basis references an unknown observation")
            current_value = _nested_typed_value(owner.get("metrics") or {}, field)
            owner_label = str(owner.get("source"))
        elif owner_type == "claim":
            owner = claims.get(owner_id)
            if not isinstance(owner, dict):
                raise ValueError("current_basis references an unknown claim")
            current_value = _nested_typed_value(owner, field)
            owner_label = CLAIM_TYPE_CN.get(
                str(owner.get("claim_type")), str(owner.get("claim_type"))
            )
        else:
            raise ValueError("current_basis owner_type is outside the closed vocabulary")
        submitted_value = clause.get("value")
        if not (
            type(submitted_value) is type(current_value)
            and submitted_value == current_value
        ):
            raise ValueError("current_basis value differs from its typed current owner")
        projected_clauses.append(
            {key: copy.deepcopy(clause[key]) for key in (
                "owner_type",
                "owner_id",
                "field",
                "operator",
                "value",
            )}
        )
        field_label = TYPED_FIELD_LABEL_CN.get(field, _metric_label(field))
        rendered.append(
            f"{_owner_field_display(owner_label, field_label)}="
            f"{_metric_value(current_value)}"
        )
    joiner = "且" if mode == "all" else "或"
    return {
        "mode": mode,
        "clauses": projected_clauses,
        "condition": joiner.join(rendered),
    }


def _typed_account_controls(
    reasoning: dict[str, Any],
    *,
    maker: dict[str, Any],
    main: dict[str, Any],
    trigger_policy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Render certified trigger clauses without inventing new conditions."""

    claims = _claim_index(reasoning)
    observations = {
        str(item.get("id")): item
        for item in reasoning.get("observations", [])
        if isinstance(item, dict) and item.get("id")
    }
    claims_by_id = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    field_labels = {
        "timeframes.1d.structure": "TradingView 1D结构",
        "timeframes.4h.structure": "TradingView 4H结构",
        "timeframes.1h.structure": "TradingView 1H结构",
        "timeframes.15m.structure": "TradingView 15m结构",
        "flow_direction": "Farside ETF流向",
        "final_direction": "Coinglass最终主判",
        "pivot.anchor_reset": "Coinglass新锚点重置",
        "cross_check_result": "Exocharts交叉核验",
        "realization_state": "基本面—价格跨源兑现状态",
    }
    operator_labels = {
        "becomes": "转为",
        "equals_at_trigger": "触发时必须为",
        "one_of_at_trigger": "触发时必须属于",
    }

    def nested(payload: Any, field: str) -> Any:
        current = payload
        for part in field.split("."):
            current = current.get(part) if isinstance(current, dict) else None
        return current

    def project(claim: dict[str, Any]) -> dict[str, Any]:
        trigger = claim.get("trigger_logic") if isinstance(claim.get("trigger_logic"), dict) else {}
        raw_mode = trigger.get("mode")
        if not _canonical_closed_string(raw_mode):
            raise ValueError("certified account trigger mode is not canonical")
        mode = raw_mode
        allowed_modes = set(trigger_policy.get("allowed_modes") or [])
        if mode not in allowed_modes:
            raise ValueError("certified account trigger mode is not allowed")
        raw_claim_type = claim.get("claim_type")
        if not _canonical_closed_string(raw_claim_type):
            raise ValueError("certified account control claim type is not canonical")
        claim_type = raw_claim_type
        expected_effect = (trigger_policy.get("claim_effects") or {}).get(claim_type)
        if expected_effect is None or trigger.get("effect") != expected_effect:
            raise ValueError("certified account trigger effect is invalid")
        if (
            claim_type == "invalidation_path"
            and mode != trigger_policy.get("invalidation_mode")
        ):
            raise ValueError("certified invalidation trigger mode is invalid")
        raw_clauses = trigger.get("clauses")
        minimum_clause_count = trigger_policy.get("minimum_clause_count")
        if (
            not isinstance(minimum_clause_count, int)
            or isinstance(minimum_clause_count, bool)
            or minimum_clause_count < 1
            or not isinstance(raw_clauses, list)
            or len(raw_clauses) < minimum_clause_count
        ):
            raise ValueError("certified account trigger requires typed clauses")
        clauses: list[dict[str, Any]] = []
        rendered: list[str] = []
        conjunctive_target_sets: dict[tuple[str, str, str], list[Any]] = {}
        for item in raw_clauses:
            if not isinstance(item, dict):
                raise ValueError("certified account trigger clause must be an object")
            raw_owner_id = item.get("owner_id")
            raw_owner_type = item.get("owner_type")
            raw_field = item.get("field")
            raw_operator = item.get("operator")
            if not all(
                _canonical_closed_string(value)
                for value in (
                    raw_owner_id,
                    raw_owner_type,
                    raw_field,
                    raw_operator,
                )
            ):
                raise ValueError(
                    "certified account trigger identifiers are not canonical"
                )
            owner_id = raw_owner_id
            owner_type = raw_owner_type
            field = raw_field
            operator = raw_operator
            expected_clause_fields = (
                {"owner_type", "owner_id", "field", "operator", "values"}
                if operator == "one_of_at_trigger"
                else {"owner_type", "owner_id", "field", "operator", "value"}
            )
            if set(item) != expected_clause_fields:
                raise ValueError("certified account trigger clause schema is invalid")
            if owner_type == "observation":
                owner = observations.get(owner_id)
                source = str((owner or {}).get("source") or "")
                allowed_targets = (
                    ((trigger_policy.get("observation_fields") or {}).get(source) or {}).get(field)
                    or []
                )
            elif owner_type == "claim":
                owner = claims_by_id.get(owner_id)
                owner_claim_type = str((owner or {}).get("claim_type") or "")
                allowed_targets = (
                    ((trigger_policy.get("claim_fields") or {}).get(owner_claim_type) or {}).get(field)
                    or []
                )
            else:
                raise ValueError("certified account trigger owner type is invalid")
            if (
                owner is None
                or field not in field_labels
                or operator not in operator_labels
                or operator not in set(trigger_policy.get("allowed_operators") or [])
            ):
                raise ValueError("certified account trigger owner, field, or operator is invalid")
            payload = (owner or {}).get("metrics") if owner_type == "observation" else owner
            current = nested(payload or {}, field)
            raw_targets = item.get("values")
            if operator == "one_of_at_trigger":
                if not isinstance(raw_targets, list) or not raw_targets:
                    raise ValueError("certified account trigger target shape is invalid")
                targets = list(raw_targets)
            else:
                targets = [item.get("value")]
            if (
                current is None
                or not allowed_targets
                or any(
                    not _typed_domain_contains(allowed_targets, value)
                    for value in targets
                )
            ):
                raise ValueError("certified account trigger value is invalid")
            if (
                operator == "becomes"
                and len(targets) == 1
                and type(targets[0]) is type(current)
                and targets[0] == current
            ):
                raise ValueError("certified account trigger becomes target does not change state")
            if mode == "all":
                owner_field = (owner_type, owner_id, field)
                prior_targets = conjunctive_target_sets.get(owner_field)
                if prior_targets is None:
                    conjunctive_target_sets[owner_field] = list(targets)
                else:
                    reachable_targets = _typed_domain_intersection(
                        prior_targets, list(targets)
                    )
                    if not reachable_targets:
                        raise ValueError(
                            "certified account all-trigger has mutually exclusive same-field clauses"
                        )
                    conjunctive_target_sets[owner_field] = reachable_targets
            target_text = "／".join(_metric_value(value) for value in targets)
            rendered.append(
                f"{field_labels.get(field, field)}当前为{_metric_value(current)}，"
                f"{operator_labels.get(operator, operator)}{target_text}"
            )
            clauses.append(
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "field": field,
                    "operator": operator,
                    "targets": copy.deepcopy(targets),
                    "current_value": copy.deepcopy(current),
                }
            )
        mode_text = "且" if mode == "all" else "或"
        raw_claim_id = claim.get("id")
        if not _canonical_closed_string(raw_claim_id):
            raise ValueError("certified account control claim id is not canonical")
        return {
            "claim_id": raw_claim_id,
            "mode": mode,
            "effect": str(trigger.get("effect", "")),
            "clauses": clauses,
            "condition": f"{mode_text.join(rendered)}；按{('全部' if mode == 'all' else '任一')}条款触发。",
        }

    return {
        "main": {
            "counter": project(claims.get("strongest_counterevidence:main") or {}),
            "invalidation": project(claims.get("invalidation_path:main") or {}),
            "direction": str(main.get("direction", "")),
        },
        "maker": {
            "counter": project(claims.get("strongest_counterevidence:maker") or {}),
            "invalidation": project(claims.get("invalidation_path:maker") or {}),
            "direction": str(maker.get("direction", "")),
        },
    }


def _support_dag_reachability(
    reasoning: dict[str, Any],
    root_claim_ids: list[str],
) -> tuple[set[str], set[str]]:
    observations_by_id = {
        str(item.get("id")): item
        for item in reasoning.get("observations", [])
        if isinstance(item, dict) and item.get("id")
    }
    claims_by_id = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    reachable_nodes: set[str] = set()
    pending = list(root_claim_ids)
    while pending:
        node_id = str(pending.pop())
        if node_id in reachable_nodes:
            continue
        if node_id not in claims_by_id and node_id not in observations_by_id:
            raise ValueError("support DAG references an unknown certified node")
        reachable_nodes.add(node_id)
        if node_id in claims_by_id:
            pending.extend(str(value) for value in claims_by_id[node_id].get("support_ids") or [])
    reachable_observation_ids = reachable_nodes & set(observations_by_id)
    reachable_sources = {
        str(observations_by_id[node_id].get("source") or "")
        for node_id in reachable_observation_ids
    } - {""}
    return reachable_observation_ids, reachable_sources


def _typed_scoring_explanations(
    reasoning: dict[str, Any],
    *,
    maker: dict[str, Any],
    timeframe_contract: dict[str, Any] | None = None,
    adjustment_policy: dict[str, Any] | None = None,
    anchor_policy: dict[str, Any] | None = None,
    counter_resolution_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain exact scores from typed metrics, never model-authored rationale."""

    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()

    orderflow_score = Decimal(str(maker.get("orderflow_score")))
    if orderflow_score < 0 or orderflow_score > ORDERFLOW_SCORE_MAX:
        raise ValueError("human report orderflow score must remain within 0..60")
    if (
        adjustment_policy is None
        or anchor_policy is None
        or counter_resolution_policy is None
    ):
        default_conviction_policy = load_scoring_policy().get("conviction") or {}
        if adjustment_policy is None:
            adjustment_policy = dict(
                default_conviction_policy.get("adjustment_policy") or {}
            )
        if anchor_policy is None:
            anchor_policy = dict(default_conviction_policy.get("anchor_policy") or {})
        if counter_resolution_policy is None:
            counter_resolution_policy = dict(
                default_conviction_policy.get("counter_resolution_policy") or {}
            )
    reason_policies = adjustment_policy.get("reason_codes")
    if not isinstance(reason_policies, dict):
        raise ValueError("win-rate adjustment policy lacks closed reason codes")

    observations = _observation_index(reasoning)
    observations_by_id = {
        str(item.get("id")): item
        for item in reasoning.get("observations", [])
        if isinstance(item, dict) and item.get("id")
    }
    claim_by_id = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    liquidation_claims = [
        item
        for item in claim_by_id.values()
        if item.get("claim_type") == "liquidation_confirmation"
    ]
    if len(liquidation_claims) != 1:
        raise ValueError("exactly one typed liquidation_confirmation claim is required")
    liquidation_result = liquidation_claims[0].get("confirmation_result")
    coinglass = (observations.get("Coinglass") or {}).get("metrics") or {}
    exocharts = (observations.get("Exocharts") or {}).get("metrics") or {}
    tradingview = (observations.get("TradingView") or {}).get("metrics") or {}
    frames = tradingview.get("timeframes") if isinstance(tradingview.get("timeframes"), dict) else {}
    profile = tradingview.get("volume_profile") if isinstance(tradingview.get("volume_profile"), dict) else {}
    chart_basis = tradingview.get("chart_basis") if isinstance(tradingview.get("chart_basis"), dict) else {}
    profile_zones = profile.get("zones") if isinstance(profile.get("zones"), list) else []
    structure_zones = (
        chart_basis.get("structure_zones")
        if isinstance(chart_basis.get("structure_zones"), list)
        else []
    )
    profile_zone_text = "、".join(
        f"{_plain_number(item.get('lower_bound'))}-{_plain_number(item.get('upper_bound'))}"
        f"({_timeframe_display_label(timeframe_contract, item.get('timeframe'))})"
        for item in profile_zones
        if isinstance(item, dict)
    ) or "无认证区间"
    structure_zone_text = "、".join(
        f"{_plain_number(item.get('lower_bound'))}-{_plain_number(item.get('upper_bound'))}"
        f"({_timeframe_display_label(timeframe_contract, item.get('timeframe'))})"
        for item in structure_zones
        if isinstance(item, dict)
    ) or "无认证结构区间"
    supports = "、".join(_plain_number(item) for item in chart_basis.get("support_levels", [])) or "无"
    resistances = "、".join(_plain_number(item) for item in chart_basis.get("resistance_levels", [])) or "无"
    sma_text = "；".join(
        f"{label}价格{_plain_number((frames.get(key) or {}).get('price'))} vs SMA20 {_plain_number((frames.get(key) or {}).get('sma20'))}，结构{_metric_value((frames.get(key) or {}).get('structure', '未认证'))}"
        for key, label in (
            (code, _timeframe_display_label(timeframe_contract, code))
            for code in timeframe_contract["tradingview_projection_order"][:3]
        )
    )
    fib = "、".join(_plain_number(item) for item in chart_basis.get("fibonacci_levels", [])) or "无"
    orderflow = (
        f"组合{coinglass.get('combination_id', '未认证')}：价格={_metric_value(coinglass.get('price_direction', '未认证'))}、"
        f"CVD={_metric_value(coinglass.get('cvd_direction', '未认证'))}、OI={_metric_value(coinglass.get('oi_direction', '未认证'))}形成主体；"
        f"资金费率={_metric_value(coinglass.get('funding_direction', '未认证'))}/{_metric_value(coinglass.get('funding_sign', '未认证'))}仅作"
        f"{_metric_value(coinglass.get('funding_effect', '未认证'))}修正；Exocharts={_metric_value(exocharts.get('cross_check_result', '未认证'))}；"
        f"因此类型化盘口分={maker.get('orderflow_score')}/{ORDERFLOW_SCORE_MAX}。"
    )
    chart = {
        "chart.support_resistance": (
            f"当前认证支撑={supports}，压力={resistances}，结构区间={structure_zone_text}；"
            "分值只评价多周期边界是否清晰及失效是否可定义。"
        ),
        "chart.liquidity_hunt": (
            f"用户手绘成交量分布状态={_metric_value(profile.get('status', '未认证'))}，认证区间={profile_zone_text}，"
            f"清算图辅助结果={_metric_value(liquidation_result or '未认证')}；"
            "手绘区域主判位置概率，清算图不替代也不翻向。"
        ),
        "chart.sma20_interaction": f"{sma_text}；该项只评价1D/4H/1H与SMA20的结构一致性。",
        "chart.volume_price": (
            "TradingView量价状态="
            f"{_visible_enum('tradingview.chart_basis.volume_price_state', chart_basis.get('volume_price_state'))}；"
            "只评价机会质量，不承担方向主判。"
        ),
        "chart.fibonacci_trendline": (
            f"认证Fibonacci位置={fib}，趋势线状态="
            f"{_visible_enum('tradingview.chart_basis.trendline_status', chart_basis.get('trendline_status'))}；"
            "只提供次级位置质量。"
        ),
    }
    winrate = maker.get("winrate_rubric") if isinstance(maker.get("winrate_rubric"), dict) else {}
    anchor = winrate.get("anchor")
    raw_anchor_claim_ids = winrate.get("anchor_claim_ids")
    if (
        not isinstance(raw_anchor_claim_ids, list)
        or not raw_anchor_claim_ids
        or len({str(value) for value in raw_anchor_claim_ids})
        != len(raw_anchor_claim_ids)
    ):
        raise ValueError("win-rate anchor claim_ids must be a non-empty unique array")
    clean_anchor_claim_ids = [str(value) for value in raw_anchor_claim_ids]
    if any(claim_id not in claim_by_id for claim_id in clean_anchor_claim_ids):
        raise ValueError("win-rate anchor references an unknown certified claim")
    allowed_anchor_accounts = set(anchor_policy.get("allowed_claim_accounts") or [])
    forbidden_anchor_types = set(anchor_policy.get("forbidden_claim_types") or [])
    axis_types = anchor_policy.get("required_claim_types_by_axis")
    axis_sources = anchor_policy.get("required_reachable_sources_by_axis")
    optional_anchor_types = set(anchor_policy.get("optional_claim_types") or [])
    if (
        not allowed_anchor_accounts
        or not isinstance(axis_types, dict)
        or not isinstance(axis_sources, dict)
    ):
        raise ValueError("win-rate anchor policy is incomplete")
    anchor_rationale = str(anchor_policy.get("canonical_rationale") or "").strip()
    if (
        len(anchor_rationale) < 8
        or winrate.get("anchor_rationale") != anchor_rationale
    ):
        raise ValueError(
            "win-rate anchor rationale must equal the authority-owned canonical explanation"
        )
    allowed_anchor_types = optional_anchor_types | {
        str(claim_type)
        for values in axis_types.values()
        for claim_type in (values if isinstance(values, list) else [])
    }
    for claim_id in clean_anchor_claim_ids:
        claim = claim_by_id[claim_id]
        claim_type = str(claim.get("claim_type") or "")
        account = str(claim.get("account") or "")
        if (
            account not in allowed_anchor_accounts
            or claim_type in forbidden_anchor_types
            or claim_type not in allowed_anchor_types
            or (claim_type == "invalidation_path" and account != "maker")
        ):
            raise ValueError("win-rate anchor binds a forbidden claim or account")
    axis_labels = {
        "orderflow": "盘口轴",
        "structural_position": "结构位置轴",
    }
    axis_explanations: list[str] = []
    for axis, allowed_types in axis_types.items():
        allowed_type_set = set(allowed_types or [])
        axis_claim_ids = [
            claim_id
            for claim_id in clean_anchor_claim_ids
            if str(claim_by_id[claim_id].get("claim_type") or "")
            in allowed_type_set
        ]
        if not axis_claim_ids:
            raise ValueError(f"win-rate anchor lacks required {axis} axis")
        _, reachable_sources = _support_dag_reachability(reasoning, axis_claim_ids)
        required_sources = set(axis_sources.get(axis) or [])
        missing_sources = required_sources - reachable_sources
        if missing_sources:
            raise ValueError(
                "win-rate anchor axis lacks required sources: "
                + ", ".join(sorted(missing_sources))
            )
        claim_labels = "、".join(
            CLAIM_TYPE_CN.get(
                str(claim_by_id[claim_id].get("claim_type") or ""),
                str(claim_by_id[claim_id].get("claim_type") or ""),
            )
            for claim_id in axis_claim_ids
        )
        axis_explanations.append(
            f"{axis_labels.get(str(axis), str(axis))}={claim_labels}"
            f"（真实来源：{'、'.join(sorted(required_sources))}）"
        )
    anchor_explanation = (
        f"基准锚{anchor}%先由{'；'.join(axis_explanations)}独立绑定；"
        f"认证锚点说明：{_sentence(anchor_rationale)}"
        "这是计划时置信锚，不是回测命中率。"
    )
    adjustment_explanations = []
    anchor_claim_ids = set(clean_anchor_claim_ids)
    counter_resolution = (
        winrate.get("counter_resolution")
        if isinstance(winrate.get("counter_resolution"), dict)
        else {}
    )
    required_counter_fields = set(
        counter_resolution_policy.get("required_fields") or []
    )
    if (
        not required_counter_fields
        or set(counter_resolution) != required_counter_fields
    ):
        raise ValueError("Maker counter resolution differs from the closed schema")
    if counter_resolution.get("disposition") != "adjusted":
        raise ValueError("Maker current counter must use the adjusted disposition")
    expected_counter_id = str(
        (((reasoning.get("methodology") or {}).get("account_separation") or {}).get(
            "maker_counter_claim_id"
        ))
        or ""
    )
    if (
        not expected_counter_id
        or counter_resolution.get("counter_claim_id") != expected_counter_id
        or counter_resolution.get("adjustment_reason_code")
        != counter_resolution_policy.get("adjusted_reason_code")
        or counter_resolution.get("resolution_claim_ids") != []
    ):
        raise ValueError("Maker counter resolution does not bind the current Maker counter")
    raw_adjustments = winrate.get("adjustments")
    if not isinstance(raw_adjustments, list):
        raise ValueError("win-rate adjustments must be an array")
    required_first_reason_code = str(
        adjustment_policy.get("required_first_reason_code") or ""
    )
    if (
        not required_first_reason_code
        or not raw_adjustments
        or not isinstance(raw_adjustments[0], dict)
        or str(raw_adjustments[0].get("reason_code") or "")
        != required_first_reason_code
    ):
        raise ValueError(
            "Maker current strongest-counter adjustment must be first"
        )
    seen_reason_codes: set[str] = set()
    seen_claim_ids: set[str] = set()
    seen_owner_signatures: set[tuple[str, str, str]] = set()
    for item in raw_adjustments:
        if not isinstance(item, dict):
            continue
        claim_ids = list(item.get("claim_ids") or [])
        delta = item.get("delta")
        reason_code = str(item.get("reason_code") or "")
        reason_policy = reason_policies.get(reason_code)
        if not isinstance(reason_policy, dict):
            raise ValueError("win-rate adjustment reason_code is outside the closed policy")
        if reason_code in seen_reason_codes:
            raise ValueError("win-rate adjustment reason_code is duplicated")
        seen_reason_codes.add(reason_code)
        bound_claims = [claim_by_id.get(str(claim_id)) for claim_id in claim_ids]
        if not claim_ids or any(not isinstance(claim, dict) for claim in bound_claims):
            raise ValueError("win-rate adjustment references an unknown certified claim")
        normalized_claim_ids = [str(value) for value in claim_ids]
        if len(set(normalized_claim_ids)) != len(normalized_claim_ids):
            raise ValueError("win-rate adjustment claim_ids must be unique")
        if set(normalized_claim_ids) & seen_claim_ids:
            raise ValueError("win-rate adjustment reuses an earlier claim")
        if set(normalized_claim_ids) & anchor_claim_ids:
            raise ValueError("win-rate adjustment reuses an anchor claim")
        seen_claim_ids.update(normalized_claim_ids)
        typed_claims = [claim for claim in bound_claims if isinstance(claim, dict)]
        reachable_observation_ids, reachable_sources = _support_dag_reachability(
            reasoning,
            [str(claim_id) for claim_id in claim_ids],
        )
        required_sources = set(reason_policy.get("required_reachable_sources") or [])
        missing_sources = required_sources - reachable_sources
        if missing_sources:
            raise ValueError(
                "win-rate adjustment claim DAG lacks required sources: "
                + ", ".join(sorted(missing_sources))
            )
        allowed_claim_types = set(reason_policy.get("allowed_claim_types") or [])
        if any(str(claim.get("claim_type")) not in allowed_claim_types for claim in typed_claims):
            raise ValueError("win-rate adjustment binds a claim type outside its reason_code policy")
        required_claim_account = str(reason_policy.get("required_claim_account") or "")
        if required_claim_account and any(
            str(claim.get("account") or "") != required_claim_account
            for claim in typed_claims
        ):
            raise ValueError("win-rate adjustment binds the wrong account")
        typed_values: list[dict[str, Any]] = []
        sources: set[str] = set()
        typed_value_text: list[str] = []
        typed_owner_mode = str(reason_policy.get("typed_value_owner_mode") or "")
        if typed_owner_mode == "selected_current_basis_clauses":
            if (
                len(typed_claims) != 1
                or counter_resolution.get("disposition") != "adjusted"
                or counter_resolution.get("adjustment_reason_code") != reason_code
                or counter_resolution.get("counter_claim_id")
                != str(typed_claims[0].get("id") or "")
            ):
                raise ValueError("Maker counter adjustment lacks its closed resolution")
            projected_basis = _typed_current_basis(reasoning, typed_claims[0])
            residual_indexes = counter_resolution.get("residual_clause_indexes")
            if (
                not isinstance(residual_indexes, list)
                or not residual_indexes
                or any(
                    not isinstance(index, int) or isinstance(index, bool)
                    for index in residual_indexes
                )
                or len(set(residual_indexes)) != len(residual_indexes)
            ):
                raise ValueError("Maker counter residual clause indexes are invalid")
            projected_clauses = projected_basis.get("clauses") or []
            if residual_indexes != list(range(len(projected_clauses))):
                raise ValueError(
                    "Maker counter residual clauses must cover current_basis in order"
                )
            for index in residual_indexes:
                if index < 0 or index >= len(projected_clauses):
                    raise ValueError("Maker counter residual clause index is outside current_basis")
                clause = projected_clauses[index]
                owner_type = str(clause.get("owner_type") or "")
                owner_id = str(clause.get("owner_id") or "")
                field = str(clause.get("field") or "")
                value = copy.deepcopy(clause.get("value"))
                signature = (owner_type, owner_id, field)
                if signature in seen_owner_signatures:
                    raise ValueError("win-rate adjustment reuses a typed owner")
                seen_owner_signatures.add(signature)
                if owner_type == "observation":
                    owner = observations_by_id.get(owner_id)
                    if not isinstance(owner, dict):
                        raise ValueError("Maker counter residual owner is missing")
                    owner_label = str(owner.get("source") or "")
                    sources.add(owner_label)
                elif owner_type == "claim":
                    owner = claim_by_id.get(owner_id)
                    if not isinstance(owner, dict):
                        raise ValueError("Maker counter residual claim owner is missing")
                    owner_label = CLAIM_TYPE_CN.get(
                        str(owner.get("claim_type") or ""),
                        str(owner.get("claim_type") or ""),
                    )
                else:
                    raise ValueError("Maker counter residual owner type is invalid")
                typed_values.append(
                    {
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "field": field,
                        "value": value,
                    }
                )
                typed_value_text.append(
                    f"{owner_label}{TYPED_FIELD_LABEL_CN.get(field, _metric_label(field))}={_metric_value(value)}"
                )
        for owner_spec in reason_policy.get("typed_value_owners") or []:
            if not isinstance(owner_spec, dict):
                raise ValueError("win-rate typed value owner is invalid")
            owner_type = str(owner_spec.get("owner_type"))
            field = str(owner_spec.get("field"))
            if owner_type == "observation":
                source = str(owner_spec.get("source"))
                observation = observations.get(source)
                if not isinstance(observation, dict):
                    raise ValueError("win-rate adjustment lacks its typed observation owner")
                owner_id = str(observation.get("id"))
                if owner_id not in reachable_observation_ids:
                    raise ValueError(
                        "win-rate adjustment typed observation owner is not reachable"
                    )
                value = _nested_typed_value(observation.get("metrics") or {}, field)
                owner_label = source
                sources.add(source)
            elif owner_type == "claim":
                claim_type = str(owner_spec.get("claim_type"))
                matching = [
                    claim
                    for claim in typed_claims
                    if str(claim.get("claim_type")) == claim_type
                ]
                if len(matching) != 1:
                    raise ValueError("win-rate adjustment lacks its typed claim owner")
                owner = matching[0]
                owner_id = str(owner.get("id"))
                value = _nested_typed_value(owner, field)
                owner_label = CLAIM_TYPE_CN.get(claim_type, claim_type)
            else:
                raise ValueError("win-rate typed owner_type is outside the closed policy")
            if owner_spec.get("value_contract") != "certified_source_schema":
                if value not in set(owner_spec.get("allowed_values") or []):
                    raise ValueError("win-rate typed value is outside its reason_code policy")
            signature = (owner_type, owner_id, field)
            if signature in seen_owner_signatures:
                raise ValueError("win-rate adjustment reuses a typed owner")
            seen_owner_signatures.add(signature)
            typed_values.append(
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "field": field,
                    "value": copy.deepcopy(value),
                }
            )
            typed_value_text.append(
                f"{owner_label}{_metric_label(field)}={_metric_value(value)}"
            )
        if not typed_values:
            raise ValueError("win-rate adjustment reason_code lacks typed value owners")
        sources.update(required_sources)
        if not isinstance(delta, int) or delta == 0:
            raise ValueError("win-rate adjustment delta must be a non-zero integer")
        expected_sign = str(reason_policy.get("delta_sign"))
        if (expected_sign == "positive" and delta <= 0) or (
            expected_sign == "negative" and delta >= 0
        ):
            raise ValueError("win-rate adjustment delta sign differs from reason_code policy")
        direction_relation = str(
            reason_policy.get("typed_value_relation_to_maker_direction") or ""
        )
        if direction_relation:
            typed_direction = {
                "bullish": "long",
                "bearish": "short",
            }.get(str(typed_values[0].get("value")))
            maker_direction = str(maker.get("direction") or "")
            relation_valid = (
                typed_direction == maker_direction
                if direction_relation == "same"
                else typed_direction != maker_direction
                if direction_relation == "opposite_or_nonconfirming"
                else False
            )
            if not relation_valid:
                raise ValueError(
                    "win-rate adjustment typed direction differs from Maker relation"
                )
        reason_label = ADJUSTMENT_REASON_CN.get(reason_code)
        if reason_label is None:
            raise ValueError("win-rate adjustment reason_code has no report label")
        source_text = "、".join(sorted(sources)) or "共享认证claim"
        explanation = (
            f"原因={reason_label}；"
            f"真实来源={source_text}；类型化当前值={'、'.join(typed_value_text)}；"
            f"因此类型化调整={delta:+d}个百分点。"
        )
        adjustment_explanations.append(
            {
                "reason_code": reason_code,
                "source_binding": sorted(sources),
                "typed_values": typed_values,
                "explanation": explanation,
            }
        )
    maker_counter_adjustments = [
        item
        for item in adjustment_explanations
        if item.get("reason_code") == "maker_counter_current"
    ]
    if len(maker_counter_adjustments) != 1:
        raise ValueError("Maker counter resolution lacks one residual adjustment")
    counter_resolution_explanation = (
        "Maker当前最强反证的全部类型化当前基线条款仍属当前残余，"
        "已作为当前反证独立扣减；未来触发条件未被当作当前反证。"
    )
    return {
        "orderflow": orderflow,
        "chart": chart,
        "winrate_anchor": anchor_explanation,
        "winrate_adjustments": adjustment_explanations,
        "counter_resolution": counter_resolution_explanation,
    }


def _typed_signal_disposition_projections(
    reasoning: dict[str, Any],
    *,
    maker: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expose each closed secondary-signal disposition and its typed owner."""

    if policy is None:
        policy = dict(
            (
                (load_scoring_policy().get("conviction") or {}).get(
                    "secondary_signal_disposition_policy"
                )
                or {}
            )
        )
    required_fields = set(policy.get("required_fields") or [])
    signal_specs = policy.get("signals")
    allowed_dispositions = set(policy.get("allowed_dispositions") or [])
    allowed_no_adjustment = set(
        policy.get("allowed_no_adjustment_reason_codes") or []
    )
    if (
        not required_fields
        or not isinstance(signal_specs, dict)
        or not signal_specs
        or not allowed_dispositions
    ):
        raise ValueError("secondary signal disposition policy is incomplete")
    rubric = maker.get("winrate_rubric") if isinstance(maker.get("winrate_rubric"), dict) else {}
    raw_items = rubric.get("signal_dispositions")
    if not isinstance(raw_items, list):
        raise ValueError("secondary signal dispositions must be an array")
    by_type: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict) or set(item) != required_fields:
            raise ValueError("secondary signal disposition differs from the closed schema")
        signal_type = str(item.get("signal_type") or "")
        if signal_type in by_type or signal_type not in signal_specs:
            raise ValueError("secondary signal disposition type is unknown or duplicated")
        by_type[signal_type] = item
    if set(by_type) != set(signal_specs):
        raise ValueError("secondary signal dispositions do not cover the closed signal set")

    claims = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    projected: list[dict[str, Any]] = []
    for signal_type, spec in signal_specs.items():
        item = by_type[signal_type]
        claim_id = str(item.get("claim_id") or "")
        claim = claims.get(claim_id)
        if (
            not isinstance(claim, dict)
            or str(claim.get("claim_type") or "") != signal_type
        ):
            raise ValueError("secondary signal disposition does not bind its typed claim")
        value_field = str((spec or {}).get("value_field") or "")
        if not value_field or value_field not in claim:
            raise ValueError("secondary signal disposition typed value is unavailable")
        typed_value = copy.deepcopy(claim[value_field])
        expected_adjustment = ((spec or {}).get("adjustment_reason_by_value") or {}).get(
            str(typed_value)
        )
        disposition = str(item.get("disposition") or "")
        required_disposition = str((spec or {}).get("required_disposition") or "")
        required_no_adjustment_reason = str(
            (spec or {}).get("required_no_adjustment_reason_code") or ""
        )
        matching_adjustments = [
            adjustment
            for adjustment in (
                rubric.get("adjustments")
                if isinstance(rubric.get("adjustments"), list)
                else []
            )
            if isinstance(adjustment, dict)
            and list(adjustment.get("claim_ids") or []) == [claim_id]
        ]
        if disposition not in allowed_dispositions:
            raise ValueError("secondary signal disposition is outside the closed vocabulary")
        if required_disposition and disposition != required_disposition:
            raise ValueError("observation-only secondary signal cannot be adjusted")
        if disposition == "adjusted":
            reason_code = str(item.get("adjustment_reason_code") or "")
            if (
                not expected_adjustment
                or reason_code != expected_adjustment
                or item.get("no_adjustment_reason_code") is not None
                or reason_code not in ADJUSTMENT_REASON_CN
                or len(matching_adjustments) != 1
                or matching_adjustments[0].get("reason_code") != reason_code
            ):
                raise ValueError("adjusted secondary signal has an invalid closed reason")
            reason_text = ADJUSTMENT_REASON_CN[reason_code]
        else:
            if item.get("adjustment_reason_code") is not None:
                raise ValueError("no-adjustment secondary signal retains an adjustment code")
            reason_code = str(item.get("no_adjustment_reason_code") or "")
            if (
                reason_code not in allowed_no_adjustment
                or reason_code not in NO_ADJUSTMENT_REASON_CN
                or (reason_code == "neutral_signal" and expected_adjustment)
                or (
                    required_no_adjustment_reason
                    and reason_code != required_no_adjustment_reason
                )
                or matching_adjustments
            ):
                raise ValueError("secondary signal no-adjustment reason is invalid")
            reason_text = NO_ADJUSTMENT_REASON_CN[reason_code]
        projected.append(
            {
                "signal_type": signal_type,
                "signal_label": SIGNAL_TYPE_CN[signal_type],
                "claim_id": claim_id,
                "typed_value": typed_value,
                "typed_value_text": _metric_value(typed_value),
                "disposition": disposition,
                "disposition_text": SIGNAL_DISPOSITION_CN[disposition],
                "reason_code": reason_code,
                "reason_text": reason_text,
            }
        )
    return projected


def _validate_fundamental_event_observation_only_usage(
    reasoning: dict[str, Any],
    *,
    event_policy: dict[str, Any],
) -> None:
    """Keep v1 event realization visible but non-load-bearing."""

    if (
        event_policy.get("schema_version") != "fundamental-event-assessment-v1"
        or event_policy.get("load_bearing_allowed") is not False
        or event_policy.get("observation_only_reason_code")
        != "event_price_attribution_unavailable"
        or set(event_policy.get("forbidden_load_bearing_uses") or [])
        != {
            "winrate_adjustment",
            "account_current_basis",
            "account_trigger_logic",
        }
        or event_policy.get("price_attribution_basis_required_to_reenable")
        is not True
    ):
        raise ValueError(
            "fundamental-event-assessment-v1 observation-only policy is invalid"
        )
    aggregate_type = str(
        event_policy.get("aggregate_realization_claim_type") or ""
    )
    claims_by_id = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    for claim in claims_by_id.values():
        if claim.get("claim_type") not in {
            "strongest_counterevidence",
            "invalidation_path",
        }:
            continue
        for field in ("current_basis", "trigger_logic"):
            control = claim.get(field)
            clauses = (
                control.get("clauses")
                if isinstance(control, dict)
                and isinstance(control.get("clauses"), list)
                else []
            )
            for clause in clauses:
                owner = (
                    claims_by_id.get(str(clause.get("owner_id") or ""))
                    if isinstance(clause, dict)
                    and clause.get("owner_type") == "claim"
                    else None
                )
                if isinstance(owner, dict) and owner.get("claim_type") == aggregate_type:
                    raise ValueError(
                        "fundamental-event-assessment-v1 cannot own "
                        f"{claim.get('claim_type')}.{field}"
                    )


FUNDAMENTAL_IMPACT_CHANNEL_CN = {
    "liquidity": "流动性",
    "regulation": "监管",
    "risk_appetite": "风险偏好",
}

FUNDAMENTAL_EXPECTED_EFFECT_CN = {
    "supportive_for_risk_assets": "对风险资产形成支持",
    "adverse_for_risk_assets": "对风险资产形成压力",
    "two_sided_or_conditional": "影响双向或取决于后续条件",
    "no_material_effect": "当前无实质价格影响",
}

FUNDAMENTAL_REALIZATION_CN = {
    "realized": "观察枚举为已兑现（未绑定逐事件价格窗口）",
    "partially_realized": "观察枚举为部分兑现（未绑定逐事件价格窗口）",
    "not_realized": "观察枚举为尚未兑现（未绑定逐事件价格窗口）",
    "conflicted": "观察枚举为与当期价格结构冲突（未绑定逐事件价格窗口）",
}

FUNDAMENTAL_BOUNDARY_CN = {
    "no_standalone_direction_requires_cross_source_realization": (
        "事件不能单独给出BTC方向；v1未绑定逐事件价格窗口，只作观察记录，"
        "不得进入置信度调整或账户触发"
    ),
}


def _typed_fundamental_event_projections(
    reasoning: dict[str, Any],
    blockbeats_events: list[dict[str, Any]],
    *,
    event_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Bind each sealed BlockBeats event to its typed assessment and realization.

    Human-facing event facts come only from the sealed card.  Typed methodology
    owns impact/effect/boundary, while the hash-bound event-realization claim owns
    the current realization state.  Account-scoped prose is never read here.
    """

    if len(blockbeats_events) != 3:
        raise ValueError("fundamental event projection requires exactly three sealed cards")
    observations = _observation_index(reasoning)
    blockbeats = observations.get("BlockBeats")
    if not isinstance(blockbeats, dict):
        raise ValueError("fundamental event projection lacks BlockBeats observation")
    metrics = blockbeats.get("metrics") if isinstance(blockbeats.get("metrics"), dict) else {}
    selected_hashes = metrics.get("selected_event_sha256")
    if (
        not isinstance(selected_hashes, list)
        or len(selected_hashes) != 3
        or len(set(str(value) for value in selected_hashes)) != 3
    ):
        raise ValueError("BlockBeats selected_event_sha256 must contain three unique hashes")
    selected_hashes = [str(value) for value in selected_hashes]
    card_hashes = [str(card.get("source_event_sha256") or "") for card in blockbeats_events]
    if card_hashes != selected_hashes:
        raise ValueError("sealed BlockBeats card order differs from selected_event_sha256")

    methodology = reasoning.get("methodology") if isinstance(reasoning.get("methodology"), dict) else {}
    assessments = methodology.get("fundamental_event_assessments")
    if not isinstance(assessments, list) or len(assessments) != 3:
        raise ValueError("fundamental_event_assessments must contain exactly three items")
    assessments_by_hash: dict[str, dict[str, Any]] = {}
    for item in assessments:
        event_hash = (
            str(item.get("selected_event_sha256") or "")
            if isinstance(item, dict)
            else ""
        )
        if not event_hash or event_hash in assessments_by_hash:
            raise ValueError(
                "fundamental event assessments must bind each sealed hash exactly once"
            )
        assessments_by_hash[event_hash] = item
    if set(assessments_by_hash) != set(selected_hashes):
        raise ValueError(
            "fundamental event assessments must cover the sealed event hashes exactly"
        )

    claims_by_id = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and item.get("id")
    }
    event_claims = [
        item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict)
        and item.get("claim_type") == "fundamental_event_realization"
    ]
    event_claims_by_hash: dict[str, dict[str, Any]] = {}
    for item in event_claims:
        event_hash = str(item.get("selected_event_sha256") or "")
        if not event_hash or event_hash in event_claims_by_hash:
            raise ValueError(
                "event realization claims must bind each sealed hash exactly once"
            )
        event_claims_by_hash[event_hash] = item
    if set(event_claims_by_hash) != set(selected_hashes):
        raise ValueError(
            "event realization claims must cover the sealed event hashes exactly"
        )

    required_fields = set(event_policy.get("required_item_fields") or [])
    allowed_impact_channels = set(event_policy.get("impact_channels") or [])
    allowed_effects = set(event_policy.get("expected_effects") or [])
    allowed_boundaries = set(event_policy.get("boundary_codes") or [])
    allowed_counter_types = set(event_policy.get("allowed_counter_claim_types") or [])
    allowed_realization_states = set(event_policy.get("event_realization_states") or [])
    if not all(
        (
            required_fields,
            allowed_impact_channels,
            allowed_effects,
            allowed_boundaries,
            allowed_counter_types,
            allowed_realization_states,
        )
    ):
        raise ValueError("fundamental event assessment policy is incomplete")

    projected: list[dict[str, Any]] = []
    for index, (event_hash, card) in enumerate(
        zip(selected_hashes, blockbeats_events, strict=True), start=1
    ):
        assessment = assessments_by_hash[event_hash]
        if not isinstance(assessment, dict) or set(assessment) != required_fields:
            raise ValueError(f"fundamental event assessment {index} differs from closed schema")
        realization_claim_id = str(assessment.get("realization_claim_id") or "")
        realization_claim = claims_by_id.get(realization_claim_id)
        if (
            not isinstance(realization_claim, dict)
            or realization_claim.get("claim_type") != "fundamental_event_realization"
            or realization_claim.get("account") != "shared"
            or realization_claim.get("selected_event_sha256") != event_hash
        ):
            raise ValueError(
                f"fundamental event assessment {index} has a mismatched realization claim"
            )
        impact_channel = str(assessment.get("impact_channel") or "")
        expected_effect = str(assessment.get("expected_effect") or "")
        boundary_code = str(assessment.get("boundary_code") or "")
        realization_state = str(realization_claim.get("realization_state") or "")
        if impact_channel not in allowed_impact_channels:
            raise ValueError(f"fundamental event assessment {index} has invalid impact_channel")
        if expected_effect not in allowed_effects:
            raise ValueError(f"fundamental event assessment {index} has invalid expected_effect")
        if boundary_code not in allowed_boundaries:
            raise ValueError(f"fundamental event assessment {index} has invalid boundary_code")
        if realization_state not in allowed_realization_states:
            raise ValueError(
                f"fundamental event realization {index} has invalid realization_state"
            )
        counter_ids = assessment.get("counter_claim_ids")
        minimum_counter_ids = int(event_policy.get("minimum_counter_claim_ids") or 1)
        if (
            not isinstance(counter_ids, list)
            or len(counter_ids) < minimum_counter_ids
            or len(set(map(str, counter_ids))) != len(counter_ids)
        ):
            raise ValueError(f"fundamental event assessment {index} has invalid counter_claim_ids")
        counter_types: list[str] = []
        for counter_id in counter_ids:
            counter_claim = claims_by_id.get(str(counter_id))
            counter_type = str((counter_claim or {}).get("claim_type") or "")
            if (
                not isinstance(counter_claim, dict)
                or counter_claim.get("account") != "shared"
                or counter_type not in allowed_counter_types
            ):
                raise ValueError(
                    f"fundamental event assessment {index} has an uncertified counter claim"
                )
            counter_types.append(counter_type)
        projected.append(
            {
                "rank": index,
                "selected_event_sha256": event_hash,
                "source_event_sha256": str(card.get("source_event_sha256") or ""),
                "time": str(card.get("time") or ""),
                "title": str(card.get("title") or ""),
                "impact_channel": impact_channel,
                "expected_effect": expected_effect,
                "realization_claim_id": realization_claim_id,
                "realization_state": realization_state,
                "counter_claim_ids": [str(value) for value in counter_ids],
                "counter_claim_types": counter_types,
                "boundary_code": boundary_code,
            }
        )
    return projected


def _source_explanations(
    reasoning: dict[str, Any],
    *,
    fedwatch_outcome_pattern: re.Pattern[str],
    timeframe_contract: dict[str, Any] | None = None,
    rate_expectation_provider: dict[str, Any] | None = None,
    blockbeats_events: list[dict[str, Any]] | None = None,
    fundamental_event_projections: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, str]]:
    """Project six certified sources into role -> fact -> value -> boundary.

    The raw metric tree remains in the canonical audit object.  The human
    surface receives only the facts and conclusions already certified by the
    reasoning gate, so readability cannot introduce a second market judgment.
    """

    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    claims = _claim_index(reasoning)
    observations = _observation_index(reasoning)
    realization = claims.get("fundamental_price_realization") or {}
    etf = claims.get("etf_confirmation") or {}
    realization_text = {
        "realized": "观察枚举为已兑现",
        "partially_realized": "观察枚举为部分兑现",
        "not_realized": "观察枚举为尚未兑现",
        "conflicted": "观察枚举为与当期价格结构冲突",
    }.get(str(realization.get("realization_state")), "观察枚举未认证")
    etf_relation_text = {
        "confirm": "ETF现货流与同锚价格方向一致，形成确认",
        "weaken": "ETF现货流与同锚价格方向背离，只能削弱",
        "neutral": "ETF现货流或同锚价格方向中性，不提供确认",
    }.get(str(etf.get("price_relation")), "ETF与价格关系未认证")
    result: dict[str, dict[str, str]] = {}
    for source in REQUIRED_SOURCES:
        observation = observations.get(source) or {}
        metrics = observation.get("metrics") if isinstance(observation.get("metrics"), dict) else {}
        compact_detail = ""
        decision_value = ""
        if source == "BlockBeats":
            event_chains: list[str] = []
            for event in fundamental_event_projections or []:
                index = int(event["rank"])
                counter_text = "、".join(
                    CLAIM_TYPE_CN.get(claim_type, claim_type)
                    for claim_type in event.get("counter_claim_types", [])
                ) or "无已认证逐事件反证"
                event_chains.append(
                    f"事件{index}｜事实：{event.get('time', '未提供')}，"
                    f"{event.get('title', '未提供')}；正文唯一所有者为BlockBeats卡片{index}"
                    f"（事件校验摘要{str(event.get('selected_event_sha256') or '')[:12]}）；"
                    f"影响通道：{FUNDAMENTAL_IMPACT_CHANNEL_CN[event['impact_channel']]}；"
                    f"预期影响：{FUNDAMENTAL_EXPECTED_EFFECT_CN[event['expected_effect']]}；"
                    f"兑现：{FUNDAMENTAL_REALIZATION_CN[event['realization_state']]}；"
                    f"当前反证：{counter_text}；"
                    f"边界：{FUNDAMENTAL_BOUNDARY_CN[event['boundary_code']]}"
                )
            event_summary = (
                f"事件影响层级=T{_plain_number(metrics.get('tier'))}；"
                f"事件窗口（小时）={metrics.get('event_window_hours', '未提供')}；"
                f"入选重要事件{metrics.get('selected_event_count', '未提供')}条"
            )
            compact_detail = (
                event_summary + "；" + "；".join(event_chains)
                if event_chains
                else event_summary + "。"
            )
            decision_value = (
                f"逐事件状态只作观察记录；总体{realization_text}；"
                "v1未绑定逐事件价格窗口，不参与置信度调整或账户触发"
            )
        elif source == "FedWatch":
            provider = rate_expectation_provider or {
                "display_name": "利率预期来源未绑定",
                "provider_id": "unknown",
                "method_disclosure": "来源与方法口径未绑定",
                "observation_only": True,
            }
            current_text = _fedwatch_map_text(
                metrics.get("current_probabilities"),
                outcome_pattern=fedwatch_outcome_pattern,
                signed_delta=False,
            )
            delta_1d_text = _fedwatch_map_text(
                metrics.get("change_1d"),
                outcome_pattern=fedwatch_outcome_pattern,
                signed_delta=True,
            )
            delta_1w_text = _fedwatch_map_text(
                metrics.get("change_1w"),
                outcome_pattern=fedwatch_outcome_pattern,
                signed_delta=True,
            )
            delta_1m_text = _fedwatch_map_text(
                metrics.get("change_1m"),
                outcome_pattern=fedwatch_outcome_pattern,
                signed_delta=True,
            )
            data_as_of_label = (
                "Kalshi API数据时点"
                if provider.get("provider_id") == "kalshi_public_market_data_api"
                else "CME页面Data as of"
            )
            compact_detail = (
                f"来源={provider['display_name']}；"
                f"下一次FOMC日期={metrics.get('next_fomc_date', '未提供')}；"
                f"当前概率={current_text}；"
                f"{data_as_of_label}={metrics.get('data_as_of', '未提供')}；"
                f"1日边际={delta_1d_text}；1周边际={delta_1w_text}；"
                f"1月边际={delta_1m_text}；口径={provider['method_disclosure']}。"
            )
            decision_value = (
                "仅作备用观察，不计clean、不进入生产切换；"
                if provider.get("observation_only") is True
                else ""
            ) + "只定义宏观环境及其变化，不直接决定任何账户方向或Maker动作"
        elif source == "Farside":
            compact_detail = (
                f"最新完整交易日={metrics.get('latest_complete_date', '未提供')}；"
                f"总净流量={_plain_number(metrics.get('latest_total_usd_m', 0))}百万美元；"
                f"流向={_metric_value(metrics.get('flow_direction', '未提供'))}。"
            )
            decision_value = etf_relation_text
        elif source == "Coinglass":
            heatmap = (
                metrics.get("liquidation_map")
                if isinstance(metrics.get("liquidation_map"), dict)
                else {}
            )
            pivot = metrics.get("pivot") if isinstance(metrics.get("pivot"), dict) else {}
            effect = (
                metrics.get("effect_divergence")
                if isinstance(metrics.get("effect_divergence"), dict)
                else {}
            )
            captured = (
                heatmap.get("captured_timeframes")
                if isinstance(heatmap.get("captured_timeframes"), list)
                else []
            )
            timeframe_text = "、".join(
                _timeframe_display_label(timeframe_contract, value)
                for value in captured
            ) or "未提供"
            side_text = {"above": "上方", "below": "下方"}
            strength_text = {"strong": "强", "medium": "中", "weak": "弱"}
            levels = heatmap.get("levels") if isinstance(heatmap.get("levels"), list) else []
            level_text = "、".join(
                f"{side_text.get(str(item.get('side')), str(item.get('side', '未知')))}"
                f"{_plain_number(item.get('price', 0))}"
                f"（{_timeframe_display_label(timeframe_contract, item.get('timeframe'))}；"
                f"{strength_text.get(str(item.get('strength')), str(item.get('strength', '未提供')))}）"
                for item in levels
                if isinstance(item, dict)
            ) or "未提供"
            compact_detail = (
                f"同锚组合{metrics.get('combination_id', '未提供')}；"
                "主体三项="
                f"价格{_metric_value(metrics.get('price_direction', '未提供'))}、"
                f"CVD{_metric_value(metrics.get('cvd_direction', '未提供'))}、"
                f"OI{_metric_value(metrics.get('oi_direction', '未提供'))}，"
                f"主判{_metric_value(metrics.get('main_triad_direction', '未提供'))}；"
                f"资金费率{_metric_value(metrics.get('funding_direction', '未提供'))}"
                f"（{_metric_value(metrics.get('funding_sign', '未提供'))}），"
                f"仅作{_metric_value(metrics.get('funding_effect', '未提供'))}修正；"
                f"清算图周期：{timeframe_text}；阈值={_plain_number(heatmap.get('threshold', 0))}；"
                f"辅助位置={level_text}。"
            )
            compact_detail += (
                f"1H pivot={_plain_number(pivot.get('start_price'))}→"
                f"{_plain_number(pivot.get('end_price'))}；"
                f"主腿={_metric_value(pivot.get('dominant_leg'))}；"
                f"趋势线={_metric_value(pivot.get('trendline_status'))}；"
                f"是否重置新锚={_metric_value(pivot.get('anchor_reset'))}；"
                f"效果背离={_metric_value_with_prefix('CVD', effect.get('cvd_break'))}/"
                f"价格{_metric_value(effect.get('price_confirmation'))}/"
                f"解释{_metric_value(effect.get('interpretation'))}；"
                f"价格突破状态={_metric_value(metrics.get('price_break_status'))}；"
                f"OI×价格语义={_metric_value(metrics.get('oi_price_context'))}。"
            )
            decision_value = (
                "价格、CVD、OI共同拥有盘口主判；资金费率只修正强弱，"
                f"最终主判={_metric_value(metrics.get('final_direction', '未提供'))}"
            )
        elif source == "Exocharts":
            profile = metrics.get("capture_profile") if isinstance(metrics.get("capture_profile"), dict) else {}
            ohlc = metrics.get("ohlc") if isinstance(metrics.get("ohlc"), dict) else {}
            compact_detail = (
                f"配置={profile.get('exchange', '未提供')} {profile.get('symbol', '未提供')}、"
                f"{profile.get('timeframe', '未提供')}、Tick×{profile.get('tick_multiplier', '未提供')}、"
                f"{profile.get('cluster_type', '未提供')}、{profile.get('text_type', '未提供')}、"
                f"Candle {profile.get('candle_type', '未提供')}、FPBS/vWap；"
                "对主体主判的交叉核验="
                f"{_metric_value(metrics.get('cross_check_result', '未提供'))}。"
            )
            compact_detail += (
                f"OHLC={_plain_number(ohlc.get('open'))}/"
                f"{_plain_number(ohlc.get('high'))}/"
                f"{_plain_number(ohlc.get('low'))}/"
                f"{_plain_number(ohlc.get('close'))}；"
                f"POC={_plain_number(metrics.get('poc'))}；"
                f"Delta={_plain_number(metrics.get('delta'))}；"
                f"CVD={_plain_number(metrics.get('cvd'))}；"
                f"Volume={_plain_number(metrics.get('volume'))}。"
            )
            decision_value = (
                "只确认、削弱或反驳Coinglass同锚主判；不得单独重建或翻转方向"
            )
        elif source == "TradingView":
            timeframes = metrics.get("timeframes") if isinstance(metrics.get("timeframes"), dict) else {}
            frame_parts: list[str] = []
            for key in timeframe_contract["tradingview_projection_order"]:
                label = _timeframe_display_label(timeframe_contract, key)
                frame = timeframes.get(key) if isinstance(timeframes.get(key), dict) else {}
                sma20 = frame.get("sma20")
                sma20_text = _plain_number(sma20) if sma20 is not None else "未提供（15m非必需）"
                frame_parts.append(
                    f"{label}价格={_plain_number(frame.get('price'))}、"
                    f"SMA20={sma20_text}、"
                    f"结构={_metric_value(frame.get('structure'))}"
                )
            frame_text = "；".join(frame_parts)
            profile = metrics.get("volume_profile") if isinstance(metrics.get("volume_profile"), dict) else {}
            profile_status_basis = _manual_profile_status_basis(profile)
            zones = profile.get("zones") if isinstance(profile.get("zones"), list) else []
            zone_text = "、".join(
                f"{_plain_number(zone.get('lower_bound'))}-{_plain_number(zone.get('upper_bound'))}"
                f"（{_timeframe_display_label(timeframe_contract, zone.get('timeframe'))}；"
                f"{_metric_value(zone.get('role'))}）"
                for zone in zones
                if isinstance(zone, dict)
            ) or "无认证手绘区间"
            compact_detail = (
                f"{frame_text}；用户手绘量价区域状态={_metric_value(profile.get('status'))}；"
                f"认证手绘区间={zone_text}；判定依据={profile_status_basis}。"
            )
            decision_value = (
                "只评价多周期结构、位置与机会质量；15m只服务Maker入场精度，"
                f"{profile_status_basis}；盘面不承担方向主判"
            )
        fact_text = compact_detail.strip()
        role_text = SOURCE_ROLE_CN[source]
        if source == "FedWatch":
            role_text = (
                "利率预期兼容槽位；实际来源="
                f"{provider['display_name']}；宏观概率变化与事件窗口"
            )
        result[source] = {
            "role": role_text,
            "fact": fact_text,
            "decision_value": decision_value,
            "boundary": SOURCE_BOUNDARY_CN[source],
        }
    return result


def _etf_price_relation_text(value: Any) -> str:
    mapping = {
        "confirm": "ETF现货流与同锚价格方向一致，形成确认",
        "weaken": "ETF现货流与同锚价格方向背离，只能削弱",
        "neutral": "ETF现货流或同锚价格方向中性，不提供确认",
    }
    key = str(value or "")
    if key not in mapping:
        raise ValueError("ETF price relation is outside the closed vocabulary")
    return mapping[key]


def _liquidation_confirmation_text(value: Any) -> str:
    mapping = {
        "confirm": "清算图对已认证手绘区域的流动性概率形成辅助确认",
        "weaken": "清算图削弱已认证手绘区域的流动性概率",
        "contradict": "清算图对已认证手绘区域的流动性概率构成反证",
        "neutral": "清算图保持中性，不提供手绘区域流动性概率确认",
    }
    key = str(value or "")
    if key not in mapping:
        raise ValueError("liquidation confirmation result is outside the closed vocabulary")
    return mapping[key]


def _human_reasoning_proof(
    reasoning: dict[str, Any],
    *,
    maker: dict[str, Any],
    main: dict[str, Any],
    fedwatch_outcome_pattern: re.Pattern[str],
    account_trigger_policy: dict[str, Any],
    timeframe_contract: dict[str, Any] | None = None,
    rate_expectation_provider: dict[str, Any] | None = None,
    blockbeats_events: list[dict[str, Any]] | None = None,
    fundamental_event_projections: list[dict[str, Any]] | None = None,
    winrate_adjustment_policy: dict[str, Any] | None = None,
    winrate_anchor_policy: dict[str, Any] | None = None,
    winrate_counter_resolution_policy: dict[str, Any] | None = None,
    maker_stop_policy: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    claims = _claim_index(reasoning)
    observations = _observation_index(reasoning)
    source_explanations = _source_explanations(
        reasoning,
        fedwatch_outcome_pattern=fedwatch_outcome_pattern,
        timeframe_contract=timeframe_contract,
        rate_expectation_provider=rate_expectation_provider,
        blockbeats_events=blockbeats_events,
        fundamental_event_projections=fundamental_event_projections,
    )
    account_controls = _typed_account_controls(
        reasoning,
        maker=maker,
        main=main,
        trigger_policy=account_trigger_policy,
    )
    scoring_explanations = _typed_scoring_explanations(
        reasoning,
        maker=maker,
        adjustment_policy=winrate_adjustment_policy,
        anchor_policy=winrate_anchor_policy,
        counter_resolution_policy=winrate_counter_resolution_policy,
    )
    entry_reach_probability_projection = _typed_entry_reach_probability_projection(maker)
    def observation_fact(source: str) -> str:
        observation = observations.get(source) or {}
        certification_state = "已认证" if observation.get("id") else "未认证"
        return f"{source}类型化证据节点{certification_state}（完整事实仅见附录B六源事实区）"

    def claim(claim_type: str, account: str | None = None) -> dict[str, Any]:
        key = f"{claim_type}:{account}" if account else claim_type
        return claims.get(key) or {}

    orderflow = claim("orderflow_interpretation")
    chart = claim("chart_interpretation")
    liquidity = claim("liquidity_hunt")
    liquidation = claim("liquidation_confirmation")
    etf = claim("etf_confirmation")
    realization = claim("fundamental_price_realization")
    main_regime = claim("market_regime", "main")
    maker_regime = claim("market_regime", "maker")
    main_thesis = claim("main_account_thesis", "main")
    maker_thesis = claim("maker_thesis", "maker")
    main_counter_claim = claim("strongest_counterevidence", "main")
    maker_counter_claim = claim("strongest_counterevidence", "maker")
    main_invalidation_claim = claim("invalidation_path", "main")
    maker_invalidation_claim = claim("invalidation_path", "maker")
    coinglass_metrics = (observations.get("Coinglass") or {}).get("metrics") or {}
    tradingview_metrics = (observations.get("TradingView") or {}).get("metrics") or {}
    manual_profile = (
        tradingview_metrics.get("volume_profile")
        if isinstance(tradingview_metrics.get("volume_profile"), dict)
        else {}
    )
    profile_status = str(manual_profile.get("status") or "")
    profile_status_basis = _manual_profile_status_basis(manual_profile)
    if profile_status == "readable":
        profile_logic = profile_status_basis + "；用户手绘成交量分布区域只用于位置与猎杀概率主判；清算图只辅助印证这些位置概率，不替代手绘区域；二者均不承担盘口方向或直接翻向。"
    else:
        profile_logic = profile_status_basis + "；本轮不推断任何 POC、VAH、VAL、HVN、LVN 或猎杀概率落点；清算图不得替代该维度、生成位置概率或翻向。"
    pivot = coinglass_metrics.get("pivot") if isinstance(coinglass_metrics.get("pivot"), dict) else {}
    orderflow_dimensions = (
        f"组合{coinglass_metrics.get('combination_id', '未提供')}；"
        f"1H锚点{pivot.get('start_price', '未提供')}→{pivot.get('end_price', '未提供')}；"
        "主体三项="
        f"价格{_metric_value(coinglass_metrics.get('price_direction', '未提供'))}、"
        f"CVD{_metric_value(coinglass_metrics.get('cvd_direction', '未提供'))}、"
        f"OI{_metric_value(coinglass_metrics.get('oi_direction', '未提供'))}，"
        f"主判{_metric_value(coinglass_metrics.get('main_triad_direction', '未提供'))}；"
        f"资金费率{_metric_value(coinglass_metrics.get('funding_direction', '未提供'))}"
        f"（{_metric_value(coinglass_metrics.get('funding_sign', '未提供'))}），"
        f"仅作{_metric_value(coinglass_metrics.get('funding_effect', '未提供'))}修正"
    )
    orderflow_scorecard = maker.get("orderflow_scorecard") or {}
    winrate = maker.get("winrate_rubric") or {}
    adjustments = winrate.get("adjustments") if isinstance(winrate.get("adjustments"), list) else []
    adjustment_text = "；".join(
        f"第{index}项类型化次因{item.get('delta', 0):+d}个百分点"
        for index, item in enumerate(adjustments, start=1)
        if isinstance(item, dict) and isinstance(item.get("delta"), int)
    )
    risk_plan = _typed_risk_plan(maker, stop_policy=maker_stop_policy)
    entries = risk_plan.get("entries") if isinstance(risk_plan.get("entries"), list) else []
    semantic_state = _maker_semantic_state(maker)
    if semantic_state == QUALIFIED_CANDIDATE:
        risk_evidence = (
            "候选分类=认证候选计划；"
            f"执行状态={_execution_action_text(maker.get('execution_action'))}；"
            f"策略类型={maker.get('strategy_type', '未提供')}；"
            f"账户={maker.get('exchange', '未提供')} {maker.get('instrument', '未提供')}；"
            f"计划持仓={maker.get('position_notional_usdt', '无')} USDT；"
            f"入场类型={_visible_enum('maker.entry_type', maker.get('entry_type'))}；"
            f"杠杆={risk_plan.get('leverage', '无')}x；"
            f"入场={','.join(_plain_number(item) for item in entries) or '无'}；"
            f"止损={risk_plan.get('stop', '无')}；TP1={risk_plan.get('tp1', '无')}；"
            f"TP2={risk_plan.get('tp2', '无')}"
        )
        risk_logic = (
            "每个成交情景独立复算 TP1 盈亏比与名义风险；TP1/TP2、止损、"
            "取消价和防守触发由同一决策模型拥有。"
        )
        risk_conclusion = (
            "认证候选计划的全部情景必须达到 1:2.5 且名义风险不高于 3%；"
            "真实执行资格仍由独立授权决定。"
        )
    elif semantic_state == REJECTED_SUBMITTED_CANDIDATE:
        risk_evidence = (
            "本轮提交过候选风险输入，但候选未通过认证；"
            "附录D只按真实输入展示可复算或不可复算审计，全部不可执行且不得用于下单"
        )
        risk_logic = (
            "只对已提交的原始候选风险输入做确定性审计；风险复算不得把被拒候选"
            "升级为认证候选，也不得生成执行资格。"
        )
        risk_conclusion = (
            "本轮候选未通过认证；附录风险值仅用于解释拒绝原因，"
            "不得进入正文执行位、订单生命周期或下单。"
        )
    elif semantic_state == DIRECTIONAL_THESIS_ONLY:
        risk_evidence = (
            "本轮Maker只保留方向判断；不存在候选计划；"
            "未提交风险输入，不生成仓位、入场、止损、止盈、防守或风险情景"
        )
        risk_logic = (
            "方向判断与候选计划分离；没有非空风险输入时不运行成交情景、"
            "盈亏比、名义风险、止损或防守计算。"
        )
        risk_conclusion = (
            "本轮只保留方向判断，未提交候选计划；所有仓位、价格、"
            "订单生命周期与防守字段均不适用。"
        )
    elif semantic_state == NON_DIRECTIONAL_OBSERVATION:
        risk_evidence = (
            "本轮Maker为无方向观察结论；不存在候选计划；"
            "入场区、名义仓位、风险参数与防守参数均不适用；不得用于下单"
        )
        risk_logic = (
            "无方向观察不进入候选构造；不运行成交情景、盈亏比、名义风险、"
            "止损、止盈或防守计算。"
        )
        risk_conclusion = (
            "本轮没有方向性候选；计划、仓位、价格、订单生命周期与防守字段"
            "全部不适用。"
        )
    else:
        raise ValueError("Maker reasoning proof lacks a closed semantic state")
    typed_orderflow_conclusion = str(orderflow.get("conclusion") or "未提供")
    main_plan_state_text = {
        "new": "新建",
        "iterate": "迭代",
        "unchanged": "维持",
        "observe": "观察且不执行",
    }.get(str(main.get("plan_state")), "未认证")
    typed_main_conclusion = (
        f"{str(main_thesis.get('conclusion') or '未提供')}；"
        f"计划状态={main_plan_state_text}。"
    )
    typed_maker_conclusion = (
        f"{str(maker_thesis.get('conclusion') or '未提供')}；"
        f"计划状态={'合格' if _maker_plan_is_qualified(maker) else '观察'}。"
    )
    typed_chart_conclusion = str(chart.get("conclusion") or "未提供")
    typed_liquidation_conclusion = _liquidation_confirmation_text(
        liquidation.get("confirmation_result")
    )
    typed_etf_conclusion = _etf_price_relation_text(etf.get("price_relation"))
    main_counter_reference = "完整类型化触发条件见附录D“主账户反证情景”"
    maker_counter_reference = "完整类型化触发条件见附录D“Maker反证情景”"
    main_invalidation_reference = "完整类型化触发条件见附录D“主账户失效情景”"
    maker_invalidation_reference = "完整类型化触发条件见附录D“Maker失效情景”"
    main_counter_text = (
        f"当前类型化反证={_typed_current_basis(reasoning, main_counter_claim)['condition']}；"
        f"{main_counter_reference}"
    )
    maker_counter_text = (
        f"当前类型化反证={_typed_current_basis(reasoning, maker_counter_claim)['condition']}；"
        f"{maker_counter_reference}"
    )
    main_invalidation_text = (
        f"当前类型化失效基线={_typed_current_basis(reasoning, main_invalidation_claim)['condition']}；"
        f"{main_invalidation_reference}"
    )
    maker_invalidation_text = (
        f"当前类型化失效基线={_typed_current_basis(reasoning, maker_invalidation_claim)['condition']}；"
        f"{maker_invalidation_reference}"
    )
    return {
        "orderflow_anchor": {
            "evidence": [observation_fact("Coinglass"), orderflow_dimensions],
            "logic": orderflow_dimensions + "；盘口分数只由类型化同锚指标与足迹关系落值。",
            "conclusion": typed_orderflow_conclusion,
            "counter": maker_counter_text,
            "invalidation": str(orderflow.get("invalidation") or "未提供"),
        },
        "footprint_cross_check": {
            "evidence": [observation_fact("Exocharts")],
            "logic": "足迹只回答对 Coinglass 同锚主体主判是确认、削弱还是构成反证；不得另起方向或单方翻向。",
            "conclusion": typed_orderflow_conclusion,
            "counter": maker_counter_text,
            "invalidation": str(orderflow.get("invalidation") or "未提供"),
        },
        "multi_timeframe_structure": {
            "evidence": [
                observation_fact("TradingView"),
                _four_timeframe_line(
                    reasoning,
                    timeframe_contract=timeframe_contract,
                ),
            ],
            "logic": "按1D→4H→1H→15m逐级读取结构；前三个周期形成盘面机会质量，15m只服务Maker入场精度。",
            "conclusion": typed_chart_conclusion,
            "counter": maker_counter_text,
            "invalidation": str(chart.get("invalidation") or "未提供"),
        },
        "july_additions": {
            "evidence": [
                observation_fact("TradingView"),
                str((source_explanations.get("Coinglass") or {}).get("decision_value", "")),
                str((source_explanations.get("Farside") or {}).get("decision_value", "")),
            ],
            "logic": profile_logic + "ETF只确认或削弱现货承接，不能替换原始盘口与多周期结构。",
            "conclusion": "；".join(
                (
                    str(liquidity.get("conclusion") or "未提供"),
                    typed_liquidation_conclusion,
                    typed_etf_conclusion,
                )
            ),
            "counter": maker_counter_text,
            "invalidation": str(liquidity.get("invalidation") or "未提供"),
        },
        "fundamental_and_etf_realization": {
            "evidence": [
                observation_fact("BlockBeats"),
                observation_fact("FedWatch"),
                observation_fact("Farside"),
            ],
            "logic": (
                f"{(source_explanations.get('BlockBeats') or {}).get('decision_value', '')}；"
                f"{(source_explanations.get('Farside') or {}).get('decision_value', '')}。"
            ),
            "conclusion": (
                "基本面逐事件v1只作价格归因观察，不承担置信度调整或账户触发；"
                f"ETF类型化关系={_metric_value(etf.get('price_relation'))}"
            ),
            "counter": main_counter_text,
            "invalidation": (
                "基本面价格归因只有在未来建立逐事件价格窗口、方向关系和聚合真值表后，"
                "才可重新申请承重资格。"
            ),
        },
        "main_account_closure": {
            "evidence": [
                observation_fact("BlockBeats"),
                observation_fact("Farside"),
                observation_fact("TradingView"),
            ],
            "logic": str(main_regime.get("conclusion") or "未提供"),
            "conclusion": typed_main_conclusion,
            "counter": main_counter_text,
            "invalidation": main_invalidation_text,
        },
        "maker_account_closure": {
            "evidence": [
                observation_fact("Coinglass"),
                observation_fact("Exocharts"),
                observation_fact("TradingView"),
            ],
            "logic": str(maker_regime.get("conclusion") or "未提供"),
            "conclusion": typed_maker_conclusion,
            "counter": maker_counter_text,
            "invalidation": maker_invalidation_text,
        },
        "account_separation": {
            "evidence": [
                typed_main_conclusion,
                typed_maker_conclusion,
            ],
            "logic": "主账户按基本面、盘面、盘口排序；Maker 按盘口、盘面、基本面排序，两者不强制同向。",
            "conclusion": (
                f"主账户={AUDIT_DIRECTION_CN.get(str(main.get('direction')), '未知')}；"
                f"Maker={AUDIT_DIRECTION_CN.get(str(maker.get('direction')), '未知')}；"
                "两套闭环独立且只在分析完成后并列展示。"
            ),
            "counter": _join_clauses(
                f"主账户：{main_counter_reference}",
                f"Maker：{maker_counter_reference}",
            ),
            "invalidation": _join_clauses(
                f"主账户：{main_invalidation_reference}",
                f"Maker：{maker_invalidation_reference}",
            ),
        },
        "score_and_winrate": {
            "evidence": [
                f"盘口{maker.get('orderflow_score')}/{ORDERFLOW_SCORE_MAX}；盘面{maker.get('chart_score')}/{CHART_SCORE_MAX}；总分{maker.get('total_score')}",
                str(scoring_explanations["orderflow"]),
                str(scoring_explanations["winrate_anchor"]),
                str(scoring_explanations["counter_resolution"]),
                adjustment_text or "无调整项",
            ],
            "logic": f"评分先按证据落值，再由胜率锚和整数次因调整得到{maker.get('win_rate')}%，禁止由开单结果倒推分数。",
            "conclusion": (
                f"总分{maker.get('total_score')}；计划时置信度{maker.get('win_rate')}%；"
                f"入场价格触达概率{_entry_reach_probability_display(entry_reach_probability_projection)}。"
            ),
            "counter": maker_counter_reference,
            "invalidation": "证据、评分分项或胜率调整项发生变化时必须重新认证，正文不得手改结果。",
        },
        "risk_and_scenarios": {
            "evidence": [risk_evidence],
            "logic": risk_logic,
            "conclusion": risk_conclusion,
            "counter": maker_counter_reference,
            "invalidation": maker_invalidation_reference,
        },
    }


def _metric_label(key: str) -> str:
    return METRIC_LABEL_CN.get(key, f"补充指标（{key}）")


def _visible_enum(domain: str, value: Any) -> str:
    mapping = VISIBLE_ENUM_CN_BY_DOMAIN.get(domain)
    if mapping is None:
        raise ValueError(f"unknown human-visible enum domain: {domain}")
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value not in mapping
    ):
        raise ValueError(
            f"human-visible enum is outside the closed domain: {domain}={value!r}"
        )
    return mapping[value]


def _metric_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, dict):
        return "；".join(
            f"{_metric_label(str(key))}：{_metric_value(item)}"
            for key, item in sorted(value.items())
        )
    if isinstance(value, list):
        return "、".join(_metric_value(item) for item in value)
    text = str(value)
    if text in METRIC_VALUE_CN:
        return METRIC_VALUE_CN[text]
    if _MACHINE_ENUM_PATTERN.fullmatch(text):
        raise ValueError(
            "human-visible metric enum lacks a deterministic translation: "
            f"{text}"
        )
    return text


def _metric_value_with_prefix(prefix: str, value: Any) -> str:
    rendered = _metric_value(value)
    if re.match(rf"^{re.escape(prefix)}(?:\s|$)", rendered, flags=re.IGNORECASE):
        return rendered
    return f"{prefix} {rendered}"


def _metric_summary(metrics: dict[str, Any]) -> str:
    return "；".join(
        f"{_metric_label(str(key))}：{_metric_value(value)}"
        for key, value in sorted(metrics.items())
    )


def _risk_scenarios(maker: dict[str, Any]) -> list[dict[str, str]]:
    plan = maker.get("risk_plan") or {}
    direction = maker.get("direction")
    stop = Decimal(str(plan["stop"]))
    tp1 = Decimal(str(plan["tp1"]))
    tp2 = Decimal(str(plan["tp2"]))
    leverage = Decimal(str(plan["leverage"]))
    return maker_fill_scenarios(
        entries=[Decimal(str(value)) for value in plan.get("entries", [])],
        allocations=[
            Decimal(str(value))
            for value in plan.get("entry_allocations_pct", [])
        ],
        direction=direction,
        stop=stop,
        tp1=tp1,
        tp2=tp2,
        leverage=leverage,
    )


def _rejected_risk_input_is_bounded(maker: dict[str, Any]) -> bool:
    """Bound rejected-input work before any exponential fill enumeration."""

    risk = maker.get("risk_plan")
    if not isinstance(risk, dict) or maker.get("direction") not in {"long", "short"}:
        return False
    entries = risk.get("entries")
    allocations = risk.get("entry_allocations_pct")
    if (
        not isinstance(entries, list)
        or not isinstance(allocations, list)
        or not 2 <= len(entries) <= 5
        or len(entries) != len(allocations)
    ):
        return False
    try:
        decimal_entries = [Decimal(str(value)) for value in entries]
        decimal_allocations = [Decimal(str(value)) for value in allocations]
        scalar_values = [
            Decimal(str(risk.get(field)))
            for field in ("stop", "tp1", "tp2", "leverage")
        ]
    except (ArithmeticError, TypeError, ValueError):
        return False
    all_values = [*decimal_entries, *decimal_allocations, *scalar_values]
    return (
        all(value.is_finite() for value in all_values)
        and all(value > 0 for value in decimal_entries)
        and all(value > 0 for value in decimal_allocations)
        and all(value > 0 for value in scalar_values)
        and sum(decimal_allocations, Decimal("0")) == Decimal("100")
    )


def _rejected_risk_projection(
    maker: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Recalculate rejected risk only when its sealed inputs are computable."""

    if maker.get("plan_state") == "qualified":
        status = "not_applicable"
        return [], {
            "status": status,
            "reason_code": REJECTED_RISK_RECALCULATION_STATES[status],
        }
    risk = maker.get("risk_plan")
    if not isinstance(risk, dict) or not risk:
        status = "not_submitted"
        return [], {
            "status": status,
            "reason_code": REJECTED_RISK_RECALCULATION_STATES[status],
        }
    if not _rejected_risk_input_is_bounded(maker):
        status = "not_recalculable"
        return [], {
            "status": status,
            "reason_code": REJECTED_RISK_RECALCULATION_STATES[status],
        }
    try:
        scenarios = _risk_scenarios(maker)
    except (ArithmeticError, IndexError, KeyError, TypeError, ValueError):
        scenarios = []
    status = "recalculated" if scenarios else "not_recalculable"
    return scenarios, {
        "status": status,
        "reason_code": REJECTED_RISK_RECALCULATION_STATES[status],
    }


def _main_risk_scenarios(main: dict[str, Any]) -> list[dict[str, Any]]:
    if main.get("plan_state") == "observe":
        return []
    return maker_fill_scenarios(
        entries=[Decimal(str(value)) for value in main.get("entries", [])],
        allocations=[
            Decimal(str(value))
            for value in main.get("entry_allocations_pct", [])
        ],
        direction=str(main.get("direction")),
        stop=Decimal(str(main["stop"])),
        tp1=Decimal(str(main["tp1"])),
        tp2=Decimal(str(main["final_take_profit"])),
        leverage=Decimal(str(main["leverage"])),
    )


def _plain_number(value: Any) -> str:
    number = Decimal(str(value))
    plain = format(number, "f")
    return plain.rstrip("0").rstrip(".") if "." in plain else plain


def _audit_number(value: Any) -> str:
    try:
        return _plain_number(value)
    except (ArithmeticError, TypeError, ValueError):
        return "未提供"


def _display_decimal(value: Any, *, places: int = 2) -> str:
    """Render exact contract decimals without leaking machine precision."""

    quantum = Decimal("1").scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum)
    return _plain_number(rounded)


def _canonical_risk_frontstage(
    maker: dict[str, Any],
    *,
    stop_policy: dict[str, Any] | None = None,
    invalidation_claim: dict[str, Any] | None = None,
    buffer_policy: dict[str, Any] | None = None,
    timeframe_contract: dict[str, Any] | None = None,
    run_mode: str = "production",
) -> dict[str, str]:
    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    plan = maker.get("risk_plan") if isinstance(maker.get("risk_plan"), dict) else {}
    entries = plan.get("entries") if isinstance(plan.get("entries"), list) else []
    allocations = (
        plan.get("entry_allocations_pct")
        if isinstance(plan.get("entry_allocations_pct"), list)
        else []
    )
    entry_low = min(Decimal(str(value)) for value in entries)
    entry_high = max(Decimal(str(value)) for value in entries)
    level_text = "、".join(
        f"{_plain_number(entry)}（{_plain_number(allocation)}%）"
        for entry, allocation in zip(entries, allocations, strict=True)
    )
    direction_text = "做多" if maker.get("direction") == "long" else "做空"
    if stop_policy is None:
        risk_policy = load_scoring_policy().get("risk_execution") or {}
        stop_policy = dict(risk_policy.get("maker_initial_stop_policy") or {})
        buffer_policy = dict(
            risk_policy.get("structural_noise_buffer_judgment") or {}
        )
    if not isinstance(invalidation_claim, dict) or not isinstance(buffer_policy, dict):
        raise ValueError("Maker risk projection requires its sealed invalidation buffer owner")
    stop_projection = _structural_stop_projection(
        plan.get("stop_basis"),
        direction=str(maker.get("direction")),
        account="maker",
        policy=stop_policy,
        invalidation_claim=invalidation_claim,
        buffer_policy=buffer_policy,
        timeframe_contract=timeframe_contract,
    )
    if Decimal(str((plan.get("stop_basis") or {}).get("derived_stop"))) != Decimal(
        str(plan.get("stop"))
    ):
        raise ValueError("Maker structural-stop projection differs from risk_plan.stop")
    if run_mode == "shadow":
        return {
            "maker_strategy": (
                f"候选入场区间{_plain_number(entry_low)}–{_plain_number(entry_high)}分档{direction_text}；"
                f"候选挂单参数为{level_text}；若未来另获 production 授权，价格不到区间不成交"
            ),
            "maker_tp": (
                f"候选TP1为{_plain_number(plan['tp1'])}，候选减仓{_plain_number(plan['tp1_close_pct'])}%；"
                f"候选TP2为{_plain_number(plan['tp2'])}，候选清剩余{_plain_number(plan['tp2_close_pct'])}%"
            ),
            "maker_sl": (
                f"若未来另获 production 授权并成交，候选初始止损为{_plain_number(plan['stop'])}；"
                f"{stop_projection}"
            ),
            "defense_cancel": (
                f"候选未成交取消价为{_plain_number(plan['cancel_before_fill'])}；"
                f"若未来另获 production 授权并成交，候选止损仍为{_plain_number(plan['stop'])}"
            ),
        }
    return {
        "maker_strategy": (
            f"入场区间{_plain_number(entry_low)}–{_plain_number(entry_high)}分档{direction_text}；"
            f"挂单为{level_text}；价格不到区间不成交"
        ),
        "maker_tp": (
            f"TP1为{_plain_number(plan['tp1'])}，减仓{_plain_number(plan['tp1_close_pct'])}%；"
            f"TP2为{_plain_number(plan['tp2'])}，清剩余{_plain_number(plan['tp2_close_pct'])}%"
        ),
        "maker_sl": f"成交后初始止损为{_plain_number(plan['stop'])}；{stop_projection}",
        "defense_cancel": (
            f"未成交前触及{_plain_number(plan['cancel_before_fill'])}只取消订单；"
            f"成交后止损仍为{_plain_number(plan['stop'])}"
        ),
    }


def _prefill_trigger_scenario(
    defense: dict[str, Any],
    *,
    level_count: int,
) -> dict[str, Any]:
    expected_indexes = list(range(1, level_count + 1))
    rows = defense.get("trigger_scenarios")
    matches = [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        and row.get("filled_level_indexes") == expected_indexes
    ]
    if len(matches) != 1:
        raise ValueError("defense plan lacks one exact full-ladder trigger scenario")
    row = matches[0]
    prefill = defense.get("prefill_anchor")
    if (
        not isinstance(prefill, dict)
        or Decimal(str(prefill.get("weighted_fill")))
        != Decimal(str(row.get("weighted_fill")))
    ):
        raise ValueError("full-ladder trigger scenario differs from prefill anchor")
    return row


def _canonical_defense_frontstage(
    maker: dict[str, Any],
    *,
    slot: str,
    run_mode: str = "production",
) -> dict[str, str]:
    plan = maker.get("risk_plan") if isinstance(maker.get("risk_plan"), dict) else {}
    entries = plan.get("entries") if isinstance(plan.get("entries"), list) else []
    defense = _typed_defense_plan(maker)
    prefill = defense["prefill_anchor"]
    trigger = _prefill_trigger_scenario(defense, level_count=len(entries))
    anchor_text = _plain_number(prefill["weighted_fill"])
    first_text = _plain_number(trigger["first_trigger_price"])
    second_text = _plain_number(trigger["second_trigger_price"])
    first_recalculation = (
        "若未来另获 production 授权并实际成交，则按实际加权成交价重新计算并替换该投影。"
        if run_mode == "shadow"
        else "实际成交后按实际加权成交价重新计算并替换该投影。"
    )
    second_recalculation = first_recalculation
    conditional_prefix = "若上述获授权成交条件成立，" if run_mode == "shadow" else ""
    result = {
        "defense_first": (
            f"完整分档的预成交加权锚为{anchor_text}（不是实际成交价，也不是单档价），"
            f"第一层预成交投影价为{first_text}；{first_recalculation}"
            f"{conditional_prefix}只有随后形成并确认新的4H结构极点，"
            "才按成交后4H结构极点规则处理第一层止损，不预填未来极点价格。"
        ),
        "defense_second": (
            f"完整分档的第二层预成交投影价为{second_text}；{second_recalculation}"
            f"{conditional_prefix}第二层只把剩余仓位止损移至实际加权成交价对应的保本损位置，"
            "不得借此加仓、翻向或改写TP。"
        ),
        "defense_note": (
            "前述精确价只是未成交时的完整分档情景投影；R在成交后只由实际加权成交价与认证止损的距离重算；"
            "未成交不触发防守，未成交取消价也不得冒充成交后止损。"
        ),
    }
    if slot == "evening":
        result["defense_core"] = (
            "晚间防守仍服从同一1.5R/2R与成交后4H结构极点合同；"
            "任何展示文字都不能新增价格、仓位或执行动作。"
        )
    return result


def _canonical_execution_frontstage(
    maker: dict[str, Any],
    continuity: dict[str, Any],
    *,
    run_mode: str,
    authorization: dict[str, Any],
) -> dict[str, str]:
    semantic_state = _maker_semantic_state(maker)
    if semantic_state != QUALIFIED_CANDIDATE:
        reason_texts = _maker_plan_reason_texts(maker)
        reason_text = "；".join(
            f"{index}.{text}" for index, text in enumerate(reason_texts, start=1)
        )
        execution_prefix = {
            REJECTED_SUBMITTED_CANDIDATE: "已提交候选未通过认证，不可执行；",
            DIRECTIONAL_THESIS_ONLY: "只保留方向判断，未提交候选计划；仓位与风险均不适用；",
            NON_DIRECTIONAL_OBSERVATION: "本轮无方向观察；计划、仓位与风险均不适用；",
        }[semantic_state]
        frontstage = {
            "maker_execution": execution_prefix + f"全部原因={reason_text}",
            "maker_authorization": _execution_authorization_text(
                run_mode=run_mode,
                authorization=authorization,
                execution_action=maker.get("execution_action"),
                semantic_state=semantic_state,
            ),
        }
        if run_mode == "shadow":
            continuity_prefix, validity_label = {
                REJECTED_SUBMITTED_CANDIDATE: (
                    "影子被拒候选审计状态",
                    "被拒候选审计有效至",
                ),
                DIRECTIONAL_THESIS_ONLY: (
                    "影子方向观察状态",
                    "方向判断有效至",
                ),
                NON_DIRECTIONAL_OBSERVATION: (
                    "影子无方向观察状态",
                    "观察结论有效至",
                ),
            }[semantic_state]
            frontstage["maker_continuity"] = (
                f"{continuity_prefix}；未读取个人持仓/订单状态；"
                "未创建、撤销或挂出真实订单；"
                f"{validity_label}{continuity.get('plan_valid_until', '未提供')}"
            )
            return frontstage
        current = continuity.get("current_plan") if isinstance(continuity.get("current_plan"), dict) else {}
        continuity_action = {
            "new": "新建",
            "keep": "沿用",
            "cancel_replace": "撤旧换新",
            "cancel": "撤销",
            "observe": "观望",
            "reconcile_filled": "核对已成交",
        }.get(str(current.get("action")), "未认证")
        production_prefix = {
            REJECTED_SUBMITTED_CANDIDATE: "本轮已提交候选被拒；",
            DIRECTIONAL_THESIS_ONLY: "本轮只保留方向判断，未提交候选计划；",
            NON_DIRECTIONAL_OBSERVATION: "本轮为无方向观察；",
        }[semantic_state]
        frontstage["maker_continuity"] = (
            production_prefix
            + f"订单连续性={continuity_action}；"
            f"有效挂单{current.get('executable_order_count_after', '未提供')}个"
        )
        return frontstage
    entry_type = _visible_enum("maker.entry_type", maker.get("entry_type"))
    position = maker.get("position_notional_usdt")
    position_text = "无" if position in {None, 0} else _plain_number(position)
    plan = maker.get("risk_plan") if isinstance(maker.get("risk_plan"), dict) else {}
    frontstage = {
        "maker_execution": (
            f"{maker.get('strategy_type', '未提供')}；{maker.get('order_method', '未提供')}；"
            f"{maker.get('exchange', '未提供')} {maker.get('instrument', '未提供')}；"
            f"{entry_type}；计划持仓{position_text} USDT；"
            f"杠杆{_plain_number(plan.get('leverage', 0))}x"
        ),
        "maker_authorization": _execution_authorization_text(
            run_mode=run_mode,
            authorization=authorization,
            execution_action=maker.get("execution_action"),
            semantic_state=semantic_state,
        ),
    }
    if run_mode == "shadow":
        frontstage["maker_continuity"] = (
            "影子候选计划；未读取个人持仓/订单状态；"
            "未创建、撤销或挂出真实订单；"
            f"候选计划有效至{continuity.get('plan_valid_until', '未提供')}"
        )
        return frontstage

    current = continuity.get("current_plan") if isinstance(continuity.get("current_plan"), dict) else {}
    continuity_action = {
        "new": "新建",
        "keep": "沿用",
        "cancel_replace": "撤旧换新",
        "cancel": "撤销",
        "observe": "观望",
        "reconcile_filled": "核对已成交",
    }.get(str(current.get("action")), "未认证")
    frontstage["maker_continuity"] = (
        f"计划结论：{_maker_plan_summary(maker)}；"
        f"执行资格：{_execution_action_text(maker.get('execution_action'))}；"
        f"订单连续性：{continuity_action}；已执行{current.get('executed_pct', '未提供')}%；"
        f"本轮后有效挂单{current.get('executable_order_count_after', '未提供')}个；"
        f"当日累计交易{current.get('daily_trade_count_after', '未提供')}次；"
        f"有效至{current.get('valid_until', '未提供')}"
    )
    return frontstage


def _nonqualified_maker_risk_frontstage(
    semantic_state: str,
    *,
    slot: str,
) -> dict[str, str]:
    """Return the exact no-execution projection for each non-qualified state."""

    by_state = {
        DIRECTIONAL_THESIS_ONLY: {
            "maker_strategy": "本轮Maker只保留方向判断，未提交候选计划，不输出入场价格。",
            "maker_tp": "方向观察状态未提交候选，不生成 TP1 或 TP2 价格。",
            "maker_sl": "方向观察状态未提交候选，不生成成交后止损价格。",
            "defense_first": "未提交 Maker 候选计划，第一层防守不适用。",
            "defense_second": "未提交 Maker 候选计划，第二层防守不适用。",
            "defense_note": "提交并重新认证完整候选计划前不执行任何 Maker 防守动作。",
            "defense_cancel": "未提交挂单时不生成取消价，也不得把取消价冒充成交后止损。",
        },
        NON_DIRECTIONAL_OBSERVATION: {
            "maker_strategy": "本轮Maker为无方向观察结论，入场计划与入场价格均不适用。",
            "maker_tp": "无方向观察状态不生成 TP1 或 TP2 价格。",
            "maker_sl": "无方向观察状态不生成成交后止损价格。",
            "defense_first": "无可执行 Maker 计划，第一层防守暂不触发。",
            "defense_second": "无可执行 Maker 计划，第二层防守暂不触发。",
            "defense_note": "形成并重新认证方向性计划前不执行任何 Maker 防守动作。",
            "defense_cancel": "无挂单时不生成取消价，也不得把取消价冒充成交后止损。",
        },
        REJECTED_SUBMITTED_CANDIDATE: {
            "maker_strategy": "本轮候选计划未同时通过评分门槛与可构造性验证，因此只观察且不输出入场价格。",
            "maker_tp": "无可执行 Maker 计划，不生成 TP1 或 TP2 价格。",
            "maker_sl": "无可执行 Maker 计划，不生成成交后止损价格。",
            "defense_first": "无可执行 Maker 计划，第一层防守暂不触发。",
            "defense_second": "无可执行 Maker 计划，第二层防守暂不触发。",
            "defense_note": "重新认证完整计划前不执行任何 Maker 防守动作。",
            "defense_cancel": "无挂单时不生成取消价，也不得把取消价冒充成交后止损。",
        },
    }
    projection = copy.deepcopy(by_state.get(semantic_state))
    if not isinstance(projection, dict):
        raise ValueError("non-qualified Maker projection lacks a closed semantic state")
    if slot == "evening":
        projection["defense_core"] = {
            DIRECTIONAL_THESIS_ONLY: "本轮为方向观察状态，晚间不触发任何防守动作或价格投影。",
            NON_DIRECTIONAL_OBSERVATION: "本轮为无方向观察状态，晚间不触发任何防守动作或价格投影。",
            REJECTED_SUBMITTED_CANDIDATE: "本轮无可执行 Maker 计划，晚间不触发任何防守动作或价格投影。",
        }[semantic_state]
    return projection


def _defense_trigger_text(
    defense: dict[str, Any],
    layer: str,
    *,
    level_count: int,
) -> str:
    scenario = _prefill_trigger_scenario(defense, level_count=level_count)
    return _plain_number(scenario[f"{layer}_trigger_price"])


def _defense_calculation_audit_lines(
    defense: dict[str, Any],
    *,
    run_mode: str = "production",
) -> list[str]:
    lines: list[str] = []
    for scenario in defense.get("trigger_scenarios", []):
        if not isinstance(scenario, dict):
            continue
        indexes = "、".join(
            str(index) for index in scenario.get("filled_level_indexes", [])
        ) or "未提供"
        rounding_rule = str(scenario.get("rounding_rule", ""))
        if rounding_rule == "exact_no_rounding":
            rounding_text = "精确值不取整（最终价等于原始计算值）"
        elif rounding_rule == "nearest_step_half_up":
            rounding_text = (
                f"按价格步长{_plain_number(scenario.get('rounding_step'))}"
                "使用半入规则取最近步长"
            )
        else:
            raise ValueError("defense trigger uses an uncertified rounding rule")
        title = "候选防守计算" if run_mode == "shadow" else "防守计算"
        lines.append(
            f"**{title}（成交档位{indexes}）**：加权成交锚"
            f"{_plain_number(scenario.get('weighted_fill'))}；"
            f"L1原始值{_plain_number(scenario.get('first_trigger_price_raw'))}，"
            f"L2原始值{_plain_number(scenario.get('second_trigger_price_raw'))}；"
            f"取整规则={rounding_text}；"
            f"最终L1={_plain_number(scenario.get('first_trigger_price'))}，"
            f"最终L2={_plain_number(scenario.get('second_trigger_price'))}。"
        )
    return lines


def _entry_reach_probability_text(
    basis: dict[str, Any],
    *,
    projection: dict[str, Any],
    run_mode: str = "production",
    timeframe_contract: dict[str, Any] | None = None,
) -> str:
    if projection.get("applicability") != "applicable":
        return (
            _entry_reach_probability_display(projection)
            + "；不得以0%代替不可计算状态，也不得补写价格或执行位。"
        )
    if timeframe_contract is None:
        timeframe_contract = _default_timeframe_display_contract()
    source = str(basis.get("reference_source") or "未提供")
    timeframe = _timeframe_display_label(
        timeframe_contract,
        basis.get("reference_timeframe"),
    )
    reference_price = basis.get("reference_price")
    reference_entry = basis.get("reference_entry")
    entry_distance = basis.get("entry_distance")
    direction = {
        "up_to_entry": "上涨",
        "down_to_entry": "下跌",
        "at_entry": "无需移动",
    }.get(str(basis.get("reach_direction") or ""), "移动")
    if reference_price is None or reference_entry is None or entry_distance is None:
        raise ValueError("applicable entry reach probability lacks complete reach geometry")
    level_label = "最近候选档位" if run_mode == "shadow" else "最近可执行档位"
    probability_label = "入场价格触达概率" if run_mode == "shadow" else "入场价格触达概率"
    distance_text = (
        f"认证距离：{level_label}{_plain_number(reference_entry)}相对"
        f"{source} {timeframe}认证价{_plain_number(reference_price)}，"
        f"需{direction}{_plain_number(entry_distance)}才触达。"
    )
    return (
        distance_text
        + f"判断：{probability_label}{_entry_reach_probability_display(projection)}，"
        "只描述从认证现价到最近档位的触达难度，不改变方向、评分或计划参数。"
    )


def _blockbeats_cards(
    evidence: dict[str, Any],
    *,
    root: Path,
    trading_date: str,
    slot: str,
) -> list[dict[str, Any]]:
    source = (evidence.get("sources") or {}).get("BlockBeats") or {}
    records = source.get("artifacts") if isinstance(source.get("artifacts"), list) else []
    structured = [
        record
        for record in records
        if isinstance(record, dict)
        and Path(str(record.get("path", ""))).name.lower() == "blockbeats.json"
    ]
    if len(structured) != 1:
        raise ValueError("canonical report requires exactly one certified blockbeats.json artifact")
    record = structured[0]
    target = (root / str(record.get("path", ""))).resolve()
    target.relative_to(root.resolve())
    if (
        not target.is_file()
        or sha256_file(target) != record.get("sha256")
        or target.stat().st_size != record.get("bytes")
    ):
        raise ValueError("certified BlockBeats structured artifact changed")
    payload = json.loads(target.read_text(encoding="utf-8"))
    rows = payload.get("selected_rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("BlockBeats structured evidence must contain exactly three selected rows")
    cards: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"BlockBeats selected row {index} is invalid")
        time_text = str(row.get("time", "")).strip()
        title = str(row.get("title", "")).strip()
        body = str(row.get("body", "")).strip()
        priority = (
            row.get("analysis_priority")
            if isinstance(row.get("analysis_priority"), dict)
            else {}
        )
        if (
            row.get("selected_rank") != index
            or not time_text
            or len(title) < 2
            or len(body) < 8
            or not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", title + body)
        ):
            raise ValueError(f"BlockBeats selected row {index} is not Chinese-readable")
        cards.append(
            {
                "filename": f"{trading_date}_{slot}_{index}.png",
                "time": time_text,
                "title": title,
                "body": body,
                "analysis_priority": {
                    key: copy.deepcopy(priority.get(key))
                    for key in (
                        "tier",
                        "category",
                        "priority_bucket",
                        "directness_label",
                    )
                    if key in priority
                },
                "source_event_sha256": canonical_sha256(row),
            }
        )
    if len({card["source_event_sha256"] for card in cards}) != 3:
        raise ValueError("BlockBeats selected rows must be three distinct events")
    return cards


def render_blockbeats_cards(
    model: dict[str, Any],
    *,
    attempt_root: Path,
    repo_root: Path,
) -> list[dict[str, Any]]:
    from outputs.blockbeats_card import make_card

    destination = attempt_root / "cards"
    records: list[dict[str, Any]] = []
    for card in model.get("blockbeats_cards", []):
        path = Path(
            make_card(
                card["filename"],
                card["time"],
                card["title"],
                card["body"],
                output_dir=destination,
                quiet=True,
            )
        ).resolve()
        path.relative_to(attempt_root.resolve())
        records.append(
            {
                "path": path.relative_to(repo_root.resolve()).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    if len(records) != 3:
        raise ValueError("canonical report must render exactly three BlockBeats cards")
    return records


def load_presentation_contract(root: Path) -> dict[str, Any]:
    path = (root / PRESENTATION_CONTRACT_PATH).resolve()
    path.relative_to(root.resolve())
    payload = json.loads(path.read_text(encoding="utf-8"))
    maker_semantics = (
        payload.get("maker_semantic_state_contract")
        if isinstance(payload, dict)
        and isinstance(payload.get("maker_semantic_state_contract"), dict)
        else {}
    )
    event_projection = (
        payload.get("fundamental_event_assessment_v1_projection")
        if isinstance(payload, dict)
        and isinstance(
            payload.get("fundamental_event_assessment_v1_projection"), dict
        )
        else {}
    )
    source_of_truth = (
        payload.get("human_surface_source_of_truth")
        if isinstance(payload, dict)
        and isinstance(payload.get("human_surface_source_of_truth"), dict)
        else {}
    )
    semantic_projection = (
        payload.get("semantic_projection_contract")
        if isinstance(payload, dict)
        and isinstance(payload.get("semantic_projection_contract"), dict)
        else {}
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != PRESENTATION_CONTRACT_SCHEMA_VERSION
        or set(payload.get("required_reasoning_proof_blocks") or [])
        != set(REASONING_PROOF_LABELS)
        or payload.get("appendix_semantic_ownership")
        != APPENDIX_SEMANTIC_OWNERSHIP
        or payload.get("human_visible_enum_domains")
        != VISIBLE_ENUM_CN_BY_DOMAIN
        or maker_semantics.get("schema_version")
        != REGISTRY.maker_semantic_state_schema_version
        or maker_semantics.get("candidate_submission_owner")
        != "maker.risk_plan_nonempty"
        or set(maker_semantics.get("exclusive_states") or [])
        != set(MAKER_SEMANTIC_STATES)
        or maker_semantics.get("plan_numbers_require_candidate_submission")
        is not True
        or event_projection.get("role")
        != "observation_only_no_event_aligned_price_attribution"
        or event_projection.get("load_bearing_allowed") is not False
        or event_projection.get("observation_only_reason_code")
        != "event_price_attribution_unavailable"
        or set(event_projection.get("forbidden_load_bearing_uses") or [])
        != {
            "winrate_adjustment",
            "account_current_basis",
            "account_trigger_logic",
        }
        or event_projection.get("price_attribution_basis_required_to_reenable")
        is not True
        or event_projection.get("required_disposition") != "no_adjustment"
        or event_projection.get("required_no_adjustment_reason_code")
        != "event_price_attribution_unavailable"
        or source_of_truth.get("typed_account_control_is_sole_load_bearing_source")
        is not True
        or source_of_truth.get(
            "free_control_conclusion_or_invalidation_projection_allowed"
        )
        is not False
        or set(payload.get("maker_execution_fields") or [])
        != {
            "direction",
            "plan_state",
            "execution_action",
            "strategy_type",
            "order_method",
            "entry_type",
            "exchange",
            "instrument",
            "position_notional_usdt",
            "cannot_do_code",
            "cannot_do_claim_id",
            "threshold_eligible",
            "plan_constructible",
            "plan_constructibility",
            "order_transition_action",
        }
        or semantic_projection.get("maker_summary_and_execution_frontstage_owner")
        != "audit.maker_execution"
        or semantic_projection.get("main_authorization_owner")
        != "audit.main_plan.plan_state"
        or semantic_projection.get("scenario_condition_owner")
        != "bound_owner_claim.typed_state_or_trigger_logic"
        or semantic_projection.get("scenario_transition_owner")
        != "scenario_ownership.transition_code_by_type"
        or semantic_projection.get("free_scenario_prose_projectable") is not False
        or semantic_projection.get("execution_lifecycle_owner")
        != "decision_and_continuity"
    ):
        raise ValueError("vNext report presentation contract is invalid")
    _validated_timeframe_display_contract(payload)
    _scenario_projection_policy(payload)
    return payload


def _validate_execution_projection_contract(decision: dict[str, Any]) -> None:
    run_mode = decision.get("run_mode")
    authorization = (
        decision.get("execution_authorization")
        if isinstance(decision.get("execution_authorization"), dict)
        else {}
    )
    if set(authorization) != EXECUTION_AUTHORIZATION_FIELDS:
        raise ValueError("execution_authorization must use the exact report projection field set")
    if run_mode not in {"shadow", "production"}:
        raise ValueError("canonical report requires an explicit shadow or production run_mode")
    maker = decision.get("maker") if isinstance(decision.get("maker"), dict) else {}
    if maker.get("plan_state") not in {"qualified", "observe"}:
        raise ValueError("canonical report requires a certified Maker plan_state")
    if not isinstance(maker.get("threshold_eligible"), bool) or not isinstance(
        maker.get("plan_constructible"), bool
    ):
        raise ValueError("canonical report requires separated threshold and constructibility results")
    if maker.get("plan_state") == "qualified" and not (
        maker.get("threshold_eligible") is True
        and maker.get("plan_constructible") is True
    ):
        raise ValueError("qualified Maker report requires both threshold eligibility and plan constructibility")
    if maker.get("execution_action") not in {
        "not_attempted",
        "place_order",
        "observe",
        "blocked",
    }:
        raise ValueError("canonical report requires a certified Maker execution_action")

    continuity = (
        decision.get("continuity_contract")
        if isinstance(decision.get("continuity_contract"), dict)
        else {}
    )
    if run_mode == "shadow":
        if set(continuity) != SHADOW_CONTINUITY_FIELDS:
            raise ValueError("shadow continuity must use the exact report projection field set")
        if (
            continuity.get("schema_version") != SHADOW_CONTINUITY_SCHEMA_VERSION
            or continuity.get("reasoning_sha256") != decision.get("reasoning_sha256")
            or continuity.get("run_sha256") != decision.get("run_sha256")
            or continuity.get("live_state_read") is not False
            or continuity.get("order_mutation_attempted") is not False
            or continuity.get("execution_action") != "not_attempted"
            or continuity.get("reason_code") != "shadow_mode_forbids_live_execution"
        ):
            raise ValueError("shadow continuity is not a sealed no-live-execution projection")
        if (
            authorization.get("source_kind") != "sealed_shadow_run"
            or authorization.get("source_sha256") != decision.get("run_sha256")
            or authorization.get("live_execution_allowed") is not False
            or authorization.get("reason_code") != "shadow_mode_forbids_live_execution"
            or maker.get("execution_action") != "not_attempted"
            or maker.get("order_transition_action") != "not_attempted"
        ):
            raise ValueError("shadow execution authorization is invalid")
        return

    live_allowed = authorization.get("live_execution_allowed") is True
    expected_reason = (
        "pretrade_gate_allows_live_execution"
        if live_allowed
        else "pretrade_gate_blocks_live_execution"
    )
    expected_execution_action = (
        "place_order"
        if live_allowed and maker.get("plan_state") == "qualified"
        else "observe"
        if live_allowed
        else "blocked"
    )
    current = continuity.get("current_plan") if isinstance(continuity.get("current_plan"), dict) else {}
    allowed_continuity_actions = (
        {"new", "keep", "cancel_replace"}
        if expected_execution_action == "place_order"
        else {"cancel", "observe", "reconcile_filled"}
    )
    expected_order_count = 1 if expected_execution_action == "place_order" else 0
    if (
        authorization.get("source_kind") != "notion_pretrade_gate"
        or authorization.get("reason_code") != expected_reason
        or maker.get("execution_action") != expected_execution_action
        or maker.get("order_transition_action") != current.get("action")
        or continuity.get("schema_version")
        != "post-reasoning-continuity-contract-vnext-v1"
        or current.get("action") not in allowed_continuity_actions
        or current.get("executable_order_count_after") != expected_order_count
    ):
        raise ValueError("production execution authorization and continuity are inconsistent")


def build_canonical_report_model(
    *,
    evidence: dict[str, Any],
    reasoning: dict[str, Any],
    decision: dict[str, Any],
    methodology_sha256: str,
    report_contract_sha256: str,
    root: Path,
) -> dict[str, Any]:
    expected_reasoning_fields = set(REGISTRY.reasoning_model_field_order)
    if (
        reasoning.get("schema_version") != REGISTRY.reasoning_model_schema_version
        or set(reasoning) - {"reasoning_sha256"} != expected_reasoning_fields
    ):
        raise ValueError(
            "vNext report compiler only accepts the exact reasoning-model-v5 "
            "typed field set"
        )
    expected_decision_fields = set(REGISTRY.decision_model_field_order)
    if (
        decision.get("schema_version") != REGISTRY.decision_model_schema_version
        or set(decision) - {"decision_sha256"} != expected_decision_fields
    ):
        raise ValueError(
            "vNext report compiler only accepts the exact decision-model-v7 "
            "typed field set"
        )
    presentation_contract = load_presentation_contract(root)
    timeframe_contract = _validated_timeframe_display_contract(presentation_contract)
    submission_contract = load_reasoning_submission_contract(root=root)
    scoring_policy = load_scoring_policy(root=root)
    try:
        rate_expectation_provider_contract = json.loads(
            (
                root / "data_sources" / "rate_expectation_provider_contract.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("rate-expectation provider contract is unavailable") from exc
    if not isinstance(rate_expectation_provider_contract, dict):
        raise ValueError("rate-expectation provider contract must be an object")
    risk_execution_policy = (
        scoring_policy.get("risk_execution")
        if isinstance(scoring_policy.get("risk_execution"), dict)
        else {}
    )
    main_risk_policy = (
        risk_execution_policy.get("main_account")
        if isinstance(risk_execution_policy.get("main_account"), dict)
        else {}
    )
    main_stop_policy = (
        risk_execution_policy.get("main_initial_stop_policy")
        if isinstance(risk_execution_policy.get("main_initial_stop_policy"), dict)
        else {}
    )
    maker_stop_policy = (
        risk_execution_policy.get("maker_initial_stop_policy")
        if isinstance(risk_execution_policy.get("maker_initial_stop_policy"), dict)
        else {}
    )
    structural_noise_buffer_policy = (
        risk_execution_policy.get("structural_noise_buffer_judgment")
        if isinstance(
            risk_execution_policy.get("structural_noise_buffer_judgment"), dict
        )
        else {}
    )
    fedwatch_outcome_pattern = _fedwatch_outcome_pattern(scoring_policy)
    rate_expectation_provider = _rate_expectation_provider_projection(
        evidence,
        provider_contract=rate_expectation_provider_contract,
    )
    account_trigger_policy = dict(
        (scoring_policy.get("gold_methodology") or {}).get("account_trigger_logic")
        or {}
    )
    fundamental_event_policy = dict(
        (scoring_policy.get("gold_methodology") or {}).get(
            "fundamental_event_assessment_policy"
        )
        or {}
    )
    winrate_adjustment_policy = dict(
        (scoring_policy.get("conviction") or {}).get("adjustment_policy") or {}
    )
    winrate_anchor_policy = dict(
        (scoring_policy.get("conviction") or {}).get("anchor_policy") or {}
    )
    winrate_counter_resolution_policy = dict(
        (scoring_policy.get("conviction") or {}).get("counter_resolution_policy")
        or {}
    )
    secondary_signal_disposition_policy = dict(
        (scoring_policy.get("conviction") or {}).get(
            "secondary_signal_disposition_policy"
        )
        or {}
    )
    _validate_execution_projection_contract(decision)
    maker = decision["maker"]
    main = decision["main_account"]
    entry_reach_probability_projection = _typed_entry_reach_probability_projection(maker)
    order_lifecycle = _typed_order_lifecycle(maker)
    main_counter = _claim_by_type(reasoning, "strongest_counterevidence", account="main")
    maker_counter = _claim_by_type(reasoning, "strongest_counterevidence", account="maker")
    main_invalidation = _claim_by_type(reasoning, "invalidation_path", account="main")
    maker_invalidation = _claim_by_type(reasoning, "invalidation_path", account="maker")
    main_current_counter = _typed_current_basis(reasoning, main_counter)
    maker_current_counter = _typed_current_basis(reasoning, maker_counter)
    main_current_invalidation = _typed_current_basis(reasoning, main_invalidation)
    maker_current_invalidation = _typed_current_basis(reasoning, maker_invalidation)
    blockbeats_cards = _blockbeats_cards(
        evidence,
        root=root,
        trading_date=decision["trading_date"],
        slot=decision["slot"],
    )
    fundamental_event_projections = _typed_fundamental_event_projections(
        reasoning,
        blockbeats_cards,
        event_policy=fundamental_event_policy,
    )
    _validate_fundamental_event_observation_only_usage(
        reasoning,
        event_policy=fundamental_event_policy,
    )
    source_facts = _source_facts(
        reasoning,
        fedwatch_outcome_pattern=fedwatch_outcome_pattern,
        timeframe_contract=timeframe_contract,
        rate_expectation_provider=rate_expectation_provider,
        blockbeats_events=blockbeats_cards,
        fundamental_event_projections=fundamental_event_projections,
    )
    source_metrics = _source_metrics(
        reasoning,
        fedwatch_outcome_pattern=fedwatch_outcome_pattern,
    )
    source_explanations = _source_explanations(
        reasoning,
        fedwatch_outcome_pattern=fedwatch_outcome_pattern,
        timeframe_contract=timeframe_contract,
        rate_expectation_provider=rate_expectation_provider,
        blockbeats_events=blockbeats_cards,
        fundamental_event_projections=fundamental_event_projections,
    )
    account_controls = _typed_account_controls(
        reasoning,
        maker=maker,
        main=main,
        trigger_policy=account_trigger_policy,
    )
    scoring_explanations = _typed_scoring_explanations(
        reasoning,
        maker=maker,
        timeframe_contract=timeframe_contract,
        adjustment_policy=winrate_adjustment_policy,
        anchor_policy=winrate_anchor_policy,
        counter_resolution_policy=winrate_counter_resolution_policy,
    )
    signal_disposition_projections = _typed_signal_disposition_projections(
        reasoning,
        maker=maker,
        policy=secondary_signal_disposition_policy,
    )
    typed_continuity = _typed_continuity_contract(decision["continuity_contract"])
    missing_observations = [source for source, facts in source_facts.items() if not facts]
    if missing_observations:
        raise ValueError(
            "canonical report requires at least one observation per source: "
            + ", ".join(missing_observations)
        )
    direction = maker["direction"]
    plan_state = maker["plan_state"]
    execution_action = maker["execution_action"]
    semantic_state = _maker_semantic_state(maker)
    plan_summary = _maker_plan_summary(maker)
    if reasoning.get("schema_version") != "reasoning-model-v5":
        raise ValueError(
            "vNext report compiler only accepts reasoning-model-v5; "
            "legacy runs must use their immutable compiled artifact"
        )
    if decision.get("schema_version") != "decision-model-v7":
        raise ValueError("vNext report compiler only accepts decision-model-v7")
    frontstage: dict[str, str] = {}
    frontstage.update(
        _canonical_market_frontstage(
            reasoning,
            maker=maker,
            main=main,
            run_mode=decision["run_mode"],
            fedwatch_outcome_pattern=fedwatch_outcome_pattern,
            rate_expectation_provider=rate_expectation_provider,
        )
    )
    frontstage["multi_timeframe"] = _four_timeframe_line(
        reasoning,
        timeframe_contract=timeframe_contract,
    )
    _validate_manual_profile_projection(reasoning, frontstage)
    frontstage["cannot_do"] = f"{maker['cannot_do_code']}：{frontstage['cannot_do']}"
    frontstage.update(
        _canonical_execution_frontstage(
            maker,
            decision["continuity_contract"],
            run_mode=decision["run_mode"],
            authorization=decision["execution_authorization"],
        )
    )
    if semantic_state == QUALIFIED_CANDIDATE:
        frontstage.update(
            _canonical_risk_frontstage(
                maker,
                stop_policy=maker_stop_policy,
                invalidation_claim=maker_invalidation,
                buffer_policy=structural_noise_buffer_policy,
                timeframe_contract=timeframe_contract,
                run_mode=decision["run_mode"],
            )
        )
        frontstage.update(
            _canonical_defense_frontstage(
                maker,
                slot=decision["slot"],
                run_mode=decision["run_mode"],
            )
        )
    elif semantic_state in {
        REJECTED_SUBMITTED_CANDIDATE,
        DIRECTIONAL_THESIS_ONLY,
        NON_DIRECTIONAL_OBSERVATION,
    }:
        frontstage.update(
            _nonqualified_maker_risk_frontstage(
                semantic_state,
                slot=str(decision["slot"]),
            )
        )
    else:
        raise ValueError("Maker frontstage lacks a closed semantic state")
    rejected_risk_scenarios, rejected_risk_recalculation = (
        _rejected_risk_projection(maker)
    )
    scenario_tree = _scenario_audit(
        reasoning,
        account_controls=account_controls,
        scenario_ownership=submission_contract["scenario_ownership"],
        presentation_contract=presentation_contract,
    )
    model: dict[str, Any] = {
        "schema_version": REPORT_MODEL_SCHEMA_VERSION,
        "presentation_contract_version": presentation_contract["schema_version"],
        "presentation_contract_sha256": sha256_file(root / PRESENTATION_CONTRACT_PATH),
        "run_id": decision["run_id"],
        "run_sha256": decision["run_sha256"],
        "run_mode": decision["run_mode"],
        "execution_authorization": decision["execution_authorization"],
        "trading_date": decision["trading_date"],
        "slot": decision["slot"],
        "methodology_sha256": methodology_sha256,
        "report_contract_sha256": report_contract_sha256,
        "evidence_snapshot_sha256": decision["evidence_snapshot_sha256"],
        "reasoning_sha256": reasoning_model_sha256(reasoning),
        "decision_sha256": decision_model_sha256(decision),
        "blockbeats_cards": blockbeats_cards,
        "frontstage": frontstage,
        "maker_summary": {
            "semantic_state": semantic_state,
            "plan_state": plan_state,
            "threshold_eligible": maker["threshold_eligible"],
            "plan_constructible": maker["plan_constructible"],
            "constructibility_reason": (maker.get("plan_constructibility") or {}).get("primary_reason_code"),
            "constructibility_failure_codes": list(
                (maker.get("plan_constructibility") or {}).get("failure_codes") or []
            ),
            "constructibility_reason_explanations": _constructibility_reason_texts(
                maker.get("plan_constructibility")
            ),
            "plan_reason_explanations": _maker_plan_reason_texts(maker),
            "execution_action": execution_action,
            "order_transition_action": maker["order_transition_action"],
            "direction": direction,
            "plan_summary": plan_summary,
            "entry_reach_probability": entry_reach_probability_projection["value_pct"],
            "entry_reach_probability_applicability": entry_reach_probability_projection[
                "applicability"
            ],
            "entry_reach_probability_reason_code": entry_reach_probability_projection[
                "reason_code"
            ],
            "order_lifecycle_state": order_lifecycle["state"],
            "legal_fill_path_exists": order_lifecycle["legal_fill_path_exists"],
            "actual_fill_probability": order_lifecycle["fill_probability"],
            "win_rate": maker["win_rate"],
            "strategy_type": maker["strategy_type"],
            "cannot_do_code": maker["cannot_do_code"],
        },
        "main_summary": {
            "direction": main["direction"],
            "plan_state": main["plan_state"],
            "action": main["action"],
            "plan_projection": _main_plan_projection(
                main,
                stop_policy=main_stop_policy,
                invalidation_claim=main_invalidation,
                buffer_policy=structural_noise_buffer_policy,
                timeframe_contract=timeframe_contract,
                run_mode=decision["run_mode"],
            ),
            "position_notional_usdt": main["position_notional_usdt"],
            "leverage": main["leverage"],
        },
        "audit": {
            "source_facts": source_facts,
            "source_metrics": source_metrics,
            "source_explanations": source_explanations,
            "rate_expectation_provider": rate_expectation_provider,
            "fundamental_event_assessments": fundamental_event_projections,
            "claims": _claim_audit(reasoning),
            "reasoning_proof": _human_reasoning_proof(
                reasoning,
                maker=maker,
                main=main,
                fedwatch_outcome_pattern=fedwatch_outcome_pattern,
                account_trigger_policy=account_trigger_policy,
                timeframe_contract=timeframe_contract,
                rate_expectation_provider=rate_expectation_provider,
                blockbeats_events=blockbeats_cards,
                fundamental_event_projections=fundamental_event_projections,
                winrate_adjustment_policy=winrate_adjustment_policy,
                winrate_anchor_policy=winrate_anchor_policy,
                winrate_counter_resolution_policy=winrate_counter_resolution_policy,
                maker_stop_policy=maker_stop_policy,
            ),
            "main_direction": main["direction"],
            "main_plan": _typed_main_plan(main, stop_policy=main_stop_policy),
            "account_controls": account_controls,
            "orderflow_score": maker["orderflow_score"],
            "chart_score": maker["chart_score"],
            "total_score": maker["total_score"],
            "win_rate": maker["win_rate"],
            "winrate_rubric": {
                "anchor": (maker.get("winrate_rubric") or {}).get("anchor"),
                "anchor_claim_ids": list((maker.get("winrate_rubric") or {}).get("anchor_claim_ids") or []),
                "anchor_explanation": scoring_explanations["winrate_anchor"],
                "counter_resolution_explanation": scoring_explanations[
                    "counter_resolution"
                ],
                "adjustments": [
                    {
                        "delta": item.get("delta"),
                        "claim_ids": list(item.get("claim_ids") or []),
                        "reason_code": (
                            scoring_explanations["winrate_adjustments"][index].get("reason_code")
                            if index < len(scoring_explanations["winrate_adjustments"])
                            else "unbound_adjustment"
                        ),
                        "source_binding": (
                            scoring_explanations["winrate_adjustments"][index].get("source_binding", [])
                            if index < len(scoring_explanations["winrate_adjustments"])
                            else []
                        ),
                        "typed_values": (
                            scoring_explanations["winrate_adjustments"][index].get("typed_values", [])
                            if index < len(scoring_explanations["winrate_adjustments"])
                            else []
                        ),
                        "explanation": (
                            scoring_explanations["winrate_adjustments"][index].get("explanation")
                            if index < len(scoring_explanations["winrate_adjustments"])
                            else "无类型化调整解释。"
                        ),
                    }
                    for index, item in enumerate((maker.get("winrate_rubric") or {}).get("adjustments", []))
                    if isinstance(item, dict)
                ],
                "signal_dispositions": signal_disposition_projections,
                "counter_resolution": {
                    key: copy.deepcopy(
                        ((maker.get("winrate_rubric") or {}).get("counter_resolution") or {}).get(key)
                    )
                    for key in (
                        "counter_claim_id",
                        "disposition",
                        "adjustment_reason_code",
                        "residual_clause_indexes",
                        "resolution_claim_ids",
                    )
                },
                "final": (maker.get("winrate_rubric") or {}).get("final"),
            },
            "orderflow_scorecard": {
                "score": (maker.get("orderflow_scorecard") or {}).get("score"),
                "claim_ids": list((maker.get("orderflow_scorecard") or {}).get("claim_ids") or []),
                "explanation": scoring_explanations["orderflow"],
            },
            "chart_scorecard": {
                key: {
                    "score": value.get("score"),
                    "claim_ids": list(value.get("claim_ids") or []),
                    **(
                        {
                            "timeframe_relations": copy.deepcopy(
                                value.get("timeframe_relations")
                            )
                        }
                        if "timeframe_relations" in value
                        else {}
                    ),
                    "explanation": (scoring_explanations["chart"] or {}).get(
                        key,
                        "该分项只由认证TradingView类型化指标落值。",
                    ),
                }
                for key, value in (maker.get("chart_scorecard") or {}).items()
                if isinstance(value, dict)
            },
            "entry_reach_probability_basis": _typed_entry_reach_probability_basis(maker),
            "entry_reach_probability_projection": entry_reach_probability_projection,
            "order_lifecycle": order_lifecycle,
            "risk_plan": _typed_risk_plan(
                maker, stop_policy=maker_stop_policy
            ),
            "risk_scenarios": _risk_scenarios(maker) if plan_state == "qualified" else [],
            "rejected_candidate_risk_scenarios": rejected_risk_scenarios,
            "rejected_candidate_risk_recalculation": rejected_risk_recalculation,
            "main_risk_scenarios": _main_risk_scenarios(main),
            "risk_limits": {
                "main_account_maximum_nominal_risk_pct": copy.deepcopy(
                    main_risk_policy.get("maximum_nominal_risk_pct")
                ),
                "maker_maximum_nominal_risk_pct": copy.deepcopy(
                    risk_execution_policy.get("maximum_nominal_risk_pct")
                ),
            },
            "defense_plan": _typed_defense_plan(maker),
            "maker_execution": {
                key: (
                    _typed_plan_constructibility(maker.get(key))
                    if key == "plan_constructibility"
                    else maker.get(key)
                )
                for key in (
                    "direction",
                    "plan_state",
                    "execution_action",
                    "strategy_type",
                    "order_method",
                    "entry_type",
                    "exchange",
                    "instrument",
                    "position_notional_usdt",
                    "cannot_do_code",
                    "cannot_do_claim_id",
                    "threshold_eligible",
                    "plan_constructible",
                    "plan_constructibility",
                    "order_transition_action",
                )
            },
            "execution_authorization": decision["execution_authorization"],
            "continuity_contract": typed_continuity,
            "scenario_tree": scenario_tree,
            "main_current_counterevidence": main_current_counter,
            "maker_current_counterevidence": maker_current_counter,
            "main_current_invalidation_basis": main_current_invalidation,
            "maker_current_invalidation_basis": maker_current_invalidation,
            "main_counter_trigger": account_controls["main"]["counter"]["condition"],
            "maker_counter_trigger": account_controls["maker"]["counter"]["condition"],
            "main_invalidation_trigger": account_controls["main"]["invalidation"]["condition"],
            "maker_invalidation_trigger": account_controls["maker"]["invalidation"]["condition"],
        },
    }
    report_fields = tuple(
        field
        for field in REGISTRY.report_model_field_order
        if field != "model_sha256"
    )
    if set(model) != set(report_fields):
        raise RuntimeError("report builder fields differ from the domain registry")
    model = {field: model[field] for field in report_fields}
    model["model_sha256"] = canonical_report_model_sha256(model)
    return model


def canonical_report_model_sha256(model: dict[str, Any]) -> str:
    clean = dict(model)
    clean.pop("model_sha256", None)
    return canonical_sha256(clean)


def render_combined_markdown(model: dict[str, Any]) -> str:
    if model.get("schema_version") != REPORT_MODEL_SCHEMA_VERSION:
        raise ValueError(f"expected {REPORT_MODEL_SCHEMA_VERSION}")
    front = model["frontstage"]
    maker = model["maker_summary"]
    main = model["main_summary"]
    main_plan_state = {
        "new": "新建",
        "iterate": "迭代",
        "unchanged": "沿用",
        "observe": "观察",
    }.get(str(main.get("plan_state")), "未认证")
    audit = model["audit"]
    entry_reach_probability_projection = (
        audit.get("entry_reach_probability_projection")
        if isinstance(audit.get("entry_reach_probability_projection"), dict)
        else {}
    )
    entry_reach_probability_display = _entry_reach_probability_display(
        entry_reach_probability_projection
    )
    order_lifecycle = (
        audit.get("order_lifecycle")
        if isinstance(audit.get("order_lifecycle"), dict)
        else {}
    )
    order_lifecycle_display = _order_lifecycle_display(order_lifecycle)
    run_mode = str(model.get("run_mode") or "")
    is_shadow = run_mode == "shadow"
    defense = audit.get("defense_plan") or {}
    risk_limits = audit.get("risk_limits") if isinstance(audit.get("risk_limits"), dict) else {}
    main_risk_scenarios = audit.get("main_risk_scenarios") if isinstance(audit.get("main_risk_scenarios"), list) else []
    rejected_risk_scenarios = (
        audit.get("rejected_candidate_risk_scenarios")
        if isinstance(audit.get("rejected_candidate_risk_scenarios"), list)
        else []
    )
    rejected_risk_recalculation = (
        audit.get("rejected_candidate_risk_recalculation")
        if isinstance(audit.get("rejected_candidate_risk_recalculation"), dict)
        else {}
    )
    main_maximum_risk = max(
        (Decimal(str(item.get("nominal_risk_pct"))) for item in main_risk_scenarios),
        default=None,
    )
    rejected_candidate_lines: list[str] = []
    semantic_state = _maker_semantic_state(maker)
    if semantic_state in {
        DIRECTIONAL_THESIS_ONLY,
        NON_DIRECTIONAL_OBSERVATION,
    }:
        reason_texts = maker.get("plan_reason_explanations")
        if not isinstance(reason_texts, list) or not reason_texts:
            raise ValueError("Maker observation without a candidate lacks its closed reason")
        risk_plan = audit.get("risk_plan") if isinstance(audit.get("risk_plan"), dict) else {}
        maker_execution_audit = (
            audit.get("maker_execution")
            if isinstance(audit.get("maker_execution"), dict)
            else {}
        )
        if (
            risk_plan
            or audit.get("defense_plan")
            or rejected_risk_scenarios
            or rejected_risk_recalculation.get("status") != "not_submitted"
            or rejected_risk_recalculation.get("reason_code")
            != REJECTED_RISK_RECALCULATION_STATES["not_submitted"]
            or maker_execution_audit.get("position_notional_usdt") is not None
            or maker_execution_audit.get("entry_type") != "not_applicable"
        ):
            raise ValueError("Maker observation without a candidate contains ghost candidate fields")
        if (
            semantic_state == NON_DIRECTIONAL_OBSERVATION
            and (
                maker_execution_audit.get("plan_constructibility") or {}
            ).get("entry_zone_basis")
            is not None
        ):
            raise ValueError("non-directional Maker observation contains an entry-zone ghost")
        state_label = (
            "本轮方向观察（未提交候选）"
            if semantic_state == DIRECTIONAL_THESIS_ONLY
            else "本轮无方向观察（风险与执行均不适用）"
        )
        state_detail = (
            "本轮只保留方向判断，没有提交候选输入"
            if semantic_state == DIRECTIONAL_THESIS_ONLY
            else "本轮没有方向或候选输入"
        )
        rejected_candidate_lines.append(
            f"**{state_label}**："
            + "；".join(
                f"{index}.{text}"
                for index, text in enumerate(reason_texts, start=1)
            )
            + f"；{state_detail}，不生成仓位、入场、止损、止盈或风险值。"
        )
    elif semantic_state == REJECTED_SUBMITTED_CANDIDATE:
        reason_texts = maker.get("plan_reason_explanations")
        if not isinstance(reason_texts, list) or not reason_texts:
            raise ValueError("rejected Maker candidate lacks complete plan reasons")
        rejected_candidate_lines.append(
            "**被拒候选否决原因（不可执行，不得用于下单）**："
            + "；".join(
                f"{index}.{text}"
                for index, text in enumerate(reason_texts, start=1)
            )
            + "。"
        )
        risk_plan = audit.get("risk_plan") if isinstance(audit.get("risk_plan"), dict) else {}
        maker_execution_audit = (
            audit.get("maker_execution")
            if isinstance(audit.get("maker_execution"), dict)
            else {}
        )
        recalculation_status = str(
            rejected_risk_recalculation.get("status") or ""
        )
        expected_recalculation_reason = REJECTED_RISK_RECALCULATION_STATES.get(
            recalculation_status
        )
        if (
            expected_recalculation_reason is None
            or rejected_risk_recalculation.get("reason_code")
            != expected_recalculation_reason
        ):
            raise ValueError("rejected risk recalculation status is invalid")
        if risk_plan:
            entries = risk_plan.get("entries") if isinstance(risk_plan.get("entries"), list) else []
            rejected_candidate_lines.append(
                "**被拒候选审计输入（不可执行，不得用于下单）**："
                f"候选名义持仓={_audit_number(maker_execution_audit.get('position_notional_usdt'))} USDT；"
                f"入场类型={_visible_enum('maker.entry_type', maker_execution_audit.get('entry_type'))}；"
                f"杠杆={_audit_number(risk_plan.get('leverage'))}x；"
                f"入场={','.join(_audit_number(item) for item in entries) or '未提供'}；"
                f"止损={_audit_number(risk_plan.get('stop'))}；"
                f"TP1={_audit_number(risk_plan.get('tp1'))}；"
                f"TP2={_audit_number(risk_plan.get('tp2'))}。"
            )
            if recalculation_status == "recalculated" and rejected_risk_scenarios:
                rejected_candidate_lines.extend(
                    (
                        "**被拒候选风险情景（不可执行，不得用于下单）**："
                        f"成交档位{item['filled_levels']}，"
                        f"加权入场{_display_decimal(item['entry'])}，"
                        f"TP1 盈亏比 1:{_display_decimal(item['rr_to_tp1'])}，"
                        f"TP2盈亏比1:{_display_decimal(item['rr_to_tp2'])}，"
                        f"名义风险{_display_decimal(item['nominal_risk_pct'])}%。"
                    )
                    for item in rejected_risk_scenarios
                )
                rejected_candidate_lines.append(
                    "**被拒候选机械结论（不可执行，不得用于下单）**："
                    f"以上数值只复算已否决输入，不认可其结构止损；Maker名义风险上限="
                    f"{_audit_number(risk_limits.get('maker_maximum_nominal_risk_pct'))}%。"
                )
            elif (
                recalculation_status == "not_recalculable"
                and not rejected_risk_scenarios
            ):
                rejected_candidate_lines.append(
                    "**被拒候选机械结论（不可执行，不得用于下单）**："
                    "候选风险输入未满足确定性复算前提，因此不生成盈亏比或名义风险值；"
                    "这不代表风险合格，候选仍不可执行且不得用于下单。"
                )
            else:
                raise ValueError("rejected risk scenarios conflict with recalculation status")
        else:
            raise ValueError("a submitted rejected candidate lacks its risk input")
    elif semantic_state != QUALIFIED_CANDIDATE:
        raise ValueError("Maker appendix lacks a closed semantic state")
    date = model["trading_date"]
    slot = model["slot"]
    main_direction_text = AUDIT_DIRECTION_CN.get(str(main.get("direction")), "未知")
    maker_direction_text = AUDIT_DIRECTION_CN.get(str(maker.get("direction")), "未知")
    account_controls = audit.get("account_controls") if isinstance(audit.get("account_controls"), dict) else {}
    scenario_lines: list[str] = []
    for item in audit.get("scenario_tree", []):
        scenario = SCENARIO_TYPE_CN.get(item["scenario_type"], "补充情景")
        account_label = ACCOUNT_CN.get(str(item.get("account")), str(item.get("account")))
        account = str(item.get("account"))
        scenario_type = str(item.get("scenario_type"))
        condition = str(item.get("condition") or "未提供")
        expected_path = str(item.get("expected_path") or "未提供")
        action = str(item.get("action") or "未提供")
        account_has_executable_plan = (
            account == "maker" and semantic_state == QUALIFIED_CANDIDATE
        ) or (
            account == "main" and str(main.get("plan_state")) != "observe"
        )
        action_label = "分析状态转换"
        if not account_has_executable_plan:
            if account == "maker" and semantic_state == REJECTED_SUBMITTED_CANDIDATE:
                authorization_boundary = (
                    "当前仅保留被拒候选审计，不生成、撤销或改变真实订单；"
                    "形成新候选后仍须重新认证"
                )
            else:
                authorization_boundary = (
                    "当前只保留观察，不生成、撤销或改变真实订单；"
                    "未来形成计划仍须重新认证"
                )
        elif is_shadow:
            if account == "main" and scenario_type == "base":
                authorization_boundary = "当前不执行；未来另获production授权后仍须重新认证主账户候选计划"
            elif account == "main":
                authorization_boundary = "当前不执行；该控制规则只供未来独立认证"
            elif scenario_type == "base":
                authorization_boundary = "当前不生成真实订单；未来另获production授权后仍须重新认证Maker候选计划"
            else:
                authorization_boundary = "当前不撤销或改变真实订单；该控制规则只供未来独立认证"
        else:
            authorization_boundary = "是否执行仍服从本轮独立执行授权与连续性门"
        scenario_lines.append(
            f"**{account_label}{scenario}**：触发条件为{_sentence(condition)}"
            f"预期路径为{_sentence(expected_path)}"
            f"{action_label}为{_sentence(action)}"
            f"授权边界为{_sentence(authorization_boundary)}"
        )
    chart_score_lines: list[str] = []
    for key, basis in audit.get("chart_scorecard", {}).items():
        if not isinstance(basis, dict):
            continue
        chart_score_lines.append(
            f"**{CHART_COMPONENT_CN.get(key, key)} {basis.get('score')} 分**："
            f"依据：{_sentence(basis.get('explanation', '仅按认证TradingView结构评价机会质量'))}"
        )
    claim_type_by_id = {
        str(item.get("id")): CLAIM_TYPE_CN.get(str(item.get("claim_type")), str(item.get("claim_type")))
        for item in audit.get("claims", [])
        if isinstance(item, dict)
    }
    adjustment_lines: list[str] = []
    for index, item in enumerate((audit.get("winrate_rubric") or {}).get("adjustments", []), start=1):
        if not isinstance(item, dict):
            continue
        delta = item.get("delta")
        delta_text = f"+{delta}" if isinstance(delta, int) and delta > 0 else str(delta)
        bound_claims = "、".join(
            claim_type_by_id.get(str(claim_id), "认证判断")
            for claim_id in item.get("claim_ids") or []
        ) or "认证判断"
        adjustment_lines.append(
            f"**次因调整｜第{index}项 {delta_text} 个百分点**："
            f"绑定{bound_claims}；{_sentence(item.get('explanation', '调整值只由类型化delta拥有'))}"
        )
    signal_disposition_lines: list[str] = []
    for item in (audit.get("winrate_rubric") or {}).get(
        "signal_dispositions", []
    ):
        if not isinstance(item, dict):
            continue
        signal_disposition_lines.append(
            f"**二级信号处置｜{item.get('signal_label', '未认证信号')}**："
            f"类型化当前值={item.get('typed_value_text', '未认证')}；"
            f"处置={item.get('disposition_text', '未认证')}；"
            f"闭合理由={_sentence(item.get('reason_text', '未认证'))}"
        )
    source_lines: list[str] = []
    for index, source in enumerate(REQUIRED_SOURCES, start=1):
        item = (audit.get("source_explanations") or {}).get(source) or {}
        source_lines.extend(
            [
                f"**{index}. {source}｜{item.get('role', SOURCE_ROLE_CN[source])}**",
                f"证据事实：{_sentence(item.get('fact', '未提供'))}",
                f"判断价值：{_sentence(item.get('decision_value', '未提供'))}",
                f"使用边界：{_sentence(item.get('boundary', SOURCE_BOUNDARY_CN[source]))}",
            ]
        )
    proof_lines: list[str] = []
    for key, label in REASONING_PROOF_LABELS.items():
        item = (audit.get("reasoning_proof") or {}).get(key) or {}
        evidence = "；".join(
            str(value).strip().rstrip("。；;")
            for value in item.get("evidence", [])
            if str(value).strip()
        )
        line = (
            f"**{label}**｜证据：{_sentence(evidence or '未提供')}"
            f"推导：{_sentence(item.get('logic', '未提供'))}"
            f"结论：{_sentence(item.get('conclusion', '未提供'))}"
        )
        if key in {"main_account_closure", "maker_account_closure"}:
            line += f"最强反证：{_sentence(item.get('counter', '未提供'))}"
        if key not in {"footprint_cross_check", "risk_and_scenarios"}:
            line += f"控制边界：{_sentence(item.get('invalidation', '未提供'))}"
        proof_lines.append(line)
    if semantic_state == QUALIFIED_CANDIDATE:
        defense_lines = [
            (
                f"第一层：触及{_defense_trigger_text(defense, 'first', level_count=len((audit.get('risk_plan') or {}).get('entries') or []))}后，"
                f"{front['defense_first']}"
            ),
            (
                f"第二层：触及{_defense_trigger_text(defense, 'second', level_count=len((audit.get('risk_plan') or {}).get('entries') or []))}后，"
                f"{front['defense_second']}"
            ),
        ]
    else:
        defense_lines = [
            _prefixed(front["defense_first"], "第一层："),
            _prefixed(front["defense_second"], "第二层："),
        ]
    defense_calculation_lines = (
        _defense_calculation_audit_lines(defense, run_mode=run_mode)
        if semantic_state == QUALIFIED_CANDIDATE
        else []
    )
    if semantic_state == QUALIFIED_CANDIDATE:
        maker_header = "### BTC（候选策略）" if is_shadow else "### BTC（策略）"
        maker_summary = (
            f"BTC（候选策略）：候选策略类型：{maker['strategy_type']}；候选计划结论：{maker['plan_summary']}；"
            f"真实执行状态：{_execution_action_text(maker['execution_action'])}；"
            f"入场价格触达概率：{entry_reach_probability_display}；"
            f"计划时置信度{maker['win_rate']}%（非回测命中率）"
            if is_shadow
            else (
                f"BTC（策略）：策略类型：{maker['strategy_type']}；计划结论：{maker['plan_summary']}；"
                f"执行状态：{_execution_action_text(maker['execution_action'])}；"
                f"入场价格触达概率：{entry_reach_probability_display}；"
                f"计划时置信度{maker['win_rate']}%（非回测命中率）"
            )
        )
    elif semantic_state == REJECTED_SUBMITTED_CANDIDATE:
        maker_header = "### BTC（被拒候选审计）"
        maker_summary = (
            f"BTC（被拒候选审计）：候选策略类型：{maker['strategy_type']}；"
            f"审计结论：{maker['plan_summary']}；"
            f"真实执行状态：{_execution_action_text(maker['execution_action'])}；"
            f"入场价格触达概率：{entry_reach_probability_display}；"
            f"计划时置信度{maker['win_rate']}%（非回测命中率）"
        )
    elif semantic_state == DIRECTIONAL_THESIS_ONLY:
        maker_header = "### BTC（方向观察）"
        maker_summary = (
            f"BTC（方向观察）：观察类型：{maker['strategy_type']}；"
            f"方向结论：{maker['plan_summary']}；"
            f"真实执行状态：{_execution_action_text(maker['execution_action'])}；"
            f"入场价格触达概率：{entry_reach_probability_display}；"
            f"计划时置信度{maker['win_rate']}%（非回测命中率）"
        )
    elif semantic_state == NON_DIRECTIONAL_OBSERVATION:
        maker_header = "### BTC（无方向观察）"
        maker_summary = (
            f"BTC（无方向观察）：观察类型：{maker['strategy_type']}；观察结论：{maker['plan_summary']}；"
            f"真实执行状态：{_execution_action_text(maker['execution_action'])}；"
            f"入场价格触达概率：{entry_reach_probability_display}；"
            f"计划时置信度{maker['win_rate']}%（非回测命中率）"
        )
    else:
        raise ValueError("Maker markdown lacks a closed semantic state")
    main_authorization_label = "影子授权边界" if is_shadow else "执行声明"
    maker_authorization_label = "影子授权边界" if is_shadow else "执行资格"
    lines = [
        f"# {expected_title(date, slot)}",
        "",
        f"> {front['opening_quote']}",
        "",
        "**作者自查（内部审计，不进入 Notion 判断正文）**",
        "证据完整性：六源均来自本时段认证快照；历史金标只控制方法链与版式，不提供市场事实。",
        "推理完整性：同锚盘口、足迹交叉验证、多周期结构、7 月增量逻辑、反证与失效均已进入认证模型。",
        "交付完整性：正文、Maker、后附、Word 与后续 Notion 均只能投影同一统一认证模型。",
        "",
        "## ① 正文",
        "",
        "### 基本面",
        _prefixed(front["fundamentals"], "基本面："),
        "",
        "### 技术面",
        _prefixed(front["orderflow_label"], "盘口："),
        front["orderflow_text"],
        "",
        "### 解读",
        _prefixed(front["interpretation"], "解读："),
        _prefixed(front["chart_label"], "盘面："),
        _prefixed(front["daily_line"], "日线级别："),
        _prefixed(front["hourly_line"], "小时级别：")
        + " 四周期认证："
        + front["multi_timeframe"],
        "",
        "### 趋势确认",
        front["trend_confirmation"],
        "",
        "### 日内支撑/压力",
        front["support_resistance"],
        "",
        "### 策略",
        _join_clauses(
            _prefixed(front["strategy"], "策略："),
            f"主账户计划状态：{main_plan_state}",
            main["plan_projection"],
            f"{main_authorization_label}：{front['main_authorization']}",
        ),
        "",
        "## 不能做",
        _prefixed(front["cannot_do"], "不能做："),
        "",
        "## ② Maker 计划",
        "",
        maker_header,
        maker_summary,
        _join_clauses(
            _prefixed(front["maker_strategy"], "策略："),
            f"计划参数：{front['maker_execution']}",
            f"{maker_authorization_label}：{front['maker_authorization']}",
            f"连续性：{front['maker_continuity']}",
        ),
        _prefixed(front["maker_tp"], "止盈："),
        _prefixed(front["maker_sl"], "止损："),
        "",
        "### 防守计划",
        *defense_lines,
        _prefixed(front["defense_note"], "注意事项："),
        _prefixed(front["defense_cancel"], "取消价≠止损："),
    ]
    if slot == "evening":
        lines.append(_prefixed(front["defense_core"], "核心："))
    lines.extend(
        [
            _prefixed(front["independent_boundary"], "独立边界："),
            "",
            "## ③ 后附",
            "",
            f"### A. 评分明细（{ORDERFLOW_SCORE_MAX}+{CHART_SCORE_MAX}）",
            f"**盘口 {audit['orderflow_score']}／{ORDERFLOW_SCORE_MAX}**：{_sentence((audit.get('orderflow_scorecard') or {}).get('explanation', '分数只由类型化score字段拥有'))}",
            f"**盘面 {audit['chart_score']}／{CHART_SCORE_MAX}**：盘面只评价机会质量，不担任方向盘。",
            *chart_score_lines,
            f"**总分**：{audit['orderflow_score']} + {audit['chart_score']} = {audit['total_score']}。",
            f"**入场价格触达概率**：{_entry_reach_probability_text(audit.get('entry_reach_probability_basis') or {}, projection=entry_reach_probability_projection, run_mode=run_mode)}",
            f"**订单生命周期**：{order_lifecycle_display}；成交概率=N/A（本系统未估计）。",
            "",
            "**计划时置信度推导链（非回测命中率）**",
            f"基准锚：{(audit.get('winrate_rubric') or {}).get('anchor', '未提供')}%；{_sentence((audit.get('winrate_rubric') or {}).get('anchor_explanation', '只绑定类型化证据'))}",
            *adjustment_lines,
            *signal_disposition_lines,
            f"计划时置信度：{audit['win_rate']}%；与 60% 门槛比较。",
            "",
            "### B. 六源支持与底层作用",
            *source_lines,
            "",
            "### C. 人类可读推理证明链",
            *proof_lines,
            "",
            "### D. 风险、情景与机械校验",
        ]
    )
    lines.extend(
        [
            *rejected_candidate_lines,
            *[
                (
                    f"**{'Maker候选成交情景' if is_shadow else 'Maker成交情景'}**：成交档位{item['filled_levels']}，加权入场{_display_decimal(item['entry'])}，"
                    f"TP1 盈亏比 1:{_display_decimal(item['rr_to_tp1'])}，"
                    f"TP2盈亏比1:{_display_decimal(item['rr_to_tp2'])}，"
                    f"名义风险{_display_decimal(item['nominal_risk_pct'])}%。"
                )
                for item in audit.get("risk_scenarios", [])
            ],
            (
                f"**{'主账户候选风险机械校验' if is_shadow else '主账户风险机械校验'}**：覆盖{len(main_risk_scenarios)}种非空成交组合，"
                f"最大名义风险{_display_decimal(main_maximum_risk)}%，"
                f"独立上限{_plain_number(risk_limits.get('main_account_maximum_nominal_risk_pct'))}%。"
            )
            if main_risk_scenarios
            else "**主账户风险机械校验**：主账户处于观察状态，不生成仓位或风险值。",
            *defense_calculation_lines,
            (
                f"**{'候选减仓规则' if is_shadow else '仓位账本'}**：TP1减仓{(audit.get('risk_plan') or {}).get('tp1_close_pct', '未提供')}%；"
                f"TP2清剩余{(audit.get('risk_plan') or {}).get('tp2_close_pct', '未提供')}%。"
            )
            if semantic_state == QUALIFIED_CANDIDATE
            else (
                "**被拒候选审计**：候选未通过认证，不生成可执行减仓规则。"
                if semantic_state == REJECTED_SUBMITTED_CANDIDATE
                else "**方向观察状态**：未提交风险计划，不适用减仓规则。"
                if semantic_state == DIRECTIONAL_THESIS_ONLY
                else "**无方向观察状态**：风险计划与减仓规则均不适用。"
            ),
            (
                f"{'Maker候选机械校验' if is_shadow else 'Maker机械校验'}：全部情景均达到1:2.5且不高于{_plain_number(risk_limits.get('maker_maximum_nominal_risk_pct'))}%。"
                if semantic_state == QUALIFIED_CANDIDATE
                else "被拒候选机械审计：只审计真实提交的输入，不形成可执行风险结论。"
                if semantic_state == REJECTED_SUBMITTED_CANDIDATE
                else "机械校验：本轮未提交 Maker 风险计划，不生成风险情景。"
            ),
            *scenario_lines,
            (
                f"**方向主判**：主账户{AUDIT_DIRECTION_CN.get(audit['main_direction'], audit['main_direction'])}，"
                f"{ORDERFLOW_DIRECTION_METHOD_CN}"
            ),
            f"**主账户当前最强反证**：{_sentence((audit['main_current_counterevidence'] or {}).get('condition', '未认证'))}",
            "**主账户未来反证触发条件**：见上方“主账户反证情景”的完整类型化触发条件。",
            f"**主账户当前失效路径基线**：{_sentence((audit['main_current_invalidation_basis'] or {}).get('condition', '未认证'))}",
            "**主账户未来失效触发条件**：见上方“主账户失效情景”的完整类型化触发条件。",
            f"**Maker当前最强反证**：{_sentence((audit['maker_current_counterevidence'] or {}).get('condition', '未认证'))}",
            "**Maker未来反证触发条件**：见上方“Maker反证情景”的完整类型化触发条件。",
            f"**Maker当前失效路径基线**：{_sentence((audit['maker_current_invalidation_basis'] or {}).get('condition', '未认证'))}",
            "**Maker未来失效触发条件**：见上方“Maker失效情景”的完整类型化触发条件。",
            "",
        ]
    )
    text = "\n".join(lines)
    parsed_lines = text.splitlines()
    assert_combined_structure(parsed_lines, date, slot)
    parse_daily_text_contract(parsed_lines, date, slot)
    return text


def evaluate_human_reasoning_depth(
    model: dict[str, Any],
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    defects: list[dict[str, str]] = []
    if model.get("schema_version") != REPORT_MODEL_SCHEMA_VERSION:
        defects.append({"code": "report_projection.schema_invalid", "message": f"expected {REPORT_MODEL_SCHEMA_VERSION}", "path": "schema_version", "severity": "hard"})
    audit = model.get("audit") if isinstance(model.get("audit"), dict) else {}
    proof = audit.get("reasoning_proof") if isinstance(audit.get("reasoning_proof"), dict) else {}
    required = contract.get("required_reasoning_proof_blocks") or []
    for name in required:
        item = proof.get(name)
        path = f"audit.reasoning_proof.{name}"
        if not isinstance(item, dict):
            defects.append({"code": "reasoning_proof.block_missing", "message": f"missing reasoning proof block: {name}", "path": path, "severity": "hard"})
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        if not evidence or not all(str(value).strip() for value in evidence):
            defects.append({"code": "reasoning_proof.evidence_missing", "message": f"reasoning proof block lacks evidence: {name}", "path": f"{path}.evidence", "severity": "hard"})
        for field in ("logic", "conclusion", "counter", "invalidation"):
            value = str(item.get(field, "")).strip()
            if len(value) < 8 or not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value):
                defects.append({"code": "reasoning_proof.field_thin", "message": f"{name}.{field} must be Chinese-readable and explicit", "path": f"{path}.{field}", "severity": "hard"})
    explanations = audit.get("source_explanations") if isinstance(audit.get("source_explanations"), dict) else {}
    required_fields = contract.get("source_explanation_fields") or []
    if set(explanations) != set(REQUIRED_SOURCES):
        defects.append({"code": "reasoning_proof.source_set", "message": "source explanation set must equal the certified six sources", "path": "audit.source_explanations", "severity": "hard"})
    for source in REQUIRED_SOURCES:
        item = explanations.get(source) if isinstance(explanations.get(source), dict) else {}
        for field in required_fields:
            value = str(item.get(field, "")).strip()
            minimum_length = 4 if field == "role" else 8
            if len(value) < minimum_length or not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value):
                defects.append({"code": "reasoning_proof.source_field_thin", "message": f"{source}.{field} must be Chinese-readable and explicit", "path": f"audit.source_explanations.{source}.{field}", "severity": "hard"})
    frontstage = model.get("frontstage") if isinstance(model.get("frontstage"), dict) else {}
    for field in contract.get("required_frontstage_fields") or []:
        if len(str(frontstage.get(field, "")).strip()) < 8:
            defects.append({"code": "report_projection.field_missing", "message": f"frontstage lacks required certified field: {field}", "path": f"frontstage.{field}", "severity": "hard"})
    timeframe_text = str(frontstage.get("multi_timeframe", ""))
    timeframe_contract = _validated_timeframe_display_contract(contract)
    for code in timeframe_contract["tradingview_projection_order"]:
        token = _timeframe_display_label(timeframe_contract, code)
        if token not in timeframe_text:
            defects.append({"code": "report_projection.timeframe_missing", "message": f"frontstage lacks explicit timeframe: {token}", "path": "frontstage.multi_timeframe", "severity": "hard"})
    maker_execution = audit.get("maker_execution") if isinstance(audit.get("maker_execution"), dict) else {}
    for field in contract.get("maker_execution_fields") or []:
        if field not in maker_execution:
            defects.append({"code": "report_projection.maker_field_missing", "message": f"audit lacks certified Maker execution field: {field}", "path": f"audit.maker_execution.{field}", "severity": "hard"})
    authorization = audit.get("execution_authorization") if isinstance(audit.get("execution_authorization"), dict) else {}
    if set(authorization) != EXECUTION_AUTHORIZATION_FIELDS:
        defects.append({"code": "report_projection.execution_authorization_invalid", "message": "report audit lacks the exact execution authorization field set", "path": "audit.execution_authorization", "severity": "hard"})
    continuity = audit.get("continuity_contract") if isinstance(audit.get("continuity_contract"), dict) else {}
    maker_summary = (
        model.get("maker_summary")
        if isinstance(model.get("maker_summary"), dict)
        else {}
    )
    risk_plan = audit.get("risk_plan") if isinstance(audit.get("risk_plan"), dict) else {}
    defense_plan = (
        audit.get("defense_plan")
        if isinstance(audit.get("defense_plan"), dict)
        else {}
    )
    order_lifecycle = (
        audit.get("order_lifecycle")
        if isinstance(audit.get("order_lifecycle"), dict)
        else {}
    )
    entry_reach_basis = (
        audit.get("entry_reach_probability_basis")
        if isinstance(audit.get("entry_reach_probability_basis"), dict)
        else {}
    )
    reconstructed_maker = copy.deepcopy(maker_execution)
    reconstructed_maker.update(
        {
            "risk_plan": risk_plan,
            "defense_plan": defense_plan,
            "order_lifecycle": order_lifecycle,
            "entry_reach_probability_basis": entry_reach_basis,
        }
    )
    reported_semantic_state = maker_summary.get("semantic_state")
    derived_semantic_state: str | None = None
    try:
        derived_semantic_state = _maker_semantic_state(reconstructed_maker)
    except ValueError as exc:
        defects.append(
            {
                "code": "report_projection.maker_semantic_state_invalid",
                "message": str(exc),
                "path": "maker_summary.semantic_state",
                "severity": "hard",
            }
        )
    if derived_semantic_state is not None:
        try:
            expected_summary_projection = {
                "semantic_state": derived_semantic_state,
                "plan_state": reconstructed_maker.get("plan_state"),
                "threshold_eligible": reconstructed_maker.get("threshold_eligible"),
                "plan_constructible": reconstructed_maker.get("plan_constructible"),
                "constructibility_reason": (
                    reconstructed_maker.get("plan_constructibility") or {}
                ).get("primary_reason_code"),
                "constructibility_failure_codes": list(
                    (
                        reconstructed_maker.get("plan_constructibility") or {}
                    ).get("failure_codes")
                    or []
                ),
                "constructibility_reason_explanations": (
                    _constructibility_reason_texts(
                        reconstructed_maker.get("plan_constructibility")
                    )
                ),
                "plan_reason_explanations": _maker_plan_reason_texts(
                    reconstructed_maker
                ),
                "execution_action": reconstructed_maker.get("execution_action"),
                "order_transition_action": reconstructed_maker.get(
                    "order_transition_action"
                ),
                "direction": reconstructed_maker.get("direction"),
                "plan_summary": _maker_plan_summary(reconstructed_maker),
                "strategy_type": reconstructed_maker.get("strategy_type"),
                "cannot_do_code": reconstructed_maker.get("cannot_do_code"),
            }
        except ValueError as exc:
            defects.append(
                {
                    "code": "report_projection.maker_summary_reconstruction_invalid",
                    "message": str(exc),
                    "path": "audit.maker_execution",
                    "severity": "hard",
                }
            )
        else:
            drifted_summary_fields = [
                field
                for field, expected_value in expected_summary_projection.items()
                if maker_summary.get(field) != expected_value
            ]
            if drifted_summary_fields:
                defects.append(
                    {
                        "code": "report_projection.maker_summary_audit_drift",
                        "message": (
                            "Maker summary differs from its sealed audit projection: "
                            + ", ".join(drifted_summary_fields)
                        ),
                        "path": "maker_summary",
                        "severity": "hard",
                    }
                )
        try:
            expected_execution_frontstage = _canonical_execution_frontstage(
                reconstructed_maker,
                continuity,
                run_mode=str(model.get("run_mode") or ""),
                authorization=authorization,
            )
        except (KeyError, TypeError, ValueError) as exc:
            defects.append(
                {
                    "code": "report_projection.maker_execution_reconstruction_invalid",
                    "message": str(exc),
                    "path": "audit.maker_execution",
                    "severity": "hard",
                }
            )
        else:
            drifted_execution_fields = [
                field
                for field, expected_value in expected_execution_frontstage.items()
                if frontstage.get(field) != expected_value
            ]
            if drifted_execution_fields:
                defects.append(
                    {
                        "code": "report_projection.maker_execution_audit_drift",
                        "message": (
                            "Maker execution frontstage differs from its sealed audit "
                            "projection: "
                            + ", ".join(drifted_execution_fields)
                        ),
                        "path": "frontstage",
                        "severity": "hard",
                    }
                )
    if reported_semantic_state not in MAKER_SEMANTIC_STATES:
        defects.append(
            {
                "code": "report_projection.maker_semantic_state_missing",
                "message": "Maker summary lacks a closed semantic state",
                "path": "maker_summary.semantic_state",
                "severity": "hard",
            }
        )
    elif (
        derived_semantic_state is not None
        and reported_semantic_state != derived_semantic_state
    ):
        defects.append(
            {
                "code": "report_projection.maker_semantic_state_drift",
                "message": "Maker summary semantic state differs from sealed audit facts",
                "path": "maker_summary.semantic_state",
                "severity": "hard",
            }
        )
    semantic_state = (
        derived_semantic_state
        if derived_semantic_state is not None
        else reported_semantic_state
        if reported_semantic_state in MAKER_SEMANTIC_STATES
        else None
    )
    if semantic_state in {
        REJECTED_SUBMITTED_CANDIDATE,
        DIRECTIONAL_THESIS_ONLY,
        NON_DIRECTIONAL_OBSERVATION,
    }:
        try:
            expected_nonqualified_frontstage = _nonqualified_maker_risk_frontstage(
                semantic_state,
                slot=str(model.get("slot") or ""),
            )
        except ValueError as exc:
            defects.append(
                {
                    "code": "report_projection.maker_nonqualified_state_invalid",
                    "message": str(exc),
                    "path": "frontstage",
                    "severity": "hard",
                }
            )
        else:
            drifted_fields = [
                field
                for field, expected_value in expected_nonqualified_frontstage.items()
                if frontstage.get(field) != expected_value
            ]
            if drifted_fields:
                defects.append(
                    {
                        "code": "report_projection.maker_nonqualified_ghost_plan",
                        "message": (
                            "non-qualified Maker frontstage differs from its exact "
                            "no-execution projection: "
                            + ", ".join(drifted_fields)
                        ),
                        "path": "frontstage",
                        "severity": "hard",
                    }
                )
    main_plan = audit.get("main_plan") if isinstance(audit.get("main_plan"), dict) else {}
    expected_main_authorization = _main_authorization_text(
        plan_state=main_plan.get("plan_state"),
        run_mode=str(model.get("run_mode") or ""),
    )
    if frontstage.get("main_authorization") != expected_main_authorization:
        defects.append(
            {
                "code": "report_projection.main_authorization_audit_drift",
                "message": (
                    "main-account authorization differs from its sealed plan state"
                ),
                "path": "frontstage.main_authorization",
                "severity": "hard",
            }
        )
    scenarios = (
        audit.get("scenario_tree")
        if isinstance(audit.get("scenario_tree"), list)
        else []
    )
    try:
        _validate_scenario_projection(
            scenarios,
            claims=(
                audit.get("claims")
                if isinstance(audit.get("claims"), list)
                else []
            ),
            account_controls=(
                audit.get("account_controls")
                if isinstance(audit.get("account_controls"), dict)
                else {}
            ),
            presentation_contract=contract,
        )
    except ValueError as exc:
        defects.append(
            {
                "code": "report_projection.scenario_typed_projection_drift",
                "message": str(exc),
                "path": "audit.scenario_tree",
                "severity": "hard",
            }
        )
    if model.get("run_mode") == "shadow":
        shadow_continuity_valid = (
            set(continuity) == SHADOW_CONTINUITY_FIELDS
            and continuity.get("schema_version") == SHADOW_CONTINUITY_SCHEMA_VERSION
            and continuity.get("reasoning_sha256") == model.get("reasoning_sha256")
            and continuity.get("run_sha256") == model.get("run_sha256")
            and continuity.get("live_state_read") is False
            and continuity.get("order_mutation_attempted") is False
            and continuity.get("execution_action") == "not_attempted"
            and continuity.get("reason_code") == "shadow_mode_forbids_live_execution"
        )
        if not shadow_continuity_valid:
            defects.append({"code": "report_projection.shadow_continuity_invalid", "message": "shadow report audit lacks the sealed no-live-execution continuity contract", "path": "audit.continuity_contract", "severity": "hard"})
        shadow_disclosure_prefix = {
            QUALIFIED_CANDIDATE: "影子候选计划",
            REJECTED_SUBMITTED_CANDIDATE: "影子被拒候选审计状态",
            DIRECTIONAL_THESIS_ONLY: "影子方向观察状态",
            NON_DIRECTIONAL_OBSERVATION: "影子无方向观察状态",
        }.get(semantic_state)
        shadow_disclosure = (
            f"{shadow_disclosure_prefix}；未读取个人持仓/订单状态；"
            "未创建、撤销或挂出真实订单"
            if shadow_disclosure_prefix is not None
            else ""
        )
        projected_shadow_text = "\n".join(
            str(frontstage.get(field, ""))
            for field in ("maker_authorization", "maker_continuity")
        )
        if not shadow_disclosure or shadow_disclosure not in projected_shadow_text:
            defects.append({"code": "report_projection.shadow_disclosure_missing", "message": "shadow report must disclose the exact Maker semantic state and zero live-state/order mutation", "path": "frontstage.maker_continuity", "severity": "hard"})
        semantic_conflicts = {
            QUALIFIED_CANDIDATE: (
                "影子被拒候选审计状态",
                "影子方向观察状态",
                "影子无方向观察状态",
                "被拒候选审计有效至",
                "方向判断有效至",
                "观察结论有效至",
            ),
            REJECTED_SUBMITTED_CANDIDATE: (
                "影子候选计划",
                "影子方向观察状态",
                "影子无方向观察状态",
                "候选计划有效至",
                "方向判断有效至",
                "观察结论有效至",
            ),
            DIRECTIONAL_THESIS_ONLY: (
                "影子候选计划",
                "影子被拒候选审计状态",
                "影子无方向观察状态",
                "候选计划有效至",
                "被拒候选审计有效至",
                "观察结论有效至",
            ),
            NON_DIRECTIONAL_OBSERVATION: (
                "影子候选计划",
                "影子被拒候选审计状态",
                "影子方向观察状态",
                "候选计划有效至",
                "被拒候选审计有效至",
                "方向判断有效至",
            ),
        }.get(semantic_state, ())
        present_conflicts = [
            phrase for phrase in semantic_conflicts if phrase in projected_shadow_text
        ]
        if present_conflicts:
            defects.append(
                {
                    "code": "report_projection.shadow_semantic_state_conflict",
                    "message": (
                        "shadow Maker disclosure mixes mutually exclusive semantic states: "
                        + ", ".join(present_conflicts)
                    ),
                    "path": "frontstage.maker_continuity",
                    "severity": "hard",
                }
            )
        if re.search(r"\b(?:place_order|new_order_created)\b|有效订单数量|有效挂单\d+个", projected_shadow_text):
            defects.append({"code": "report_projection.shadow_live_state_leak", "message": "shadow report must not project live order actions or counts", "path": "frontstage.maker_continuity", "severity": "hard"})
    elif continuity.get("schema_version") != "post-reasoning-continuity-contract-vnext-v1":
        defects.append({"code": "report_projection.continuity_missing", "message": "production report audit lacks the certified continuity contract", "path": "audit.continuity_contract", "severity": "hard"})
    main_summary = model.get("main_summary") if isinstance(model.get("main_summary"), dict) else {}
    if not str(main_summary.get("plan_projection", "")).strip() or not str(main_summary.get("plan_state", "")).strip():
        defects.append({"code": "report_projection.main_plan_missing", "message": "report lacks the certified main-account plan", "path": "main_summary", "severity": "hard"})
    main_summary_drift = [
        field
        for field in (
            "direction",
            "plan_state",
            "action",
            "position_notional_usdt",
            "leverage",
        )
        if main_summary.get(field) != main_plan.get(field)
    ]
    if main_summary_drift:
        defects.append(
            {
                "code": "report_projection.main_summary_audit_drift",
                "message": (
                    "main-account summary differs from its sealed plan: "
                    + ", ".join(main_summary_drift)
                ),
                "path": "main_summary",
                "severity": "hard",
            }
        )
    main_entries = main_plan.get("entries") if isinstance(main_plan.get("entries"), list) else []
    main_allocations = main_plan.get("entry_allocations_pct") if isinstance(main_plan.get("entry_allocations_pct"), list) else []
    if main_plan.get("plan_state") != "observe" and (
        len(main_entries) != 4
        or len(main_allocations) != 4
        or any(Decimal(str(value)) != Decimal("25") for value in main_allocations)
        or main_plan.get("position_notional_usdt") in {None, 0}
        or Decimal(str(main_plan.get("leverage", 0))) != Decimal("5")
        or any(field not in main_plan for field in ("stop", "tp1", "final_take_profit", "counter_claim_id", "invalidation_claim_id", "scenario_ids"))
    ):
        defects.append({"code": "report_projection.main_typed_plan_incomplete", "message": "main account must retain its typed four-stage position, risk, counterevidence, invalidation and scenarios", "path": "audit.main_plan", "severity": "hard"})
    if main_plan.get("plan_state") == "observe" and (
        main_entries
        or main_allocations
        or main_plan.get("position_notional_usdt") not in {None, 0}
        or any(main_plan.get(field) is not None for field in ("leverage", "entry_zone_basis", "stop_basis", "stop", "tp1", "final_take_profit"))
    ):
        defects.append({"code": "report_projection.main_observe_fabrication", "message": "an observing main account must not project position or price fields", "path": "audit.main_plan", "severity": "hard"})
    maker_summary = model.get("maker_summary") if isinstance(model.get("maker_summary"), dict) else {}
    probability_projection = (
        audit.get("entry_reach_probability_projection")
        if isinstance(audit.get("entry_reach_probability_projection"), dict)
        else {}
    )
    try:
        _entry_reach_probability_display(probability_projection)
    except ValueError as exc:
        defects.append(
            {
                "code": "report_projection.entry_reach_probability_invalid",
                "message": str(exc),
                "path": "audit.entry_reach_probability_projection",
                "severity": "hard",
            }
        )
    if (
        maker_summary.get("entry_reach_probability")
        != probability_projection.get("value_pct")
        or maker_summary.get("entry_reach_probability_applicability")
        != probability_projection.get("applicability")
        or maker_summary.get("entry_reach_probability_reason_code")
        != probability_projection.get("reason_code")
    ):
        defects.append(
            {
                "code": "report_projection.entry_reach_probability_drift",
                "message": "Maker summary must exactly project the typed entry-price-reach probability applicability contract",
                "path": "maker_summary.entry_reach_probability",
                "severity": "hard",
            }
        )
    lifecycle = (
        audit.get("order_lifecycle")
        if isinstance(audit.get("order_lifecycle"), dict)
        else {}
    )
    try:
        _order_lifecycle_display(lifecycle)
    except ValueError as exc:
        defects.append(
            {
                "code": "report_projection.order_lifecycle_invalid",
                "message": str(exc),
                "path": "audit.order_lifecycle",
                "severity": "hard",
            }
        )
    if (
        maker_summary.get("order_lifecycle_state") != lifecycle.get("state")
        or maker_summary.get("legal_fill_path_exists")
        is not lifecycle.get("legal_fill_path_exists")
        or maker_summary.get("actual_fill_probability") is not None
    ):
        defects.append(
            {
                "code": "report_projection.order_lifecycle_drift",
                "message": "Maker summary must preserve the typed lifecycle and must not invent fill probability",
                "path": "maker_summary.order_lifecycle_state",
                "severity": "hard",
            }
        )
    semantic_projection = (
        contract.get("semantic_projection_contract")
        if isinstance(contract.get("semantic_projection_contract"), dict)
        else {}
    )
    signal_dispositions = (
        (audit.get("winrate_rubric") or {}).get("signal_dispositions")
        if isinstance(audit.get("winrate_rubric"), dict)
        else []
    )
    if semantic_projection.get("secondary_signal_disposition_reason_must_be_visible") is True:
        if (
            not isinstance(signal_dispositions, list)
            or len(signal_dispositions) != 2
            or any(
                not isinstance(item, dict)
                or not str(item.get("signal_label") or "").strip()
                or not str(item.get("typed_value_text") or "").strip()
                or not str(item.get("disposition_text") or "").strip()
                or not str(item.get("reason_text") or "").strip()
                for item in signal_dispositions
            )
        ):
            defects.append({"code": "report_projection.signal_disposition_hidden", "message": "ETF and fundamental signal dispositions require typed values and closed visible reasons", "path": "audit.winrate_rubric.signal_dispositions", "severity": "hard"})
    rejected_scenarios = audit.get("rejected_candidate_risk_scenarios")
    rejected_recalculation = (
        audit.get("rejected_candidate_risk_recalculation")
        if isinstance(audit.get("rejected_candidate_risk_recalculation"), dict)
        else {}
    )
    risk_plan = audit.get("risk_plan") if isinstance(audit.get("risk_plan"), dict) else {}
    if semantic_state in {
        REJECTED_SUBMITTED_CANDIDATE,
        DIRECTIONAL_THESIS_ONLY,
        NON_DIRECTIONAL_OBSERVATION,
    }:
        failure_codes = maker_summary.get("constructibility_failure_codes")
        reason_explanations = maker_summary.get("constructibility_reason_explanations")
        plan_reason_explanations = maker_summary.get("plan_reason_explanations")
        if (
            not isinstance(failure_codes, list)
            or not isinstance(reason_explanations, list)
            or len(reason_explanations) != max(1, len(failure_codes))
        ):
            defects.append({"code": "report_projection.constructibility_failures_hidden", "message": "rejected Maker reports must retain every ordered constructibility reason", "path": "maker_summary.constructibility_reason_explanations", "severity": "hard"})
        expected_plan_reasons = (
            list(reason_explanations)
            if isinstance(failure_codes, list) and failure_codes
            else []
        )
        if maker_summary.get("threshold_eligible") is False:
            expected_plan_reasons.append(THRESHOLD_INELIGIBLE_CN)
        if plan_reason_explanations != expected_plan_reasons:
            defects.append({"code": "report_projection.plan_reasons_hidden", "message": "rejected Maker reports must expose both ordered constructibility failures and threshold ineligibility", "path": "maker_summary.plan_reason_explanations", "severity": "hard"})
        if audit.get("risk_scenarios"):
            defects.append({"code": "report_projection.rejected_risk_mixed_with_qualified", "message": "rejected candidate scenarios must not reuse the qualified risk_scenarios channel", "path": "audit.risk_scenarios", "severity": "hard"})
        recalculation_status = rejected_recalculation.get("status")
        recalculation_reason = rejected_recalculation.get("reason_code")
        if (
            REJECTED_RISK_RECALCULATION_STATES.get(str(recalculation_status))
            != recalculation_reason
        ):
            defects.append({"code": "report_projection.rejected_risk_status_invalid", "message": "rejected risk projection requires a closed recalculation status and reason", "path": "audit.rejected_candidate_risk_recalculation", "severity": "hard"})
        elif (
            semantic_state == REJECTED_SUBMITTED_CANDIDATE
            and risk_plan
            and recalculation_status == "recalculated"
        ):
            if (
                semantic_projection.get("rejected_candidate_risk_values_must_be_visible_when_recalculable") is True
                and (not isinstance(rejected_scenarios, list) or not rejected_scenarios)
            ):
                defects.append({"code": "report_projection.rejected_risk_hidden", "message": "a rejected but recalculable risk input requires separate audit scenarios", "path": "audit.rejected_candidate_risk_scenarios", "severity": "hard"})
        elif (
            semantic_state == REJECTED_SUBMITTED_CANDIDATE
            and risk_plan
            and recalculation_status == "not_recalculable"
        ):
            if rejected_scenarios:
                defects.append({"code": "report_projection.unrecalculable_risk_has_scenarios", "message": "an unrecalculable rejected input cannot expose invented risk scenarios", "path": "audit.rejected_candidate_risk_scenarios", "severity": "hard"})
        elif (
            semantic_state
            in {DIRECTIONAL_THESIS_ONLY, NON_DIRECTIONAL_OBSERVATION}
            and not risk_plan
            and recalculation_status == "not_submitted"
        ):
            if rejected_scenarios or audit.get("defense_plan"):
                defects.append({"code": "report_projection.absent_risk_has_scenarios", "message": "an absent rejected risk input cannot expose scenarios", "path": "audit.rejected_candidate_risk_scenarios", "severity": "hard"})
        else:
            defects.append({"code": "report_projection.rejected_risk_status_mismatch", "message": "rejected risk input presence conflicts with recalculation status", "path": "audit.rejected_candidate_risk_recalculation", "severity": "hard"})
    elif semantic_state == QUALIFIED_CANDIDATE and (
        rejected_scenarios
        or rejected_recalculation.get("status") != "not_applicable"
        or rejected_recalculation.get("reason_code")
        != REJECTED_RISK_RECALCULATION_STATES["not_applicable"]
    ):
        defects.append({"code": "report_projection.qualified_plan_has_rejected_risk", "message": "a qualified Maker plan cannot expose rejected-candidate scenarios or a rejected-risk state", "path": "audit.rejected_candidate_risk_scenarios", "severity": "hard"})
    if semantic_state == QUALIFIED_CANDIDATE:
        plan = risk_plan
        entries = plan.get("entries") if isinstance(plan.get("entries"), list) else []
        allocations = plan.get("entry_allocations_pct") if isinstance(plan.get("entry_allocations_pct"), list) else []
        if (
            not 2 <= len(entries) <= 5
            or len(entries) != len(allocations)
            or sum(Decimal(str(value)) for value in allocations) != Decimal("100")
            or any(field not in plan for field in ("leverage", "tp1", "tp2", "stop"))
            or Decimal(str(plan.get("leverage", 0))) != Decimal("5")
            or maker_execution.get("position_notional_usdt") in {None, 0}
            or not audit.get("risk_scenarios")
            or not audit.get("defense_plan")
        ):
            defects.append({"code": "report_projection.qualified_plan_incomplete", "message": "qualified Maker plan must retain the full ladder, 100% allocation, position, 5x risk plan, TP/SL, defense and scenarios", "path": "audit.risk_plan", "severity": "hard"})
    risk_limits = audit.get("risk_limits") if isinstance(audit.get("risk_limits"), dict) else {}
    if (
        Decimal(str(risk_limits.get("main_account_maximum_nominal_risk_pct", -1)))
        != Decimal("8")
        or Decimal(str(risk_limits.get("maker_maximum_nominal_risk_pct", -1)))
        != Decimal("3")
    ):
        defects.append({"code": "report_projection.risk_limit_drift", "message": "report must preserve the independent 8% main-account and 3% Maker nominal-risk limits", "path": "audit.risk_limits", "severity": "hard"})
    main_risk_scenarios = audit.get("main_risk_scenarios") if isinstance(audit.get("main_risk_scenarios"), list) else []
    if main_plan.get("plan_state") != "observe" and (
        not main_risk_scenarios
        or max(Decimal(str(item.get("nominal_risk_pct", 999))) for item in main_risk_scenarios)
        > Decimal("8")
    ):
        defects.append({"code": "report_projection.main_risk_invalid", "message": "main-account fill scenarios must be present and remain at or below 8%", "path": "audit.main_risk_scenarios", "severity": "hard"})
    return {
        "gate": "human_reasoning_depth",
        "passed": not defects,
        "defects": defects,
        "facts": {
            "proof_block_count": len(proof),
            "source_explanation_count": len(explanations),
        },
    }


def evaluate_gold_template_fidelity(
    markdown: str,
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    defects: list[dict[str, str]] = []
    lines = markdown.splitlines()
    headings = [line for line in lines if re.match(r"^#{1,6}\s+", line)]
    h4_count = sum(1 for line in lines if line.startswith("#### "))
    bullet_count = sum(1 for line in lines if re.match(r"^\s*-\s+", line))
    nonempty_count = sum(1 for line in lines if line.strip())
    limits = contract.get("density_limits") or {}
    if len(headings) > int(limits.get("maximum_heading_count", 18)):
        defects.append({"code": "template.heading_overflow", "message": "report uses too many headings for the gold reading rhythm", "path": "markdown.headings", "severity": "hard"})
    if h4_count > int(limits.get("maximum_h4_count", 0)):
        defects.append({"code": "template.h4_forbidden", "message": "one-heading-per-claim projection is forbidden", "path": "markdown.headings", "severity": "hard"})
    bullet_ratio = bullet_count / max(nonempty_count, 1)
    if bullet_ratio > float(limits.get("maximum_bullet_ratio", 0.35)):
        defects.append({"code": "template.fragmentation", "message": "bullet fragmentation exceeds the gold presentation contract", "path": "markdown", "severity": "hard"})
    required_markers = (
        "**作者自查（内部审计，不进入 Notion 判断正文）**",
        "## ① 正文",
        "## 不能做",
        "## ② Maker 计划",
        "## ③ 后附",
        f"### A. 评分明细（{ORDERFLOW_SCORE_MAX}+{CHART_SCORE_MAX}）",
        "### B. 六源支持与底层作用",
        "### C. 人类可读推理证明链",
        "### D. 风险、情景与机械校验",
    )
    positions = []
    for marker in required_markers:
        try:
            positions.append(lines.index(marker))
        except ValueError:
            defects.append({"code": "template.marker_missing", "message": f"missing gold presentation marker: {marker}", "path": "markdown", "severity": "hard"})
    if len(positions) == len(required_markers) and positions != sorted(positions):
        defects.append({"code": "template.marker_order", "message": "gold presentation markers are out of order", "path": "markdown", "severity": "hard"})
    raw_patterns = (
        (r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", "template.raw_snake_case"),
        (r"\b[0-9a-f]{64}\b", "template.raw_sha256"),
        (r"(?:/|／)\s*70\b", "template.legacy_orderflow_denominator"),
        (r"补充指标（|补充判断｜", "template.generic_machine_label"),
        (
            r"\b(?:place_order|not_attempted|qualified|neutral|short|long|observe|blocked)\b",
            "template.raw_enum",
        ),
        (
            r"入场类型\s*[=：]\s*(?:left|right|not_applicable)\b",
            "template.raw_enum",
        ),
    )
    for pattern, code in raw_patterns:
        if re.search(pattern, markdown, re.I):
            defects.append({"code": code, "message": "machine-facing audit text leaked into the human report", "path": "markdown", "severity": "hard"})
    proof_section = ""
    if "### C. 人类可读推理证明链" in markdown and "### D. 风险、情景与机械校验" in markdown:
        proof_section = markdown.split("### C. 人类可读推理证明链", 1)[1].split(
            "### D. 风险、情景与机械校验",
            1,
        )[0]
    for marker in SCENARIO_DETAIL_MARKERS:
        count = markdown.count(marker)
        if count != 1:
            defects.append(
                {
                    "code": "template.scenario_projection_count",
                    "message": f"full scenario detail must appear exactly once in appendix D: {marker}",
                    "path": "markdown.appendix_risk_and_scenarios",
                    "severity": "hard",
                }
            )
        if marker in proof_section:
            defects.append(
                {
                    "code": "template.scenario_projection_duplicate",
                    "message": "appendix C may prove scenario mechanics but must not repeat the full scenario tree",
                    "path": "markdown.appendix_reasoning_proof",
                    "severity": "hard",
                }
            )
    for marker in (
        "**主账户当前最强反证**：",
        "**主账户未来反证触发条件**：",
        "**主账户当前失效路径基线**：",
        "**主账户未来失效触发条件**：",
        "**Maker当前最强反证**：",
        "**Maker未来反证触发条件**：",
        "**Maker当前失效路径基线**：",
        "**Maker未来失效触发条件**：",
    ):
        if markdown.count(marker) != 1:
            defects.append(
                {
                    "code": "template.closure_projection_count",
                    "message": f"final closure marker must appear exactly once in appendix D: {marker}",
                    "path": "markdown.appendix_risk_and_scenarios",
                    "severity": "hard",
                }
            )
    return {
        "gate": "gold_template_fidelity",
        "passed": not defects,
        "defects": defects,
        "facts": {
            "heading_count": len(headings),
            "h4_count": h4_count,
            "bullet_count": bullet_count,
            "nonempty_line_count": nonempty_count,
            "bullet_ratio": round(bullet_ratio, 4),
        },
    }


def run_compatibility_lint(report_path: Path, *, root: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(root / "outputs" / "report_lint.py"),
        str(report_path),
        "--timeframe-contract",
        str(root / PRESENTATION_CONTRACT_PATH),
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output": output,
    }
