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
        risk_math = {
            "entry": _plain(entry),
            "stop": _plain(stop),
            "tp1": _plain(tp1),
            "risk_per_unit": _plain(risk),
            "reward_to_tp1": _plain(reward),
            "rr_to_tp1": round(float(rr), 6),
        }

    normalized = {
        "schema_version": "trading-decision-contract-v1",
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
        "plan": {"direction": direction, "risk_math": risk_math},
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
