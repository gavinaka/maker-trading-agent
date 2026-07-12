"""Deterministically verify score, win-rate adjustments and Maker risk math."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLOTS = {"morning", "midday", "evening"}
MAKER_EXECUTION_CUTOVER = ("2026-07-11", "evening")


def maker_execution_contract_required(trading_date: str, slot: str) -> bool:
    return (trading_date, {"morning": 0, "midday": 1, "evening": 2}[slot]) >= (
        MAKER_EXECUTION_CUTOVER[0],
        2,
    )


def _decimal(value, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _plain(number: Decimal):
    value = float(number)
    return int(value) if value.is_integer() else value


def build_contract(payload: dict) -> dict:
    trading_date = str(payload.get("trading_date", ""))
    slot = payload.get("slot")
    if slot not in SLOTS:
        raise ValueError("slot must be morning, midday or evening")
    score = payload.get("score") or {}
    orderflow = _decimal(score.get("orderflow"), "score.orderflow")
    chart = _decimal(score.get("chart"), "score.chart")
    if not Decimal("0") <= orderflow <= Decimal("70"):
        raise ValueError("score.orderflow must be between 0 and 70")
    if not Decimal("0") <= chart <= Decimal("30"):
        raise ValueError("score.chart must be between 0 and 30")
    total = orderflow + chart
    claimed_total = score.get("total")
    if claimed_total is not None and _decimal(claimed_total, "score.total") != total:
        raise ValueError("score.total does not equal orderflow + chart")

    winrate = payload.get("winrate") or {}
    anchor = _decimal(winrate.get("anchor"), "winrate.anchor")
    adjustments = winrate.get("adjustments") or []
    if not isinstance(adjustments, list):
        raise ValueError("winrate.adjustments must be an array")
    adjustment_total = Decimal("0")
    normalized_adjustments = []
    ids: set[str] = set()
    for index, item in enumerate(adjustments):
        if not isinstance(item, dict):
            raise ValueError(f"winrate.adjustments[{index}] must be an object")
        item_id = str(item.get("id", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if not item_id or item_id in ids:
            raise ValueError("winrate adjustment ids must be non-empty and unique")
        if not evidence:
            raise ValueError(f"winrate adjustment {item_id} requires evidence")
        ids.add(item_id)
        delta = _decimal(item.get("delta"), f"winrate.adjustments[{index}].delta")
        adjustment_total += delta
        normalized_adjustments.append({"id": item_id, "delta": _plain(delta), "evidence": evidence})
    final = anchor + adjustment_total
    if not Decimal("0") <= final <= Decimal("100"):
        raise ValueError("winrate final must be between 0 and 100")
    claimed_final = winrate.get("final")
    if claimed_final is not None and _decimal(claimed_final, "winrate.final") != final:
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
        if any(value <= 0 for value in (entry, stop, tp1)):
            raise ValueError("plan prices must be positive")
        risk = entry - stop if direction == "long" else stop - entry
        reward = tp1 - entry if direction == "long" else entry - tp1
        if risk <= 0 or reward <= 0:
            raise ValueError("plan stop/TP1 are inconsistent with direction")
        rr = reward / risk
        if rr < Decimal("2.5"):
            raise ValueError("plan TP1 reward/risk must be at least 2.5")
        risk_math = {
            "entry": _plain(entry),
            "stop": _plain(stop),
            "tp1": _plain(tp1),
            "risk_per_unit": _plain(risk),
            "reward_to_tp1": _plain(reward),
            "rr_to_tp1": round(float(rr), 6),
        }
        if maker_execution_contract_required(trading_date, slot):
            tp2 = _decimal(plan.get("tp2"), "plan.tp2")
            if tp2 <= 0 or (
                direction == "long" and tp2 <= tp1
            ) or (
                direction == "short" and tp2 >= tp1
            ):
                raise ValueError("plan.tp2 is inconsistent with direction and TP1")
            tp1_close_pct = _decimal(
                plan.get("tp1_close_pct"), "plan.tp1_close_pct"
            )
            tp2_close_pct = _decimal(
                plan.get("tp2_close_pct"), "plan.tp2_close_pct"
            )
            if tp1_close_pct != Decimal("50") or tp2_close_pct != Decimal("50"):
                raise ValueError(
                    "Maker position ledger requires TP1 50% and TP2 remaining 50%"
                )
            sign = Decimal("1") if direction == "long" else Decimal("-1")
            first_trigger = entry + sign * Decimal("1.5") * risk
            second_trigger = entry + sign * Decimal("2.0") * risk
            claimed_first = _decimal(
                plan.get("defense_first_trigger"), "plan.defense_first_trigger"
            )
            claimed_second = _decimal(
                plan.get("defense_second_trigger"), "plan.defense_second_trigger"
            )
            if claimed_first != first_trigger:
                raise ValueError("plan.defense_first_trigger must equal entry +/- 1.5R")
            if claimed_second != second_trigger:
                raise ValueError("plan.defense_second_trigger must equal entry +/- 2R")
            maker_execution = {
                "tp2": _plain(tp2),
                "tp1_close_pct": 50,
                "tp2_close_pct": 50,
                "defense_first_trigger": _plain(first_trigger),
                "defense_first_stop_rule": (
                    "post-entry-confirmed-4h-structure-low"
                    if direction == "long"
                    else "post-entry-confirmed-4h-structure-high"
                ),
                "defense_first_cancel_additions": True,
                "defense_second_trigger": _plain(second_trigger),
                "defense_second_action": "move-stop-to-breakeven-only",
            }

    normalized = {
        "schema_version": (
            "trading-decision-contract-v2"
            if maker_execution_contract_required(trading_date, slot)
            else "trading-decision-contract-v1"
        ),
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
    normalized["contract_sha256"] = hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return normalized


def validate_contract_file(path: Path, trading_date: str, slot: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_hash = payload.pop("contract_sha256", None)
    actual_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload["contract_sha256"] = expected_hash
    if expected_hash != actual_hash:
        raise ValueError("decision contract hash mismatch")
    if payload.get("trading_date") != trading_date or payload.get("slot") != slot:
        raise ValueError("decision contract date/slot mismatch")
    if maker_execution_contract_required(trading_date, slot):
        if payload.get("schema_version") != "trading-decision-contract-v2":
            raise ValueError("decision contract v2 is required for Maker execution cutover")
        plan = payload.get("plan") or {}
        direction = plan.get("direction")
        execution = plan.get("maker_execution")
        if direction != "none":
            if not isinstance(execution, dict):
                raise ValueError("decision contract v2 requires Maker execution binding")
            risk_math = plan.get("risk_math") or {}
            entry = _decimal(risk_math.get("entry"), "plan.risk_math.entry")
            risk = _decimal(
                risk_math.get("risk_per_unit"), "plan.risk_math.risk_per_unit"
            )
            sign = Decimal("1") if direction == "long" else Decimal("-1")
            expected_first = entry + sign * Decimal("1.5") * risk
            expected_second = entry + sign * Decimal("2.0") * risk
            if (
                _decimal(execution.get("tp1_close_pct"), "maker.tp1_close_pct")
                != Decimal("50")
                or _decimal(execution.get("tp2_close_pct"), "maker.tp2_close_pct")
                != Decimal("50")
            ):
                raise ValueError("decision contract Maker ledger binding changed")
            if _decimal(
                execution.get("defense_first_trigger"),
                "maker.defense_first_trigger",
            ) != expected_first or _decimal(
                execution.get("defense_second_trigger"),
                "maker.defense_second_trigger",
            ) != expected_second:
                raise ValueError("decision contract Maker defense trigger binding changed")
            if (
                execution.get("defense_first_cancel_additions") is not True
                or execution.get("defense_second_action")
                != "move-stop-to-breakeven-only"
            ):
                raise ValueError("decision contract Maker defense action binding changed")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=tuple(sorted(SLOTS)))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("trading_date") != args.date or payload.get("slot") != args.slot:
        raise SystemExit("input date/slot mismatch")
    contract = build_contract(payload)
    output = args.output or ROOT / "runtime_state" / args.date / f"decision_contract_{args.slot}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps({"status": "VALID", "output": str(output), "sha256": contract["contract_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
