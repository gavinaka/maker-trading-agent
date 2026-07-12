"""Canonical mechanical report lines bound to the deterministic decision contract."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from runtime.decision_contract import validate_contract_file
from runtime.pretrade_gate import (
    assert_transition_binding,
    pretrade_gate_required,
)
from runtime.state_store import atomic_json_write


ROOT = Path(__file__).resolve().parents[1]
def report_contract_required(trading_date: str, slot: str) -> bool:
    return pretrade_gate_required(trading_date, slot)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return {
        "path": resolved.relative_to(root.resolve()).as_posix(),
        "sha256": _sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _manifest_hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _plain_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def build_report_contract(
    trading_date: str,
    slot: str,
    *,
    decision_contract_path: Path,
    leverage: Decimal | int | str = Decimal("5"),
    root: Path = ROOT,
) -> dict[str, Any]:
    gate_contract, gate_contract_path = assert_transition_binding(
        trading_date, slot, root=root
    )
    gate = str(gate_contract["subjective_conclusion"])
    leverage_value = Decimal(str(leverage))
    if not leverage_value.is_finite() or leverage_value <= 0:
        raise ValueError("leverage must be a positive finite number")
    decision_path = decision_contract_path.resolve()
    decision_path.relative_to((root / "runtime_state" / trading_date).resolve())
    decision = validate_contract_file(decision_path, trading_date, slot, root=root)
    if decision.get("schema_version") == "trading-decision-contract-v3":
        plan_input = (decision.get("plan") or {}).get("input") or {}
        if "leverage" in plan_input:
            leverage_value = Decimal(str(plan_input["leverage"]))
    score = decision["score"]
    winrate = decision["winrate"]
    gate_label = "门禁" if slot == "morning" else "门禁沿用"
    gate_line = f"{gate_label}：{gate}"
    confidence_label = str(winrate.get("report_label") or "胜率自估")
    score_line = (
        f"盘口：{score['orderflow']}/70　盘面：{score['chart']}/30　"
        f"总分：{score['total']}　{confidence_label}：{winrate['final']}%"
    )
    risk_math = decision["plan"].get("risk_math")
    if decision.get("schema_version") == "trading-decision-contract-v3":
        plan = decision["plan"]
        if plan.get("entry_mode") == "conditional_zone":
            risk_line = (
                "风险验算：当前仅为条件观察区，不是可执行订单；"
                "必须确认后生成精确单价或分档价位并重新认证。"
            )
        elif plan.get("executable") is True and isinstance(risk_math, dict):
            scenario_count = int(risk_math["scenario_count"])
            worst_rr = Decimal(str(risk_math["worst_rr_to_tp1"]))
            worst_risk = Decimal(str(risk_math["worst_nominal_risk_pct"]))
            leverage_value = Decimal(str(plan["input"]["leverage"]))
            risk_line = (
                f"风险验算：{plan['entry_mode']}订单共{scenario_count}种非空成交情景，"
                f"最差TP1盈亏比1:{_plain_decimal(worst_rr)}，"
                f"最高{_plain_decimal(leverage_value)}倍杠杆名义风险"
                f"{_plain_decimal(worst_risk)}%；全部情景均达到1:2.5且不高于3%。"
            )
        else:
            risk_line = "风险验算：本时段无可执行 Maker 计划，名义风险为0。"
    elif isinstance(risk_math, dict):
        entry = Decimal(str(risk_math["entry"]))
        stop = Decimal(str(risk_math["stop"]))
        nominal_risk = (abs(entry - stop) / entry * leverage_value * Decimal("100")).quantize(
            Decimal("0.00001")
        )
        rr = Decimal(str(risk_math["rr_to_tp1"]))
        risk_line = (
            f"风险验算：代表入场{risk_math['entry']:,}、止损{risk_math['stop']:,}，"
            f"{_plain_decimal(leverage_value)}倍杠杆名义风险{_plain_decimal(nominal_risk)}%，"
            f"TP1盈亏比1:{_plain_decimal(rr)}，低于3%且达到1:2.5。"
        )
    else:
        risk_line = "风险验算：本时段无 Maker 计划，名义风险为0。"
    payload: dict[str, Any] = {
        "schema_version": "canonical-report-contract-v1",
        "status": "ready",
        "trading_date": trading_date,
        "slot": slot,
        "gate_summary": gate,
        "pretrade_gate_contract": _file_record(gate_contract_path, root),
        "leverage": _plain_decimal(leverage_value),
        "decision_contract": _file_record(decision_path, root),
        "lines": {
            "gate": gate_line,
            "score": score_line,
            "risk": risk_line,
        },
    }
    payload["manifest_sha256"] = _manifest_hash(payload)
    return payload


def manifest_path(trading_date: str, slot: str, *, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date / f"report_contract_{slot}.json"


def write_report_contract(
    trading_date: str,
    slot: str,
    **kwargs: Any,
) -> tuple[dict[str, Any], Path]:
    root = kwargs.get("root", ROOT)
    payload = build_report_contract(trading_date, slot, **kwargs)
    target = manifest_path(trading_date, slot, root=root)
    atomic_json_write(target, payload)
    return payload, target


def _normalized_report_lines(report: Path) -> list[str]:
    normalized = []
    for raw in report.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("> "):
            line = line[2:].strip()
        normalized.append(line)
    return normalized


def validate_report_contract_manifest(
    trading_date: str,
    slot: str,
    report: Path | None = None,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any] | None, Path | None]:
    if not report_contract_required(trading_date, slot):
        return None, None
    target = manifest_path(trading_date, slot, root=root)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "canonical-report-contract-v1"
        or set((payload.get("lines") or {}).keys()) != {"gate", "score", "risk"}
        or payload.get("status") != "ready"
        or payload.get("trading_date") != trading_date
        or payload.get("slot") != slot
        or payload.get("manifest_sha256") != _manifest_hash(payload)
    ):
        raise ValueError("canonical report contract manifest is invalid")
    gate_record = payload.get("pretrade_gate_contract") or {}
    gate_path = root / str(gate_record.get("path", ""))
    if not gate_path.is_file() or gate_record != _file_record(gate_path, root):
        raise ValueError("canonical report contract gate binding changed")
    assert_transition_binding(trading_date, slot, root=root)
    record = payload.get("decision_contract") or {}
    decision_path = root / str(record.get("path", ""))
    if not decision_path.is_file() or record.get("sha256") != _sha256_file(decision_path):
        raise ValueError("canonical report contract decision binding changed")
    validate_contract_file(decision_path, trading_date, slot, root=root)
    rebuilt = build_report_contract(
        trading_date,
        slot,
        decision_contract_path=decision_path,
        leverage=str(payload.get("leverage", "")),
        root=root,
    )
    if payload != rebuilt:
        raise ValueError("canonical report contract differs from deterministic rebuild")
    if report is not None:
        lines = _normalized_report_lines(report.resolve())
        for key, expected in (payload.get("lines") or {}).items():
            if lines.count(str(expected)) != 1:
                raise ValueError(
                    f"report must contain exactly one standalone canonical {key} line"
                )
    return payload, target
