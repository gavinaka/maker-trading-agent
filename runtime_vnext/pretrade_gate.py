"""Pure vNext production pretrade-gate contract.

This module validates caller-supplied facts only.  It never connects to Notion
or any other external service.  Shadow runs must not import, create, or consume
this contract; the controller enforces that boundary from the sealed run mode.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .methodology import canonical_sha256


SCHEMA_VERSION = "pretrade-gate-vnext-v1"
CONCLUSIONS = {"可交易", "不可交易"}
PHYSICAL_CONDITIONS = {"normal", "tired", "unwell"}
UUID_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.I,
)


def _parse_timezone_iso(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _gate_fields(
    *,
    emotion_stable: bool,
    rhythm_consistent: bool,
    result_dependency: bool,
    continuous_stop_loss_count: int,
    physical_condition: str,
) -> dict[str, Any]:
    if any(
        type(value) is not bool
        for value in (emotion_stable, rhythm_consistent, result_dependency)
    ):
        raise ValueError("pretrade gate boolean fields must be true or false")
    if (
        type(continuous_stop_loss_count) is not int
        or continuous_stop_loss_count < 0
    ):
        raise ValueError("continuous stop-loss count must be a non-negative integer")
    if physical_condition not in PHYSICAL_CONDITIONS:
        raise ValueError("unsupported physical condition")
    return {
        "emotion_stable": emotion_stable,
        "rhythm_consistent": rhythm_consistent,
        "result_dependency": result_dependency,
        "continuous_stop_loss_count": continuous_stop_loss_count,
        "physical_condition": physical_condition,
    }


def _blocking_fields(fields: dict[str, Any]) -> list[str]:
    blocked: list[str] = []
    if fields["emotion_stable"] is not True:
        blocked.append("emotion_stable")
    if fields["rhythm_consistent"] is not True:
        blocked.append("rhythm_consistent")
    if fields["result_dependency"] is not False:
        blocked.append("result_dependency")
    if fields["continuous_stop_loss_count"] >= 3:
        blocked.append("continuous_stop_loss_count")
    if fields["physical_condition"] != "normal":
        blocked.append("physical_condition")
    return blocked


def build_pretrade_gate_contract(
    trading_date: str,
    *,
    source_reference: str,
    source_observed_at: str,
    subjective_conclusion: str,
    emotion_stable: bool,
    rhythm_consistent: bool,
    result_dependency: bool,
    continuous_stop_loss_count: int,
    physical_condition: str,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build a production-only immutable contract from already supplied facts."""

    datetime.fromisoformat(trading_date)
    reference = source_reference.strip().lower()
    if not UUID_RE.fullmatch(reference):
        raise ValueError("pretrade gate source reference must be a UUID")
    observed = _parse_timezone_iso(source_observed_at, "source observed at")
    if observed.date().isoformat() != trading_date:
        raise ValueError("pretrade gate source observation must be from the trading date")
    recorded_text = recorded_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _parse_timezone_iso(recorded_text, "recorded at")
    if subjective_conclusion not in CONCLUSIONS:
        raise ValueError("unsupported subjective gate conclusion")
    fields = _gate_fields(
        emotion_stable=emotion_stable,
        rhythm_consistent=rhythm_consistent,
        result_dependency=result_dependency,
        continuous_stop_loss_count=continuous_stop_loss_count,
        physical_condition=physical_condition,
    )
    blocked = _blocking_fields(fields)
    if subjective_conclusion == "可交易" and blocked:
        raise ValueError(
            "subjective gate conclusion conflicts with blocking fields: "
            + ", ".join(blocked)
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "verified",
        "trading_date": trading_date,
        "source_slot": "morning",
        "source_kind": "notion_pretrade_gate",
        "provenance_mode": "live_notion_row",
        "source_reference": reference,
        "source_observed_at": source_observed_at.strip(),
        "recorded_at": recorded_text,
        "subjective_conclusion": subjective_conclusion,
        "allow_trade_today": subjective_conclusion == "可交易",
        "gate_fields": fields,
        "blocking_fields": blocked,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def validate_pretrade_gate_contract(
    payload: dict[str, Any],
    *,
    trading_date: str,
) -> dict[str, Any]:
    expected_fields = {
        "schema_version",
        "status",
        "trading_date",
        "source_slot",
        "source_kind",
        "provenance_mode",
        "source_reference",
        "source_observed_at",
        "recorded_at",
        "subjective_conclusion",
        "allow_trade_today",
        "gate_fields",
        "blocking_fields",
        "manifest_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise ValueError("vNext pretrade gate field set is invalid")
    fields = payload.get("gate_fields")
    if not isinstance(fields, dict):
        raise ValueError("vNext pretrade gate fields are invalid")
    rebuilt = build_pretrade_gate_contract(
        trading_date,
        source_reference=str(payload.get("source_reference", "")),
        source_observed_at=str(payload.get("source_observed_at", "")),
        subjective_conclusion=str(payload.get("subjective_conclusion", "")),
        emotion_stable=fields.get("emotion_stable"),
        rhythm_consistent=fields.get("rhythm_consistent"),
        result_dependency=fields.get("result_dependency"),
        continuous_stop_loss_count=fields.get("continuous_stop_loss_count"),
        physical_condition=str(fields.get("physical_condition", "")),
        recorded_at=str(payload.get("recorded_at", "")),
    )
    if payload != rebuilt or payload.get("manifest_sha256") != canonical_sha256(payload):
        raise ValueError("vNext pretrade gate is invalid or changed")
    return payload
