"""Immutable same-day pretrade gate contract shared across report slots."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.state_store import atomic_json_write


ROOT = Path(__file__).resolve().parents[1]
FIRST_SLOT = ("2026-07-11", "evening")
SLOT_INDEX = {"morning": 0, "midday": 1, "evening": 2}
UUID_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.I,
)
CONCLUSIONS = {"可交易", "不可交易"}
PHYSICAL_CONDITIONS = {"normal", "tired", "unwell"}
PROVENANCE_MODES = {"live_notion_row", "maintenance_backfill"}


def pretrade_gate_required(trading_date: str, slot: str) -> bool:
    return (trading_date, SLOT_INDEX[slot]) >= (
        FIRST_SLOT[0],
        SLOT_INDEX[FIRST_SLOT[1]],
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _parse_iso(value: str | None, label: str, *, required: bool) -> str | None:
    if value is None or not value.strip():
        if required:
            raise ValueError(f"{label} is required")
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    return value.strip()


def _gate_fields(
    *,
    emotion_stable: bool,
    rhythm_consistent: bool,
    result_dependency: bool,
    continuous_stop_loss_count: int,
    physical_condition: str,
) -> dict[str, Any]:
    bools = {
        "emotion_stable": emotion_stable,
        "rhythm_consistent": rhythm_consistent,
        "result_dependency": result_dependency,
    }
    if any(type(value) is not bool for value in bools.values()):
        raise ValueError("pretrade gate boolean fields must be true or false")
    if type(continuous_stop_loss_count) is not int or continuous_stop_loss_count < 0:
        raise ValueError("continuous stop-loss count must be a non-negative integer")
    if physical_condition not in PHYSICAL_CONDITIONS:
        raise ValueError("unsupported physical condition")
    return {
        **bools,
        "continuous_stop_loss_count": continuous_stop_loss_count,
        "physical_condition": physical_condition,
    }


def _blocking_fields(fields: dict[str, Any]) -> list[str]:
    blocked = []
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
    source_observed_at: str | None,
    subjective_conclusion: str,
    emotion_stable: bool,
    rhythm_consistent: bool,
    result_dependency: bool,
    continuous_stop_loss_count: int,
    physical_condition: str,
    provenance_mode: str = "live_notion_row",
    backfill_reason: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    datetime.fromisoformat(trading_date)
    if provenance_mode not in PROVENANCE_MODES:
        raise ValueError("unsupported pretrade gate provenance mode")
    reference = source_reference.strip()
    if not UUID_RE.fullmatch(reference):
        raise ValueError("pretrade gate source reference must be a UUID")
    observed_at = _parse_iso(
        source_observed_at,
        "source observed at",
        required=provenance_mode == "live_notion_row",
    )
    reason = (backfill_reason or "").strip()
    if provenance_mode == "maintenance_backfill" and len(reason) < 8:
        raise ValueError("maintenance backfill requires an explicit reason")
    if provenance_mode == "live_notion_row" and reason:
        raise ValueError("live Notion gate records cannot contain a backfill reason")
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
        "schema_version": "pretrade-gate-contract-v1",
        "status": "verified",
        "trading_date": trading_date,
        "source_slot": "morning",
        "source_kind": "notion_pretrade_gate",
        "provenance_mode": provenance_mode,
        "source_reference": reference.lower(),
        "source_observed_at": observed_at,
        "recorded_at": recorded_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "subjective_conclusion": subjective_conclusion,
        "allow_trade_today": subjective_conclusion == "可交易",
        "gate_fields": fields,
        "blocking_fields": blocked,
        "backfill_reason": reason or None,
    }
    payload["manifest_sha256"] = _manifest_hash(payload)
    return payload


def manifest_path(trading_date: str, *, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date / "pretrade_gate.json"


def write_pretrade_gate_contract(
    trading_date: str,
    *,
    root: Path = ROOT,
    **kwargs: Any,
) -> tuple[dict[str, Any], Path]:
    target = manifest_path(trading_date, root=root)
    if target.exists():
        existing, _ = validate_pretrade_gate_contract(trading_date, root=root)
        requested = build_pretrade_gate_contract(
            trading_date,
            recorded_at=str(existing["recorded_at"]),
            **kwargs,
        )
        if existing != requested:
            raise ValueError("same-day pretrade gate contract is immutable")
        return existing, target
    payload = build_pretrade_gate_contract(trading_date, **kwargs)
    atomic_json_write(target, payload)
    return payload, target


def validate_pretrade_gate_contract(
    trading_date: str,
    slot: str | None = None,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    if slot is not None and slot not in SLOT_INDEX:
        raise ValueError(f"unsupported slot: {slot}")
    target = manifest_path(trading_date, root=root)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("pretrade gate contract must be a JSON object")
    rebuilt = build_pretrade_gate_contract(
        trading_date,
        source_reference=str(payload.get("source_reference", "")),
        source_observed_at=payload.get("source_observed_at"),
        subjective_conclusion=str(payload.get("subjective_conclusion", "")),
        emotion_stable=(payload.get("gate_fields") or {}).get("emotion_stable"),
        rhythm_consistent=(payload.get("gate_fields") or {}).get(
            "rhythm_consistent"
        ),
        result_dependency=(payload.get("gate_fields") or {}).get(
            "result_dependency"
        ),
        continuous_stop_loss_count=(payload.get("gate_fields") or {}).get(
            "continuous_stop_loss_count"
        ),
        physical_condition=str(
            (payload.get("gate_fields") or {}).get("physical_condition", "")
        ),
        provenance_mode=str(payload.get("provenance_mode", "")),
        backfill_reason=payload.get("backfill_reason"),
        recorded_at=str(payload.get("recorded_at", "")),
    )
    if payload != rebuilt or payload.get("manifest_sha256") != _manifest_hash(payload):
        raise ValueError("pretrade gate contract is invalid or changed")
    return payload, target


def transition_binding(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any] | None:
    if not pretrade_gate_required(trading_date, slot):
        return None
    payload, target = validate_pretrade_gate_contract(
        trading_date, slot, root=root
    )
    return {
        "path": target.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": _sha256_file(target),
        "manifest_sha256": payload["manifest_sha256"],
        "source_slot": payload["source_slot"],
        "subjective_conclusion": payload["subjective_conclusion"],
    }


def assert_transition_binding(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    payload, target = validate_pretrade_gate_contract(
        trading_date, slot, root=root
    )
    transition_path = root / "runtime_state" / trading_date / f"transition_{slot}.json"
    transition = json.loads(transition_path.read_text(encoding="utf-8"))
    if transition.get("pretrade_gate_contract") != transition_binding(
        trading_date, slot, root=root
    ):
        raise ValueError("transition pretrade gate binding is missing or stale")
    return payload, target
