"""Validate the learned 2026-06-22..26 reasoning method as typed data.

Historical reports never enter production.  This module validates only the
method and user-intent invariants distilled during maintenance.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,79}$")
VISIBLE_SECTIONS = {
    "opening_quote",
    "cannot_do",
    "fundamentals",
    "orderflow",
    "interpretation",
    "daily_line",
    "hourly_line",
    "trend_confirmation",
    "support_resistance",
    "strategy",
    "maker",
    "defense",
}
NUMERIC_UNITS = {
    "independent_synthesis",
    "same_pivot_orderflow",
    "footprint_cross_check",
    "multi_timeframe_transition",
    "volume_profile_liquidity",
    "etf_flow_relation",
}


def _text(value: Any, field: str, minimum: int = 1) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < minimum:
        raise ValueError(f"{field} must contain at least {minimum} characters")
    return normalized


def _id(value: Any, field: str) -> str:
    normalized = _text(value, field)
    if not ID_RE.fullmatch(normalized):
        raise ValueError(f"{field} has invalid identifier syntax")
    return normalized


def _decimal(value: Any, field: str) -> int | float:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    plain = float(number)
    return int(plain) if plain.is_integer() else plain


def _enum(value: Any, allowed: set[str], field: str) -> str:
    normalized = str(value or "")
    if normalized not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}")
    return normalized


def _combination_id(
    cvd: str,
    price: str,
    oi: str,
    funding_sign: str,
    policy: dict[str, Any],
) -> str:
    """Derive the canonical C01-C81 id from the four same-pivot states."""
    if policy.get("combination_dimension_order") != [
        "cvd", "price", "oi", "funding_sign"
    ]:
        raise ValueError("C01-C81 combination dimension order is unsupported")
    directions = [str(item) for item in policy["combination_direction_order"]]
    funding = [str(item) for item in policy["combination_funding_order"]]
    try:
        index = (
            ((directions.index(cvd) * 3 + directions.index(price)) * 3
             + directions.index(oi))
            * 3
            + funding.index(funding_sign)
            + 1
        )
    except ValueError as exc:
        raise ValueError("same-pivot state cannot be mapped to C01-C81") from exc
    return f"C{index:02d}"


def _normalize_effect_divergence(
    value: Any,
    *,
    cvd_direction: str,
    price_direction: str,
    policy: dict[str, Any],
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Coinglass effect_divergence must be an object")
    cvd_break = _enum(
        value.get("cvd_break"), set(policy["effect_cvd_breaks"]),
        "Coinglass effect_divergence.cvd_break",
    )
    price_confirmation = _enum(
        value.get("price_confirmation"),
        set(policy["effect_price_confirmations"]),
        "Coinglass effect_divergence.price_confirmation",
    )
    interpretation = _enum(
        value.get("interpretation"), set(policy["effect_interpretations"]),
        "Coinglass effect_divergence.interpretation",
    )
    if cvd_break == "higher_high" and cvd_direction != "up":
        raise ValueError("CVD higher_high requires cvd_direction=up")
    if cvd_break == "lower_low" and cvd_direction != "down":
        raise ValueError("CVD lower_low requires cvd_direction=down")
    if price_confirmation == "confirmed":
        if cvd_break == "higher_high" and price_direction != "up":
            raise ValueError("confirmed CVD higher_high requires price_direction=up")
        if cvd_break == "lower_low" and price_direction != "down":
            raise ValueError("confirmed CVD lower_low requires price_direction=down")
    expected = {
        ("higher_high", "not_confirmed"): "bearish",
        ("lower_low", "not_confirmed"): "bullish",
    }.get((cvd_break, price_confirmation), "none")
    if cvd_break == "ambiguous" or price_confirmation == "ambiguous":
        expected = "ambiguous"
    if interpretation != expected:
        raise ValueError(
            "effect divergence interpretation conflicts with CVD break and price confirmation"
        )
    return {
        "cvd_break": cvd_break,
        "price_confirmation": price_confirmation,
        "interpretation": interpretation,
    }


def _normalize_oi_price_context(
    value: Any,
    *,
    price_direction: str,
    oi_direction: str,
    price_break_status: str,
    policy: dict[str, Any],
) -> str:
    context = _enum(
        value, set(policy["oi_price_contexts"]), "Coinglass oi_price_context"
    )
    strict_pairs = {
        "new_long_expansion": ("up", "up"),
        "new_short_expansion": ("down", "up"),
        "short_cover_squeeze": ("up", "down"),
        "profit_taking_plus_spot_supply": ("up", "down"),
        "long_liquidation": ("down", "down"),
    }
    if context in strict_pairs and strict_pairs[context] != (
        price_direction,
        oi_direction,
    ):
        raise ValueError(
            f"oi_price_context={context} conflicts with price/OI directions"
        )
    if context == "position_reduction" and oi_direction != "down":
        raise ValueError("position_reduction requires oi_direction=down")
    if (price_direction, oi_direction) == ("up", "down"):
        expected_by_break = {
            "new_high_or_breakout": "short_cover_squeeze",
            "stalled_no_new_high": "profit_taking_plus_spot_supply",
            "ambiguous": "unclear",
        }
        expected = expected_by_break.get(price_break_status)
        if expected is None or context != expected:
            raise ValueError(
                "price-up/OI-down context must distinguish breakout squeeze from "
                "stalled profit-taking plus spot supply"
            )
    if context == "long_liquidation" and price_break_status not in {
        "new_low_or_breakdown", "ambiguous"
    }:
        raise ValueError(
            "long_liquidation requires a new-low/breakdown or explicitly ambiguous status"
        )
    return context


def _refs(value: Any, known: set[str], field: str, minimum: int = 1) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result: list[str] = []
    for raw in value:
        ref = str(raw)
        if ref not in known:
            raise ValueError(f"{field} references missing node: {ref}")
        if ref not in result:
            result.append(ref)
    if len(result) < minimum:
        raise ValueError(f"{field} requires at least {minimum} unique references")
    return result


def _claim_sources(
    claim_id: str,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
) -> set[str]:
    pending = [claim_id]
    seen: set[str] = set()
    sources: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        if node_id in observations:
            sources.add(str(observations[node_id]["source"]))
        elif node_id in claims:
            pending.extend(claims[node_id]["support_ids"])
    return sources


def _value_path_exists(values: Any, path: str) -> bool:
    current = values
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current not in (None, "", [], {})


def _normalize_source_methodology(
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Bind every source to its allowed judgment method and direct claim role."""
    roles = policy.get("source_roles")
    required_groups = policy.get("required_direct_source_groups")
    if not isinstance(roles, dict) or not isinstance(required_groups, dict):
        raise ValueError("gold methodology source-role policy is incomplete")

    by_source: dict[str, list[dict[str, Any]]] = {}
    for observation in observations.values():
        by_source.setdefault(str(observation["source"]), []).append(observation)

    normalized_roles: dict[str, Any] = {}
    for source, role in roles.items():
        if not isinstance(role, dict):
            raise ValueError(f"source role {source} must be an object")
        source_observations = by_source.get(source, [])
        if not source_observations:
            raise ValueError(f"source methodology missing observation: {source}")
        required_paths = role.get("required_value_paths")
        if not isinstance(required_paths, list) or not required_paths:
            raise ValueError(f"source role {source} lacks required_value_paths")
        for observation in source_observations:
            values = observation.get("values")
            for path in required_paths:
                if not _value_path_exists(values, str(path)):
                    raise ValueError(
                        f"source {source} missing required judgment value: {path}"
                    )
        allowed = role.get("direct_claim_types")
        if not isinstance(allowed, list) or not allowed:
            raise ValueError(f"source role {source} lacks direct_claim_types")
        for field in (
            "role", "judgment_standard", "evaluation_sequence", "conflict_rule",
            "missing_data_rule", "forbidden_inference", "score_bucket",
        ):
            if role.get(field) in (None, "", [], {}):
                raise ValueError(f"source role {source} lacks {field}")
        if role.get("single_variable_direction_flip") is not False:
            raise ValueError(
                f"source role {source} must forbid single-variable direction flips"
            )
        normalized_roles[source] = {
            "role": str(role["role"]),
            "judgment_standard": str(role["judgment_standard"]),
            "required_value_paths": [str(item) for item in required_paths],
            "evaluation_sequence": [str(item) for item in role["evaluation_sequence"]],
            "conflict_rule": str(role["conflict_rule"]),
            "missing_data_rule": str(role["missing_data_rule"]),
            "forbidden_inference": [str(item) for item in role["forbidden_inference"]],
            "direct_claim_types": [str(item) for item in allowed],
            "score_bucket": str(role["score_bucket"]),
            "single_variable_direction_flip": False,
        }

    direct_sources_by_type: dict[str, set[str]] = {}
    for claim_id, claim_item in claims.items():
        claim_type = str(claim_item["claim_type"])
        for support_id in claim_item["support_ids"]:
            if support_id not in observations:
                continue
            source = str(observations[support_id]["source"])
            if source not in normalized_roles:
                raise ValueError(f"claim {claim_id} uses ungoverned source {source}")
            allowed_types = set(normalized_roles[source]["direct_claim_types"])
            if claim_type not in allowed_types:
                raise ValueError(
                    f"source-role violation: {source} cannot directly support {claim_type}"
                )
            direct_sources_by_type.setdefault(claim_type, set()).add(source)

    for claim_type, expected_sources in required_groups.items():
        actual = direct_sources_by_type.get(str(claim_type), set())
        missing = set(str(item) for item in expected_sources) - actual
        if missing:
            raise ValueError(
                f"claim type {claim_type} missing direct source roles: {', '.join(sorted(missing))}"
            )
    return normalized_roles


def _observation(
    item_id: Any,
    source: str,
    observations: dict[str, dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    ref = str(item_id or "")
    if ref not in observations:
        raise ValueError(f"{field} references missing observation: {ref}")
    item = observations[ref]
    if item.get("source") != source:
        raise ValueError(f"{field} must reference {source} observation")
    if not isinstance(item.get("values"), dict):
        raise ValueError(f"{field} observation requires structured values")
    return item


def _claim(
    item_id: Any,
    claims: dict[str, dict[str, Any]],
    field: str,
    claim_type: str | None = None,
) -> str:
    ref = str(item_id or "")
    if ref not in claims:
        raise ValueError(f"{field} references missing claim: {ref}")
    if claim_type is not None and claims[ref].get("claim_type") != claim_type:
        raise ValueError(f"{field} must reference claim type {claim_type}")
    return ref


def _numeric_dict(value: Any, field: str) -> dict[str, int | float]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field} must be a non-empty numeric object")
    return {str(key): _decimal(item, f"{field}.{key}") for key, item in value.items()}


def _number_list(value: Any, field: str) -> list[int | float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty numeric array")
    return [_decimal(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _iso_date(value: Any, field: str) -> str:
    normalized = _text(value, field)
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


def _iso_timestamp(value: Any, field: str) -> str:
    normalized = _text(value, field)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.isoformat(timespec="seconds")


def _only_source_observation(
    source: str,
    observations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    matches = [item for item in observations.values() if item.get("source") == source]
    if len(matches) != 1:
        raise ValueError(f"source {source} requires exactly one current-slot observation")
    return matches[0]


def normalize_methodology(
    payload: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("methodology must be an object")
    claim_ids = set(claims)
    normalized_source_roles = _normalize_source_methodology(
        observations, claims, policy
    )

    blockbeats = _only_source_observation("blockbeats", observations)
    bv = blockbeats["values"]
    blockbeats_tier = _decimal(bv.get("tier"), "BlockBeats tier")
    if blockbeats_tier not in {1, 2, 3}:
        raise ValueError("BlockBeats tier must be 1, 2 or 3")
    if _decimal(bv.get("event_window_hours"), "BlockBeats event_window_hours") != 12:
        raise ValueError("BlockBeats event window must cover 12 hours")
    if _decimal(bv.get("selected_event_count"), "BlockBeats selected_event_count") != 3:
        raise ValueError("BlockBeats reasoning must use the certified top3 events")

    fedwatch = _only_source_observation("fedwatch", observations)
    fd = fedwatch["values"]
    fed_current = _numeric_dict(fd.get("current_probabilities"), "FedWatch current_probabilities")
    fed_changes = {
        window: _numeric_dict(fd.get(window), f"FedWatch {window}")
        for window in ("change_1d", "change_1w", "change_1m")
    }
    if not 99.8 <= sum(float(value) for value in fed_current.values()) <= 100.2:
        raise ValueError("FedWatch current probabilities must sum to approximately 100")
    for window, values in fed_changes.items():
        if set(values) != set(fed_current):
            raise ValueError(f"FedWatch {window} outcomes differ from current distribution")
        if abs(sum(float(value) for value in values.values())) > 0.2:
            raise ValueError(f"FedWatch {window} deltas must net to approximately zero")
    fed_as_of = _iso_timestamp(fd.get("data_as_of"), "FedWatch data_as_of")
    next_fomc_date = _iso_date(fd.get("next_fomc_date"), "FedWatch next_fomc_date")
    observation_date = date.fromisoformat(str(fedwatch["observed_at"])[:10])
    if date.fromisoformat(next_fomc_date) < observation_date:
        raise ValueError("FedWatch next_fomc_date cannot precede the observation date")

    farside_observation = _only_source_observation("farside_btc_etf", observations)
    fsv = farside_observation["values"]
    farside_date = _iso_date(
        fsv.get("latest_complete_date"), "Farside latest_complete_date"
    )
    farside_observed_date = date.fromisoformat(
        str(farside_observation["observed_at"])[:10]
    )
    if date.fromisoformat(farside_date) > farside_observed_date:
        raise ValueError("Farside latest_complete_date cannot be in the future")
    farside_total = _decimal(fsv.get("latest_total_usd_m"), "Farside latest_total_usd_m")
    farside_direction = _enum(
        fsv.get("flow_direction"), {"inflow", "outflow", "flat"},
        "Farside flow_direction"
    )
    if (
        (farside_direction == "inflow" and farside_total <= 0)
        or (farside_direction == "outflow" and farside_total >= 0)
        or (farside_direction == "flat" and farside_total != 0)
    ):
        raise ValueError("Farside flow_direction conflicts with latest total")

    synthesis = payload.get("independent_synthesis")
    if not isinstance(synthesis, dict):
        raise ValueError("methodology.independent_synthesis must be an object")
    primary = _refs(
        synthesis.get("primary_evidence_claim_ids"),
        claim_ids,
        "methodology.independent_synthesis.primary_evidence_claim_ids",
        2,
    )
    normalized_synthesis = {
        "market_stage_claim_id": _claim(
            synthesis.get("market_stage_claim_id"), claims,
            "methodology.independent_synthesis.market_stage_claim_id", "market_regime"
        ),
        "dominant_leg": _enum(
            synthesis.get("dominant_leg"), set(policy["dominant_legs"]),
            "methodology.independent_synthesis.dominant_leg"
        ),
        "primary_evidence_claim_ids": primary,
        "strongest_counter_claim_id": _claim(
            synthesis.get("strongest_counter_claim_id"), claims,
            "methodology.independent_synthesis.strongest_counter_claim_id",
            "strongest_counterevidence",
        ),
        "action_claim_id": _claim(
            synthesis.get("action_claim_id"), claims,
            "methodology.independent_synthesis.action_claim_id"
        ),
    }

    realization = payload.get("fundamental_price_realization")
    if not isinstance(realization, dict):
        raise ValueError("methodology.fundamental_price_realization must be an object")
    normalized_realization = {
        "blockbeats_observation_id": blockbeats["id"],
        "fundamental_claim_id": _claim(
            realization.get("fundamental_claim_id"), claims,
            "methodology.fundamental_price_realization.fundamental_claim_id",
            "fundamental_context",
        ),
        "price_claim_id": _claim(
            realization.get("price_claim_id"), claims,
            "methodology.fundamental_price_realization.price_claim_id",
            "chart_interpretation",
        ),
        "synthesis_claim_id": _claim(
            realization.get("synthesis_claim_id"), claims,
            "methodology.fundamental_price_realization.synthesis_claim_id",
            "main_account_thesis",
        ),
        "event_window_hours": 12,
        "selected_event_count": 3,
        "realization_state": _enum(
            realization.get("realization_state"),
            set(policy["fundamental_realization_states"]),
            "methodology.fundamental_price_realization.realization_state",
        ),
        "historical_market_fact_used": False,
    }
    if realization.get("historical_market_fact_used") is not False:
        raise ValueError("fundamental price realization must use current-slot facts only")

    pivot = payload.get("same_pivot_orderflow")
    if not isinstance(pivot, dict):
        raise ValueError("methodology.same_pivot_orderflow must be an object")
    coinglass = _observation(
        pivot.get("observation_id"), "coinglass", observations,
        "methodology.same_pivot_orderflow.observation_id"
    )
    cv = coinglass["values"]
    pivot_values = cv.get("pivot")
    if not isinstance(pivot_values, dict):
        raise ValueError("Coinglass values.pivot must be an object")
    normalized_pivot_values = {
        "timeframe": _enum(pivot_values.get("timeframe"), {"1h"}, "Coinglass pivot.timeframe"),
        "start_price": _decimal(pivot_values.get("start_price"), "Coinglass pivot.start_price"),
        "end_price": _decimal(pivot_values.get("end_price"), "Coinglass pivot.end_price"),
        "dominant_leg": _enum(
            pivot_values.get("dominant_leg"), set(policy["dominant_legs"]),
            "Coinglass pivot.dominant_leg"
        ),
        "trendline_status": _enum(
            pivot_values.get("trendline_status"), set(policy["trendline_statuses"]),
            "Coinglass pivot.trendline_status"
        ),
        "anchor_reset": bool(pivot_values.get("anchor_reset")),
    }
    price_direction = _enum(
        cv.get("price_direction"), set(policy["directions"]),
        "Coinglass price_direction",
    )
    cvd_direction = _enum(
        cv.get("cvd_direction"), set(policy["directions"]),
        "Coinglass cvd_direction",
    )
    oi_direction = _enum(
        cv.get("oi_direction"), set(policy["directions"]),
        "Coinglass oi_direction",
    )
    funding_sign = _enum(
        cv.get("funding_sign"), set(policy["funding_signs"]),
        "Coinglass funding_sign",
    )
    derived_combination_id = _combination_id(
        cvd_direction, price_direction, oi_direction, funding_sign, policy
    )
    claimed_combination_id = _text(
        cv.get("combination_id"), "Coinglass combination_id"
    )
    if claimed_combination_id != derived_combination_id:
        raise ValueError(
            f"Coinglass combination_id must be {derived_combination_id} for the four states"
        )
    effect_divergence = _normalize_effect_divergence(
        cv.get("effect_divergence"),
        cvd_direction=cvd_direction,
        price_direction=price_direction,
        policy=policy,
    )
    price_break_status = _enum(
        cv.get("price_break_status"), set(policy["price_break_statuses"]),
        "Coinglass price_break_status",
    )
    oi_price_context = _normalize_oi_price_context(
        cv.get("oi_price_context"),
        price_direction=price_direction,
        oi_direction=oi_direction,
        price_break_status=price_break_status,
        policy=policy,
    )
    main_triad_direction = _enum(
        cv.get("main_triad_direction"), set(policy["triad_directions"]),
        "Coinglass main_triad_direction",
    )
    main_triad_rationale = _text(
        cv.get("main_triad_rationale"), "Coinglass main_triad_rationale", 20
    )
    if effect_divergence["interpretation"] in {"bullish", "bearish"}:
        if main_triad_direction != effect_divergence["interpretation"]:
            raise ValueError(
                "main triad direction conflicts with the evidenced effect divergence"
            )
    aligned_direction = {
        ("up", "up", "up"): "bullish",
        ("down", "down", "up"): "bearish",
        ("flat", "flat", "flat"): "neutral",
    }.get((cvd_direction, price_direction, oi_direction))
    if aligned_direction is not None and effect_divergence["interpretation"] == "none":
        if main_triad_direction != aligned_direction:
            raise ValueError(
                "main triad direction conflicts with aligned CVD/price/OI states"
            )
    funding_effect = _enum(
        cv.get("funding_effect"), set(policy["funding_effects"]),
        "Coinglass funding_effect",
    )
    final_direction = _enum(
        cv.get("final_direction"), set(policy["triad_directions"]),
        "Coinglass final_direction",
    )
    if cv.get("funding_single_variable_flip") is not False:
        raise ValueError("funding must not flip the CVD+price+OI direction")
    if final_direction != main_triad_direction:
        raise ValueError("final orderflow direction must preserve the CVD+price+OI direction")

    normalized_pivot = {
        "observation_id": coinglass["id"],
        "claim_id": _claim(
            pivot.get("claim_id"), claims,
            "methodology.same_pivot_orderflow.claim_id", "orderflow_interpretation"
        ),
        "pivot": normalized_pivot_values,
        "price_direction": price_direction,
        "cvd_direction": cvd_direction,
        "oi_direction": oi_direction,
        "funding_direction": _enum(cv.get("funding_direction"), set(policy["directions"]), "Coinglass funding_direction"),
        "funding_sign": funding_sign,
        "combination_id": derived_combination_id,
        "effect_divergence": effect_divergence,
        "price_break_status": price_break_status,
        "oi_price_context": oi_price_context,
        "main_triad_direction": main_triad_direction,
        "main_triad_rationale": main_triad_rationale,
        "funding_effect": funding_effect,
        "final_direction": final_direction,
        "funding_single_variable_flip": False,
        "leg_selected": pivot.get("leg_selected") is True,
        "pullback_anchor_checked": pivot.get("pullback_anchor_checked") is True,
        "four_dimensions_same_anchor": pivot.get("four_dimensions_same_anchor") is True,
    }
    for key in ("leg_selected", "pullback_anchor_checked", "four_dimensions_same_anchor"):
        if normalized_pivot[key] is not True:
            raise ValueError(f"methodology.same_pivot_orderflow.{key} must be true")
    if normalized_pivot_values["dominant_leg"] != normalized_synthesis["dominant_leg"]:
        raise ValueError("dominant leg differs between synthesis and same-pivot analysis")

    footprint = payload.get("footprint_cross_check")
    if not isinstance(footprint, dict):
        raise ValueError("methodology.footprint_cross_check must be an object")
    exocharts = _observation(
        footprint.get("observation_id"), "exocharts", observations,
        "methodology.footprint_cross_check.observation_id"
    )
    ev = exocharts["values"]
    ohlc = ev.get("ohlc")
    if not isinstance(ohlc, dict) or set(ohlc) != {"open", "high", "low", "close"}:
        raise ValueError("Exocharts values.ohlc must contain open/high/low/close")
    normalized_ohlc = {key: _decimal(value, f"Exocharts ohlc.{key}") for key, value in ohlc.items()}
    if not (
        normalized_ohlc["low"]
        <= min(normalized_ohlc["open"], normalized_ohlc["close"])
        <= max(normalized_ohlc["open"], normalized_ohlc["close"])
        <= normalized_ohlc["high"]
    ):
        raise ValueError("Exocharts OHLC is internally inconsistent")
    normalized_footprint = {
        "observation_id": exocharts["id"],
        "claim_id": _claim(
            footprint.get("claim_id"), claims,
            "methodology.footprint_cross_check.claim_id", "orderflow_interpretation"
        ),
        "relationship": _enum(
            footprint.get("relationship"), set(policy["cross_check_results"]),
            "methodology.footprint_cross_check.relationship"
        ),
        "ohlc": normalized_ohlc,
        "poc": _decimal(ev.get("poc"), "Exocharts poc"),
        "delta": _decimal(ev.get("delta"), "Exocharts delta"),
        "cvd": _decimal(ev.get("cvd"), "Exocharts cvd"),
        "volume": _decimal(ev.get("volume"), "Exocharts volume"),
    }
    if not normalized_ohlc["low"] <= normalized_footprint["poc"] <= normalized_ohlc["high"]:
        raise ValueError("Exocharts POC must lie inside the captured OHLC range")

    multi = payload.get("multi_timeframe_transition")
    if not isinstance(multi, dict):
        raise ValueError("methodology.multi_timeframe_transition must be an object")
    tradingview = _observation(
        multi.get("observation_id"), "tradingview", observations,
        "methodology.multi_timeframe_transition.observation_id"
    )
    tv = tradingview["values"]
    frames = tv.get("timeframes")
    if not isinstance(frames, dict):
        raise ValueError("TradingView values.timeframes must be an object")
    normalized_frames: dict[str, Any] = {}
    for timeframe in policy["timeframes"]:
        item = frames.get(timeframe)
        if not isinstance(item, dict):
            raise ValueError(f"TradingView timeframe missing: {timeframe}")
        normalized_frames[timeframe] = {
            "price": _decimal(item.get("price"), f"TradingView {timeframe}.price"),
            "sma20": _decimal(item.get("sma20"), f"TradingView {timeframe}.sma20"),
            "structure": _enum(
                item.get("structure"), {"bullish", "bearish", "range"},
                f"TradingView {timeframe}.structure"
            ),
        }
    normalized_multi = {
        "observation_id": tradingview["id"],
        "claim_id": _claim(
            multi.get("claim_id"), claims,
            "methodology.multi_timeframe_transition.claim_id", "chart_interpretation"
        ),
        "timeframes": normalized_frames,
        "transition_summary": _text(
            multi.get("transition_summary"),
            "methodology.multi_timeframe_transition.transition_summary", 20
        ),
    }

    liquidity = payload.get("volume_profile_liquidity")
    if not isinstance(liquidity, dict):
        raise ValueError("methodology.volume_profile_liquidity must be an object")
    profile = tv.get("volume_profile")
    if not isinstance(profile, dict):
        raise ValueError("TradingView values.volume_profile must be an object")
    heatmap = tv.get("liquidation_map")
    if not isinstance(heatmap, dict):
        raise ValueError("TradingView values.liquidation_map must be an object")
    if heatmap.get("role") != policy["liquidation_map_role"]:
        raise ValueError("liquidation map must remain auxiliary_only")
    levels = heatmap.get("levels")
    if not isinstance(levels, list) or not levels:
        raise ValueError("liquidation map requires at least one evidenced level")
    normalized_levels = []
    for index, item in enumerate(levels):
        if not isinstance(item, dict):
            raise ValueError(f"liquidation map levels[{index}] must be an object")
        normalized_levels.append({
            "side": _enum(item.get("side"), {"above", "below"}, f"liquidation level {index}.side"),
            "price": _decimal(item.get("price"), f"liquidation level {index}.price"),
            "timeframe": _text(item.get("timeframe"), f"liquidation level {index}.timeframe", 2),
        })
    normalized_liquidity = {
        "observation_id": tradingview["id"],
        "claim_id": _claim(
            liquidity.get("claim_id"), claims,
            "methodology.volume_profile_liquidity.claim_id", "chart_interpretation"
        ),
        "poc": _decimal(profile.get("poc"), "TradingView volume_profile.poc"),
        "value_area_position": _enum(
            profile.get("value_area_position"), {"above", "inside", "below"},
            "TradingView volume_profile.value_area_position"
        ),
        "hvn_levels": _number_list(profile.get("hvn_levels"), "TradingView volume_profile.hvn_levels"),
        "lvn_levels": _number_list(profile.get("lvn_levels"), "TradingView volume_profile.lvn_levels"),
        "liquidation_map_role": policy["liquidation_map_role"],
        "liquidation_levels": normalized_levels,
    }

    etf = payload.get("etf_flow_relation")
    if not isinstance(etf, dict):
        raise ValueError("methodology.etf_flow_relation must be an object")
    farside = _observation(
        etf.get("observation_id"), "farside_btc_etf", observations,
        "methodology.etf_flow_relation.observation_id"
    )
    normalized_etf = {
        "observation_id": farside["id"],
        "claim_id": _claim(etf.get("claim_id"), claims, "methodology.etf_flow_relation.claim_id"),
        "latest_complete_date": farside_date,
        "latest_total_usd_m": farside_total,
        "flow_direction": farside_direction,
        "price_relation": _enum(
            etf.get("price_relation"), set(policy["price_relations"]),
            "methodology.etf_flow_relation.price_relation"
        ),
    }

    account = payload.get("account_separation")
    if not isinstance(account, dict):
        raise ValueError("methodology.account_separation must be an object")
    if account.get("main_priority") != policy["main_account_priority"]:
        raise ValueError("main account priority differs from constitution")
    if account.get("maker_priority") != policy["maker_priority"]:
        raise ValueError("Maker priority differs from constitution")
    if account.get("forced_consensus") is not False:
        raise ValueError("main account and Maker must not be forced into one direction")
    normalized_account = {
        "main_priority": list(policy["main_account_priority"]),
        "maker_priority": list(policy["maker_priority"]),
        "main_claim_id": _claim(
            account.get("main_claim_id"), claims,
            "methodology.account_separation.main_claim_id", "main_account_thesis"
        ),
        "maker_claim_id": _claim(
            account.get("maker_claim_id"), claims,
            "methodology.account_separation.maker_claim_id", "maker_thesis"
        ),
        "conflict_resolution_claim_id": _claim(
            account.get("conflict_resolution_claim_id"), claims,
            "methodology.account_separation.conflict_resolution_claim_id"
        ),
        "forced_consensus": False,
    }

    scenarios = payload.get("scenario_tree")
    if not isinstance(scenarios, list):
        raise ValueError("methodology.scenario_tree must be an array")
    normalized_scenarios = []
    kinds: set[str] = set()
    for index, item in enumerate(scenarios):
        if not isinstance(item, dict):
            raise ValueError(f"methodology.scenario_tree[{index}] must be an object")
        kind = _enum(item.get("kind"), {"base", "counter", "invalidation"}, f"scenario {index}.kind")
        kinds.add(kind)
        normalized_scenarios.append({
            "kind": kind,
            "claim_id": _claim(item.get("claim_id"), claims, f"scenario {index}.claim_id"),
            "trigger_claim_ids": _refs(
                item.get("trigger_claim_ids"), claim_ids,
                f"scenario {index}.trigger_claim_ids"
            ),
            "action": _text(item.get("action"), f"scenario {index}.action", 12),
        })
    if len(normalized_scenarios) < int(policy["minimum_scenario_count"]) or kinds != {"base", "counter", "invalidation"}:
        raise ValueError("scenario tree must contain base/counter/invalidation paths")

    cannot = payload.get("cannot_do_derivation")
    if not isinstance(cannot, dict):
        raise ValueError("methodology.cannot_do_derivation must be an object")
    if cannot.get("filled_after_full_analysis") is not True:
        raise ValueError("cannot_do must be filled after the full analysis")
    normalized_cannot = {
        "claim_id": _claim(
            cannot.get("claim_id"), claims,
            "methodology.cannot_do_derivation.claim_id", "cannot_do"
        ),
        "basis_claim_ids": _refs(
            cannot.get("basis_claim_ids"), claim_ids,
            "methodology.cannot_do_derivation.basis_claim_ids", 2
        ),
        "filled_after_full_analysis": True,
    }

    minimum_sources_by_type = policy.get("minimum_independent_sources_by_claim_type")
    if not isinstance(minimum_sources_by_type, dict):
        raise ValueError("gold methodology requires per-claim source minimums")
    for claim_id, claim_item in claims.items():
        claim_type = str(claim_item["claim_type"])
        if claim_type not in minimum_sources_by_type:
            continue
        minimum_sources = int(minimum_sources_by_type[claim_type])
        sources = _claim_sources(claim_id, observations, claims)
        if len(sources) < minimum_sources:
            raise ValueError(
                f"load-bearing claim {claim_id} ({claim_type}) requires "
                f"{minimum_sources} independent sources"
            )

    return {
        "source_methodology": normalized_source_roles,
        "source_calibration": {
            "blockbeats": {
                "tier": blockbeats_tier,
                "event_window_hours": 12,
                "selected_event_count": 3,
            },
            "fedwatch": {
                "data_as_of": fed_as_of,
                "next_fomc_date": next_fomc_date,
                "current_probabilities": fed_current,
                **fed_changes,
            },
            "farside_btc_etf": {
                "latest_complete_date": farside_date,
                "latest_total_usd_m": farside_total,
                "flow_direction": farside_direction,
            },
        },
        "independent_synthesis": normalized_synthesis,
        "fundamental_price_realization": normalized_realization,
        "same_pivot_orderflow": normalized_pivot,
        "footprint_cross_check": normalized_footprint,
        "multi_timeframe_transition": normalized_multi,
        "volume_profile_liquidity": normalized_liquidity,
        "etf_flow_relation": normalized_etf,
        "account_separation": normalized_account,
        "scenario_tree": normalized_scenarios,
        "cannot_do_derivation": normalized_cannot,
    }


def _resolve_value_path(observation: dict[str, Any], path: str, field: str) -> int | float:
    value: Any = observation.get("values")
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError(f"{field} references missing observation value path: {path}")
    return _decimal(value, field)


def _number_tokens(value: int | float) -> set[str]:
    number = Decimal(str(value))
    plain = format(number.normalize(), "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    tokens = {plain}
    integer = number == number.to_integral_value()
    if integer:
        tokens.add(f"{int(number):,}")
    return tokens


def normalize_report_projection(
    payload: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("report_projection.items must be an array")
    required_units = set(policy["required_semantic_units"])
    visible_units_required = set(policy["visible_semantic_units"])
    known_claims = set(claims)
    normalized = []
    ids: set[str] = set()
    appendix_units: set[str] = set()
    visible_units: set[str] = set()
    visible_claim_types: set[str] = set()
    for index, item in enumerate(payload["items"]):
        if not isinstance(item, dict):
            raise ValueError(f"report_projection.items[{index}] must be an object")
        item_id = _id(item.get("id"), f"report projection {index}.id")
        if item_id in ids:
            raise ValueError(f"duplicate report projection id: {item_id}")
        ids.add(item_id)
        unit = _enum(
            item.get("semantic_unit"), required_units,
            f"report projection {item_id}.semantic_unit"
        )
        surface = _enum(item.get("surface"), {"visible", "appendix"}, f"report projection {item_id}.surface")
        section = str(item.get("section", ""))
        if surface == "visible":
            if section not in VISIBLE_SECTIONS:
                raise ValueError(f"report projection {item_id} has invalid visible section")
            visible_units.add(unit)
        else:
            if section != "appendix":
                raise ValueError(f"report projection {item_id} appendix surface requires appendix section")
            appendix_units.add(unit)
        claim_refs = _refs(
            item.get("claim_ids"), known_claims,
            f"report projection {item_id}.claim_ids"
        )
        if surface == "visible":
            visible_claim_types.update(claims[ref]["claim_type"] for ref in claim_refs)
        text = _text(item.get("text"), f"report projection {item_id}.text", 20)
        value_refs = item.get("value_refs")
        if not isinstance(value_refs, list):
            raise ValueError(f"report projection {item_id}.value_refs must be an array")
        normalized_values = []
        for value_index, ref in enumerate(value_refs):
            if not isinstance(ref, dict):
                raise ValueError(f"report projection {item_id}.value_refs[{value_index}] must be an object")
            observation_id = str(ref.get("observation_id", ""))
            if observation_id not in observations:
                raise ValueError(f"report projection {item_id} references missing observation value")
            path = _text(ref.get("path"), f"report projection {item_id}.value_refs[{value_index}].path")
            value = _resolve_value_path(
                observations[observation_id], path,
                f"report projection {item_id}.value_refs[{value_index}]"
            )
            if not any(token in text for token in _number_tokens(value)):
                raise ValueError(
                    f"report projection {item_id} does not render bound value {observation_id}:{path}"
                )
            normalized_values.append({
                "observation_id": observation_id,
                "path": path,
                "value": value,
            })
        if unit in NUMERIC_UNITS and not normalized_values:
            raise ValueError(f"report projection {item_id} requires bound numeric value_refs")
        normalized.append({
            "id": item_id,
            "semantic_unit": unit,
            "surface": surface,
            "section": section,
            "claim_ids": claim_refs,
            "text": text,
            "value_refs": normalized_values,
        })
    missing_appendix = sorted(required_units - appendix_units)
    if missing_appendix:
        raise ValueError("report projection appendix missing semantic units: " + ", ".join(missing_appendix))
    missing_visible_units = sorted(visible_units_required - visible_units)
    if missing_visible_units:
        raise ValueError("report projection visible body missing semantic units: " + ", ".join(missing_visible_units))
    missing_visible_claims = sorted(set(policy["visible_claim_types"]) - visible_claim_types)
    if missing_visible_claims:
        raise ValueError("report projection visible body missing claim types: " + ", ".join(missing_visible_claims))
    return {"items": normalized}
