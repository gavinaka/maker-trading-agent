"""Deterministically verify reasoning-derived score and Maker execution risk."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.reasoning_contract import validate_reasoning_contract_file


SLOTS = {"morning", "midday", "evening"}
SLOT_INDEX = {"morning": 0, "midday": 1, "evening": 2}
MAKER_EXECUTION_CUTOVER = ("2026-07-11", "evening")
REASONING_BOUND_V3_CUTOVER = ("2026-07-12", "midday")
MIN_RR = Decimal("2.5")
MAX_NOMINAL_RISK_PCT = Decimal("3")


def _at_or_after(trading_date: str, slot: str, cutover: tuple[str, str]) -> bool:
    return (trading_date, SLOT_INDEX[slot]) >= (cutover[0], SLOT_INDEX[cutover[1]])


def maker_execution_contract_required(trading_date: str, slot: str) -> bool:
    return _at_or_after(trading_date, slot, MAKER_EXECUTION_CUTOVER)


def reasoning_bound_contract_required(trading_date: str, slot: str) -> bool:
    return _at_or_after(trading_date, slot, REASONING_BOUND_V3_CUTOVER)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _plain(number: Decimal) -> int | float:
    value = float(number)
    return int(value) if value.is_integer() else value


def _hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("contract_sha256", None)
    return hashlib.sha256(
        json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _text(value: Any, field: str, minimum: int = 1) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < minimum:
        raise ValueError(f"{field} must contain at least {minimum} characters")
    return normalized


def _legacy_contract(payload: dict[str, Any]) -> dict[str, Any]:
    trading_date = str(payload.get("trading_date", ""))
    slot = payload.get("slot")
    score = payload.get("score") or {}
    orderflow = _decimal(score.get("orderflow"), "score.orderflow")
    chart = _decimal(score.get("chart"), "score.chart")
    if not Decimal("0") <= orderflow <= Decimal("70"):
        raise ValueError("score.orderflow must be between 0 and 70")
    if not Decimal("0") <= chart <= Decimal("30"):
        raise ValueError("score.chart must be between 0 and 30")
    total = orderflow + chart
    if score.get("total") is not None and _decimal(score["total"], "score.total") != total:
        raise ValueError("score.total does not equal orderflow + chart")
    winrate = payload.get("winrate") or {}
    anchor = _decimal(winrate.get("anchor"), "winrate.anchor")
    adjustments = winrate.get("adjustments") or []
    if not isinstance(adjustments, list):
        raise ValueError("winrate.adjustments must be an array")
    normalized_adjustments = []
    adjustment_total = Decimal("0")
    ids: set[str] = set()
    for index, item in enumerate(adjustments):
        if not isinstance(item, dict):
            raise ValueError(f"winrate.adjustments[{index}] must be an object")
        item_id = _text(item.get("id"), f"winrate.adjustments[{index}].id")
        if item_id in ids:
            raise ValueError("winrate adjustment ids must be unique")
        ids.add(item_id)
        evidence = _text(item.get("evidence"), f"winrate adjustment {item_id}.evidence")
        delta = _decimal(item.get("delta"), f"winrate adjustment {item_id}.delta")
        adjustment_total += delta
        normalized_adjustments.append(
            {"id": item_id, "delta": _plain(delta), "evidence": evidence}
        )
    final = anchor + adjustment_total
    if not Decimal("0") <= final <= Decimal("100"):
        raise ValueError("winrate final must be between 0 and 100")
    if winrate.get("final") is not None and _decimal(winrate["final"], "winrate.final") != final:
        raise ValueError("winrate.final does not equal anchor + adjustments")

    plan = payload.get("plan") or {}
    direction = str(plan.get("direction", "none")).lower()
    risk_math = None
    maker_execution = None
    if direction != "none":
        if direction not in {"long", "short"}:
            raise ValueError("plan.direction must be long, short or none")
        entry = _decimal(plan.get("entry"), "plan.entry")
        stop = _decimal(plan.get("stop"), "plan.stop")
        tp1 = _decimal(plan.get("tp1"), "plan.tp1")
        risk, reward, rr = _risk_reward(direction, entry, stop, tp1)
        if rr < MIN_RR:
            raise ValueError("plan TP1 reward/risk must be at least 2.5")
        risk_math = _scenario("single", direction, entry, stop, tp1, Decimal("1"))
        if maker_execution_contract_required(trading_date, slot):
            tp2 = _decimal(plan.get("tp2"), "plan.tp2")
            _validate_tp2(direction, tp1, tp2)
            if _decimal(plan.get("tp1_close_pct"), "plan.tp1_close_pct") != 50 or _decimal(
                plan.get("tp2_close_pct"), "plan.tp2_close_pct"
            ) != 50:
                raise ValueError("Maker position ledger requires TP1 50% and TP2 remaining 50%")
            sign = Decimal("1") if direction == "long" else Decimal("-1")
            first = entry + sign * Decimal("1.5") * risk
            second = entry + sign * Decimal("2") * risk
            if _decimal(plan.get("defense_first_trigger"), "plan.defense_first_trigger") != first:
                raise ValueError("plan.defense_first_trigger must equal entry +/- 1.5R")
            if _decimal(plan.get("defense_second_trigger"), "plan.defense_second_trigger") != second:
                raise ValueError("plan.defense_second_trigger must equal entry +/- 2R")
            maker_execution = {
                "tp2": _plain(tp2),
                "tp1_close_pct": 50,
                "tp2_close_pct": 50,
                "defense_first_trigger": _plain(first),
                "defense_first_stop_rule": _first_stop_rule(direction),
                "defense_first_cancel_additions": True,
                "defense_second_trigger": _plain(second),
                "defense_second_action": "move-stop-to-breakeven-only",
            }
    normalized: dict[str, Any] = {
        "schema_version": "trading-decision-contract-v2" if maker_execution_contract_required(trading_date, slot) else "trading-decision-contract-v1",
        "trading_date": trading_date,
        "slot": slot,
        "score": {
            "orderflow": _plain(orderflow),
            "chart": _plain(chart),
            "total": _plain(total),
            "formula": "orderflow(0..70)+chart(0..30)",
        },
        "winrate": {
            "anchor": _plain(anchor),
            "adjustments": normalized_adjustments,
            "adjustment_total": _plain(adjustment_total),
            "final": _plain(final),
        },
        "plan": {
            "direction": direction,
            "risk_math": risk_math,
            "maker_execution": maker_execution,
        },
    }
    normalized["contract_sha256"] = _hash(normalized)
    return normalized


def _first_stop_rule(direction: str) -> str:
    return (
        "post-entry-confirmed-4h-structure-low"
        if direction == "long"
        else "post-entry-confirmed-4h-structure-high"
    )


def _validate_tp2(direction: str, tp1: Decimal, tp2: Decimal) -> None:
    if tp2 <= 0 or (direction == "long" and tp2 <= tp1) or (
        direction == "short" and tp2 >= tp1
    ):
        raise ValueError("plan.tp2 is inconsistent with direction and TP1")


def _risk_reward(
    direction: str, entry: Decimal, stop: Decimal, tp1: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    if any(value <= 0 for value in (entry, stop, tp1)):
        raise ValueError("plan prices must be positive")
    risk = entry - stop if direction == "long" else stop - entry
    reward = tp1 - entry if direction == "long" else entry - tp1
    if risk <= 0 or reward <= 0:
        raise ValueError("plan stop/TP1 are inconsistent with direction")
    return risk, reward, reward / risk


def _scenario(
    scenario_id: str,
    direction: str,
    entry: Decimal,
    stop: Decimal,
    tp1: Decimal,
    leverage: Decimal,
    *,
    filled_level_ids: list[str] | None = None,
) -> dict[str, Any]:
    risk, reward, rr = _risk_reward(direction, entry, stop, tp1)
    nominal_risk_pct = abs(entry - stop) / entry * leverage * Decimal("100")
    if rr < MIN_RR:
        raise ValueError(f"Maker scenario {scenario_id} TP1 reward/risk is below 2.5")
    if nominal_risk_pct > MAX_NOMINAL_RISK_PCT:
        raise ValueError(f"Maker scenario {scenario_id} nominal risk exceeds 3%")
    return {
        "scenario_id": scenario_id,
        "filled_level_ids": filled_level_ids or ["single"],
        "entry": _plain(entry),
        "weighted_entry": _plain(entry),
        "stop": _plain(stop),
        "tp1": _plain(tp1),
        "risk_per_unit": _plain(risk),
        "reward_to_tp1": _plain(reward),
        "rr_to_tp1": round(float(rr), 6),
        "nominal_risk_pct": round(float(nominal_risk_pct), 6),
    }


def _validate_scenarios(scenarios: list[dict[str, Any]]) -> None:
    for item in scenarios:
        if _decimal(item["rr_to_tp1"], "scenario rr") < MIN_RR:
            raise ValueError(
                f"Maker scenario {item['scenario_id']} TP1 reward/risk is below 2.5"
            )
        if _decimal(item["nominal_risk_pct"], "scenario risk") > MAX_NOMINAL_RISK_PCT:
            raise ValueError(
                f"Maker scenario {item['scenario_id']} nominal risk exceeds 3%"
            )


def _normalize_levels(
    items: Any,
) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not 2 <= len(items) <= 5:
        raise ValueError("ladder entry_levels must contain 2 to 5 levels")
    normalized = []
    ids: set[str] = set()
    prices: set[Decimal] = set()
    allocation_total = Decimal("0")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"entry_levels[{index}] must be an object")
        level_id = _text(item.get("id"), f"entry_levels[{index}].id")
        if level_id in ids:
            raise ValueError("ladder level ids must be unique")
        ids.add(level_id)
        price = _decimal(item.get("price"), f"entry level {level_id}.price")
        allocation = _decimal(
            item.get("allocation_pct"), f"entry level {level_id}.allocation_pct"
        )
        if price <= 0 or allocation <= 0:
            raise ValueError("ladder price and allocation must be positive")
        if price in prices:
            raise ValueError("ladder level prices must be unique")
        prices.add(price)
        allocation_total += allocation
        normalized.append(
            {
                "id": level_id,
                "price": _plain(price),
                "allocation_pct": _plain(allocation),
            }
        )
    if allocation_total != Decimal("100"):
        raise ValueError("ladder allocations must total 100%")
    return normalized


def _ladder_scenarios(
    levels: list[dict[str, Any]],
    direction: str,
    stop: Decimal,
    tp1: Decimal,
    leverage: Decimal,
) -> list[dict[str, Any]]:
    scenarios = []
    for count in range(1, len(levels) + 1):
        for subset in itertools.combinations(levels, count):
            allocation = sum(
                (_decimal(item["allocation_pct"], "allocation") for item in subset),
                Decimal("0"),
            )
            weighted = sum(
                (
                    _decimal(item["price"], "level price")
                    * _decimal(item["allocation_pct"], "allocation")
                    for item in subset
                ),
                Decimal("0"),
            ) / allocation
            ids = [str(item["id"]) for item in subset]
            scenarios.append(
                _scenario(
                    "+".join(ids),
                    direction,
                    weighted,
                    stop,
                    tp1,
                    leverage,
                    filled_level_ids=ids,
                )
            )
    return scenarios


def _normalize_plan_v3(plan: Any, score: dict[str, Any], conviction: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    direction = str(plan.get("direction", "none")).lower()
    if direction not in {"none", "long", "short"}:
        raise ValueError("plan.direction must be long, short or none")
    if direction == "none":
        return {
            "input": {"direction": "none", "entry_mode": "none"},
            "direction": "none",
            "entry_mode": "none",
            "executable": False,
            "risk_math": None,
            "maker_execution": None,
        }
    entry_mode = str(plan.get("entry_mode", ""))
    if entry_mode not in {"single", "ladder", "conditional_zone"}:
        raise ValueError("directional plan requires single, ladder or conditional_zone")
    leverage = _decimal(plan.get("leverage"), "plan.leverage")
    if leverage != Decimal("5"):
        raise ValueError("Maker v3 requires fixed 5x leverage")
    exchange = str(plan.get("exchange", "")).upper()
    if exchange != "OKX":
        raise ValueError("Maker v3 requires exchange=OKX")
    instrument = str(plan.get("instrument", "")).upper()
    position_ranges = {
        "BTCUSDT": (Decimal("500"), Decimal("1000")),
        "ETHUSDT": (Decimal("300"), Decimal("800")),
    }
    if instrument not in position_ranges:
        raise ValueError("plan.instrument must be BTCUSDT or ETHUSDT")
    notional = _decimal(plan.get("position_notional_usdt"), "plan.position_notional_usdt")
    minimum_notional, maximum_notional = position_ranges[instrument]
    if not minimum_notional <= notional <= maximum_notional:
        raise ValueError("plan.position_notional_usdt is outside instrument policy")
    common_input: dict[str, Any] = {
        "direction": direction,
        "entry_mode": entry_mode,
        "exchange": exchange,
        "instrument": instrument,
        "leverage": _plain(leverage),
        "position_notional_usdt": _plain(notional),
    }
    if entry_mode == "conditional_zone":
        low = _decimal(plan.get("zone_low"), "plan.zone_low")
        high = _decimal(plan.get("zone_high"), "plan.zone_high")
        if low <= 0 or high <= low:
            raise ValueError("conditional zone requires positive zone_low < zone_high")
        common_input.update(
            {
                "zone_low": _plain(low),
                "zone_high": _plain(high),
                "confirmation_rule": _text(
                    plan.get("confirmation_rule"), "plan.confirmation_rule", 12
                ),
            }
        )
        return {
            "input": common_input,
            "direction": direction,
            "entry_mode": entry_mode,
            "executable": False,
            "execution_status": "awaiting_confirmation",
            "risk_math": {
                "status": "not_executable_until_exact_order_levels_are_certified"
            },
            "maker_execution": None,
        }
    if _decimal(score["total"], "score.total") < 65 or _decimal(
        conviction["final"], "conviction.final"
    ) < 60:
        raise ValueError("executable Maker plan violates score/conviction double gate")
    stop = _decimal(plan.get("stop"), "plan.stop")
    tp1 = _decimal(plan.get("tp1"), "plan.tp1")
    tp2 = _decimal(plan.get("tp2"), "plan.tp2")
    _validate_tp2(direction, tp1, tp2)
    if _decimal(plan.get("tp1_close_pct"), "plan.tp1_close_pct") != 50 or _decimal(
        plan.get("tp2_close_pct"), "plan.tp2_close_pct"
    ) != 50:
        raise ValueError("Maker position ledger requires TP1 50% and TP2 remaining 50%")
    common_input.update(
        {
            "stop": _plain(stop),
            "tp1": _plain(tp1),
            "tp2": _plain(tp2),
            "tp1_close_pct": 50,
            "tp2_close_pct": 50,
            "cancel_before_fill": _text(
                plan.get("cancel_before_fill"), "plan.cancel_before_fill", 8
            ),
        }
    )
    if entry_mode == "single":
        entry = _decimal(plan.get("entry"), "plan.entry")
        common_input["entry"] = _plain(entry)
        scenarios = [_scenario("single", direction, entry, stop, tp1, leverage)]
    else:
        levels = _normalize_levels(plan.get("entry_levels"))
        common_input["entry_levels"] = levels
        scenarios = _ladder_scenarios(levels, direction, stop, tp1, leverage)
    _validate_scenarios(scenarios)
    worst_rr = min(_decimal(item["rr_to_tp1"], "scenario rr") for item in scenarios)
    worst_risk = max(
        _decimal(item["nominal_risk_pct"], "scenario risk") for item in scenarios
    )
    if entry_mode == "single":
        scenario = scenarios[0]
        risk = _decimal(scenario["risk_per_unit"], "risk")
        entry = _decimal(scenario["weighted_entry"], "entry")
        sign = Decimal("1") if direction == "long" else Decimal("-1")
        first_trigger: int | float | None = _plain(entry + sign * Decimal("1.5") * risk)
        second_trigger: int | float | None = _plain(entry + sign * Decimal("2") * risk)
        activation_basis = "certified_single_entry"
    else:
        first_trigger = None
        second_trigger = None
        activation_basis = "actual_weighted_fill_required"
    return {
        "input": common_input,
        "direction": direction,
        "entry_mode": entry_mode,
        "executable": True,
        "execution_status": "certified",
        "risk_math": {
            "scenario_policy": "all_nonempty_fill_subsets",
            "scenario_count": len(scenarios),
            "scenarios": scenarios,
            "worst_rr_to_tp1": _plain(worst_rr),
            "worst_nominal_risk_pct": _plain(worst_risk),
            "max_nominal_risk_pct": 3,
            "min_rr_to_tp1": 2.5,
        },
        "maker_execution": {
            "tp2": _plain(tp2),
            "tp1_close_pct": 50,
            "tp2_close_pct": 50,
            "defense_trigger_basis": activation_basis,
            "defense_first_trigger": first_trigger,
            "defense_first_formula": "actual_weighted_fill +/- 1.5R",
            "defense_first_stop_rule": _first_stop_rule(direction),
            "defense_first_cancel_additions": True,
            "defense_second_trigger": second_trigger,
            "defense_second_formula": "actual_weighted_fill +/- 2R",
            "defense_second_action": "move-stop-to-breakeven-only",
        },
    }


def _v3_contract(
    payload: dict[str, Any],
    *,
    reasoning_contract_path: Path,
    root: Path,
) -> dict[str, Any]:
    trading_date = str(payload.get("trading_date", ""))
    slot = str(payload.get("slot", ""))
    reasoning_path = reasoning_contract_path.resolve()
    reasoning_path.relative_to((root / "runtime_state" / trading_date).resolve())
    reasoning = validate_reasoning_contract_file(
        reasoning_path, trading_date, slot, root=root
    )
    score = {
        "orderflow": reasoning["score"]["orderflow"]["value"],
        "chart": reasoning["score"]["chart"]["total"],
        "total": reasoning["score"]["total"],
        "formula": reasoning["score"]["formula"],
    }
    conviction = reasoning["conviction"]
    plan = _normalize_plan_v3(payload.get("plan"), score, conviction)
    normalized: dict[str, Any] = {
        "schema_version": "trading-decision-contract-v3",
        "trading_date": trading_date,
        "slot": slot,
        "reasoning_contract": {
            "path": reasoning_path.relative_to(root).as_posix(),
            "sha256": reasoning["contract_sha256"],
        },
        "score": score,
        "winrate": {
            "metric_kind": "plan_time_conviction",
            "calibrated_probability": False,
            "calibration_status": "insufficient_outcome_samples",
            "report_label": conviction["report_label"],
            "anchor": conviction["anchor"],
            "adjustments": conviction["adjustments"],
            "adjustment_total": conviction["adjustment_total"],
            "final": conviction["final"],
        },
        "plan": plan,
    }
    normalized["contract_sha256"] = _hash(normalized)
    return normalized


def build_contract(
    payload: dict[str, Any],
    *,
    reasoning_contract_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    trading_date = str(payload.get("trading_date", ""))
    slot = str(payload.get("slot", ""))
    if slot not in SLOTS:
        raise ValueError("slot must be morning, midday or evening")
    if reasoning_bound_contract_required(trading_date, slot):
        if reasoning_contract_path is None:
            raise ValueError("decision contract v3 requires reasoning contract")
        return _v3_contract(
            payload, reasoning_contract_path=reasoning_contract_path, root=root
        )
    return _legacy_contract(payload)


def validate_contract_file(
    path: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract_sha256") != _hash(payload):
        raise ValueError("decision contract hash mismatch")
    if payload.get("trading_date") != trading_date or payload.get("slot") != slot:
        raise ValueError("decision contract date/slot mismatch")
    if reasoning_bound_contract_required(trading_date, slot):
        if payload.get("schema_version") != "trading-decision-contract-v3":
            raise ValueError("decision contract v3 is required")
        reasoning_path = root / str((payload.get("reasoning_contract") or {}).get("path", ""))
        rebuilt = _v3_contract(
            {
                "trading_date": trading_date,
                "slot": slot,
                "plan": (payload.get("plan") or {}).get("input"),
            },
            reasoning_contract_path=reasoning_path,
            root=root,
        )
        if rebuilt != payload:
            raise ValueError("decision contract v3 differs from deterministic rebuild")
        return payload
    expected_schema = (
        "trading-decision-contract-v2"
        if maker_execution_contract_required(trading_date, slot)
        else "trading-decision-contract-v1"
    )
    if payload.get("schema_version") != expected_schema:
        if expected_schema.endswith("v2"):
            raise ValueError("decision contract v2 is required for Maker execution cutover")
        raise ValueError("decision contract v1 is required")
    expected = _legacy_contract(
        {
            "trading_date": trading_date,
            "slot": slot,
            "score": payload.get("score"),
            "winrate": payload.get("winrate"),
            "plan": _legacy_input_from_contract(payload),
        }
    )
    if expected != payload:
        raise ValueError("legacy decision contract differs from deterministic rebuild")
    return payload


def _legacy_input_from_contract(payload: dict[str, Any]) -> dict[str, Any]:
    plan = payload.get("plan") or {}
    direction = plan.get("direction", "none")
    if direction == "none":
        return {"direction": "none"}
    risk = plan.get("risk_math") or {}
    result: dict[str, Any] = {
        "direction": direction,
        "entry": risk.get("weighted_entry", risk.get("entry")),
        "stop": risk.get("stop"),
        "tp1": risk.get("tp1"),
    }
    execution = plan.get("maker_execution")
    if isinstance(execution, dict):
        result.update(
            {
                "tp2": execution.get("tp2"),
                "tp1_close_pct": execution.get("tp1_close_pct"),
                "tp2_close_pct": execution.get("tp2_close_pct"),
                "defense_first_trigger": execution.get("defense_first_trigger"),
                "defense_second_trigger": execution.get("defense_second_trigger"),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--reasoning-contract", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=tuple(sorted(SLOTS)))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("trading_date") != args.date or payload.get("slot") != args.slot:
        raise SystemExit("input date/slot mismatch")
    contract = build_contract(
        payload,
        reasoning_contract_path=args.reasoning_contract,
        root=ROOT,
    )
    output = args.output or (
        ROOT / "runtime_state" / args.date / f"decision_contract_{args.slot}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, output)
    print(
        json.dumps(
            {"status": "VALID", "output": str(output), "sha256": contract["contract_sha256"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
