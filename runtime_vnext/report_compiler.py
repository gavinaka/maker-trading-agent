"""Pure in-memory projection of one certified vNext report IR.

This module deliberately has no filesystem, policy-loader, subprocess, raw
evidence/reasoning/decision, or trading-math dependency.  All semantic
certification happens in :mod:`runtime_vnext.validation.report`; persistence
and image rendering belong to the controller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .domain_ir import (
    CertifiedReportProjectionInput,
    ProjectedReport,
    ReportField,
    ReportRecord,
    ReportValue,
    project_blockbeats_cards_spec,
    project_canonical_report_model,
    to_plain,
)
_SLOT_LABELS = {
    "morning": "早间",
    "midday": "午间",
    "evening": "晚间",
}
_DIRECTION_LABELS = {
    "long": "偏多",
    "short": "偏空",
    "neutral": "中性",
    "observe": "观察",
    "blocked": "阻断",
}
_PLAN_STATE_LABELS = {
    "new": "新计划",
    "qualified": "合格候选",
    "rejected": "被拒候选",
    "observe": "仅观察",
    "blocked": "阻断",
    "not_applicable": "不适用",
}
_ENTRY_TYPE_LABELS = {
    "left": "左侧",
    "right": "右侧",
    "not_applicable": "不适用",
}
_VALUE_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "inflow": "净流入",
    "outflow": "净流出",
    "confirm": "确认",
    "confirmed": "确认",
    "down": "下行",
    "up": "上行",
    "negative": "负值",
    "positive": "正值",
    "intact": "保持有效",
    "not_attempted": "未尝试真实执行",
    "place_order": "仅按本轮认证授权处理",
}
_OWNER_LABELS = {
    "obs_tv": "TradingView",
    "obs_fs": "Farside",
    "obs_cg": "Coinglass",
    "obs_exo": "Exocharts",
}
_FIELD_LABELS = {
    "timeframes.1d.structure": "1D结构",
    "timeframes.4h.structure": "4H结构",
    "timeframes.1h.structure": "1H结构",
    "timeframes.15m.structure": "15m结构",
    "flow_direction": "ETF流向",
    "final_direction": "最终主判",
    "pivot.anchor_reset": "是否重置新锚",
    "cross_check_result": "交叉核验",
}
_CHART_COMPONENT_LABELS = {
    "chart.support_resistance": "支撑阻力",
    "chart.liquidity_hunt": "流动性猎杀",
    "chart.sma20_interaction": "SMA20互动",
    "chart.volume_price": "量价",
    "chart.fibonacci_trendline": "斐波那契/趋势线",
}
_PROFILE_ROLE_LABELS = {
    "value_area": "价值区",
    "poc_zone": "成交量重心区",
    "hvn_zone": "高成交量区",
    "lvn_zone": "低成交量区",
}
_SCENARIO_LABELS = {
    ("main", "base"): "主账户基准情景",
    ("main", "counter"): "主账户反证情景",
    ("main", "invalidation"): "主账户失效情景",
    ("maker", "base"): "Maker基准情景",
    ("maker", "counter"): "Maker反证情景",
    ("maker", "invalidation"): "Maker失效情景",
}
_CLAIM_TYPE_LABELS = {
    "fundamental_context": "基本面背景",
    "orderflow_interpretation": "订单流主判",
    "chart_interpretation": "多周期盘面",
    "fundamental_event_realization": "事件兑现核验",
    "fundamental_price_realization": "基本面与价格兑现",
    "etf_confirmation": "ETF确认",
    "liquidation_confirmation": "清算图辅助确认",
    "liquidity_hunt": "流动性猎杀假设",
    "market_regime": "市场阶段",
    "strongest_counterevidence": "最强反证",
    "invalidation_path": "失效路径",
    "main_account_thesis": "主账户论点",
    "maker_thesis": "Maker论点",
    "cannot_do": "禁止动作",
}


def _freeze(value: Any, *, path: str) -> ReportValue:
    if isinstance(value, Mapping):
        return _freeze_record(value, path=path)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise TypeError(f"unsupported projected report value at {path}")


def _freeze_record(value: Mapping[str, Any], *, path: str) -> ReportRecord:
    return ReportRecord(
        tuple(
            ReportField(str(key), _freeze(item, path=f"{path}.{key}"))
            for key, item in value.items()
        )
    )


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _text(value: Any, fallback: str = "未提供") -> str:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "是" if value else "否"
    rendered = str(value).strip()
    return rendered or fallback


def _number(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return _text(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        rendered = f"{value:.8f}".rstrip("0").rstrip(".")
        return rendered or "0"
    return _text(value)


def _display_decimal(value: Any, *, places: int = 2) -> str:
    """Round only the human projection; never feed this value back into risk."""

    try:
        quantum = Decimal("1").scaleb(-places)
        rendered = Decimal(str(value)).quantize(quantum)
    except (InvalidOperation, TypeError, ValueError):
        return _number(value)
    return format(rendered, "f").rstrip("0").rstrip(".") or "0"


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    return _VALUE_LABELS.get(str(value), _text(value))


def _timeframe(value: Any) -> str:
    code = str(value or "")
    return {"1d": "1D", "4h": "4H", "1h": "1H", "15m": "15m", "48h": "48H", "24h": "24H"}.get(
        code.lower(), _text(value)
    )


def _strip_terminal(value: Any) -> str:
    return _text(value).rstrip("。！？；;，,. ")


def _display_condition(value: Any) -> str:
    rendered = _text(value)
    for raw, visible in (
        ("bullish", "偏多"),
        ("bearish", "偏空"),
        ("inflow", "净流入"),
        ("outflow", "净流出"),
        ("confirm", "确认"),
    ):
        rendered = rendered.replace(raw, visible)
    return rendered


def _annotate_liquidity(value: Any, periods: str) -> str:
    rendered = _strip_terminal(value)
    if periods and any(
        marker in rendered
        for marker in ("清算密集", "流动性密集", "清算带", "猎杀位")
    ) and not any(period in rendered for period in periods.split("、")):
        return f"{rendered}（{periods}）"
    return rendered


def _list_numbers(value: Any) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return "未提供"
    return "、".join(_number(item) for item in value) or "未提供"


def _title(trading_date: str, slot: str) -> str:
    parts = trading_date.split("-")
    if len(parts) != 3 or slot not in _SLOT_LABELS:
        raise ValueError("certified report date or slot is not projectable")
    year, month, day = (int(item) for item in parts)
    return f"{year}.{month}.{day} {_SLOT_LABELS[slot]}日报"


def _claim_sentence(claim: Mapping[str, Any]) -> str:
    label = _CLAIM_TYPE_LABELS.get(str(claim.get("claim_type")), "认证判断")
    conclusion = _text(claim.get("conclusion"))
    invalidation = _text(claim.get("invalidation"))
    return f"**{label}**：{conclusion}。失效边界：{invalidation}。"


def _main_plan_lines(main: Mapping[str, Any]) -> list[str]:
    direction = _DIRECTION_LABELS.get(str(main.get("direction")), _text(main.get("direction")))
    plan_state = str(main.get("plan_state") or "observe")
    if plan_state in {"new", "iterate", "unchanged"}:
        plan_line = (
            f"主账户计划：{_text(main.get('exchange'))} {_text(main.get('instrument'))}，"
            f"计划名义持仓{_number(main.get('position_notional_usdt'))} USDT，杠杆{_number(main.get('leverage'))}x；"
            f"分档入场{_list_numbers(main.get('entries'))}，止损{_number(main.get('stop'))}，"
            f"第一止盈{_number(main.get('tp1'))}，最终止盈{_number(main.get('final_take_profit'))}。"
        )
    elif plan_state == "observe":
        plan_line = f"主账户保留做{'多' if main.get('direction') == 'long' else '空'}中线判断，但本轮计划状态为观察。"
    else:
        plan_line = "主账户当前没有可执行计划，不投影仓位、入场、止损或止盈几何。"
    return [
        f"主账户独立结论：{direction}；{_text(main.get('thesis'))}",
        plan_line,
        f"主账户最强反证：{_text(main.get('counter'))}",
        f"主账户失效路径：{_text(main.get('invalidation'))}",
    ]


def _risk_plan_lines(maker: Mapping[str, Any]) -> list[str]:
    semantic_state = str(
        maker.get("semantic_state") or maker.get("plan_state") or "observe"
    )
    if semantic_state == "rejected_submitted_candidate":
        return ["Maker风险计划：已提交方案未通过认证，前台不投影入场、仓位、止损、止盈或取消指令。"]
    if semantic_state == "directional_thesis_only":
        return ["Maker风险计划：本轮仅保留方向论点，风险与执行均不适用。"]
    if semantic_state != "qualified_candidate":
        return ["Maker风险计划：本轮无方向观察，风险与执行均不适用。"]
    risk = _record(maker.get("risk_plan"))
    if not risk:
        return ["Maker风险计划：当前认证状态没有可执行风险几何。"]
    entries = list(risk.get("entries") or [])
    ordered_entries = sorted(entries, key=lambda item: Decimal(str(item)))
    direction = "做多" if maker.get("direction") == "long" else "做空"
    entry_range = (
        f"{_number(ordered_entries[0])}–{_number(ordered_entries[-1])}"
        if ordered_entries
        else "未提供"
    )
    allocations = _list_numbers(risk.get("entry_allocations_pct"))
    return [
        (
            f"Maker风险计划：入场区间{entry_range}分档{direction}，各档{_list_numbers(entries)}，分配{allocations}%；"
            f"止损{_number(risk.get('stop'))}，TP1 {_number(risk.get('tp1'))}，"
            f"TP2 {_number(risk.get('tp2'))}，杠杆{_number(risk.get('leverage'))}x。"
        ),
        (
            f"未成交取消位：{_number(risk.get('cancel_before_fill'))}；"
            "该值与成交后止损分别来自已认证决策，报告不重新计算。"
        ),
    ]


def _maker_plan_lines(
    maker: Mapping[str, Any],
    frontstage: Mapping[str, Any],
) -> list[str]:
    semantic_state = str(
        maker.get("semantic_state") or maker.get("plan_state") or "observe"
    )
    if semantic_state == "qualified_candidate":
        heading = "### BTC（候选策略）"
        state_line = f"BTC（候选策略）：候选策略类型：{_text(maker.get('strategy_type'))}。"
        entry_type = _ENTRY_TYPE_LABELS.get(
            str(maker.get("entry_type")), _text(maker.get("entry_type"))
        )
        execution_line = (
            f"候选计划合同：{_text(maker.get('exchange'))} {_text(maker.get('instrument'))}，"
            f"{entry_type}{_text(maker.get('strategy_type'))}，{_text(maker.get('order_method'))}；"
            f"候选名义持仓{_number(maker.get('position_notional_usdt'))} USDT，"
            f"{entry_type}计划入场。"
        )
    elif semantic_state == "rejected_submitted_candidate":
        heading = "### BTC（未通过认证）"
        state_line = _text(frontstage.get("maker_execution"))
        execution_line = "本轮前台不展示被拒候选的入场、仓位或风险参数；完整中性审计见附录 D。"
    elif semantic_state == "directional_thesis_only":
        heading = "### BTC（方向论点）"
        state_line = _text(frontstage.get("maker_execution"))
        execution_line = "本轮未提交可执行计划，不展示入场、仓位或风险几何。"
    else:
        heading = "### BTC（无方向观察）"
        state_line = _text(
            frontstage.get("maker_execution"),
            "本轮无方向观察（风险与执行均不适用）",
        )
        execution_line = "本轮未提交可执行计划，不展示入场、仓位或风险几何。"
    lines = [heading, state_line, _text(frontstage.get("maker_execution_status"))]
    if semantic_state == "qualified_candidate":
        lines.insert(2, _text(frontstage.get("maker_execution")))
    lines.extend([execution_line, f"Maker独立结论：{_text(maker.get('thesis'))}"])
    if semantic_state != "non_directional_observation":
        lines.extend(
            [
                f"Maker最强反证：{_text(maker.get('counter'))}",
                f"Maker失效路径：{_text(maker.get('invalidation'))}",
            ]
        )
    lines.extend(_risk_plan_lines(maker))
    lifecycle = _record(maker.get("order_lifecycle"))
    if lifecycle and semantic_state == "qualified_candidate":
        lines.append(f"订单生命周期：{_text(maker.get('order_lifecycle_display'))}")
    return lines


def _defense_lines(maker: Mapping[str, Any]) -> list[str]:
    semantic_state = str(
        maker.get("semantic_state") or maker.get("plan_state") or "observe"
    )
    if semantic_state == "rejected_submitted_candidate":
        return [
            "第一层：无可执行 Maker 计划，第一层防守暂不触发。",
            "第二层：无可执行 Maker 计划，第二层防守暂不触发。",
        ]
    if semantic_state == "directional_thesis_only":
        return [
            "第一层：无可执行 Maker 计划，第一层防守暂不触发。",
            "第二层：无可执行 Maker 计划，第二层防守暂不触发。",
        ]
    if semantic_state != "qualified_candidate":
        return [
            "第一层：无可执行 Maker 计划，第一层防守暂不触发。",
            "第二层：无可执行 Maker 计划，第二层防守暂不触发。",
        ]
    defense = _record(maker.get("defense_plan"))
    if not defense:
        return [
            "第一层：当前没有已认证的可执行防守几何。",
            "第二层：当前没有已认证的可执行防守几何。",
        ]
    entries = list(_record(maker.get("risk_plan")).get("entries") or [])
    full = next(
        (
            row
            for row in _records(defense.get("trigger_scenarios"))
            if len(list(row.get("filled_level_indexes") or [])) == len(entries)
        ),
        {},
    )
    anchor = _record(defense.get("prefill_anchor")).get("weighted_fill")
    first = _number(full.get("first_trigger_price"))
    second = _number(full.get("second_trigger_price"))
    return [
        (
            f"第一层：触及{first}后，完整分档的预成交加权锚为{_number(anchor)}"
            f"（不是实际成交价，也不是单档价），第一层预成交投影价为{first}；"
            "实际成交后按实际加权成交价重新计算并替换该投影。"
            "只有随后形成并确认新的4H结构极点，才按该结构极点执行第一层止损。"
        ),
        (
            f"第二层：触及{second}后，完整分档的第二层预成交投影价为{second}；"
            "实际成交后按实际加权成交价重新计算并替换该投影。"
            "第二层只把剩余仓位止损移至实际加权成交价对应的保本损位置。"
        ),
    ]


def _source_line(source: str, row: Mapping[str, Any], display: Mapping[str, Any]) -> str:
    fact = _strip_terminal(row.get("fact"))
    metrics = _record(row.get("metrics"))
    if source == "BlockBeats":
        detail = f"事件窗口（小时）{_number(metrics.get('event_window_hours'))}，入选重要事件{_number(metrics.get('selected_event_count'))}条"
    elif source == "Coinglass":
        pivot = _record(metrics.get("pivot"))
        liquidation = _record(metrics.get("liquidation_map"))
        captured = "、".join(
            _timeframe(item) for item in liquidation.get("captured_timeframes") or []
        )
        fact = _annotate_liquidity(fact, captured)
        detail = (
            f"同一{_timeframe(pivot.get('timeframe'))}枢轴，价格{_value(metrics.get('price_direction'))}、"
            f"CVD{_value(metrics.get('cvd_direction'))}、OI{_value(metrics.get('oi_direction'))}，"
            f"订单流结论{_value(metrics.get('final_direction'))}；清算图周期：{captured or '未提供'}"
        )
    elif source == "Exocharts":
        ohlc = _record(metrics.get("ohlc"))
        detail = (
            f"开{_number(ohlc.get('open'))} 高{_number(ohlc.get('high'))} 低{_number(ohlc.get('low'))} 收{_number(ohlc.get('close'))}，"
            f"足迹交叉核验{_value(metrics.get('cross_check_result'))}"
        )
    elif source == "FedWatch":
        detail = f"当前概率{_compact_values(metrics.get('current_probabilities'))}；一日变化{_compact_values(metrics.get('change_1d'))}"
    elif source == "Farside":
        detail = f"最新完整日{_text(metrics.get('latest_complete_date'))}，净流{_number(metrics.get('latest_total_usd_m'))}百万美元，方向{_value(metrics.get('flow_direction'))}"
    elif source == "TradingView":
        labels = _record(_record(display.get("timeframe_display_contract")).get("canonical_by_code"))
        parts = []
        for code in ("1d", "4h", "1h", "15m"):
            state = _record(_record(metrics.get("timeframes")).get(code))
            if not state:
                continue
            label = labels.get(code) or _timeframe(code)
            if state.get("sma20") is None and code == "15m":
                sma = "SMA20 未采集（15m非必需）"
            elif state.get("sma20") is None:
                sma = "SMA20未采集"
            else:
                sma = f"SMA20 {_number(state.get('sma20'))}"
            parts.append(
                f"{label}价格{_number(state.get('price'))}、{sma}、结构{_value(state.get('structure'))}"
            )
        profile = _record(metrics.get("volume_profile"))
        if profile.get("status") == "readable":
            zones = "、".join(
                f"{_timeframe(zone.get('timeframe'))}{_PROFILE_ROLE_LABELS.get(str(zone.get('role')), '认证区域')}"
                f"{_number(zone.get('lower_bound'))}–{_number(zone.get('upper_bound'))}"
                for zone in _records(profile.get("zones"))
            )
            profile_detail = (
                f"用户手绘成交量分布可读：{zones or '认证区域未提供'}；"
                "只表达位置与概率，不单独决定方向"
            )
        else:
            profile_detail = (
                "用户手绘成交量分布本轮证据不足且不可读："
                f"{_strip_terminal(profile.get('reason'))}；不生成位置或概率"
            )
        detail = "；".join([*parts, profile_detail])
    else:
        detail = "已绑定当期证据"
    return f"**{source}**：{fact}。关键读数：{detail}。"


def _compact_values(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _text(value)
    labels = {"hold": "维持", "hike_25bp": "加息25bp"}
    return "、".join(
        f"{labels.get(str(key), _text(key))}={_number(item)}" for key, item in value.items()
    )


def _proof_lines(audit: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    coinglass = _record(
        _record(_record(audit.get("sources")).get("Coinglass")).get("metrics")
    )
    periods = "、".join(
        _timeframe(item)
        for item in _record(coinglass.get("liquidation_map")).get("captured_timeframes") or []
    )
    for chain in _records(audit.get("proof_chains")):
        account = {"main": "主账户", "maker": "Maker", "shared": "共享证据层"}.get(
            str(chain.get("account")), "共享证据层"
        )
        label = _CLAIM_TYPE_LABELS.get(str(chain.get("claim_type")), "认证判断")
        supports = "；".join(
            _annotate_liquidity(item, periods) for item in chain.get("support") or []
        )
        counters = "；".join(
            _annotate_liquidity(item, periods) for item in chain.get("counter") or []
        ) or "无额外反证边"
        lines.append(
            f"**{account}｜{label}**：{_annotate_liquidity(chain.get('conclusion'), periods)}。支持链：{supports}。反证链：{counters}。失效条件：{_annotate_liquidity(chain.get('invalidation'), periods)}。"
        )
    return lines


def _scenario_lines(audit: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for row in _records(audit.get("scenario_tree")):
        label = _SCENARIO_LABELS.get((str(row.get("account")), str(row.get("scenario_type"))), "认证情景")
        lines.append(
            f"**{label}**：触发条件为{_display_condition(row.get('condition'))}；预期路径为{_text(row.get('expected_path'))}；动作是{_text(row.get('action'))}。"
        )
    return lines


def _claim_by_id(audit: Mapping[str, Any], claim_id: Any) -> dict[str, Any]:
    return next(
        (
            claim
            for claim in _records(audit.get("claims"))
            if claim.get("id") == claim_id
        ),
        {},
    )


def _logic_text(value: Any) -> str:
    logic = _record(value)
    clauses: list[str] = []
    for clause in _records(logic.get("clauses")):
        owner = _OWNER_LABELS.get(str(clause.get("owner_id")), "认证来源")
        field = _FIELD_LABELS.get(str(clause.get("field")), "认证字段")
        operator = str(clause.get("operator") or "")
        connector = {
            "equals": "=",
            "becomes": "转为",
            "equals_at_trigger": "在触发时=",
        }.get(operator, "=")
        clauses.append(f"{owner}{field}{connector}{_value(clause.get('value'))}")
    joiner = "且" if logic.get("mode") == "all" else "或"
    return joiner.join(clauses) or "未提供"


def _control_lines(audit: Mapping[str, Any]) -> list[str]:
    controls = _record(audit.get("account_controls"))
    result: list[str] = []
    labels = {
        ("main", "counter"): ("主账户当前最强反证", "主账户未来反证触发条件"),
        ("main", "invalidation"): ("主账户当前失效路径基线", "主账户未来失效触发条件"),
        ("maker", "counter"): ("Maker当前最强反证", "Maker未来反证触发条件"),
        ("maker", "invalidation"): ("Maker当前失效路径基线", "Maker未来失效触发条件"),
    }
    for account, kind in (
        ("main", "counter"),
        ("main", "invalidation"),
        ("maker", "counter"),
        ("maker", "invalidation"),
    ):
        control = _record(_record(controls.get(account)).get(kind))
        claim = _claim_by_id(audit, control.get("claim_id"))
        current_label, future_label = labels[(account, kind)]
        result.extend(
            [
                f"**{current_label}**：{_logic_text(claim.get('current_basis'))}。",
                f"**{future_label}**：{_logic_text(claim.get('trigger_logic'))}。",
            ]
        )
    return result


def _risk_audit_lines(maker: Mapping[str, Any], audit: Mapping[str, Any]) -> list[str]:
    semantic_state = str(
        maker.get("semantic_state") or maker.get("plan_state") or "observe"
    )
    if semantic_state == "qualified_candidate":
        lines = [
            (
                f"**Maker成交情景**：{_text(row.get('filled_levels'))}；"
                f"加权入场{_display_decimal(row.get('entry'))}；"
                f"TP1盈亏比{_text(row.get('rr_to_tp1'))}，TP2盈亏比{_text(row.get('rr_to_tp2'))}；"
                f"名义风险{_text(row.get('nominal_risk_pct'))}%。"
            )
            for row in _records(audit.get("risk_scenarios"))
        ]
        lines.append(
            "风险验算：全部情景均达到1:2.5且不高于3%；该结论仅投影认证结果，报告层不重新计算。"
        )
        return lines
    if semantic_state != "rejected_submitted_candidate":
        return []
    recalculation = _record(audit.get("rejected_candidate_risk_recalculation"))
    status_text = {
        "recalculated": "已使用被拒方案保存的类型化输入完成只读审计复算",
        "not_recalculable": "候选风险输入未满足确定性复算前提",
        "not_submitted": "未提交风险方案",
        "not_applicable": "不适用",
    }.get(str(recalculation.get("status")), "审计状态未提供")
    lines = [
        "被拒候选机械结论（不可执行，不得用于下单）",
        f"被拒候选风险审计：{status_text}；所有结果仅用于审计。",
    ]
    risk = _record(maker.get("risk_plan"))
    lines.extend(
        [
            (
                "**被拒候选参数审计（不可执行，不得用于下单）**："
                f"候选名义持仓{_number(maker.get('position_notional_usdt'))} USDT；"
                f"入场{_list_numbers(risk.get('entries'))}，分配{_list_numbers(risk.get('entry_allocations_pct'))}%；"
                f"止损{_number(risk.get('stop'))}，TP1 {_number(risk.get('tp1'))}，"
                f"TP2 {_number(risk.get('tp2'))}，杠杆{_number(risk.get('leverage'))}x，"
                f"成交前取消位{_number(risk.get('cancel_before_fill'))}。"
            ),
            (
                "**被拒候选订单生命周期审计（不可执行，不得用于下单）**："
                f"{_text(maker.get('order_lifecycle_display'))}"
            ),
        ]
    )
    for row in _records(audit.get("rejected_candidate_risk_scenarios")):
        lines.append(
            f"**被拒候选风险情景（审计）**：{_text(row.get('filled_levels'))}；"
            f"加权入场{_display_decimal(row.get('entry'))}；名义风险{_text(row.get('nominal_risk_pct'))}%；"
            "不可执行，不得用于下单。"
        )
    return lines


def _trigger_value(
    audit: Mapping[str, Any],
    *,
    account: str,
    kind: str,
    owner_id: str,
    field: str,
) -> Any:
    control = _record(
        _record(_record(audit.get("account_controls")).get(account)).get(kind)
    )
    claim = _claim_by_id(audit, control.get("claim_id"))
    for clause in _records(_record(claim.get("trigger_logic")).get("clauses")):
        if clause.get("owner_id") == owner_id and clause.get("field") == field:
            return clause.get("value")
    return None


def _score_lines(maker: Mapping[str, Any], audit: Mapping[str, Any]) -> list[str]:
    sources = _record(audit.get("sources"))
    tv = _record(_record(sources.get("TradingView")).get("metrics"))
    tv_frames = _record(tv.get("timeframes"))
    farside = _record(_record(sources.get("Farside")).get("metrics"))
    coinglass = _record(_record(sources.get("Coinglass")).get("metrics"))
    main_tv_target = _trigger_value(
        audit,
        account="main",
        kind="counter",
        owner_id="obs_tv",
        field="timeframes.1d.structure",
    )
    main_flow_target = _trigger_value(
        audit,
        account="main",
        kind="counter",
        owner_id="obs_fs",
        field="flow_direction",
    )
    maker_orderflow_target = _trigger_value(
        audit,
        account="maker",
        kind="counter",
        owner_id="obs_cg",
        field="final_direction",
    )
    lines = [
        f"**盘口 {_number(maker.get('orderflow_score'))}／60**",
        f"TradingView 1D结构当前为{_value(_record(tv_frames.get('1d')).get('structure'))}，转为{_value(main_tv_target)}。",
        f"Farside ETF流向当前为{_value(farside.get('flow_direction'))}，转为{_value(main_flow_target)}。",
        f"TradingView15m结构={_value(_record(tv_frames.get('15m')).get('structure'))}。",
        f"Coinglass最终主判当前为{_value(coinglass.get('final_direction'))}，转为{_value(maker_orderflow_target)}。",
        f"组合{_text(maker.get('combination_id'))}。",
        f"盘面机会质量{_number(maker.get('chart_score'))}/30；总分{_number(maker.get('total_score'))}。",
    ]
    chart_components = _record(maker.get("chart_components"))
    if chart_components:
        lines.append(
            "盘面分项："
            + "、".join(
                f"{_CHART_COMPONENT_LABELS.get(code, '认证分项')}{_number(score)}"
                for code, score in chart_components.items()
            )
            + "。"
        )
    supports = _record(tv.get("chart_basis")).get("support_levels")
    lines.append(f"当前认证支撑={_list_numbers(supports)}。")
    probability = maker.get("entry_reach_probability")
    if probability is None:
        lines.append("入场到达概率：不适用。")
    else:
        lines.append(
            f"入场到达概率：{_number(probability)}%（仅描述到达计划区间的概率，不等同成交或盈利概率）。"
        )
    rubric = _record(maker.get("winrate_rubric"))
    if rubric:
        anchor = _number(rubric.get("anchor"))
        adjustments = _records(rubric.get("adjustments"))
        lines.append(f"置信度基准锚{anchor}%。")
        for adjustment in adjustments:
            lines.append(f"因此类型化调整={_number(adjustment.get('delta'))}个百分点。")
        lines.append(
            f"计划时置信度推导链（非回测命中率）为{_number(maker.get('win_rate'))}%。"
        )
        adjustment_text = "、".join(
            f"次因下调{_number(item.get('delta'))}个百分点"
            for item in adjustments
        ) or "次因无调整"
        lines.append(
            "胜率自估（计划时置信度，非回测命中率）："
            f"胜率基准锚{anchor}%→{adjustment_text}→落值{_number(maker.get('win_rate'))}%→"
            "与60%门槛比较；全部数值仅来自类型化评分合同。"
        )
    return lines


def render_combined_markdown(
    source: CertifiedReportProjectionInput,
    display_projection: Mapping[str, Any],
) -> str:
    """Render a certified typed IR without reopening any semantic owner."""

    if type(source) is not CertifiedReportProjectionInput:
        raise TypeError("report compiler accepts only CertifiedReportProjectionInput")
    if not isinstance(display_projection, Mapping):
        raise TypeError("display projection must be an in-memory mapping")
    model = project_canonical_report_model(source)
    frontstage = _record(model["frontstage"])
    main = _record(model["main_summary"])
    maker = _record(model["maker_summary"])
    audit = _record(model["audit"])
    sources = _record(audit.get("sources"))
    lines = [
        f"# {_title(model['trading_date'], model['slot'])}",
        "",
        f"> {_text(frontstage.get('opening_quote'), '以下判断仅来自本时段完整六源证据。')}",
        "> 作者自检：事实、判断与执行条件分层；主账户与 Maker 独立；风险数值逐项沿用认证决策。",
        "",
        "## ① 正文：基本面 × 盘口 × 盘面",
        "",
        "### 基本面",
        "",
        _text(frontstage.get("fundamentals")),
        "",
        "### 技术面",
        "",
        _text(frontstage.get("orderflow")),
        "",
        _text(frontstage.get("chart")),
        "",
        "### 解读",
        "",
        *_main_plan_lines(main),
        "",
        "### 趋势确认",
        "",
        _text(frontstage.get("multi_timeframe")),
        "",
        "### 日内支撑/压力",
        "",
        "主账户与 Maker 的支撑、压力及风险几何分别沿用各自认证决策，不在报告层重算。",
        "",
        "### 策略",
        "",
        _text(frontstage.get("main_authorization")),
        "",
        "主账户与 Maker 分离：两套判断共享事实层，但各自保留论点、反证、失效与授权边界，不强制共识。",
        "",
        "## 不能做",
        "",
        _text(frontstage.get("cannot_do")),
        "",
        "## ② Maker 计划",
        "",
        *_maker_plan_lines(
            maker,
            frontstage,
        ),
        "",
        *_defense_lines(maker),
        "",
        f"Maker授权边界：{_text(frontstage.get('maker_authorization'))}",
        "",
        f"连续性：{_text(frontstage.get('maker_continuity'))}",
        "",
        "## ③ 后附",
        "",
        "### A. 评分明细",
        "",
        *_score_lines(maker, audit),
        "",
        "### B. 六源证据",
        "",
    ]
    for source_name in ("BlockBeats", "Coinglass", "Exocharts", "FedWatch", "Farside", "TradingView"):
        lines.extend([_source_line(source_name, _record(sources.get(source_name)), display_projection), ""])
    lines.extend(
        [
            "### C. 人类可读推理证明链",
            "",
            *_proof_lines(audit),
            "",
            "### D. 风险、情景与机械校验",
            "",
            *_scenario_lines(audit),
            "",
            *_control_lines(audit),
            "",
            *_risk_audit_lines(maker, audit),
            "",
            "风险数值声明：以上入场、仓位、杠杆、止损、止盈、取消位与防守触发值均直接投影自已认证决策；compiler 未重新计算任何交易几何。",
            "",
        ]
    )
    return "\n".join(_text(line, "") for line in lines).rstrip() + "\n"


def compile_projected_report(
    source: CertifiedReportProjectionInput,
    display_projection: Mapping[str, Any],
) -> ProjectedReport:
    """Return all pure in-memory report projections for controller persistence."""

    model = project_canonical_report_model(source)
    cards_spec = project_blockbeats_cards_spec(source)
    markdown = render_combined_markdown(source, display_projection)
    return ProjectedReport(
        model=_freeze_record(model, path="model"),
        markdown=markdown,
        cards_spec=_freeze_record(cards_spec, path="cards_spec"),
    )


__all__ = ["compile_projected_report", "render_combined_markdown"]
