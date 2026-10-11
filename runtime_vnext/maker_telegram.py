"""Pure deterministic Maker-only Telegram projection.

The renderer accepts only the certified typed projection boundary.  It does
not read a report, a Notion page, a file, or ask a model to supply wording.
All Chinese labels and their order are a closed presentation contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from typing import Any, Mapping

from .domain_ir import CertifiedReportProjectionInput, to_plain


_STATE_LABELS = {
    "qualified_candidate": "候选计划",
    "rejected_submitted_candidate": "不做（候选未通过认证）",
    "directional_thesis_only": "不做（仅方向判断）",
    "non_directional_observation": "不做（观望）",
}
_SLOT_LABELS = {
    "morning": "早09：00",
    "midday": "午16：30",
    "evening": "晚20：30",
}
_ENTRY_TYPE_LABELS = {"left": "左侧", "right": "右侧"}
_FIRST_DEFENSE_RULE_LABELS = {
    "confirmed_post_fill_4h_structural_extreme": "成交后等待4小时结构极值确认",
}
_SECOND_DEFENSE_ACTION_LABELS = {
    "move_stop_to_breakeven_only": "仅将止损移至保本",
}
_MAX_MESSAGE_CHARS = 3900


@dataclass(frozen=True, slots=True)
class MakerTelegramMessage:
    """One sealed, human-readable Maker strategy notification."""

    text: str
    message_sha256: str
    evidence_snapshot_sha256: str
    reasoning_sha256: str
    decision_sha256: str
    methodology_sha256: str


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Maker Telegram projection requires {name} mapping")
    return value


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"Maker Telegram projection requires non-empty {name}")
    return value.strip()


def _number(value: Any, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"Maker Telegram projection requires numeric {name}")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Maker Telegram projection requires numeric {name}") from exc
    if not decimal.is_finite():
        raise ValueError(f"Maker Telegram projection requires finite {name}")
    return str(value)


def _percentage(value: Any, name: str) -> str:
    text = _number(value, name)
    decimal = Decimal(text)
    if not Decimal("0") <= decimal <= Decimal("100"):
        raise ValueError(f"Maker Telegram projection requires 0..100 {name}")
    return text


def _short_sha(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"Maker Telegram projection requires SHA-256 {name}")
    return text[:12]


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError(f"Maker Telegram projection requires numeric {name}")
    else:
        raw = _number(value, name)
    try:
        decimal = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Maker Telegram projection requires numeric {name}") from exc
    if not decimal.is_finite():
        raise ValueError(f"Maker Telegram projection requires finite {name}")
    return decimal


def _ratio(value: Any, name: str) -> str:
    decimal = _decimal(value, name)
    if decimal < Decimal("0"):
        raise ValueError(f"Maker Telegram projection requires non-negative {name}")
    rounded = decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".")


def _entry_range(entries: list[Any]) -> str:
    if not 2 <= len(entries) <= 5:
        raise ValueError("qualified Maker ladder must contain two to five levels")
    ordered = sorted(
        ((_decimal(value, f"maker.risk_plan.entries[{index}]"), value) for index, value in enumerate(entries)),
        key=lambda item: item[0],
    )
    return f"{_number(ordered[0][1], 'maker.risk_plan.entries[0]')}–{_number(ordered[-1][1], 'maker.risk_plan.entries[-1]')}"


def _risk_lines(maker: Mapping[str, Any], audit: Mapping[str, Any]) -> list[str]:
    risk_plan = _mapping(maker.get("risk_plan"), "maker.risk_plan")
    entries = risk_plan.get("entries")
    allocations = risk_plan.get("entry_allocations_pct")
    if not isinstance(entries, list) or not isinstance(allocations, list):
        raise ValueError("qualified Maker plan requires entry ladder")
    if len(entries) != len(allocations) or not 2 <= len(entries) <= 5:
        raise ValueError("qualified Maker ladder must contain two to five matched levels")
    allocation_values = [Decimal(_percentage(value, f"maker.risk_plan.entry_allocations_pct[{index}]")) for index, value in enumerate(allocations)]
    if sum(allocation_values) != Decimal("100"):
        raise ValueError("qualified Maker ladder allocations must total 100")

    ladder = " / ".join(
        f"{_number(price, f'maker.risk_plan.entries[{index}]')}（{_percentage(allocation, f'maker.risk_plan.entry_allocations_pct[{index}]')}%）"
        for index, (price, allocation) in enumerate(zip(entries, allocations, strict=True))
    )
    scenarios = audit.get("risk_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("qualified Maker plan requires certified risk scenarios")
    compact_scenarios: list[str] = []
    full_fill_rr: str | None = None
    for index, scenario in enumerate(scenarios):
        row = _mapping(scenario, f"audit.risk_scenarios[{index}]")
        filled_level_indexes = row.get("filled_level_indexes")
        if (
            not isinstance(filled_level_indexes, list)
            or not filled_level_indexes
            or not all(
                isinstance(level, int)
                and not isinstance(level, bool)
                and 1 <= level <= len(entries)
                for level in filled_level_indexes
            )
        ):
            raise ValueError("qualified Maker risk scenario requires valid filled_level_indexes")
        if len(set(filled_level_indexes)) != len(filled_level_indexes):
            raise ValueError("qualified Maker risk scenario cannot repeat filled level indexes")
        filled_levels = _text(
            row.get("filled_levels"), f"audit.risk_scenarios[{index}].filled_levels"
        )
        rr = _ratio(row.get("rr_to_tp1"), f"audit.risk_scenarios[{index}].rr_to_tp1")
        compact_scenarios.append(f"{filled_levels}档：1：{rr}")
        if len(filled_level_indexes) == len(entries):
            full_fill_rr = rr
    if full_fill_rr is None:
        raise ValueError("qualified Maker risk scenarios require full-fill R:R")
    return [
        f"入场梯度：{ladder}",
        (
            "止盈：TP1 "
            + _number(risk_plan.get("tp1"), "maker.risk_plan.tp1")
            + "（减仓"
            + _percentage(risk_plan.get("tp1_close_pct"), "maker.risk_plan.tp1_close_pct")
            + "%） / TP2 "
            + _number(risk_plan.get("tp2"), "maker.risk_plan.tp2")
            + "（减仓"
            + _percentage(risk_plan.get("tp2_close_pct"), "maker.risk_plan.tp2_close_pct")
            + "%）"
        ),
        f"止损：{_number(risk_plan.get('stop'), 'maker.risk_plan.stop')}",
        f"盈亏比（TP1，全成交）：1：{full_fill_rr}",
        "全成交组合校验：" + "；".join(compact_scenarios),
    ]


def _defense_lines(maker: Mapping[str, Any]) -> list[str]:
    defense = _mapping(maker.get("defense_plan"), "maker.defense_plan")
    prefill = _mapping(defense.get("prefill_anchor"), "maker.defense_plan.prefill_anchor")
    scenarios = defense.get("trigger_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("qualified Maker plan requires defense trigger scenarios")
    first_triggers: list[str] = []
    second_triggers: list[str] = []
    for index, scenario in enumerate(scenarios):
        row = _mapping(scenario, f"maker.defense_plan.trigger_scenarios[{index}]")
        levels = row.get("filled_level_indexes")
        if not isinstance(levels, list) or not all(isinstance(level, int) and not isinstance(level, bool) for level in levels):
            raise ValueError("defense scenario requires filled level indexes")
        label = "+".join(str(level) for level in levels) + "档"
        first_triggers.append(label + "→" + _number(row.get("first_trigger_price"), f"defense first trigger {index}"))
        second_triggers.append(label + "→" + _number(row.get("second_trigger_price"), f"defense second trigger {index}"))
    first_rule = _text(defense.get("first_stop_rule"), "maker.defense_plan.first_stop_rule")
    second_action = _text(defense.get("second_action"), "maker.defense_plan.second_action")
    if first_rule not in _FIRST_DEFENSE_RULE_LABELS:
        raise ValueError("unsupported Maker first defense rule")
    if second_action not in _SECOND_DEFENSE_ACTION_LABELS:
        raise ValueError("unsupported Maker second defense action")
    weighted_fill = _number(prefill.get("weighted_fill"), "maker.defense_plan.prefill_anchor.weighted_fill")
    return [
        "防守计划：",
        f"第一层：{_FIRST_DEFENSE_RULE_LABELS[first_rule]}；计划全成交均价{weighted_fill}；" + " / ".join(first_triggers),
        f"第二层：{_SECOND_DEFENSE_ACTION_LABELS[second_action]}；" + " / ".join(second_triggers),
    ]


def _candidate_lines(maker: Mapping[str, Any], audit: Mapping[str, Any]) -> list[str]:
    risk_plan = _mapping(maker.get("risk_plan"), "maker.risk_plan")
    entries = risk_plan.get("entries")
    if not isinstance(entries, list):
        raise ValueError("qualified Maker plan requires entry ladder")
    entry_type = _text(maker.get("entry_type"), "maker.entry_type")
    if entry_type not in _ENTRY_TYPE_LABELS:
        raise ValueError("unsupported Maker entry type")
    reach_probability = _percentage(
        maker.get("entry_reach_probability"), "maker.entry_reach_probability"
    )
    confidence = _percentage(maker.get("win_rate"), "maker.win_rate")
    instrument = _text(maker.get("instrument"), "maker.instrument")
    strategy_type = _text(maker.get("strategy_type"), "maker.strategy_type")
    exchange = _text(maker.get("exchange"), "maker.exchange")
    order_method = _text(maker.get("order_method"), "maker.order_method")
    notional = _number(maker.get("position_notional_usdt"), "maker.position_notional_usdt")
    leverage = _number(risk_plan.get("leverage"), "maker.risk_plan.leverage")
    lines = [
        f"{instrument}（策略）：执行概率{reach_probability}%　胜率自估{confidence}%（计划时置信度，非回测命中率）",
        (
            f"{strategy_type}：{_entry_range(entries)}　持仓（计划）{notional} USDT　"
            f"{exchange}　{_ENTRY_TYPE_LABELS[entry_type]}　{order_method}　杠杆{leverage}x"
        ),
    ]
    lines.extend(_risk_lines(maker, audit))
    lines.extend(_defense_lines(maker))
    lines.append(
        "注意事项：若价格优先触及"
        + _number(risk_plan.get("cancel_before_fill"), "maker.risk_plan.cancel_before_fill")
        + "（未成交取消价），则此策略取消。"
    )
    return lines


def _no_trade_lines(maker: Mapping[str, Any], state: str) -> list[str]:
    instrument = _text(maker.get("instrument"), "maker.instrument")
    constructibility = _text(
        maker.get("constructibility_reason"), "maker.constructibility_reason"
    )
    return [
        f"{instrument}（策略）：不做",
        f"认证状态：{_STATE_LABELS[state]}（{constructibility}）",
    ]


def _date_display(trading_date: str) -> str:
    parts = trading_date.split("-")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError("Maker Telegram projection requires ISO trading_date")
    return f"{int(parts[0])}.{int(parts[1])}.{int(parts[2])}"


def render_maker_telegram(source: CertifiedReportProjectionInput) -> MakerTelegramMessage:
    """Render one Maker card from a certified typed source and nothing else."""

    if type(source) is not CertifiedReportProjectionInput:
        raise TypeError("Maker Telegram projection accepts only CertifiedReportProjectionInput")
    plain = _mapping(to_plain(source), "certified source")
    metadata = _mapping(plain.get("metadata"), "metadata")
    maker = _mapping(plain.get("maker_summary"), "maker_summary")
    audit = _mapping(plain.get("audit"), "audit")
    state = _text(maker.get("semantic_state"), "maker.semantic_state")
    if state not in _STATE_LABELS:
        raise ValueError(f"unsupported Maker semantic state: {state}")
    slot = _text(metadata.get("slot"), "metadata.slot")
    if slot not in _SLOT_LABELS:
        raise ValueError(f"unsupported Maker slot: {slot}")
    run_mode = _text(metadata.get("run_mode"), "metadata.run_mode")
    if run_mode not in {"shadow", "production"}:
        raise ValueError("unsupported Maker run mode")

    _short_sha(metadata.get("evidence_snapshot_sha256"), "evidence_snapshot_sha256")
    _short_sha(metadata.get("reasoning_sha256"), "reasoning_sha256")
    _short_sha(metadata.get("decision_sha256"), "decision_sha256")
    _short_sha(metadata.get("methodology_sha256"), "methodology_sha256")
    cannot_do = _text(maker.get("cannot_do_code"), "maker.cannot_do_code")

    lines = [
        f"{_SLOT_LABELS[slot]}新增计划：",
        f"不能做：{cannot_do}",
    ]
    if state == "qualified_candidate":
        lines.extend(_candidate_lines(maker, audit))
    else:
        lines.extend(_no_trade_lines(maker, state))
    lines.extend(
        [
            "开仓理由：" + _text(maker.get("thesis"), "maker.thesis"),
            "最强反证：" + _text(maker.get("counter"), "maker.counter"),
            "失效条件：" + _text(maker.get("invalidation"), "maker.invalidation"),
        ]
    )
    text = "\n".join(lines)
    if len(text) > _MAX_MESSAGE_CHARS:
        raise ValueError("Maker Telegram message exceeds safe single-message limit")
    return MakerTelegramMessage(
        text=text,
        message_sha256=sha256(text.encode("utf-8")).hexdigest(),
        evidence_snapshot_sha256=_text(metadata.get("evidence_snapshot_sha256"), "evidence_snapshot_sha256"),
        reasoning_sha256=_text(metadata.get("reasoning_sha256"), "reasoning_sha256"),
        decision_sha256=_text(metadata.get("decision_sha256"), "decision_sha256"),
        methodology_sha256=_text(metadata.get("methodology_sha256"), "methodology_sha256"),
    )


def evaluate_maker_telegram_template(
    source: CertifiedReportProjectionInput,
    message: MakerTelegramMessage,
) -> dict[str, Any]:
    """Check the closed Maker user surface without judging trading quality."""

    if type(source) is not CertifiedReportProjectionInput or type(message) is not MakerTelegramMessage:
        raise TypeError("Maker template evaluation accepts only sealed typed values")
    plain = _mapping(to_plain(source), "certified source")
    metadata = _mapping(plain.get("metadata"), "metadata")
    maker = _mapping(plain.get("maker_summary"), "maker_summary")
    slot = _text(metadata.get("slot"), "metadata.slot")
    state = _text(maker.get("semantic_state"), "maker.semantic_state")
    defects: list[str] = []
    lines = message.text.splitlines()
    expected_header = f"{_SLOT_LABELS.get(slot, '')}新增计划："
    if len(lines) < 5 or lines[0] != expected_header:
        defects.append("maker.template.slot_header")
    if len(lines) < 2 or not lines[1].startswith("不能做：") or lines[1] == "不能做：":
        defects.append("maker.template.cannot_do")
    if state == "qualified_candidate":
        required = ("（策略）：执行概率", "入场梯度：", "止盈：", "止损：", "防守计划：", "注意事项：")
    else:
        required = ("（策略）：不做", "认证状态：")
    if any(not any(marker in line for line in lines) for marker in required):
        defects.append("maker.template.strategy_body")
    if any(not any(line.startswith(marker) for line in lines) for marker in ("开仓理由：", "最强反证：", "失效条件：")):
        defects.append("maker.template.reasoning_closure")
    # "全成交组合校验：" is a required handwritten Maker line.  Ban only
    # standalone operational/audit labels, never a legitimate strategy field
    # that happens to contain the word "校验".
    if any(
        any(line.startswith(marker) for line in lines)
        for marker in ("Maker｜", "执行边界：", "校验：", "订单状态：")
    ):
        defects.append("maker.template.non_manual_surface")
    return {
        "passed": not defects,
        "defects": defects,
        "facts": {
            "slot": slot,
            "semantic_state": state,
            "line_count": len(lines),
            "cannot_do_present": len(lines) >= 2 and lines[1].startswith("不能做："),
        },
    }
