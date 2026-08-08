"""Decision-stage production validation owner for Main and Maker."""

from __future__ import annotations

import json
import re
import struct
import zipfile
import zlib
from itertools import combinations
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..methodology import canonical_sha256, load_scoring_policy, sha256_file
from ..domain_ir.projection import (
    account_current_basis_projection,
    account_trigger_logic_projection,
)
from ..domain_ir.registry import (
    ACCOUNT_CURRENT_BASIS_POLICY_FIELDS,
    ACCOUNT_LOOP_CLAIM_TYPES,
    CANNOT_DO_CODES,
    CLAIM_ACCOUNT_SCOPES,
    CLAIM_TYPES as REQUIRED_CLAIM_TYPES,
    CONTINUITY_ACTIONS,
    CONTINUITY_PRIOR_STATUSES,
    EVIDENCE_SOURCE_ORDER as REQUIRED_SOURCES,
    HIGH_IMPACT_CLAIMS,
    MINIMUM_OBSERVATION_METRICS,
    NON_ACTION_REPORT_SECTIONS,
    NON_TRACEABLE_REPORT_SECTIONS,
    POLICY_SOURCE_KEYS,
    REGISTRY,
    REPORT_SECTIONS as REQUIRED_REPORT_SECTIONS,
    SCENARIO_TYPES as REQUIRED_SCENARIO_TYPES,
    SECTION_REQUIRED_CLAIM_TYPES,
    SOURCE_ROLES,
    SOURCE_ROLE_CLAIM_OWNER,
    TRADINGVIEW_TIMEFRAMES,
    TRIGGER_CONTROL_CLAIM_TYPES,
    TRIGGER_EFFECT_BY_CLAIM_TYPE,
)
from ..plan_semantics import (
    assess_candidate,
    assess_order_lifecycle,
    classify_evidence_polarity,
    classify_maker_semantic_state,
    cannot_do_conflicts,
    expected_reach_direction,
    resting_maker_order_valid,
    structural_noise_stop_is_outside,
    structure_zone_role_valid,
)
from ..pretrade_gate import validate_pretrade_gate_contract
from ..rate_expectation import (
    RateExpectationError,
    canonical_json_sha256 as rate_canonical_sha256,
    normalize_kalshi_payload,
    validate_cme_result,
    validate_rate_provenance,
)
from ..reasoning_pipeline import validate_reasoning_pipeline
from ..reasoning_submission import (
    derive_methodology_trigger_claim_ids,
    load_reasoning_submission_contract,
)
from ..delivery_renderer import (
    ALLOWED_BACKENDS as WORD_QA_ALLOWED_BACKENDS,
    PASSED_WORD_QA_FIELDS,
    WORD_QA_SCHEMA,
    passed_word_qa_checklist_is_valid,
    passed_word_qa_run_paths_are_valid,
)
from outputs.report_lint import coupling_check

from .common import (
    Defect, GateResult, _canonical_closed_string,
    _canonical_positive_decimal_string, _contains_cjk, _decimal_matches,
    _json_number, _matches_policy_path, _nested_value, _number,
    _parse_iso_datetime, _reachable_trigger_owners, _record_paths,
    _resolve_concrete_value_path, _round_to_step, _text,
    _typed_domain_contains, _typed_domain_intersection,
    _valid_png_dimensions, _validate_file_record, gate_result as _result,
    maker_fill_scenarios,
)
from .reasoning import (
    _execution_parameter_leak,
    _reachable_observations,
    _score_second_truth,
    certified_chart_components,
    certified_orderflow_assessment,
    reasoning_model_sha256,
)

def _resolve_tradingview_entry_zone(
    basis: Any,
    observations: dict[str, dict[str, Any]],
    *,
    manual_profile_first: bool,
) -> tuple[Decimal | None, Decimal | None, str, str, str | None, str | None]:
    """Resolve a decision zone to one current TradingView observation.

    The decision stores only an observation id, zone family and array index;
    bounds remain owned by the certified reasoning observation.
    """

    if not isinstance(basis, dict) or set(basis) != {
        "observation_id",
        "zone_kind",
        "zone_index",
    }:
        return None, None, "entry_zone_basis_schema", "", None, None
    observation_id = _text(basis.get("observation_id"))
    observation = observations.get(observation_id)
    if not isinstance(observation, dict) or observation.get("source") != "TradingView":
        return None, None, "entry_zone_observation", "", None, None
    metrics = observation.get("metrics") if isinstance(observation.get("metrics"), dict) else {}
    profile = metrics.get("volume_profile") if isinstance(metrics.get("volume_profile"), dict) else {}
    manual_zones = profile.get("zones") if isinstance(profile.get("zones"), list) else []
    chart_basis = metrics.get("chart_basis") if isinstance(metrics.get("chart_basis"), dict) else {}
    structure_zones = chart_basis.get("structure_zones") if isinstance(chart_basis.get("structure_zones"), list) else []
    zone_kind = _text(basis.get("zone_kind"))
    zone_index = basis.get("zone_index")
    binding_status = "ok"
    if not isinstance(zone_index, int) or isinstance(zone_index, bool) or zone_index < 0:
        return None, None, "entry_zone_index", zone_kind, None, None
    if zone_kind == "manual_profile":
        zones = manual_zones
    elif zone_kind == "structure":
        if manual_profile_first and manual_zones:
            binding_status = "manual_profile_must_be_preferred"
        zones = structure_zones
    else:
        return None, None, "entry_zone_kind", zone_kind, None, None
    if zone_index >= len(zones) or not isinstance(zones[zone_index], dict):
        return None, None, "entry_zone_index", zone_kind, None, None
    zone = zones[zone_index]
    lower = _number(zone.get("lower_bound"))
    upper = _number(zone.get("upper_bound"))
    if lower is None or upper is None or lower <= 0 or lower >= upper:
        return None, None, "entry_zone_geometry", zone_kind, None, None
    canonical_kind = "manual_profile" if zone_kind == "manual_profile" else "structure_zone"
    role = _text(zone.get("role")) or None
    timeframe = _text(zone.get("timeframe")) or None
    return lower, upper, binding_status, canonical_kind, role, timeframe

def _validate_structural_stop_details(basis, *, claim, claim_id, defects, direction, entries, observation_id, path, policy, selected_zone, anchor_kind, anchor_price, anchor_source_field, timeframe, stop, zone_lower, zone_upper):
    selected_zone_index = selected_zone.get("zone_index")
    anchor_zone_match = re.search(r"\.(structure_zones|volume_profile\.zones)\[(\d+)\]", anchor_source_field)
    if anchor_zone_match is not None and isinstance(selected_zone_index, int):
        anchor_zone_kind = (
            "structure"
            if anchor_zone_match.group(1) == "structure_zones"
            else "manual_profile"
        )
        if (
            selected_zone.get("observation_id") == observation_id
            and selected_zone.get("zone_kind") == anchor_zone_kind
            and selected_zone_index == int(anchor_zone_match.group(2))
        ):
            defects.append(
                Defect(
                    "structural_stop.entry_zone_reused",
                    "the current entry zone cannot masquerade as its own invalidation anchor",
                    f"{path}.anchor_source_field",
                )
            )

    valid_entries = [value for value in entries if value is not None and value > 0]
    anchor_outside = (
        direction == "short"
        and anchor_price is not None
        and zone_upper is not None
        and valid_entries
        and anchor_price > zone_upper
        and anchor_price > max(valid_entries)
    ) or (
        direction == "long"
        and anchor_price is not None
        and zone_lower is not None
        and valid_entries
        and anchor_price < zone_lower
        and anchor_price < min(valid_entries)
    )
    if not anchor_outside:
        defects.append(
            Defect(
                "structural_stop.anchor_not_outside_entry",
                "the invalidation anchor must be strictly outside the certified entry zone and every entry",
                f"{path}.anchor_price",
            )
        )

    buffer_code = _text(basis.get("buffer_basis_code"))
    if buffer_code not in set(policy.get("allowed_buffer_basis_codes") or []):
        defects.append(
            Defect(
                "structural_stop.buffer_basis_code",
                "buffer_basis_code is outside the closed authority vocabulary",
                f"{path}.buffer_basis_code",
            )
        )
    if _text(basis.get("buffer_claim_id")) != claim_id:
        defects.append(
            Defect(
                "structural_stop.buffer_claim_binding",
                "buffer_claim_id must equal the same-account invalidation_path claim",
                f"{path}.buffer_claim_id",
            )
        )
    if basis.get("buffer_backsolved_from_risk") is not False:
        defects.append(
            Defect(
                "structural_stop.buffer_backsolve_forbidden",
                "outward buffer cannot be backsolved from the risk budget",
                f"{path}.buffer_backsolved_from_risk",
            )
        )

    outward_buffer = _json_number(basis.get("outward_buffer_price"))
    if outward_buffer is None or outward_buffer <= 0:
        defects.append(
            Defect(
                "structural_stop.buffer_distance",
                "outward_buffer_price must be a positive Arabic-numeric price distance",
                f"{path}.outward_buffer_price",
            )
        )

    owner_value_field = _text(policy.get("buffer_value_owner_claim_field"))
    owner_observation_field = _text(
        policy.get("buffer_observation_owner_claim_field")
    )
    owner_timeframe_field = _text(policy.get("buffer_timeframe_owner_claim_field"))
    owner_status_field = _text(policy.get("buffer_status_owner_claim_field"))
    owner_anchor_kind_field = _text(
        policy.get("buffer_anchor_kind_owner_claim_field")
    )
    owner_anchor_source_field_field = _text(
        policy.get("buffer_anchor_source_field_owner_claim_field")
    )
    owner_anchor_price_field = _text(
        policy.get("buffer_anchor_price_owner_claim_field")
    )
    owner_noise_boundary_field = _text(
        policy.get("buffer_noise_outer_boundary_owner_claim_field")
    )
    owner_policy_complete = all(
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
    )
    owner_value_found, owner_value = (
        _nested_value(claim, owner_value_field)
        if isinstance(claim, dict) and owner_value_field
        else (False, None)
    )
    owner_observation_found, owner_observation = (
        _nested_value(claim, owner_observation_field)
        if isinstance(claim, dict) and owner_observation_field
        else (False, None)
    )
    owner_timeframe_found, owner_timeframe = (
        _nested_value(claim, owner_timeframe_field)
        if isinstance(claim, dict) and owner_timeframe_field
        else (False, None)
    )
    owner_status_found, owner_status = (
        _nested_value(claim, owner_status_field)
        if isinstance(claim, dict) and owner_status_field
        else (False, None)
    )
    owner_anchor_kind_found, owner_anchor_kind = (
        _nested_value(claim, owner_anchor_kind_field)
        if isinstance(claim, dict) and owner_anchor_kind_field
        else (False, None)
    )
    owner_anchor_source_found, owner_anchor_source = (
        _nested_value(claim, owner_anchor_source_field_field)
        if isinstance(claim, dict) and owner_anchor_source_field_field
        else (False, None)
    )
    owner_anchor_price_found, owner_anchor_price = (
        _nested_value(claim, owner_anchor_price_field)
        if isinstance(claim, dict) and owner_anchor_price_field
        else (False, None)
    )
    owner_noise_boundary_found, owner_noise_boundary = (
        _nested_value(claim, owner_noise_boundary_field)
        if isinstance(claim, dict) and owner_noise_boundary_field
        else (False, None)
    )
    owner_distance = _json_number(owner_value) if owner_value_found else None
    owner_anchor_price_number = (
        _json_number(owner_anchor_price) if owner_anchor_price_found else None
    )
    owner_noise_boundary_number = (
        _json_number(owner_noise_boundary) if owner_noise_boundary_found else None
    )
    if (
        not owner_policy_complete
        or not owner_value_found
        or not owner_observation_found
        or not owner_timeframe_found
        or not owner_status_found
        or not owner_anchor_kind_found
        or not owner_anchor_source_found
        or not owner_anchor_price_found
        or not owner_noise_boundary_found
        or _text(owner_status) != "certified"
        or outward_buffer is None
        or owner_distance is None
        or outward_buffer != owner_distance
        or _text(owner_observation) != observation_id
        or _text(owner_timeframe).lower() != timeframe
        or _text(owner_anchor_kind) != anchor_kind
        or _text(owner_anchor_source) != anchor_source_field
        or anchor_price is None
        or owner_anchor_price_number is None
        or not _decimal_matches(anchor_price, owner_anchor_price_number)
    ):
        defects.append(
            Defect(
                "structural_stop.buffer_reasoning_binding",
                "decision stop identity and buffer must exactly copy the certified reasoning-owned observation, timeframe, anchor and distance before risk math",
                f"{path}.outward_buffer_price",
            )
        )

    derived_stop = _json_number(basis.get("derived_stop"))
    expected_stop = None
    if anchor_price is not None and outward_buffer is not None:
        expected_stop = (
            anchor_price + outward_buffer
            if direction == "short"
            else anchor_price - outward_buffer
            if direction == "long"
            else None
        )
    if (
        derived_stop is None
        or expected_stop is None
        or not _decimal_matches(derived_stop, expected_stop)
        or stop is None
        or not _decimal_matches(stop, expected_stop)
        or (
            direction == "short"
            and anchor_price is not None
            and derived_stop is not None
            and derived_stop <= anchor_price
        )
        or (
            direction == "long"
            and anchor_price is not None
            and derived_stop is not None
            and derived_stop >= anchor_price
        )
    ):
        defects.append(
            Defect(
                "structural_stop.derived_stop",
                "derived_stop and risk stop must equal anchor plus the direction-aware outward buffer",
                f"{path}.derived_stop",
            )
        )
    noise_boundary_valid = (
        direction == "short"
        and derived_stop is not None
        and owner_noise_boundary_number is not None
        and derived_stop > owner_noise_boundary_number
    ) or (
        direction == "long"
        and derived_stop is not None
        and owner_noise_boundary_number is not None
        and derived_stop < owner_noise_boundary_number
    )
    if not noise_boundary_valid:
        defects.append(
            Defect(
                "structural_stop.noise_envelope",
                "derived_stop must remain strictly outside the reasoning-certified visible noise envelope",
                f"{path}.derived_stop",
            )
        )
    return not defects, defects


def _validate_structural_stop_basis(
    basis: Any,
    *,
    direction: str,
    stop: Decimal | None,
    zone_lower: Decimal | None,
    zone_upper: Decimal | None,
    entries: list[Decimal | None],
    entry_zone_basis: Any,
    account: str,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    path: str,
) -> tuple[bool, list[Defect]]:
    """Bind a stop to current-run TradingView structure before risk math."""

    defects: list[Defect] = []
    if not isinstance(basis, dict):
        return False, [
            Defect(
                "structural_stop.schema",
                "stop_basis must be a closed structural-stop object",
                path,
            )
        ]
    expected_fields = set(policy.get("required_stop_basis_fields") or [])
    if not expected_fields or set(basis) != expected_fields:
        defects.append(
            Defect(
                "structural_stop.schema",
                "stop_basis differs from the authority-required field set",
                path,
            )
        )

    observation_id = _text(basis.get("observation_id"))
    observation = observations.get(observation_id)
    if not isinstance(observation, dict) or observation.get("source") != policy.get(
        "primary_source"
    ):
        defects.append(
            Defect(
                "structural_stop.observation_binding",
                "stop_basis must bind the current-run TradingView observation",
                f"{path}.observation_id",
            )
        )

    claim_id = _text(basis.get("claim_id"))
    claim = claims.get(claim_id)
    if (
        not isinstance(claim, dict)
        or claim.get("claim_type") != "invalidation_path"
        or claim.get("account") != account
    ):
        defects.append(
            Defect(
                "structural_stop.claim_binding",
                f"stop_basis must bind the {account} invalidation_path claim",
                f"{path}.claim_id",
            )
        )
    elif observation_id not in _reachable_observations(
        claim_id,
        claims,
        set(observations),
    ):
        defects.append(
            Defect(
                "structural_stop.claim_evidence_binding",
                "the invalidation claim does not reach the cited TradingView observation",
                f"{path}.claim_id",
            )
        )

    timeframe = _text(basis.get("timeframe")).lower()
    if timeframe not in {_text(item).lower() for item in policy.get("allowed_timeframes", [])}:
        defects.append(
            Defect(
                "structural_stop.timeframe",
                "stop_basis timeframe is outside the structural-stop authority",
                f"{path}.timeframe",
            )
        )

    anchor_kind = _text(basis.get("anchor_kind"))
    anchor_source_field = _text(basis.get("anchor_source_field"))
    allowed_anchor_kinds = set(policy.get("allowed_anchor_kinds") or [])
    allowed_anchor_fields = list(policy.get("allowed_anchor_source_fields") or [])
    if anchor_kind not in allowed_anchor_kinds or not _matches_policy_path(
        anchor_source_field,
        allowed_anchor_fields,
    ):
        defects.append(
            Defect(
                "structural_stop.anchor_contract",
                "anchor_kind/source_field is outside the closed structural-stop authority",
                f"{path}.anchor_source_field",
            )
        )

    direction_field_valid = {
        ("short", "manual_profile_upper_outer_boundary"): ".volume_profile.zones[" in anchor_source_field
        and anchor_source_field.endswith("].upper_bound"),
        ("long", "manual_profile_lower_outer_boundary"): ".volume_profile.zones[" in anchor_source_field
        and anchor_source_field.endswith("].lower_bound"),
        ("short", "structure_zone_outer_boundary"): ".structure_zones[" in anchor_source_field
        and anchor_source_field.endswith("].upper_bound"),
        ("long", "structure_zone_outer_boundary"): ".structure_zones[" in anchor_source_field
        and anchor_source_field.endswith("].lower_bound"),
    }.get((direction, anchor_kind), False)
    if not direction_field_valid:
        defects.append(
            Defect(
                "structural_stop.anchor_direction",
                "anchor kind/source field does not face outward for the decision direction",
                f"{path}.anchor_kind",
            )
        )

    anchor_price = _json_number(basis.get("anchor_price"))
    certified_anchor = None
    if isinstance(observation, dict) and anchor_source_field:
        try:
            certified_anchor = _json_number(
                _resolve_concrete_value_path(observation, anchor_source_field)
            )
        except ValueError:
            certified_anchor = None
    if (
        anchor_price is None
        or certified_anchor is None
        or not _decimal_matches(anchor_price, certified_anchor)
    ):
        defects.append(
            Defect(
                "structural_stop.anchor_value",
                "anchor_price must equal the mechanically located certified TradingView field",
                f"{path}.anchor_price",
            )
        )

    zone_field = (
        ".structure_zones[" in anchor_source_field
        or ".volume_profile.zones[" in anchor_source_field
    )
    if zone_field and isinstance(observation, dict):
        zone_timeframe_field = re.sub(
            r"\.(?:upper_bound|lower_bound)$",
            ".timeframe",
            anchor_source_field,
        )
        try:
            certified_timeframe = _text(
                _resolve_concrete_value_path(observation, zone_timeframe_field)
            ).lower()
        except ValueError:
            certified_timeframe = ""
        if certified_timeframe != timeframe:
            defects.append(
                Defect(
                    "structural_stop.timeframe_binding",
                    "stop_basis timeframe differs from the certified structural zone",
                    f"{path}.timeframe",
                )
            )
        if ".structure_zones[" in anchor_source_field:
            zone_role_field = re.sub(
                r"\.(?:upper_bound|lower_bound)$",
                ".role",
                anchor_source_field,
            )
            try:
                certified_role = _text(
                    _resolve_concrete_value_path(observation, zone_role_field)
                )
            except ValueError:
                certified_role = ""
            allowed_roles = set(
                (policy.get("direction_allowed_structure_zone_roles") or {}).get(
                    direction,
                    [],
                )
            )
            if certified_role not in allowed_roles:
                defects.append(
                    Defect(
                        "structural_stop.structure_zone_role",
                        "structure-zone role is incompatible with the outward stop direction",
                        f"{path}.anchor_source_field",
                    )
                )

    if ".volume_profile.zones[" in anchor_source_field:
        profile = (
            observation.get("metrics", {}).get("volume_profile", {})
            if isinstance(observation, dict)
            else {}
        )
        if (
            profile.get("status") != "readable"
            or profile.get("source_mode") != "user_drawn_manual_only"
            or profile.get("platform_vrvp_used") is not False
            or profile.get("automated_values_used") is not False
        ):
            defects.append(
                Defect(
                    "structural_stop.manual_profile_not_certified",
                    "manual-profile stop anchor requires a readable user-drawn-only certified profile",
                    f"{path}.anchor_source_field",
                )
            )

    selected_zone = entry_zone_basis if isinstance(entry_zone_basis, dict) else {}
    return _validate_structural_stop_details(
        basis,
        claim=claim,
        claim_id=claim_id,
        defects=defects,
        direction=direction,
        entries=entries,
        observation_id=observation_id,
        path=path,
        policy=policy,
        selected_zone=selected_zone,
        anchor_kind=anchor_kind,
        anchor_price=anchor_price,
        anchor_source_field=anchor_source_field,
        timeframe=timeframe,
        stop=stop,
        zone_lower=zone_lower,
        zone_upper=zone_upper,
    )

def _validate_defense_plan(
    defense: Any,
    *,
    risk: Any,
    direction: str,
    policy: dict[str, Any],
    path: str = "maker.defense_plan",
) -> tuple[bool, list[Defect]]:
    """Recompute every prefill defense trigger from every fill combination."""

    defects: list[Defect] = []
    defense_policy = policy.get("defense_trigger_policy") or {}
    if not isinstance(defense, dict) or set(defense) != set(
        defense_policy.get("decision_required_fields") or []
    ):
        return False, [
            Defect(
                "defense.schema",
                "defense_plan differs from the authority-required exact field set",
                path,
            )
        ]
    if defense.get("mode") != defense_policy.get("decision_mode"):
        defects.append(
            Defect(
                "defense.mode",
                "defense_plan mode must use exact prefill scenario projection",
                f"{path}.mode",
            )
        )

    risk_payload = risk if isinstance(risk, dict) else {}
    entries_raw = risk_payload.get("entries") if isinstance(risk_payload.get("entries"), list) else []
    allocations_raw = (
        risk_payload.get("entry_allocations_pct")
        if isinstance(risk_payload.get("entry_allocations_pct"), list)
        else []
    )
    entries = [_json_number(value) for value in entries_raw]
    allocations = [_json_number(value) for value in allocations_raw]
    stop = _json_number(risk_payload.get("stop"))
    tp1 = _json_number(risk_payload.get("tp1"))
    tp2 = _json_number(risk_payload.get("tp2"))
    leverage = _json_number(risk_payload.get("leverage"))
    scenarios: list[dict[str, Any]] = []
    if (
        direction not in {"long", "short"}
        or not entries
        or len(entries) != len(allocations)
        or any(value is None or value <= 0 for value in entries + allocations)
        or stop is None
        or tp1 is None
        or tp2 is None
        or leverage is None
    ):
        defects.append(
            Defect(
                "defense.risk_inputs",
                "defense triggers require a complete numeric Maker risk plan",
                path,
            )
        )
    else:
        try:
            scenarios = maker_fill_scenarios(
                entries=[value for value in entries if value is not None],
                allocations=[value for value in allocations if value is not None],
                direction=direction,
                stop=stop,
                tp1=tp1,
                tp2=tp2,
                leverage=leverage,
            )
        except (ArithmeticError, InvalidOperation, ValueError):
            defects.append(
                Defect(
                    "defense.risk_geometry",
                    "defense triggers cannot be derived from invalid risk geometry",
                    path,
                )
            )

    prefill = defense.get("prefill_anchor")
    if not isinstance(prefill, dict) or set(prefill) != set(
        defense_policy.get("prefill_anchor_required_fields") or []
    ):
        defects.append(
            Defect(
                "defense.prefill_anchor_schema",
                "prefill_anchor differs from the authority-required field set",
                f"{path}.prefill_anchor",
            )
        )
        prefill = {}
    expected_full_fill = next(
        (
            _number(item.get("entry"))
            for item in scenarios
            if item.get("filled_level_indexes") == list(range(1, len(entries_raw) + 1))
        ),
        None,
    )
    if (
        prefill.get("kind") != defense_policy.get("prefill_anchor")
        or prefill.get("is_actual_fill") is not False
        or prefill.get("is_single_entry") is not False
        or not _decimal_matches(_json_number(prefill.get("weighted_fill")), expected_full_fill)
    ):
        defects.append(
            Defect(
                "defense.prefill_anchor",
                "prefill_anchor must be the mechanically recomputed full-ladder weighted fill, not an actual or single fill",
                f"{path}.prefill_anchor",
            )
        )

    trigger_rows = defense.get("trigger_scenarios")
    if not isinstance(trigger_rows, list):
        defects.append(
            Defect(
                "defense.trigger_scenarios_schema",
                "trigger_scenarios must be an array",
                f"{path}.trigger_scenarios",
            )
        )
        trigger_rows = []
    expected_by_id = {str(item["risk_scenario_id"]): item for item in scenarios}
    actual_ids = [
        _text(item.get("risk_scenario_id"))
        for item in trigger_rows
        if isinstance(item, dict)
    ]
    if (
        len(trigger_rows) != len(expected_by_id)
        or len(actual_ids) != len(set(actual_ids))
        or set(actual_ids) != set(expected_by_id)
    ):
        defects.append(
            Defect(
                "defense.trigger_scenario_coverage",
                "trigger_scenarios must cover every non-empty Maker fill combination exactly once",
                f"{path}.trigger_scenarios",
            )
        )
    required_trigger_fields = set(
        defense_policy.get("trigger_scenario_required_fields") or []
    )
    first_r = _number(defense_policy.get("first_r"))
    second_r = _number(defense_policy.get("second_r"))
    allowed_rounding = set(defense_policy.get("allowed_rounding_rules") or [])
    for index, row in enumerate(trigger_rows):
        row_path = f"{path}.trigger_scenarios[{index}]"
        if not isinstance(row, dict) or set(row) != required_trigger_fields:
            defects.append(
                Defect(
                    "defense.trigger_scenario_schema",
                    "trigger scenario differs from the authority-required field set",
                    row_path,
                )
            )
            continue
        scenario_id = _text(row.get("risk_scenario_id"))
        expected = expected_by_id.get(scenario_id)
        if expected is None:
            continue
        if row.get("filled_level_indexes") != expected.get("filled_level_indexes"):
            defects.append(
                Defect(
                    "defense.trigger_scenario_binding",
                    "filled_level_indexes do not match risk_scenario_id",
                    f"{row_path}.filled_level_indexes",
                )
            )
        weighted_fill = _number(expected.get("entry"))
        actual_weighted_fill = _json_number(row.get("weighted_fill"))
        if not _decimal_matches(actual_weighted_fill, weighted_fill):
            defects.append(
                Defect(
                    "defense.weighted_fill",
                    "weighted_fill differs from the risk-plan fill combination",
                    f"{row_path}.weighted_fill",
                )
            )
        if weighted_fill is None or stop is None or first_r is None or second_r is None:
            continue
        risk_distance = abs(stop - weighted_fill)
        expected_first_raw = (
            weighted_fill + first_r * risk_distance
            if direction == "long"
            else weighted_fill - first_r * risk_distance
        )
        expected_second_raw = (
            weighted_fill + second_r * risk_distance
            if direction == "long"
            else weighted_fill - second_r * risk_distance
        )
        first_raw = _canonical_positive_decimal_string(
            row.get("first_trigger_price_raw")
        )
        second_raw = _canonical_positive_decimal_string(
            row.get("second_trigger_price_raw")
        )
        if not _decimal_matches(first_raw, expected_first_raw) or not _decimal_matches(
            second_raw,
            expected_second_raw,
        ):
            defects.append(
                Defect(
                    "defense.trigger_raw_arithmetic",
                    "raw defense triggers do not match the direction-aware 1.5R/2R calculation",
                    row_path,
                )
            )
        rounding_rule = _text(row.get("rounding_rule"))
        rounding_step = (
            None
            if row.get("rounding_step") is None
            else _canonical_positive_decimal_string(row.get("rounding_step"))
        )
        if rounding_rule not in allowed_rounding:
            defects.append(
                Defect(
                    "defense.rounding_rule",
                    "rounding_rule is outside the closed authority vocabulary",
                    f"{row_path}.rounding_rule",
                )
            )
            continue
        if rounding_rule == "exact_no_rounding":
            if row.get("rounding_step") is not None:
                defects.append(
                    Defect(
                        "defense.rounding_step",
                        "exact_no_rounding requires a null rounding_step",
                        f"{row_path}.rounding_step",
                    )
                )
            expected_first = expected_first_raw
            expected_second = expected_second_raw
        else:
            if rounding_step is None or rounding_step <= 0:
                defects.append(
                    Defect(
                        "defense.rounding_step",
                        "nearest_step_half_up requires a positive Arabic-numeric rounding_step",
                        f"{row_path}.rounding_step",
                    )
                )
                continue
            expected_first = _round_to_step(expected_first_raw, rounding_step)
            expected_second = _round_to_step(expected_second_raw, rounding_step)
        first_final = _json_number(row.get("first_trigger_price"))
        second_final = _json_number(row.get("second_trigger_price"))
        if not _decimal_matches(first_final, expected_first) or not _decimal_matches(
            second_final,
            expected_second,
        ):
            defects.append(
                Defect(
                    "defense.trigger_final_arithmetic",
                    "final defense triggers are not reproducible from raw values and rounding rule",
                    row_path,
                )
            )
        directional_geometry = (
            direction == "long"
            and first_final is not None
            and second_final is not None
            and first_final > weighted_fill
            and second_final > first_final
        ) or (
            direction == "short"
            and first_final is not None
            and second_final is not None
            and first_final < weighted_fill
            and second_final < first_final
        )
        if not directional_geometry:
            defects.append(
                Defect(
                    "defense.trigger_direction",
                    "defense triggers point in the wrong direction or layer order",
                    row_path,
                )
            )

    postfill = defense.get("postfill_recalculation")
    if not isinstance(postfill, dict) or set(postfill) != set(
        defense_policy.get("postfill_recalculation_required_fields") or []
    ):
        defects.append(
            Defect(
                "defense.postfill_schema",
                "postfill_recalculation differs from the authority-required field set",
                f"{path}.postfill_recalculation",
            )
        )
        postfill = {}
    if (
        postfill.get("required") is not True
        or postfill.get("anchor") != defense_policy.get("postfill_anchor")
        or postfill.get("replace_prefill_projection") is not True
    ):
        defects.append(
            Defect(
                "defense.postfill_recalculation",
                "actual fill must uniquely replace prefill projections using actual_weighted_fill",
                f"{path}.postfill_recalculation",
            )
        )
    if defense.get("first_stop_rule") != defense_policy.get("first_stop_rule"):
        defects.append(
            Defect(
                "defense.first_stop_rule",
                "first layer must use a confirmed post-fill 4H structural extreme",
                f"{path}.first_stop_rule",
            )
        )
    if defense.get("second_action") != defense_policy.get("second_action"):
        defects.append(
            Defect(
                "defense.second_action",
                "second layer may only move the stop to breakeven",
                f"{path}.second_action",
            )
        )
    return not defects, defects

def _maker_risk_plan_constructible(
    risk: Any,
    *,
    direction: str,
    zone_lower: Decimal | None,
    zone_upper: Decimal | None,
    policy: dict[str, Any],
) -> bool:
    if not isinstance(risk, dict):
        return False
    expected_fields = {
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
    }
    if (
        set(risk) != expected_fields
        or direction not in {"long", "short"}
    ):
        return False
    entries = risk.get("entries") if isinstance(risk.get("entries"), list) else []
    allocations = risk.get("entry_allocations_pct") if isinstance(risk.get("entry_allocations_pct"), list) else []
    entry_values = [_number(value) for value in entries]
    allocation_values = [_number(value) for value in allocations]
    if not int(policy["minimum_entry_levels"]) <= len(entries) <= int(policy["maximum_entry_levels"]):
        return False
    if (
        any(value is None or value <= 0 for value in entry_values)
        or len(set(entry_values)) != len(entry_values)
        or zone_lower is None
        or zone_upper is None
        or any(value < zone_lower or value > zone_upper for value in entry_values if value is not None)
    ):
        return False
    if (
        len(allocations) != len(entries)
        or any(value is None or value <= 0 for value in allocation_values)
        or sum((value for value in allocation_values if value is not None), Decimal("0"))
        != _number(policy["entry_allocation_total_pct"])
    ):
        return False
    stop = _number(risk.get("stop"))
    tp1 = _number(risk.get("tp1"))
    tp2 = _number(risk.get("tp2"))
    leverage = _number(risk.get("leverage"))
    cancel_before_fill = _number(risk.get("cancel_before_fill"))
    if (
        stop is None
        or tp1 is None
        or tp2 is None
        or cancel_before_fill is None
        or leverage != _number(policy["maker_fixed_leverage"])
        or _number(risk.get("tp1_close_pct")) != _number(policy["tp1_close_pct"])
        or _number(risk.get("tp2_close_pct")) != _number(policy["tp2_close_pct"])
    ):
        return False
    try:
        scenarios = maker_fill_scenarios(
            entries=[value for value in entry_values if value is not None],
            allocations=[value for value in allocation_values if value is not None],
            direction=direction,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            leverage=leverage,
        )
    except (ArithmeticError, InvalidOperation, ValueError):
        return False
    minimum_rr = _number(policy["minimum_rr_to_tp1"])
    maximum_risk = _number(policy["maximum_nominal_risk_pct"])
    return bool(scenarios) and all(
        _number(item.get("rr_to_tp1")) is not None
        and _number(item.get("rr_to_tp1")) >= minimum_rr
        and _number(item.get("nominal_risk_pct")) is not None
        and _number(item.get("nominal_risk_pct")) <= maximum_risk
        for item in scenarios
    )

def decision_model_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("decision_sha256", None)
    return canonical_sha256(clean)

def _prepare_decision_validation(payload, reasoning, run, pretrade_gate, root, defects):
    policy = load_scoring_policy(root=root)
    maker_policy = policy["maker_score"]
    conviction_policy = policy["conviction"]
    risk_policy = policy["risk_execution"]
    reasoning_hash = reasoning_model_sha256(reasoning)
    expected_schema_version = REGISTRY.decision_model_schema_version
    if payload.get("schema_version") != expected_schema_version:
        defects.append(Defect("schema.invalid", f"expected {expected_schema_version}", "schema_version"))
    expected_top_fields = {
        "schema_version",
        "run_id",
        "run_sha256",
        "run_mode",
        "trading_date",
        "slot",
        "evidence_snapshot_sha256",
        "reasoning_sha256",
        "execution_authorization",
        "main_account",
        "maker",
        "continuity_contract",
    }
    if frozenset(payload) not in {
        frozenset(expected_top_fields),
        frozenset(expected_top_fields | {"decision_sha256"}),
    }:
        defects.append(
            Defect(
                "decision.schema_fields",
                "decision must contain the exact v7 field set",
                "decision",
            )
        )
    if run.get("schema_version") != "daily-run-vnext-v2":
        defects.append(
            Defect(
                "binding.run_schema",
                "decision v7 requires a sealed daily-run-vnext-v2 run",
                "run_sha256",
            )
        )
    for key in ("run_id", "run_sha256", "run_mode"):
        if payload.get(key) != run.get(key):
            defects.append(
                Defect(
                    "binding.run",
                    f"decision {key} differs from the sealed run",
                    key,
                )
            )
    for key in ("trading_date", "slot", "evidence_snapshot_sha256"):
        if payload.get(key) != reasoning.get(key):
            defects.append(Defect("binding.mismatch", f"decision {key} differs from reasoning", key))
    if payload.get("reasoning_sha256") != reasoning_hash:
        defects.append(Defect("binding.reasoning", "decision is not bound to reasoning", "reasoning_sha256"))
    run_mode = _text(run.get("run_mode"))
    authorization = (
        payload.get("execution_authorization")
        if isinstance(payload.get("execution_authorization"), dict)
        else {}
    )
    expected_authorization_fields = {
        "source_kind",
        "source_sha256",
        "live_execution_allowed",
        "reason_code",
    }
    if set(authorization) != expected_authorization_fields:
        defects.append(
            Defect(
                "execution_authorization.schema_fields",
                "execution_authorization must use the exact typed field set",
                "execution_authorization",
            )
        )
    live_execution_allowed = False
    if run_mode == "shadow":
        expected_authorization = {
            "source_kind": "sealed_shadow_run",
            "source_sha256": run.get("run_sha256"),
            "live_execution_allowed": False,
            "reason_code": "shadow_mode_forbids_live_execution",
        }
        if authorization != expected_authorization:
            defects.append(
                Defect(
                    "execution_authorization.shadow_boundary",
                    "shadow execution authorization must bind the sealed run and forbid live execution",
                    "execution_authorization",
                )
            )
        if pretrade_gate is not None:
            defects.append(
                Defect(
                    "execution_authorization.shadow_pretrade_forbidden",
                    "shadow decisions must not receive a pretrade or personal-state contract",
                    "execution_authorization.source_kind",
                )
            )
    elif run_mode == "production":
        gate_payload = pretrade_gate if isinstance(pretrade_gate, dict) else {}
        try:
            validate_pretrade_gate_contract(
                gate_payload,
                trading_date=str(payload.get("trading_date", "")),
            )
            gate_contract_valid = True
        except (TypeError, ValueError):
            gate_contract_valid = False
        gate_allowed = gate_payload.get("allow_trade_today") is True
        expected_reason = (
            "pretrade_gate_allows_live_execution"
            if gate_allowed
            else "pretrade_gate_blocks_live_execution"
        )
        expected_authorization = {
            "source_kind": "notion_pretrade_gate",
            "source_sha256": gate_payload.get("manifest_sha256"),
            "live_execution_allowed": gate_allowed,
            "reason_code": expected_reason,
        }
        if (
            not gate_contract_valid
            or not gate_payload
            or gate_payload.get("schema_version") != "pretrade-gate-vnext-v1"
            or gate_payload.get("source_kind") != "notion_pretrade_gate"
            or gate_payload.get("provenance_mode") != "live_notion_row"
            or gate_payload.get("trading_date") != payload.get("trading_date")
            or gate_payload.get("manifest_sha256") != canonical_sha256(gate_payload)
        ):
            defects.append(
                Defect(
                    "binding.pretrade_gate",
                    "production decision requires the same-day hash-valid vNext pretrade gate",
                    "execution_authorization.source_sha256",
                )
            )
        if authorization != expected_authorization:
            defects.append(
                Defect(
                    "execution_authorization.production_binding",
                    "production execution authorization differs from the certified pretrade gate",
                    "execution_authorization",
                )
            )
        live_execution_allowed = gate_allowed
    else:
        defects.append(
            Defect(
                "binding.run_mode",
                "sealed run_mode must be shadow or production",
                "run_mode",
            )
        )

    reasoning_observations = {
        _text(item.get("id")): item
        for item in reasoning.get("observations", [])
        if isinstance(item, dict) and _text(item.get("id"))
    }
    reasoning_claims = {
        _text(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, dict) and _text(item.get("id"))
    }
    observation_ids = set(reasoning_observations)

    def claim_sources(claim_ids: list[Any]) -> set[str]:
        observation_refs: set[str] = set()
        for claim_id in claim_ids:
            key = _text(claim_id)
            if key in reasoning_claims:
                observation_refs.update(
                    _reachable_observations(key, reasoning_claims, observation_ids)
                )
        return {
            _text(reasoning_observations[item].get("source"))
            for item in observation_refs
            if item in reasoning_observations
        }

    def validate_claim_refs(
        value: Any,
        *,
        path: str,
        required_type: str | None = None,
        required_source: str | None = None,
    ) -> list[str]:
        refs = value if isinstance(value, list) else []
        normalized = [_text(item) for item in refs if _text(item)]
        if not normalized:
            defects.append(Defect("decision.claim_refs_missing", "score or probability basis requires claim_ids", path))
            return []
        for claim_id in normalized:
            if claim_id not in reasoning_claims:
                defects.append(Defect("decision.claim_ref_unknown", f"unknown reasoning claim: {claim_id}", path))
                continue
            claim_account = _text(reasoning_claims[claim_id].get("account"))
            if claim_account not in {"shared", "maker"}:
                defects.append(
                    Defect(
                        "decision.cross_account_claim",
                        f"Maker decision basis cannot reference {claim_account} claim: {claim_id}",
                        path,
                    )
                )
        if required_type and not any(
            _text(reasoning_claims.get(claim_id, {}).get("claim_type")) == required_type
            for claim_id in normalized
        ):
            defects.append(Defect("decision.claim_type_missing", f"basis requires claim type: {required_type}", path))
        if required_source and required_source not in claim_sources(normalized):
            defects.append(Defect("decision.claim_source_missing", f"basis requires source: {required_source}", path))
        return normalized

    def reject_narrative_second_truth(value: Any, *, path: str) -> None:
        leak = _execution_parameter_leak(value)
        if leak:
            defects.append(
                Defect(
                    "decision.narrative_execution_second_truth",
                    f"narrative rationale cannot own execution parameters outside typed fields: {leak}",
                    path,
                )
            )
        if _score_second_truth(value):
            defects.append(
                Defect(
                    "decision.narrative_score_second_truth",
                    "narrative rationale cannot declare a second score",
                    path,
                )
            )
    return (maker_policy, conviction_policy, risk_policy, reasoning_hash, run_mode, live_execution_allowed, reasoning_observations, reasoning_claims, claim_sources, validate_claim_refs, reject_narrative_second_truth)


def _validate_main_account_decision(payload, reasoning, reasoning_claims, reasoning_observations, risk_policy, defects):
    main = payload.get("main_account") if isinstance(payload.get("main_account"), dict) else {}
    expected_main_fields = {
        "claim_id",
        "direction",
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
        "plan_state_reason_code",
    }
    if set(main) != expected_main_fields:
        defects.append(
            Defect(
                "main.schema_fields",
                "main_account must use the exact typed plan contract",
                "main_account",
            )
        )
    if main.get("plan_state") not in {"new", "iterate", "unchanged", "observe"}:
        defects.append(
            Defect(
                "main.plan_state_invalid",
                "main-account plan_state is invalid",
                "main_account.plan_state",
            )
        )
    expected_main_action = {
        "new": "build",
        "iterate": "iterate",
        "unchanged": "hold",
        "observe": "observe",
    }.get(_text(main.get("plan_state")))
    if main.get("action") != expected_main_action:
        defects.append(
            Defect(
                "main.action_drift",
                f"main-account action must be {expected_main_action}",
                "main_account.action",
            )
        )
    main_policy = risk_policy.get("main_account") if isinstance(risk_policy.get("main_account"), dict) else {}
    if main.get("exchange") != main_policy.get("exchange"):
        defects.append(Defect("main.exchange_drift", "main-account exchange differs from authority", "main_account.exchange"))
    if main.get("instrument") != main_policy.get("instrument"):
        defects.append(Defect("main.instrument_drift", "main-account instrument differs from authority", "main_account.instrument"))
    main_plan_active = main.get("plan_state") in {"new", "iterate", "unchanged"}
    if main_plan_active and main.get("direction") not in {"long", "short"}:
        defects.append(Defect("main.active_direction_invalid", "an active main-account plan requires long or short direction", "main_account.direction"))
    main_notional = _number(main.get("position_notional_usdt"))
    if main_plan_active and (
        main_notional is None
        or main_notional < _number(main_policy.get("minimum_position_notional_usdt"))
        or main_notional > _number(main_policy.get("maximum_position_notional_usdt"))
    ):
        defects.append(Defect("main.position_notional_invalid", "main-account position notional is outside the canonical range", "main_account.position_notional_usdt"))
    if main_plan_active and _number(main.get("leverage")) != _number(main_policy.get("fixed_leverage")):
        defects.append(Defect("main.leverage_drift", "main-account leverage differs from authority", "main_account.leverage"))
    if main_plan_active and main.get("entry_mode") != main_policy.get("entry_mode"):
        defects.append(Defect("main.entry_mode_drift", "main account must use staged ladder construction", "main_account.entry_mode"))
    main_entries = main.get("entries") if isinstance(main.get("entries"), list) else []
    main_entry_values = [_number(value) for value in main_entries]
    expected_main_levels = int(main_policy.get("entry_levels", 0) or 0)
    if main_plan_active and (
        len(main_entries) != expected_main_levels
        or any(value is None or value <= 0 for value in main_entry_values)
        or len(set(main_entry_values)) != len(main_entry_values)
    ):
        defects.append(Defect("main.entries_invalid", f"main account requires {expected_main_levels} distinct staged entries", "main_account.entries"))
    main_allocations = main.get("entry_allocations_pct") if isinstance(main.get("entry_allocations_pct"), list) else []
    expected_main_allocation = _number(main_policy.get("entry_allocation_each_pct"))
    if main_plan_active and (
        len(main_allocations) != expected_main_levels
        or any(_number(value) != expected_main_allocation for value in main_allocations)
    ):
        defects.append(Defect("main.allocations_invalid", "main-account entry allocations must be four equal 25% stages", "main_account.entry_allocations_pct"))
    main_zone_lower = None
    main_zone_upper = None
    if main_plan_active:
        (
            main_zone_lower,
            main_zone_upper,
            main_zone_status,
            _,
            _,
            _,
        ) = _resolve_tradingview_entry_zone(
            main.get("entry_zone_basis"),
            reasoning_observations,
            manual_profile_first=False,
        )
        if main_zone_status != "ok":
            defects.append(Defect("main.entry_zone_binding_invalid", f"main-account entry zone is not certified: {main_zone_status}", "main_account.entry_zone_basis"))
        elif any(
            value < main_zone_lower or value > main_zone_upper
            for value in main_entry_values
            if value is not None
        ):
            defects.append(Defect("main.entries_outside_zone", "every main-account entry must remain inside its certified TradingView zone", "main_account.entries"))
    main_stop = _number(main.get("stop"))
    main_tp1 = _number(main.get("tp1"))
    main_final_tp = _number(main.get("final_take_profit"))
    main_structural_stop_valid = False
    if main_plan_active:
        main_structural_stop_valid, main_stop_defects = _validate_structural_stop_basis(
            main.get("stop_basis"),
            direction=_text(main.get("direction")),
            stop=main_stop,
            zone_lower=main_zone_lower,
            zone_upper=main_zone_upper,
            entries=main_entry_values,
            entry_zone_basis=main.get("entry_zone_basis"),
            account="main",
            observations=reasoning_observations,
            claims=reasoning_claims,
            policy=risk_policy.get("main_initial_stop_policy") or {},
            path="main_account.stop_basis",
        )
        defects.extend(main_stop_defects)
    main_geometry_valid = False
    if main_plan_active and main_entry_values and all(value is not None for value in main_entry_values):
        short_geometry = main.get("direction") == "short" and (
            main_stop is not None
            and main_stop > max(main_entry_values)
            and main_tp1 is not None
            and main_tp1 < min(main_entry_values)
            and main_final_tp is not None
            and main_final_tp < main_tp1
        )
        long_geometry = main.get("direction") == "long" and (
            main_stop is not None
            and main_stop < min(main_entry_values)
            and main_tp1 is not None
            and main_tp1 > max(main_entry_values)
            and main_final_tp is not None
            and main_final_tp > main_tp1
        )
        main_geometry_valid = short_geometry or long_geometry
        if main.get("direction") == "short" and not short_geometry:
            defects.append(Defect("main.risk_geometry", "short main-account stop/TP geometry is invalid", "main_account"))
        if main.get("direction") == "long" and not long_geometry:
            defects.append(Defect("main.risk_geometry", "long main-account stop/TP geometry is invalid", "main_account"))
    main_leverage = _number(main.get("leverage"))
    main_allocation_values = [_number(value) for value in main_allocations]
    if (
        main_plan_active
        and main_structural_stop_valid
        and main_geometry_valid
        and main_stop is not None
        and main_tp1 is not None
        and main_final_tp is not None
        and main_leverage is not None
        and all(value is not None and value > 0 for value in main_entry_values)
        and all(value is not None and value > 0 for value in main_allocation_values)
    ):
        try:
            main_scenarios = maker_fill_scenarios(
                entries=[value for value in main_entry_values if value is not None],
                allocations=[value for value in main_allocation_values if value is not None],
                direction=_text(main.get("direction")),
                stop=main_stop,
                tp1=main_tp1,
                tp2=main_final_tp,
                leverage=main_leverage,
            )
        except (ArithmeticError, InvalidOperation, ValueError) as exc:
            defects.append(
                Defect(
                    "main.risk_scenario_invalid",
                    str(exc),
                    "main_account",
                )
            )
        else:
            maximum_main_risk = _number(main_policy.get("maximum_nominal_risk_pct"))
            for scenario in main_scenarios:
                nominal = _number(scenario.get("nominal_risk_pct"))
                if (
                    nominal is None
                    or maximum_main_risk is None
                    or nominal > maximum_main_risk
                ):
                    defects.append(
                        Defect(
                            "main.risk_above_8",
                            f"main-account nominal risk is {nominal}%, above the independent {main_policy.get('maximum_nominal_risk_pct')}% limit",
                            "main_account.fill_scenarios["
                            f"{scenario['risk_scenario_id']}]",
                        )
                    )
    if main_plan_active and _number(main.get("tp1_close_pct")) != _number(main_policy.get("tp1_close_pct")):
        defects.append(Defect("main.tp1_close_pct", "main-account TP1 must close the canonical 20%", "main_account.tp1_close_pct"))
    if not main_plan_active and (
        main.get("position_notional_usdt") not in {None, 0}
        or main.get("leverage") is not None
        or main.get("entry_mode") is not None
        or main.get("entry_zone_basis") is not None
        or main_entries
        or main_allocations
        or any(main.get(field) is not None for field in ("stop_basis", "stop", "tp1", "final_take_profit", "tp1_close_pct"))
    ):
        defects.append(Defect("main.observe_fabricated_plan", "an observing main account cannot fabricate position, entries, leverage, stop or targets", "main_account"))
    expected_main_reason = {
        "new": "new_typed_plan",
        "iterate": "iterated_typed_plan",
        "unchanged": "unchanged_typed_plan",
        "observe": "no_typed_plan",
    }.get(_text(main.get("plan_state")))
    if main.get("plan_state_reason_code") != expected_main_reason:
        defects.append(
            Defect(
                "main.plan_state_reason_drift",
                f"main-account plan_state_reason_code must be {expected_main_reason}",
                "main_account.plan_state_reason_code",
            )
        )

    main_counter_id = _text(main.get("counter_claim_id"))
    main_invalidation_id = _text(main.get("invalidation_claim_id"))
    if (
        _text(reasoning_claims.get(main_counter_id, {}).get("claim_type")) != "strongest_counterevidence"
        or _text(reasoning_claims.get(main_counter_id, {}).get("account")) != "main"
    ):
        defects.append(Defect("main.counter_binding", "main account must bind its own strongest counterevidence", "main_account.counter_claim_id"))
    if (
        _text(reasoning_claims.get(main_invalidation_id, {}).get("claim_type")) != "invalidation_path"
        or _text(reasoning_claims.get(main_invalidation_id, {}).get("account")) != "main"
    ):
        defects.append(Defect("main.invalidation_binding", "main account must bind its own invalidation path", "main_account.invalidation_claim_id"))
    reasoning_scenarios = {
        _text(item.get("id")): item
        for item in reasoning.get("scenario_tree", [])
        if isinstance(item, dict) and _text(item.get("id"))
    }
    main_scenario_ids = main.get("scenario_ids") if isinstance(main.get("scenario_ids"), list) else []
    main_scenario_types = {
        _text(reasoning_scenarios.get(_text(item), {}).get("scenario_type"))
        for item in main_scenario_ids
        if reasoning_scenarios.get(_text(item), {}).get("account") == "main"
    }
    if len(main_scenario_ids) != 3 or main_scenario_types != REQUIRED_SCENARIO_TYPES:
        defects.append(Defect("main.scenario_binding", "main account must bind exactly its base/counter/invalidation scenarios", "main_account.scenario_ids"))


def _prepare_maker_decision(payload, reasoning_claims, reasoning_hash, risk_policy, run, run_mode, defects):
    maker = payload.get("maker") if isinstance(payload.get("maker"), dict) else {}
    expected_maker_fields = {
        "claim_id",
        "combination_id",
        "direction",
        "plan_state",
        "threshold_eligible",
        "plan_constructible",
        "plan_constructibility",
        "execution_action",
        "order_transition_action",
        "strategy_type",
        "order_method",
        "entry_type",
        "exchange",
        "instrument",
        "position_notional_usdt",
        "cannot_do_code",
        "cannot_do_claim_id",
        "orderflow_score",
        "extreme_confirmed",
        "orderflow_scorecard",
        "chart_components",
        "chart_scorecard",
        "chart_score",
        "total_score",
        "win_rate",
        "entry_reach_probability",
        "entry_reach_probability_basis",
        "order_lifecycle",
        "winrate_rubric",
        "risk_plan",
        "defense_plan",
    }
    if set(maker) != expected_maker_fields:
        defects.append(
            Defect(
                "maker.schema_fields",
                "Maker decision must contain the exact typed field set; prose or representative-price second truths are forbidden",
                "maker",
            )
        )
    strategy_type = _text(maker.get("strategy_type"))
    if strategy_type not in set(risk_policy["maker_strategy_types"]):
        defects.append(
            Defect(
                "maker.strategy_type_invalid",
                "Maker strategy_type is outside the canonical vocabulary",
                "maker.strategy_type",
            )
        )
    if maker.get("order_method") != risk_policy["maker_order_method"]:
        defects.append(
            Defect(
                "maker.order_method_invalid",
                "Maker order_method must remain Maker",
                "maker.order_method",
            )
        )
    maker_exchange = _text(maker.get("exchange"))
    maker_instrument = _text(maker.get("instrument"))
    maker_position_notional = _number(maker.get("position_notional_usdt"))
    maker_direction = _text(maker.get("direction"))
    non_directional_maker = maker_direction == "observe"
    maker_instrument_policy = (
        risk_policy["maker_instruments"].get(maker_instrument)
        if isinstance(risk_policy.get("maker_instruments"), dict)
        else None
    )
    if maker_exchange != risk_policy["maker_exchange"]:
        defects.append(
            Defect(
                "maker.exchange_drift",
                "Maker exchange differs from the canonical execution venue",
                "maker.exchange",
            )
        )
    if not isinstance(maker_instrument_policy, dict):
        defects.append(
            Defect(
                "maker.instrument_invalid",
                "Maker instrument is outside the canonical execution set",
                "maker.instrument",
            )
        )
    elif maker_position_notional is not None and (
        maker_position_notional
        < _number(maker_instrument_policy["minimum_position_notional_usdt"])
        or maker_position_notional
        > _number(maker_instrument_policy["maximum_position_notional_usdt"])
    ):
        defects.append(
            Defect(
                "maker.position_notional_invalid",
                "Maker candidate notional is outside the instrument-specific canonical range",
                "maker.position_notional_usdt",
            )
        )
    cannot_do_code = _text(maker.get("cannot_do_code"))
    cannot_do_claim_id = _text(maker.get("cannot_do_claim_id"))
    cannot_do_claim = reasoning_claims.get(cannot_do_claim_id, {})
    if (
        cannot_do_code not in set(risk_policy["cannot_do_codes"])
        or cannot_do_claim.get("claim_type") != "cannot_do"
        or cannot_do_claim.get("account") != "maker"
        or _text(cannot_do_claim.get("prohibition")) != cannot_do_code
    ):
        defects.append(
            Defect(
                "cannot_do.binding_invalid",
                "Maker cannot_do_code must bind the certified standardized cannot_do claim",
                "maker.cannot_do_claim_id",
            )
        )
    if non_directional_maker and cannot_do_code != "追多空":
        defects.append(
            Defect(
                "cannot_do.non_directional_scope",
                "an observe Maker thesis must prohibit chasing either direction",
                "maker.cannot_do_code",
            )
        )

    continuity = (
        payload.get("continuity_contract")
        if isinstance(payload.get("continuity_contract"), dict)
        else {}
    )
    shadow_continuity = run_mode == "shadow"
    if shadow_continuity:
        expected_shadow_continuity = {
            "schema_version",
            "reasoning_sha256",
            "run_sha256",
            "live_state_read",
            "order_mutation_attempted",
            "execution_action",
            "plan_valid_until",
            "reason_code",
        }
        if set(continuity) != expected_shadow_continuity:
            defects.append(
                Defect(
                    "continuity.shadow_schema_fields",
                    "shadow continuity must use the exact no-live-state field set",
                    "continuity_contract",
                )
            )
        if (
            continuity.get("schema_version")
            != "shadow-execution-continuity-vnext-v1"
            or continuity.get("reasoning_sha256") != reasoning_hash
            or continuity.get("run_sha256") != run.get("run_sha256")
            or continuity.get("live_state_read") is not False
            or continuity.get("order_mutation_attempted") is not False
            or continuity.get("execution_action") != "not_attempted"
            or continuity.get("reason_code")
            != "shadow_mode_forbids_live_execution"
        ):
            defects.append(
                Defect(
                    "continuity.shadow_boundary",
                    "shadow continuity must prove no personal-state read and no order mutation",
                    "continuity_contract",
                )
            )
        # Reuse the mature plan-validity checks below through a non-persisted
        # validation view.  This object is never written and makes no external
        # assertion about actual orders or personal state.
        continuity = {
            "schema_version": "post-reasoning-continuity-contract-vnext-v1",
            "reasoning_sha256": reasoning_hash,
            "prior_plan": {
                "source_kind": "none",
                "reference": "",
                "source_sha256": "",
                "observed_at": None,
                "status": "none",
                "executed_pct": 0,
                "executable_order_count_before": 0,
                "daily_trade_count_before": 0,
                "summary": "影子运行不读取个人状态，本对象仅用于内部验证计划有效期。",
            },
            "current_plan": {
                "action": "observe",
                "old_order_cancelled": False,
                "new_order_created": False,
                "executable_order_count_after": 0,
                "executed_pct": 0,
                "daily_trade_count_after": 0,
                "valid_until": payload.get("continuity_contract", {}).get(
                    "plan_valid_until"
                ),
                "independent_analysis_changed_after_lock": False,
                "reason": "影子运行只验证候选计划，未读取或改变任何真实订单状态。",
            },
        }
    expected_continuity_fields = {
        "schema_version",
        "reasoning_sha256",
        "prior_plan",
        "current_plan",
    }
    if set(continuity) != expected_continuity_fields:
        defects.append(
            Defect(
                "continuity.schema_fields",
                "continuity_contract must use the exact post-reasoning field set",
                "continuity_contract",
            )
        )
    if continuity.get("schema_version") != "post-reasoning-continuity-contract-vnext-v1":
        defects.append(
            Defect(
                "continuity.schema_invalid",
                "continuity_contract schema is invalid",
                "continuity_contract.schema_version",
            )
        )
    if continuity.get("reasoning_sha256") != reasoning_hash:
        defects.append(
            Defect(
                "continuity.reasoning_binding",
                "continuity_contract must bind the independently sealed reasoning",
                "continuity_contract.reasoning_sha256",
            )
        )
    return (maker, strategy_type, maker_position_notional, maker_direction, non_directional_maker, cannot_do_code, continuity)


def _validate_decision_continuity(continuity, defects, payload, reasoning_observations, risk_policy, root):
    prior = continuity.get("prior_plan") if isinstance(continuity.get("prior_plan"), dict) else {}
    expected_prior_fields = {
        "source_kind",
        "reference",
        "source_sha256",
        "observed_at",
        "status",
        "executed_pct",
        "executable_order_count_before",
        "daily_trade_count_before",
        "summary",
    }
    if set(prior) != expected_prior_fields:
        defects.append(
            Defect(
                "continuity.prior_schema",
                "prior_plan field set is invalid",
                "continuity_contract.prior_plan",
            )
        )
    source_kind = _text(prior.get("source_kind"))
    prior_status = _text(prior.get("status"))
    reference = _text(prior.get("reference"))
    source_sha = _text(prior.get("source_sha256")).lower()
    observed_at = prior.get("observed_at")
    if source_kind not in {"none", "local_artifact"}:
        defects.append(Defect("continuity.source_kind", "prior_plan source_kind is invalid", "continuity_contract.prior_plan.source_kind"))
    if prior_status not in CONTINUITY_PRIOR_STATUSES:
        defects.append(Defect("continuity.prior_status", "prior_plan status is invalid", "continuity_contract.prior_plan.status"))
    if source_kind == "none":
        if (
            prior_status != "none"
            or reference
            or source_sha
            or observed_at is not None
            or prior.get("executable_order_count_before") != 0
            or prior.get("daily_trade_count_before") != 0
        ):
            defects.append(
                Defect(
                    "continuity.none_source_fabricated",
                    "no prior plan must not carry source metadata or a non-none status",
                    "continuity_contract.prior_plan",
                )
            )
    elif source_kind == "local_artifact":
        source_payload: dict[str, Any] | None = None
        try:
            source_path = (root / reference).resolve()
            source_path.relative_to(root.resolve())
            source_valid = source_path.is_file() and sha256_file(source_path) == source_sha
            if source_valid:
                loaded = json.loads(source_path.read_text(encoding="utf-8"))
                source_payload = loaded if isinstance(loaded, dict) else None
        except (OSError, ValueError):
            source_valid = False
        if not source_valid:
            defects.append(
                Defect(
                    "continuity.local_source_invalid",
                    "prior local artifact is missing, outside the repository or hash-mismatched",
                    "continuity_contract.prior_plan",
                )
            )
        if _parse_iso_datetime(observed_at) is None:
            defects.append(Defect("continuity.observed_at", "prior observation time must be timezone-aware", "continuity_contract.prior_plan.observed_at"))
        expected_snapshot_fields = {
            "schema_version",
            "source_reference",
            "observed_at",
            "status",
            "executed_pct",
            "executable_order_count",
            "daily_trade_count",
            "summary",
        }
        if (
            not isinstance(source_payload, dict)
            or set(source_payload) != expected_snapshot_fields
            or source_payload.get("schema_version") != "prior-plan-snapshot-vnext-v1"
            or source_payload.get("observed_at") != observed_at
            or source_payload.get("status") != prior_status
            or source_payload.get("executed_pct") != prior.get("executed_pct")
            or source_payload.get("executable_order_count") != prior.get("executable_order_count_before")
            or source_payload.get("daily_trade_count") != prior.get("daily_trade_count_before")
            or _text(source_payload.get("summary")) != _text(prior.get("summary"))
            or not _text(source_payload.get("source_reference"))
        ):
            defects.append(
                Defect(
                    "continuity.snapshot_binding_invalid",
                    "prior-plan fields must equal the hash-bound standardized local snapshot",
                    "continuity_contract.prior_plan",
                )
            )
    before = prior.get("executable_order_count_before")
    if not isinstance(before, int) or isinstance(before, bool) or before not in {0, 1}:
        defects.append(Defect("continuity.before_count", "at most one prior system Maker order may exist", "continuity_contract.prior_plan.executable_order_count_before"))
    elif before != (1 if prior_status in {"pending", "open"} else 0):
        defects.append(Defect("continuity.prior_order_geometry", "prior status and executable order count are inconsistent", "continuity_contract.prior_plan"))
    prior_executed_pct = prior.get("executed_pct")
    prior_daily_trade_count = prior.get("daily_trade_count_before")
    if not isinstance(prior_executed_pct, int) or isinstance(prior_executed_pct, bool) or not 0 <= prior_executed_pct <= 100:
        defects.append(Defect("continuity.prior_executed_pct", "prior executed_pct must be an integer within 0..100", "continuity_contract.prior_plan.executed_pct"))
    elif (
        (prior_status in {"none", "pending", "cancelled", "stopped", "expired"} and prior_executed_pct != 0)
        or (prior_status == "open" and not 1 <= prior_executed_pct <= 99)
        or (prior_status == "filled" and prior_executed_pct != 100)
    ):
        defects.append(Defect("continuity.prior_execution_state", "prior status and executed_pct are inconsistent", "continuity_contract.prior_plan"))
    if not isinstance(prior_daily_trade_count, int) or isinstance(prior_daily_trade_count, bool) or not 0 <= prior_daily_trade_count <= risk_policy["maker_daily_trade_limit"]:
        defects.append(Defect("continuity.prior_daily_trade_count", "prior daily trade count is invalid", "continuity_contract.prior_plan.daily_trade_count_before"))
    if len(_text(prior.get("summary"))) < 12 or not _contains_cjk(prior.get("summary")):
        defects.append(Defect("continuity.prior_summary", "prior plan requires a Chinese-readable summary", "continuity_contract.prior_plan.summary"))

    current = continuity.get("current_plan") if isinstance(continuity.get("current_plan"), dict) else {}
    expected_current_fields = {
        "action",
        "old_order_cancelled",
        "new_order_created",
        "executable_order_count_after",
        "executed_pct",
        "daily_trade_count_after",
        "valid_until",
        "independent_analysis_changed_after_lock",
        "reason",
    }
    if set(current) != expected_current_fields:
        defects.append(Defect("continuity.current_schema", "current_plan field set is invalid", "continuity_contract.current_plan"))
    continuity_action = _text(current.get("action"))
    after = current.get("executable_order_count_after")
    old_cancelled = current.get("old_order_cancelled") is True
    new_created = current.get("new_order_created") is True
    current_executed_pct = current.get("executed_pct")
    daily_trade_count = current.get("daily_trade_count_after")
    valid_until = _parse_iso_datetime(current.get("valid_until"))
    if continuity_action not in CONTINUITY_ACTIONS:
        defects.append(Defect("continuity.action", "current continuity action is invalid", "continuity_contract.current_plan.action"))
    if not isinstance(after, int) or isinstance(after, bool) or after not in {0, 1}:
        defects.append(Defect("continuity.after_count", "at most one system Maker order may remain", "continuity_contract.current_plan.executable_order_count_after"))
    if not isinstance(current_executed_pct, int) or isinstance(current_executed_pct, bool) or not 0 <= current_executed_pct <= 100:
        defects.append(Defect("continuity.current_executed_pct", "current executed_pct must be an integer within 0..100", "continuity_contract.current_plan.executed_pct"))
    if not isinstance(daily_trade_count, int) or isinstance(daily_trade_count, bool) or not 0 <= daily_trade_count <= risk_policy["maker_daily_trade_limit"]:
        defects.append(Defect("continuity.daily_trade_limit", "Maker daily trade count exceeds the canonical limit", "continuity_contract.current_plan.daily_trade_count_after"))
    elif daily_trade_count != prior_daily_trade_count:
        defects.append(Defect("continuity.daily_trade_count_drift", "decision continuity cannot invent a trade execution that is absent from the prior snapshot", "continuity_contract.current_plan.daily_trade_count_after"))
    if valid_until is None:
        defects.append(Defect("continuity.valid_until", "current plan valid_until must be timezone-aware", "continuity_contract.current_plan.valid_until"))
    elif valid_until.astimezone(timezone(timedelta(hours=8))).date().isoformat() != payload.get("trading_date"):
        defects.append(Defect("continuity.valid_date", "Maker plan validity must remain inside the trading date", "continuity_contract.current_plan.valid_until"))
    else:
        observation_times = [
            parsed
            for parsed in (
                _parse_iso_datetime(item.get("observed_at"))
                for item in reasoning_observations.values()
            )
            if parsed is not None
        ]
        if observation_times and valid_until <= max(observation_times):
            defects.append(Defect("continuity.already_expired", "Maker plan validity must extend beyond the latest certified observation", "continuity_contract.current_plan.valid_until"))
    if current.get("independent_analysis_changed_after_lock") is not False:
        defects.append(Defect("continuity.analysis_mutation", "continuity must not change locked analysis", "continuity_contract.current_plan.independent_analysis_changed_after_lock"))
    if len(_text(current.get("reason"))) < 12 or not _contains_cjk(current.get("reason")):
        defects.append(Defect("continuity.reason", "continuity action requires a Chinese-readable reason", "continuity_contract.current_plan.reason"))
    if continuity_action == "new" and not (before == 0 and new_created and not old_cancelled and after == 1 and current_executed_pct == 0):
        defects.append(Defect("continuity.new_invalid", "new requires no prior order, one new unfilled order and no cancellation", "continuity_contract.current_plan"))
    if continuity_action == "keep" and not (before == 1 and not old_cancelled and not new_created and after == 1 and current_executed_pct == prior_executed_pct):
        defects.append(Defect("continuity.keep_invalid", "keep requires one unchanged prior order", "continuity_contract.current_plan"))
    if continuity_action == "cancel_replace" and not (before == 1 and old_cancelled and new_created and after == 1 and current_executed_pct == 0):
        defects.append(Defect("continuity.replace_invalid", "cancel_replace requires cancellation and one new unfilled order", "continuity_contract.current_plan"))
    if continuity_action == "cancel" and not (
        before == 1
        and old_cancelled
        and not new_created
        and after == 0
        and current_executed_pct == prior_executed_pct
    ):
        defects.append(Defect("continuity.cancel_invalid", "cancel requires one prior order to be cancelled with no replacement", "continuity_contract.current_plan"))
    if continuity_action == "observe" and not (
        before == 0
        and prior_status not in {"pending", "open"}
        and not old_cancelled
        and not new_created
        and after == 0
    ):
        defects.append(Defect("continuity.observe_invalid", "observe is legal only when no active prior order exists; an active order must be cancelled or reconciled explicitly", "continuity_contract.current_plan"))
    if continuity_action == "reconcile_filled" and not (
        prior_status == "filled"
        and before == 0
        and prior_executed_pct == 100
        and not old_cancelled
        and not new_created
        and after == 0
        and current_executed_pct == 100
    ):
        defects.append(Defect("continuity.reconcile_invalid", "reconcile_filled is legal only for a fully filled prior plan with no active order; an open remainder must be kept, cancelled or explicitly replaced", "continuity_contract.current_plan"))
    return (after, continuity_action)


def _validate_decision_scorecard(claim_sources, conviction_policy, defects, maker, maker_policy, reasoning, reasoning_claims, reasoning_observations, validate_claim_refs):
    orderflow = maker.get("orderflow_score")
    if not isinstance(orderflow, int) or isinstance(orderflow, bool):
        defects.append(Defect("score.orderflow_type", "orderflow score must be an integer", "maker.orderflow_score"))
        orderflow = 0
    if not (0 <= orderflow <= 70):
        defects.append(Defect("score.orderflow_range", "orderflow score must be within 0..70", "maker.orderflow_score"))
    certified_orderflow = certified_orderflow_assessment(reasoning)
    if certified_orderflow is None:
        defects.append(Defect("score.orderflow_certification_missing", "decision requires exactly one certified orderflow score assessment", "maker.orderflow_score"))
    else:
        if orderflow != certified_orderflow.get("score"):
            defects.append(Defect("score.orderflow_semantic_drift", "decision orderflow score differs from the certified interpretation", "maker.orderflow_score"))
        if maker.get("extreme_confirmed") != certified_orderflow.get("extreme_confirmed"):
            defects.append(Defect("score.extreme_semantic_drift", "decision extreme flag differs from the certified interpretation", "maker.extreme_confirmed"))
    extreme = maker.get("extreme_confirmed") is True
    if orderflow in set(maker_policy["orderflow"].get("legal_score_domain", {}).get("reserved_invalid", [])):
        defects.append(Defect("score.reserved_invalid", "orderflow scores 61..69 are reserved_invalid", "maker.orderflow_score"))
    if orderflow == 70 and not extreme:
        defects.append(Defect("score.extreme_unconfirmed", "orderflow 70 requires extreme_confirmed", "maker.extreme_confirmed"))
    if not extreme and orderflow > maker_policy["orderflow"]["non_extreme_max"]:
        defects.append(Defect("score.non_extreme_overflow", "non-extreme orderflow score exceeds 60", "maker.orderflow_score"))
    if extreme and orderflow != maker_policy["orderflow"]["extreme_score"]:
        defects.append(Defect("score.extreme_value", "extreme_confirmed is only valid for the exact extreme score", "maker.orderflow_score"))
    combination_id = _text(maker.get("combination_id"))
    if extreme and combination_id not in set(maker_policy["orderflow"]["extreme_candidate_combinations"]):
        defects.append(Defect("score.extreme_combination", "extreme score requires an approved extreme combination", "maker.combination_id"))
    observed_combinations = {
        _text((item.get("metrics") or {}).get("combination_id"))
        for item in reasoning_observations.values()
        if item.get("source") == "Coinglass" and isinstance(item.get("metrics"), dict)
    }
    observed_combinations.discard("")
    if len(observed_combinations) != 1 or combination_id not in observed_combinations:
        defects.append(Defect("score.combination_binding", "Maker combination_id must equal the certified Coinglass observation", "maker.combination_id"))

    orderflow_scorecard = (
        maker.get("orderflow_scorecard")
        if isinstance(maker.get("orderflow_scorecard"), dict)
        else {}
    )
    if set(orderflow_scorecard) != {"score", "claim_ids"}:
        defects.append(
            Defect(
                "score.orderflow_scorecard_schema",
                "orderflow scorecard must contain only score and typed claim_ids",
                "maker.orderflow_scorecard",
            )
        )
    if orderflow_scorecard.get("score") != orderflow:
        defects.append(Defect("score.orderflow_scorecard", "orderflow scorecard must repeat the certified orderflow score", "maker.orderflow_scorecard.score"))
    orderflow_claim_ids = validate_claim_refs(
        orderflow_scorecard.get("claim_ids"),
        path="maker.orderflow_scorecard.claim_ids",
        required_type="maker_thesis",
    )
    orderflow_sources = claim_sources(orderflow_claim_ids)
    for required_source in ("Coinglass", "Exocharts"):
        if required_source not in orderflow_sources:
            defects.append(Defect("score.orderflow_source_missing", f"orderflow scorecard requires {required_source}", "maker.orderflow_scorecard.claim_ids"))

    components = maker.get("chart_components") if isinstance(maker.get("chart_components"), dict) else {}
    expected_components = maker_policy["chart"]["components"]
    if set(components) != set(expected_components):
        defects.append(Defect("score.chart_components", "chart component set differs from scoring contract", "maker.chart_components"))
    certified_components = certified_chart_components(reasoning)
    if certified_components is None:
        defects.append(Defect("score.chart_certification_missing", "decision requires exactly one certified TradingView chart scorecard", "maker.chart_components"))
    elif components != certified_components:
        defects.append(Defect("score.chart_semantic_drift", "decision chart components differ from the certified TradingView assessment", "maker.chart_components"))
    chart_total = 0
    for name, maximum in expected_components.items():
        value = components.get(name, 0)
        if not isinstance(value, int) or isinstance(value, bool):
            defects.append(Defect("score.chart_type", f"{name} must be an integer", f"maker.chart_components.{name}"))
            continue
        if not 0 <= value <= maximum:
            defects.append(Defect("score.chart_range", f"{name} must be within 0..{maximum}", f"maker.chart_components.{name}"))
        chart_total += value
    chart_scorecard = (
        maker.get("chart_scorecard")
        if isinstance(maker.get("chart_scorecard"), dict)
        else {}
    )
    if set(chart_scorecard) != set(expected_components):
        defects.append(Defect("score.chart_scorecard_components", "chart scorecard component set differs from scoring contract", "maker.chart_scorecard"))
    tradingview_metrics = next(
        (
            item.get("metrics")
            for item in reasoning_observations.values()
            if item.get("source") == "TradingView" and isinstance(item.get("metrics"), dict)
        ),
        {},
    )
    tradingview_timeframes = (
        tradingview_metrics.get("timeframes")
        if isinstance(tradingview_metrics, dict)
        and isinstance(tradingview_metrics.get("timeframes"), dict)
        else {}
    )
    expected_sma_relations: dict[str, str] = {}
    for timeframe in ("1d", "4h", "1h"):
        values = tradingview_timeframes.get(timeframe)
        price = _number(values.get("price")) if isinstance(values, dict) else None
        sma20 = _number(values.get("sma20")) if isinstance(values, dict) else None
        expected_sma_relations[timeframe] = (
            "unavailable"
            if price is None or sma20 is None
            else "above"
            if price > sma20
            else "below"
            if price < sma20
            else "equal"
        )
    for name in expected_components:
        basis = chart_scorecard.get(name) if isinstance(chart_scorecard.get(name), dict) else {}
        expected_basis_fields = (
            {"score", "claim_ids", "timeframe_relations"}
            if name == "chart.sma20_interaction"
            else {"score", "claim_ids"}
        )
        if set(basis) != expected_basis_fields:
            defects.append(
                Defect(
                    "score.chart_scorecard_schema",
                    f"{name} scorecard differs from its closed typed field set",
                    f"maker.chart_scorecard.{name}",
                )
            )
        if basis.get("score") != components.get(name):
            defects.append(Defect("score.chart_scorecard_value", f"{name} scorecard must equal chart component score", f"maker.chart_scorecard.{name}.score"))
        if (
            name == "chart.sma20_interaction"
            and basis.get("timeframe_relations") != expected_sma_relations
        ):
            defects.append(
                Defect(
                    "score.sma20_relation_drift",
                    "SMA20 relations must be mechanically derived from certified TradingView price and SMA20 values",
                    f"maker.chart_scorecard.{name}.timeframe_relations",
                )
            )
        validate_claim_refs(
            basis.get("claim_ids"),
            path=f"maker.chart_scorecard.{name}.claim_ids",
            required_type="liquidity_hunt" if name == "chart.liquidity_hunt" else None,
            required_source="TradingView",
        )
    if maker.get("chart_score") != chart_total:
        defects.append(Defect("score.chart_sum", "chart_score must equal chart component sum", "maker.chart_score"))
    claimed_total = maker.get("total_score")
    if not isinstance(claimed_total, int) or isinstance(claimed_total, bool):
        defects.append(Defect("score.total_type", "total_score must be an integer", "maker.total_score"))
        claimed_total_value = 0
    else:
        claimed_total_value = claimed_total
    if claimed_total != orderflow + chart_total:
        defects.append(Defect("score.total_sum", "total_score must equal orderflow + chart", "maker.total_score"))

    win_rate = maker.get("win_rate")
    if not isinstance(win_rate, int) or isinstance(win_rate, bool) or not 0 <= win_rate <= 100:
        defects.append(Defect("winrate.invalid", "win_rate must be an integer within 0..100", "maker.win_rate"))
        win_rate = 0
    rubric = maker.get("winrate_rubric") if isinstance(maker.get("winrate_rubric"), dict) else {}
    expected_rubric_fields = {
        "anchor",
        "anchor_claim_ids",
        "anchor_rationale",
        "adjustments",
        "signal_dispositions",
        "counter_resolution",
        "final",
    }
    if set(rubric) != expected_rubric_fields:
        defects.append(
            Defect(
                "winrate.rubric_schema",
                "winrate rubric must use the exact anchor/adjustment/disposition/counter-resolution field set",
                "maker.winrate_rubric",
            )
        )
    anchor = rubric.get("anchor")
    if not isinstance(anchor, int) or isinstance(anchor, bool) or not 0 <= anchor <= 100:
        defects.append(Defect("winrate.anchor_invalid", "winrate rubric anchor must be an integer within 0..100", "maker.winrate_rubric.anchor"))
        anchor_value = 0
    else:
        anchor_value = anchor
    anchor_claim_ids = validate_claim_refs(
        rubric.get("anchor_claim_ids"),
        path="maker.winrate_rubric.anchor_claim_ids",
    )
    if len(anchor_claim_ids) != len(set(anchor_claim_ids)):
        defects.append(
            Defect(
                "winrate.anchor_claim_duplicate",
                "winrate anchor claim ids must be unique",
                "maker.winrate_rubric.anchor_claim_ids",
            )
        )
    anchor_policy = (
        conviction_policy.get("anchor_policy")
        if isinstance(conviction_policy.get("anchor_policy"), dict)
        else {}
    )
    canonical_anchor_rationale = _text(anchor_policy.get("canonical_rationale"))
    if (
        not canonical_anchor_rationale
        or rubric.get("anchor_rationale") != canonical_anchor_rationale
    ):
        defects.append(
            Defect(
                "winrate.anchor_rationale_not_canonical",
                "winrate anchor rationale must equal the authority-owned canonical explanation; free-text market claims are forbidden",
                "maker.winrate_rubric.anchor_rationale",
            )
        )
    allowed_anchor_accounts = set(anchor_policy.get("allowed_claim_accounts") or [])
    forbidden_anchor_types = set(anchor_policy.get("forbidden_claim_types") or [])
    optional_anchor_types = set(anchor_policy.get("optional_claim_types") or [])
    axis_types = anchor_policy.get("required_claim_types_by_axis") or {}
    axis_sources = anchor_policy.get("required_reachable_sources_by_axis") or {}
    allowed_anchor_types = optional_anchor_types | {
        _text(claim_type)
        for values in axis_types.values()
        for claim_type in (values if isinstance(values, list) else [])
    }
    for claim_id in anchor_claim_ids:
        claim = reasoning_claims.get(claim_id) or {}
        claim_type = _text(claim.get("claim_type"))
        claim_account = _text(claim.get("account"))
        if (
            claim_account not in allowed_anchor_accounts
            or claim_type in forbidden_anchor_types
            or claim_type not in allowed_anchor_types
            or (claim_type == "invalidation_path" and claim_account != "maker")
        ):
            defects.append(
                Defect(
                    "winrate.anchor_claim_forbidden",
                    "winrate anchor binds a forbidden claim type or account",
                    "maker.winrate_rubric.anchor_claim_ids",
                )
            )
    for axis, allowed_types in axis_types.items():
        axis_claim_ids = [
            claim_id
            for claim_id in anchor_claim_ids
            if _text((reasoning_claims.get(claim_id) or {}).get("claim_type"))
            in set(allowed_types or [])
        ]
        if not axis_claim_ids:
            defects.append(
                Defect(
                    "winrate.anchor_axis_missing",
                    f"winrate anchor lacks required axis: {axis}",
                    "maker.winrate_rubric.anchor_claim_ids",
                )
            )
            continue
        missing_axis_sources = set(axis_sources.get(axis) or []) - claim_sources(
            axis_claim_ids
        )
        if missing_axis_sources:
            defects.append(
                Defect(
                    "winrate.anchor_source_unreachable",
                    f"winrate anchor axis is missing source(s): {sorted(missing_axis_sources)}",
                    "maker.winrate_rubric.anchor_claim_ids",
                )
            )
    return (orderflow, certified_orderflow, chart_total, claimed_total_value, win_rate, rubric, anchor_claim_ids, anchor_value)


def _validate_decision_adjustments(anchor_claim_ids, claim_sources, conviction_policy, defects, maker, maker_direction, reasoning_claims, reasoning_observations, reject_narrative_second_truth, rubric, validate_claim_refs):
    maker_direction = _text(maker.get("direction"))
    adjustment_policy = (
        conviction_policy.get("adjustment_policy")
        if isinstance(conviction_policy.get("adjustment_policy"), dict)
        else {}
    )
    adjustment_fields = set(
        adjustment_policy.get("required_adjustment_fields") or []
    )
    reason_policies = (
        adjustment_policy.get("reason_codes")
        if isinstance(adjustment_policy.get("reason_codes"), dict)
        else {}
    )
    raw_adjustments = rubric.get("adjustments")
    if not isinstance(raw_adjustments, list):
        defects.append(
            Defect(
                "winrate.adjustments_invalid",
                "winrate adjustments must be an array",
                "maker.winrate_rubric.adjustments",
            )
        )
        adjustments = []
    else:
        adjustments = raw_adjustments
    required_first_reason_code = _text(
        adjustment_policy.get("required_first_reason_code")
    )
    if (
        not required_first_reason_code
        or not adjustments
        or not isinstance(adjustments[0], dict)
        or _text(adjustments[0].get("reason_code"))
        != required_first_reason_code
    ):
        defects.append(
            Defect(
                "winrate.counter_adjustment_order",
                "the current Maker strongest-counter adjustment must be the first adjustment before any ETF or fundamental realization adjustment",
                "maker.winrate_rubric.adjustments",
            )
        )
    adjustment_total = 0
    seen_reason_codes: set[str] = set()
    seen_adjustment_claim_ids: set[str] = set()
    seen_typed_owner_signatures: set[tuple[str, str, str]] = set()
    for index, item in enumerate(adjustments):
        path = f"maker.winrate_rubric.adjustments[{index}]"
        if not isinstance(item, dict):
            defects.append(Defect("winrate.adjustment_invalid", "winrate adjustment must be an object", path))
            continue
        if not adjustment_fields or set(item) != adjustment_fields:
            defects.append(
                Defect(
                    "winrate.adjustment_schema",
                    "winrate adjustment must use the exact closed reason-code field set",
                    path,
                )
            )
        reason_code = _text(item.get("reason_code"))
        reason_policy = reason_policies.get(reason_code)
        if not isinstance(reason_policy, dict):
            defects.append(
                Defect(
                    "winrate.reason_code_invalid",
                    "winrate adjustment reason_code is outside the closed policy",
                    f"{path}.reason_code",
                )
            )
            reason_policy = {}
        if reason_code in seen_reason_codes:
            defects.append(
                Defect(
                    "winrate.reason_code_duplicate",
                    "winrate adjustment reason_code must be unique",
                    f"{path}.reason_code",
                )
            )
        seen_reason_codes.add(reason_code)
        delta = item.get("delta")
        if (
            not isinstance(delta, int)
            or isinstance(delta, bool)
            or delta == 0
        ):
            defects.append(Defect("winrate.adjustment_delta", "winrate adjustment delta must be a non-zero integer", f"{path}.delta"))
        else:
            adjustment_total += delta
            expected_sign = _text(reason_policy.get("delta_sign"))
            if (
                (expected_sign == "positive" and delta <= 0)
                or (expected_sign == "negative" and delta >= 0)
                or expected_sign not in {"positive", "negative"}
            ):
                defects.append(
                    Defect(
                        "winrate.adjustment_sign",
                        "winrate adjustment delta sign differs from reason_code policy",
                        f"{path}.delta",
                    )
                )
        if len(_text(item.get("label"))) < 2 or len(_text(item.get("rationale"))) < 8 or not _contains_cjk(item.get("rationale")):
            defects.append(Defect("winrate.adjustment_rationale", "winrate adjustment requires label and Chinese-readable rationale", path))
        reject_narrative_second_truth(item.get("label"), path=f"{path}.label")
        reject_narrative_second_truth(item.get("rationale"), path=f"{path}.rationale")
        claim_ids = validate_claim_refs(
            item.get("claim_ids"), path=f"{path}.claim_ids"
        )
        if len(claim_ids) != len(set(claim_ids)):
            defects.append(
                Defect(
                    "winrate.adjustment_claim_duplicate",
                    "winrate adjustment claim ids must be unique",
                    f"{path}.claim_ids",
                )
            )
        if set(claim_ids) & seen_adjustment_claim_ids:
            defects.append(
                Defect(
                    "winrate.adjustment_claim_reused",
                    "the same claim cannot drive multiple winrate adjustments",
                    f"{path}.claim_ids",
                )
            )
        if set(claim_ids) & set(anchor_claim_ids):
            defects.append(
                Defect(
                    "winrate.anchor_adjustment_overlap",
                    "the same direct claim cannot drive both anchor and adjustment",
                    f"{path}.claim_ids",
                )
            )
        seen_adjustment_claim_ids.update(claim_ids)
        bound_claims = [
            reasoning_claims[claim_id]
            for claim_id in claim_ids
            if claim_id in reasoning_claims
        ]
        allowed_claim_types = set(reason_policy.get("allowed_claim_types") or [])
        if allowed_claim_types and any(
            _text(claim.get("claim_type")) not in allowed_claim_types
            for claim in bound_claims
        ):
            defects.append(
                Defect(
                    "winrate.adjustment_claim_type",
                    "winrate adjustment binds a claim type outside its reason_code policy",
                    f"{path}.claim_ids",
                )
            )
        required_claim_account = _text(reason_policy.get("required_claim_account"))
        if required_claim_account and any(
            _text(claim.get("account")) != required_claim_account
            for claim in bound_claims
        ):
            defects.append(
                Defect(
                    "winrate.adjustment_claim_account",
                    "winrate adjustment binds a claim from the wrong account",
                    f"{path}.claim_ids",
                )
            )
        reachable_sources = claim_sources(claim_ids)
        missing_sources = set(
            reason_policy.get("required_reachable_sources") or []
        ) - reachable_sources
        if missing_sources:
            defects.append(
                Defect(
                    "winrate.adjustment_source_unreachable",
                    f"winrate adjustment claim DAG is missing required source(s): {sorted(missing_sources)}",
                    f"{path}.claim_ids",
                )
            )
        relation_values: list[Any] = []
        typed_owner_mode = _text(reason_policy.get("typed_value_owner_mode"))
        for owner_index, owner_spec in enumerate(
            reason_policy.get("typed_value_owners") or []
        ):
            owner_path = f"{path}.typed_value_owners[{owner_index}]"
            if not isinstance(owner_spec, dict):
                defects.append(
                    Defect(
                        "winrate.typed_owner_policy_invalid",
                        "winrate typed owner policy is invalid",
                        owner_path,
                    )
                )
                continue
            owner_type = _text(owner_spec.get("owner_type"))
            field = _text(owner_spec.get("field"))
            found = False
            value: Any = None
            owner_id = ""
            if owner_type == "observation":
                source = _text(owner_spec.get("source"))
                candidates = [
                    observation
                    for observation in reasoning_observations.values()
                    if observation.get("source") == source
                ]
                if len(candidates) == 1 and source in reachable_sources:
                    found, value = _nested_value(
                        candidates[0].get("metrics") or {}, field
                    )
                    owner_id = _text(candidates[0].get("id"))
            elif owner_type == "claim":
                claim_type = _text(owner_spec.get("claim_type"))
                candidates = [
                    claim
                    for claim in bound_claims
                    if claim.get("claim_type") == claim_type
                ]
                if len(candidates) == 1:
                    found, value = _nested_value(candidates[0], field)
                    owner_id = _text(candidates[0].get("id"))
            if not found:
                defects.append(
                    Defect(
                        "winrate.typed_owner_missing",
                        "winrate adjustment cannot resolve its typed current owner from the bound claim DAG",
                        owner_path,
                    )
                )
                continue
            signature = (owner_type, owner_id, field)
            if signature in seen_typed_owner_signatures:
                defects.append(
                    Defect(
                        "winrate.typed_owner_reused",
                        "the same typed owner cannot drive multiple winrate adjustments",
                        owner_path,
                    )
                )
            seen_typed_owner_signatures.add(signature)
            if (
                owner_spec.get("value_contract") != "certified_source_schema"
                and value not in set(owner_spec.get("allowed_values") or [])
            ):
                defects.append(
                    Defect(
                        "winrate.typed_value_invalid",
                        "winrate adjustment typed value is outside its reason_code policy",
                        owner_path,
                    )
                )
            relation_values.append(value)
        if (
            reason_policy
            and not relation_values
            and typed_owner_mode != "selected_current_basis_clauses"
        ):
            defects.append(
                Defect(
                    "winrate.typed_values_missing",
                    "winrate adjustment reason_code requires typed current values",
                    path,
                )
            )
        direction_relation = _text(
            reason_policy.get("typed_value_relation_to_maker_direction")
        )
        if direction_relation:
            typed_direction = {
                "bullish": "long",
                "bearish": "short",
            }.get(_text(relation_values[0]) if relation_values else "")
            relation_valid = (
                typed_direction == maker_direction
                if direction_relation == "same"
                else typed_direction != maker_direction
                if direction_relation == "opposite_or_nonconfirming"
                else False
            )
            if not relation_valid:
                defects.append(
                    Defect(
                        "winrate.adjustment_direction_relation",
                        "winrate adjustment typed direction does not satisfy its reason_code relation to Maker",
                        path,
                    )
                )
    return (adjustment_total, adjustments, seen_typed_owner_signatures)


def _validate_decision_dispositions(adjustment_total, adjustments, anchor_value, conviction_policy, defects, reasoning, reasoning_claims, rubric, seen_typed_owner_signatures, win_rate):
    disposition_policy = (
        conviction_policy.get("secondary_signal_disposition_policy")
        if isinstance(
            conviction_policy.get("secondary_signal_disposition_policy"), dict
        )
        else {}
    )
    disposition_fields = set(disposition_policy.get("required_fields") or [])
    signal_specs = (
        disposition_policy.get("signals")
        if isinstance(disposition_policy.get("signals"), dict)
        else {}
    )
    raw_dispositions = rubric.get("signal_dispositions")
    dispositions = raw_dispositions if isinstance(raw_dispositions, list) else []
    if not isinstance(raw_dispositions, list):
        defects.append(
            Defect(
                "winrate.signal_dispositions_invalid",
                "secondary signal dispositions must be an array",
                "maker.winrate_rubric.signal_dispositions",
            )
        )
    seen_signal_types: set[str] = set()
    for index, item in enumerate(dispositions):
        path = f"maker.winrate_rubric.signal_dispositions[{index}]"
        if not isinstance(item, dict) or set(item) != disposition_fields:
            defects.append(
                Defect(
                    "winrate.signal_disposition_schema",
                    "secondary signal disposition must use the exact closed field set",
                    path,
                )
            )
            continue
        signal_type = _text(item.get("signal_type"))
        claim_id = _text(item.get("claim_id"))
        disposition = _text(item.get("disposition"))
        spec = signal_specs.get(signal_type)
        if not isinstance(spec, dict) or signal_type in seen_signal_types:
            defects.append(
                Defect(
                    "winrate.signal_disposition_coverage",
                    "each authority-owned secondary signal must appear exactly once",
                    path,
                )
            )
            continue
        seen_signal_types.add(signal_type)
        claim = reasoning_claims.get(claim_id) or {}
        if claim.get("claim_type") != signal_type or claim.get("account") != "shared":
            defects.append(
                Defect(
                    "winrate.signal_disposition_binding",
                    "signal disposition must bind the unique shared typed signal claim",
                    f"{path}.claim_id",
                )
            )
        signal_field = _text(spec.get("value_field"))
        signal_value = claim.get(signal_field)
        reason_by_value = spec.get("adjustment_reason_by_value") or {}
        expected_reason_code = (
            _text(reason_by_value.get(signal_value))
            if isinstance(reason_by_value, dict)
            else ""
        )
        required_disposition = _text((spec or {}).get("required_disposition"))
        required_no_adjustment_reason = _text(
            (spec or {}).get("required_no_adjustment_reason_code")
        )
        if required_disposition and disposition != required_disposition:
            defects.append(
                Defect(
                    "winrate.signal_observation_only",
                    "this secondary signal is observation-only and must use its closed no-adjustment disposition",
                    path,
                )
            )
        matching_adjustments = [
            adjustment
            for adjustment in adjustments
            if isinstance(adjustment, dict)
            and list(adjustment.get("claim_ids") or []) == [claim_id]
        ]
        if disposition == "adjusted":
            if (
                not expected_reason_code
                or item.get("adjustment_reason_code") != expected_reason_code
                or item.get("no_adjustment_reason_code") is not None
                or len(matching_adjustments) != 1
                or matching_adjustments[0].get("reason_code") != expected_reason_code
            ):
                defects.append(
                    Defect(
                        "winrate.signal_adjustment_mismatch",
                        "an adjusted secondary signal must bind exactly one correctly signed typed adjustment",
                        path,
                    )
                )
        elif disposition == "no_adjustment":
            no_adjustment_reason = _text(item.get("no_adjustment_reason_code"))
            allowed_reasons = set(
                disposition_policy.get("allowed_no_adjustment_reason_codes") or []
            )
            neutral_reason_valid = (
                no_adjustment_reason != "neutral_signal"
                or not expected_reason_code
            )
            if (
                item.get("adjustment_reason_code") is not None
                or no_adjustment_reason not in allowed_reasons
                or not neutral_reason_valid
                or (
                    required_no_adjustment_reason
                    and no_adjustment_reason != required_no_adjustment_reason
                )
                or matching_adjustments
            ):
                defects.append(
                    Defect(
                        "winrate.signal_no_adjustment_invalid",
                        "no_adjustment requires a closed reason and must not hide an existing adjustment",
                        path,
                    )
                )
        else:
            defects.append(
                Defect(
                    "winrate.signal_disposition_invalid",
                    "secondary signal disposition must be adjusted or no_adjustment",
                    f"{path}.disposition",
                )
            )
    if seen_signal_types != set(signal_specs):
        defects.append(
            Defect(
                "winrate.signal_disposition_coverage",
                "ETF and fundamental realization signals must each have one explicit disposition",
                "maker.winrate_rubric.signal_dispositions",
            )
        )

    counter_policy = (
        conviction_policy.get("counter_resolution_policy")
        if isinstance(conviction_policy.get("counter_resolution_policy"), dict)
        else {}
    )
    counter_resolution = (
        rubric.get("counter_resolution")
        if isinstance(rubric.get("counter_resolution"), dict)
        else {}
    )
    required_counter_fields = set(counter_policy.get("required_fields") or [])
    if not required_counter_fields or set(counter_resolution) != required_counter_fields:
        defects.append(
            Defect(
                "winrate.counter_resolution_schema",
                "Maker counter resolution must use the exact closed field set",
                "maker.winrate_rubric.counter_resolution",
            )
        )
    account_separation = (
        (reasoning.get("methodology") or {}).get("account_separation")
        if isinstance((reasoning.get("methodology") or {}).get("account_separation"), dict)
        else {}
    )
    expected_counter_id = _text(account_separation.get("maker_counter_claim_id"))
    counter_claim_id = _text(counter_resolution.get("counter_claim_id"))
    counter_claim = reasoning_claims.get(counter_claim_id) or {}
    if (
        not expected_counter_id
        or counter_claim_id != expected_counter_id
        or counter_claim.get("claim_type") != "strongest_counterevidence"
        or counter_claim.get("account") != "maker"
    ):
        defects.append(
            Defect(
                "winrate.counter_resolution_binding",
                "Maker counter resolution must bind the methodology-owned Maker counter",
                "maker.winrate_rubric.counter_resolution.counter_claim_id",
            )
        )
    disposition = _text(counter_resolution.get("disposition"))
    if disposition not in set(counter_policy.get("allowed_dispositions") or []):
        defects.append(
            Defect(
                "winrate.counter_resolution_disposition",
                "Maker counter resolution disposition is invalid",
                "maker.winrate_rubric.counter_resolution.disposition",
            )
        )
    adjusted_reason_code = _text(counter_policy.get("adjusted_reason_code"))
    counter_adjustments = [
        item
        for item in adjustments
        if isinstance(item, dict)
        and _text(item.get("reason_code")) == adjusted_reason_code
    ]
    residual_indexes = counter_resolution.get("residual_clause_indexes")
    resolution_claim_ids = counter_resolution.get("resolution_claim_ids")
    if not isinstance(residual_indexes, list) or not isinstance(
        resolution_claim_ids, list
    ):
        defects.append(
            Defect(
                "winrate.counter_resolution_arrays",
                "Maker counter resolution arrays are invalid",
                "maker.winrate_rubric.counter_resolution",
            )
        )
        residual_indexes = []
        resolution_claim_ids = []
    if disposition == "adjusted":
        indexes_are_ints = all(
            isinstance(index, int) and not isinstance(index, bool)
            for index in residual_indexes
        )
        if (
            counter_resolution.get("adjustment_reason_code") != adjusted_reason_code
            or len(counter_adjustments) != 1
            or list(counter_adjustments[0].get("claim_ids") or [])
            != [counter_claim_id]
            or resolution_claim_ids != []
            or not residual_indexes
            or not indexes_are_ints
            or (
                indexes_are_ints
                and len(set(residual_indexes)) != len(residual_indexes)
            )
        ):
            defects.append(
                Defect(
                    "winrate.counter_adjustment_mismatch",
                    "adjusted Maker counter must bind exactly one closed residual adjustment",
                    "maker.winrate_rubric.counter_resolution",
                )
            )
        clauses = ((counter_claim.get("current_basis") or {}).get("clauses") or [])
        if residual_indexes != list(range(len(clauses))):
            defects.append(
                Defect(
                    "winrate.counter_residual_coverage",
                    "Maker counter residual clauses must cover current_basis in order",
                    "maker.winrate_rubric.counter_resolution.residual_clause_indexes",
                )
            )
        for index in residual_indexes if indexes_are_ints else []:
            if index < 0 or index >= len(clauses):
                defects.append(
                    Defect(
                        "winrate.counter_residual_index",
                        "Maker counter residual clause index is outside current_basis",
                        "maker.winrate_rubric.counter_resolution.residual_clause_indexes",
                    )
                )
                continue
            clause = clauses[index]
            signature = (
                _text(clause.get("owner_type")),
                _text(clause.get("owner_id")),
                _text(clause.get("field")),
            )
            if signature in seen_typed_owner_signatures:
                defects.append(
                    Defect(
                        "winrate.typed_owner_reused",
                        "Maker counter residual clause reuses a typed owner",
                        "maker.winrate_rubric.counter_resolution.residual_clause_indexes",
                    )
                )
            seen_typed_owner_signatures.add(signature)
    if rubric.get("final") != win_rate or anchor_value + adjustment_total != win_rate:
        defects.append(Defect("winrate.rubric_final", "winrate rubric final must equal win_rate", "maker.winrate_rubric.final"))


def _prepare_decision_risk(claimed_total_value, conviction_policy, defects, maker, maker_direction, maker_policy, maker_position_notional, non_directional_maker, reasoning_claims, reasoning_observations, risk_policy, validate_claim_refs, win_rate):
    entry_reach_probability = maker.get("entry_reach_probability")
    execution_basis = maker.get("entry_reach_probability_basis") if isinstance(maker.get("entry_reach_probability_basis"), dict) else {}
    expected_execution_basis_fields = {
        "applicability",
        "claim_ids",
        "reference_source",
        "reference_timeframe",
        "reference_price",
        "reference_entry",
        "entry_distance",
        "reach_direction",
    }
    if set(execution_basis) != expected_execution_basis_fields:
        defects.append(
            Defect(
                "entry_reach_probability.schema_fields",
                "entry-price-reach probability basis must use the exact typed applicability and geometry field set",
                "maker.entry_reach_probability_basis",
            )
        )
    validate_claim_refs(
        execution_basis.get("claim_ids"),
        path="maker.entry_reach_probability_basis.claim_ids",
        required_type="maker_thesis",
    )

    direction = maker_direction
    risk = maker.get("risk_plan") if isinstance(maker.get("risk_plan"), dict) else {}
    required_risk_fields = {
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
    }
    if risk and set(risk) != required_risk_fields:
        defects.append(
            Defect(
                "risk.schema_fields",
                "a typed Maker candidate risk_plan must contain the exact field set",
                "maker.risk_plan",
            )
        )
    cancel_before_fill_value = _number(risk.get("cancel_before_fill"))
    if risk and (
        cancel_before_fill_value is None or cancel_before_fill_value <= 0
    ):
        defects.append(
            Defect(
                "risk.cancel_before_fill_invalid",
                "cancel_before_fill must be a positive Arabic-numeric price",
                "maker.risk_plan.cancel_before_fill",
            )
        )
    submitted_entry_values = (
        risk.get("entries") if isinstance(risk.get("entries"), list) else None
    )
    if risk and (
        not submitted_entry_values
        or any(
            _number(value) is None or _number(value) <= 0
            for value in submitted_entry_values
        )
    ):
        defects.append(
            Defect(
                "risk.entry_invalid",
                "every submitted Maker entry must be a positive Arabic-numeric price",
                "maker.risk_plan.entries",
            )
        )
    expected_threshold_eligible = (
        claimed_total_value >= maker_policy["threshold"]
        and win_rate >= conviction_policy["threshold"]
    )
    if maker.get("threshold_eligible") is not expected_threshold_eligible:
        defects.append(
            Defect(
                "maker.threshold_eligibility_drift",
                f"threshold_eligible must be {expected_threshold_eligible}",
                "maker.threshold_eligible",
            )
        )

    constructibility = (
        maker.get("plan_constructibility")
        if isinstance(maker.get("plan_constructibility"), dict)
        else {}
    )
    expected_constructibility_fields = {
        "status",
        "primary_reason_code",
        "failure_codes",
        "entry_zone_basis",
        "claim_ids",
    }
    if set(constructibility) != expected_constructibility_fields:
        defects.append(
            Defect(
                "maker.plan_constructibility_schema",
                "plan_constructibility must use the exact typed field set",
                "maker.plan_constructibility",
            )
        )
    constructibility_claim_ids = validate_claim_refs(
        constructibility.get("claim_ids"),
        path="maker.plan_constructibility.claim_ids",
        required_type="maker_thesis",
        required_source="TradingView",
    )
    constructibility_claim_types = {
        _text(reasoning_claims.get(claim_id, {}).get("claim_type"))
        for claim_id in constructibility_claim_ids
    }
    for required_type in {
        "maker_thesis",
        "strongest_counterevidence",
        "invalidation_path",
    } - constructibility_claim_types:
        defects.append(
            Defect(
                "maker.plan_constructibility_claim_missing",
                f"plan constructibility requires Maker {required_type}",
                "maker.plan_constructibility.claim_ids",
            )
        )

    tradingview_rows = [
        item
        for item in reasoning_observations.values()
        if _text(item.get("source")) == "TradingView"
    ]
    available_manual_zones: list[Any] = []
    available_structure_zones: list[Any] = []
    if len(tradingview_rows) == 1:
        tv_metrics = tradingview_rows[0].get("metrics") if isinstance(tradingview_rows[0].get("metrics"), dict) else {}
        tv_profile = tv_metrics.get("volume_profile") if isinstance(tv_metrics.get("volume_profile"), dict) else {}
        if tv_profile.get("status") == "readable" and isinstance(tv_profile.get("zones"), list):
            available_manual_zones = tv_profile.get("zones")
        tv_chart_basis = tv_metrics.get("chart_basis") if isinstance(tv_metrics.get("chart_basis"), dict) else {}
        if isinstance(tv_chart_basis.get("structure_zones"), list):
            available_structure_zones = tv_chart_basis.get("structure_zones")
    certified_zone_available = bool(available_manual_zones or available_structure_zones)
    if non_directional_maker and maker.get("position_notional_usdt") is not None:
        defects.append(
            Defect(
                "maker.non_directional_notional_forbidden",
                "an observe thesis has no Maker candidate notional",
                "maker.position_notional_usdt",
            )
        )
    elif (
        not non_directional_maker
        and maker_position_notional is None
        and (risk or certified_zone_available)
    ):
        defects.append(
            Defect(
                "maker.position_notional_invalid",
                "a submitted Maker candidate requires an instrument-valid notional",
                "maker.position_notional_usdt",
            )
        )
    if (
        maker_position_notional is not None
        and not risk
        and not certified_zone_available
    ):
        defects.append(
            Defect(
                "maker.zone_absent_notional_fabrication",
                "a run with no certified entry zone cannot fabricate candidate notional",
                "maker.position_notional_usdt",
            )
        )
    (
        zone_lower,
        zone_upper,
        zone_status,
        zone_kind,
        zone_role,
        zone_timeframe,
    ) = _resolve_tradingview_entry_zone(
        constructibility.get("entry_zone_basis"),
        reasoning_observations,
        manual_profile_first=True,
    )
    entry_zone_basis = constructibility.get("entry_zone_basis")
    if non_directional_maker and entry_zone_basis is not None:
        defects.append(
            Defect(
                "maker.non_directional_entry_zone_forbidden",
                "an observe thesis must use null entry_zone_basis",
                "maker.plan_constructibility.entry_zone_basis",
            )
        )
    elif not non_directional_maker and (
        not isinstance(entry_zone_basis, dict)
        or set(entry_zone_basis)
        != {"observation_id", "zone_kind", "zone_index"}
    ):
        defects.append(
            Defect(
                "maker.entry_zone_basis_schema",
                "entry_zone_basis must use the exact closed reference field set",
                "maker.plan_constructibility.entry_zone_basis",
            )
        )
    entry_type = _text(maker.get("entry_type"))
    if (
        non_directional_maker
        and entry_type != risk_policy.get("maker_non_directional_entry_type")
    ):
        defects.append(
            Defect(
                "maker.non_directional_entry_type",
                "an observe thesis must use entry_type=not_applicable",
                "maker.entry_type",
            )
        )
    if non_directional_maker and risk:
        defects.append(
            Defect(
                "maker.non_directional_risk_forbidden",
                "an observe thesis cannot submit a directional risk candidate",
                "maker.risk_plan",
            )
        )
    maker_stop = _number(risk.get("stop"))
    maker_stop_entries = [
        _number(value)
        for value in (
            risk.get("entries") if isinstance(risk.get("entries"), list) else []
        )
    ]
    maker_structural_stop_valid, maker_stop_defects = _validate_structural_stop_basis(
        risk.get("stop_basis"),
        direction=direction,
        stop=maker_stop,
        zone_lower=zone_lower,
        zone_upper=zone_upper,
        entries=maker_stop_entries,
        entry_zone_basis=constructibility.get("entry_zone_basis"),
        account="maker",
        observations=reasoning_observations,
        claims=reasoning_claims,
        policy=risk_policy.get("maker_initial_stop_policy") or {},
        path="maker.risk_plan.stop_basis",
    )
    if risk:
        # A structurally unusable candidate may still be sealed as observe, but
        # the decision stage may never rewrite or replace the reasoning-owned
        # stop identity, owner, buffer provenance, or exact-copy values.  Treat
        # those mechanical ownership breaches as a malformed decision
        # submission instead of a business non-constructibility result;
        # otherwise a model can make the mutation, self-report
        # structural_stop_invalid, and receive a green attempt.
        hard_stop_defect_codes = {
            "structural_stop.schema",
            "structural_stop.observation_binding",
            "structural_stop.claim_binding",
            "structural_stop.claim_evidence_binding",
            "structural_stop.buffer_basis_code",
            "structural_stop.buffer_claim_binding",
            "structural_stop.buffer_backsolve_forbidden",
            "structural_stop.buffer_reasoning_binding",
        }
        defects.extend(
            defect
            for defect in maker_stop_defects
            if defect.code in hard_stop_defect_codes
        )
    risk_plan_valid = _maker_risk_plan_constructible(
        risk,
        direction=direction,
        zone_lower=zone_lower,
        zone_upper=zone_upper,
        policy=risk_policy,
    )
    defense = maker.get("defense_plan") if isinstance(maker.get("defense_plan"), dict) else {}
    if non_directional_maker and defense:
        defects.append(
            Defect(
                "maker.non_directional_defense_forbidden",
                "an observe thesis cannot submit a directional defense plan",
                "maker.defense_plan",
            )
        )
    required_defense_fields = set(
        (risk_policy.get("defense_trigger_policy") or {}).get(
            "decision_required_fields"
        )
        or []
    )
    if defense and set(defense) != required_defense_fields:
        defects.append(
            Defect(
                "defense.schema",
                "a typed Maker candidate defense_plan must contain the exact field set",
                "maker.defense_plan",
            )
        )
    return (entry_reach_probability, execution_basis, direction, risk, required_risk_fields, expected_threshold_eligible, constructibility, tradingview_rows, certified_zone_available, zone_lower, zone_upper, zone_status, zone_kind, zone_role, entry_type, maker_stop_entries, maker_structural_stop_valid, risk_plan_valid, defense)


def _validate_decision_risk_certification(cannot_do_code, certified_zone_available, constructibility, continuity_action, defects, defense, direction, entry_reach_probability, entry_type, execution_basis, expected_threshold_eligible, live_execution_allowed, maker, maker_stop_entries, maker_structural_stop_valid, non_directional_maker, risk, risk_plan_valid, risk_policy, run_mode, strategy_type, tradingview_rows, zone_kind, zone_lower, zone_role, zone_status, zone_upper):
    if risk_plan_valid:
        defense_plan_valid, defense_plan_defects = _validate_defense_plan(
            defense,
            risk=risk,
            direction=direction,
            policy=risk_policy,
        )
        defense_schema_codes = {
            "defense.schema",
            "defense.prefill_anchor_schema",
            "defense.trigger_scenarios_schema",
            "defense.trigger_scenario_schema",
            "defense.postfill_schema",
        }
        defects.extend(
            defect
            for defect in defense_plan_defects
            if defect.code in defense_schema_codes
        )
    else:
        defense_plan_valid, defense_plan_defects = False, []
        if defense:
            defects.append(
                Defect(
                    "defense.unavailable_for_invalid_risk",
                    "defense_plan must be empty when candidate risk geometry is invalid",
                    "maker.defense_plan",
                )
            )
    reference_source = _text(execution_basis.get("reference_source"))
    reference_timeframe = _text(execution_basis.get("reference_timeframe"))
    reference_price = _number(execution_basis.get("reference_price"))
    reference_entry = _number(execution_basis.get("reference_entry"))
    entry_distance = _number(execution_basis.get("entry_distance"))
    reach_direction = _text(execution_basis.get("reach_direction"))
    certified_reference_price = None
    if len(tradingview_rows) == 1:
        metrics = tradingview_rows[0].get("metrics")
        timeframes = metrics.get("timeframes") if isinstance(metrics, dict) else {}
        one_hour = timeframes.get("1h") if isinstance(timeframes, dict) else {}
        certified_reference_price = _number(
            one_hour.get("price") if isinstance(one_hour, dict) else None
        )
    probability_applicability = _text(execution_basis.get("applicability"))
    probability_entries_are_certified = (
        zone_status == "ok"
        and zone_lower is not None
        and zone_upper is not None
        and bool(maker_stop_entries)
        and all(
            value is not None
            and value > 0
            and zone_lower <= value <= zone_upper
            for value in maker_stop_entries
        )
    )
    probability_is_applicable = bool(
        probability_entries_are_certified
        and direction in {"long", "short"}
        and certified_reference_price is not None
    )
    expected_probability_applicability = (
        "applicable"
        if probability_is_applicable
        else "not_applicable_no_certified_entry_geometry"
    )
    if probability_applicability != expected_probability_applicability:
        defects.append(
            Defect(
                "entry_reach_probability.applicability_drift",
                f"entry-price-reach probability applicability must be {expected_probability_applicability}",
                "maker.entry_reach_probability_basis.applicability",
            )
        )
    if probability_is_applicable:
        if (
            not isinstance(entry_reach_probability, int)
            or isinstance(entry_reach_probability, bool)
            or not 0 <= entry_reach_probability <= 100
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.invalid",
                    "an applicable entry_reach_probability must be an integer within 0..100",
                    "maker.entry_reach_probability",
                )
            )
        if (
            reference_source != "TradingView"
            or reference_timeframe != "1h"
            or reference_price is None
            or reference_price != certified_reference_price
            or reference_entry is None
            or entry_distance is None
            or reach_direction not in {"up_to_entry", "down_to_entry", "at_entry"}
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.applicable_geometry_incomplete",
                    "an applicable entry-price-reach probability requires complete certified TradingView 1h reach geometry",
                    "maker.entry_reach_probability_basis",
                )
            )
    else:
        if (
            reference_source != "TradingView" or reference_timeframe != "1h"
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.reference_contract",
                    "a non-applicable probability basis must still identify the certified TradingView 1h reference",
                    "maker.entry_reach_probability_basis",
                )
            )
        if (
            reference_price is None
            or certified_reference_price is None
            or reference_price != certified_reference_price
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.reference_price",
                    "reference_price must equal the certified TradingView 1h price even when entry reach is not applicable",
                    "maker.entry_reach_probability_basis.reference_price",
                )
            )
        if entry_reach_probability is not None:
            defects.append(
                Defect(
                    "entry_reach_probability.not_applicable_value",
                    "a non-applicable entry-price-reach probability must be null, never a numeric sentinel",
                    "maker.entry_reach_probability",
                )
            )
        if (
            reference_entry is not None
            or entry_distance is not None
            or bool(reach_direction)
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.not_applicable_geometry",
                    "a non-applicable entry-price-reach probability must not fabricate entry reach geometry",
                    "maker.entry_reach_probability_basis",
                )
            )
    expected_reach = expected_reach_direction(reference_price, reference_entry)
    right_entry_constructible = bool(
        (risk_policy.get("right_entry_confirmation_policy") or {}).get(
            "constructible_in_decision_model_v7"
        )
    )
    maker_entry_geometry_ready = (
        direction in {"long", "short"}
        and reference_price is not None
        and bool(maker_stop_entries)
        and all(value is not None for value in maker_stop_entries)
    )
    resting_order_valid = (
        resting_maker_order_valid(
            direction=direction,
            reference_price=reference_price,
            entries=maker_stop_entries,
        )
        if maker_entry_geometry_ready
        else None
    )
    entry_semantics_valid = (
        direction in {"long", "short"}
        and (
            entry_type == "left"
            or (entry_type == "right" and right_entry_constructible)
        )
        and reference_source == "TradingView"
        and reference_timeframe == "1h"
        and reference_price is not None
        and reference_price == certified_reference_price
        and reference_entry is not None
        and reference_entry in maker_stop_entries
        and entry_distance == abs(reference_entry - reference_price)
        and reach_direction == expected_reach
        and (
            (direction == "short" and expected_reach == "up_to_entry")
            or (direction == "long" and expected_reach == "down_to_entry")
        )
    )
    zone_reference_resolved = (
        zone_lower is not None
        and zone_upper is not None
        and zone_kind in {"manual_profile", "structure_zone"}
    )
    zone_role_valid = zone_reference_resolved and structure_zone_role_valid(
        direction=direction,
        zone_kind=zone_kind,
        zone_role=zone_role,
        allowed_roles=(
            (risk_policy.get("maker_initial_stop_policy") or {}).get(
                "direction_allowed_structure_zone_roles"
            )
            or {}
        ),
    )
    prohibited_candidate = cannot_do_conflicts(
        cannot_do_code=cannot_do_code,
        direction=direction,
        entry_type=entry_type,
        resting_order_valid=resting_order_valid,
    )
    cancel_price = _number(risk.get("cancel_before_fill"))
    order_lifecycle = assess_order_lifecycle(
        reference_price=reference_price,
        cancel_price=cancel_price,
        entries=maker_stop_entries,
    )
    expected_order_lifecycle = order_lifecycle.as_dict()
    submitted_order_lifecycle = (
        maker.get("order_lifecycle")
        if isinstance(maker.get("order_lifecycle"), dict)
        else {}
    )
    lifecycle_policy = risk_policy.get("maker_order_lifecycle") or {}
    if (
        set(submitted_order_lifecycle)
        != set(lifecycle_policy.get("required_fields") or [])
        or submitted_order_lifecycle != expected_order_lifecycle
    ):
        defects.append(
            Defect(
                "order_lifecycle.drift",
                "Maker order_lifecycle must exactly equal the gate-derived pre-fill state machine",
                "maker.order_lifecycle",
            )
        )
    candidate_submitted = bool(risk)
    candidate_requirements_evaluable = (
        not non_directional_maker
        and (candidate_submitted or certified_zone_available)
    )
    failed_checks: set[str] = set()
    if non_directional_maker:
        failed_checks.add("non_directional_thesis")
    else:
        if not certified_zone_available:
            failed_checks.add("no_certified_entry_zone")
        elif zone_status != "ok":
            failed_checks.add("entry_zone_binding_invalid")
        if zone_reference_resolved and not zone_role_valid:
            failed_checks.add("entry_zone_role_invalid")
        if resting_order_valid is False:
            failed_checks.add("maker_order_marketable")
        if candidate_submitted and not entry_semantics_valid:
            failed_checks.add("entry_semantics_invalid")
        if prohibited_candidate:
            failed_checks.add("cannot_do_conflict")
        if candidate_submitted and order_lifecycle.state != "fillable":
            failed_checks.add("order_lifecycle_invalid")
        if candidate_requirements_evaluable and not maker_structural_stop_valid:
            failed_checks.add("structural_stop_invalid")
        if candidate_requirements_evaluable and not risk_plan_valid:
            failed_checks.add("risk_math_invalid")
        elif candidate_requirements_evaluable and not defense_plan_valid:
            failed_checks.add("defense_trigger_invalid")
    candidate_assessment = assess_candidate(failed_checks=failed_checks)
    expected_plan_constructible = candidate_assessment.constructible
    expected_constructibility_reason = candidate_assessment.primary_reason_code
    expected_constructibility_status = candidate_assessment.status
    if maker.get("plan_constructible") is not expected_plan_constructible:
        defects.append(
            Defect(
                "maker.plan_constructibility_drift",
                f"plan_constructible must be {expected_plan_constructible}",
                "maker.plan_constructible",
            )
        )
    if (
        constructibility.get("status") != expected_constructibility_status
        or constructibility.get("primary_reason_code") != expected_constructibility_reason
        or constructibility.get("failure_codes") != list(candidate_assessment.failure_codes)
    ):
        defects.append(
            Defect(
                "maker.plan_constructibility_reason_drift",
                "plan constructibility status, primary reason and complete ordered failure_codes must be mechanically derived",
                "maker.plan_constructibility",
            )
        )
    if expected_constructibility_reason == "no_certified_entry_zone" and risk:
        defects.append(
            Defect(
                "maker.zone_absent_price_fabrication",
                "a run with no certified TradingView entry zone cannot fabricate a risk ladder",
                "maker.risk_plan",
            )
        )
    if expected_constructibility_reason == "risk_math_invalid" and not risk:
        defects.append(
            Defect(
                "maker.risk_probe_missing",
                "risk_math_invalid requires a typed candidate risk plan that the gate can recompute",
                "maker.risk_plan",
            )
        )

    plan_state = _text(maker.get("plan_state"))
    expected_plan_state = (
        "qualified"
        if expected_threshold_eligible and expected_plan_constructible
        else "observe"
    )
    if plan_state != expected_plan_state:
        defects.append(
            Defect(
                "maker.plan_state_drift",
                f"maker plan_state must be {expected_plan_state}",
                "maker.plan_state",
            )
        )
    try:
        classify_maker_semantic_state(
            plan_state=plan_state,
            direction=direction,
            plan_constructible=maker.get("plan_constructible"),
            threshold_eligible=maker.get("threshold_eligible"),
            risk_plan=risk,
            defense_plan=defense,
            position_notional_usdt=maker.get("position_notional_usdt"),
            entry_type=entry_type,
            order_lifecycle_state=order_lifecycle.state,
            entry_reach_probability_applicability=probability_applicability,
            constructibility_reason=constructibility.get("primary_reason_code"),
        )
    except ValueError as exc:
        defects.append(
            Defect(
                "maker.semantic_state_inconsistent",
                str(exc),
                "maker",
            )
        )
    execution_action = _text(maker.get("execution_action"))
    if run_mode == "shadow":
        expected_execution_action = "not_attempted"
    elif not live_execution_allowed:
        expected_execution_action = "blocked"
    elif expected_plan_state == "qualified":
        expected_execution_action = "place_order"
    else:
        expected_execution_action = "observe"
    if execution_action != expected_execution_action:
        defects.append(
            Defect(
                "maker.execution_action_drift",
                f"maker execution_action must be {expected_execution_action}",
                "maker.execution_action",
            )
        )
    expected_transition_action = (
        "not_attempted" if run_mode == "shadow" else continuity_action
    )
    if maker.get("order_transition_action") != expected_transition_action:
        defects.append(
            Defect(
                "maker.order_transition_action_drift",
                f"order_transition_action must be {expected_transition_action}",
                "maker.order_transition_action",
            )
        )
    if plan_state == "qualified" and direction not in {"long", "short"}:
        defects.append(Defect("maker.direction_invalid", "qualified Maker plan requires long or short", "maker.direction"))
    if plan_state != "qualified" and direction not in {"observe", "blocked", "long", "short"}:
        defects.append(Defect("maker.direction_invalid", "Maker direction is invalid", "maker.direction"))
    allowed_strategy_types = {"long": {"低多"}, "short": {"高空", "反弹空"}}
    if direction in allowed_strategy_types and strategy_type not in allowed_strategy_types[direction]:
        defects.append(
            Defect(
                "maker.strategy_direction_conflict",
                "a directional Maker candidate must retain its directional strategy_type even when rejected",
                "maker.strategy_type",
            )
        )
    if direction in {"observe", "blocked"} and strategy_type != "观望":
        defects.append(
            Defect(
                "maker.strategy_direction_conflict",
                "a non-directional Maker decision must use 观望 strategy_type",
                "maker.strategy_type",
            )
        )
    return (candidate_assessment, expected_plan_constructible, expected_constructibility_reason, expected_plan_state, expected_execution_action, probability_is_applicable, execution_action)


def _validate_decision_scenario_facts(after, continuity_action, defects, direction, entry_type, execution_action, execution_basis, expected_constructibility_reason, expected_plan_constructible, maker, maker_structural_stop_valid, probability_is_applicable, reasoning_observations, required_risk_fields, risk, risk_policy, run_mode, zone_lower, zone_upper):
    scenario_facts: list[dict[str, str]] = []
    if expected_plan_constructible or maker.get("plan_constructible") is True:
        if entry_type not in set(risk_policy["maker_entry_types"]):
            defects.append(Defect("maker.entry_type_invalid", "executable Maker plan requires canonical left or right entry_type", "maker.entry_type"))
        if run_mode == "production":
            if execution_action == "place_order" and (
                continuity_action not in {"new", "keep", "cancel_replace"}
                or after != 1
            ):
                defects.append(Defect("continuity.executable_action_conflict", "a live executable Maker decision must leave exactly one certified active order", "continuity_contract.current_plan.action"))
            if execution_action != "place_order" and (
                continuity_action not in {"cancel", "observe", "reconcile_filled"}
                or after != 0
            ):
                defects.append(Defect("continuity.non_executable_action_conflict", "a blocked or observational production decision must leave zero active orders", "continuity_contract.current_plan.action"))
        if set(risk) != required_risk_fields:
            defects.append(
                Defect(
                    "risk.schema_fields",
                    "executable risk_plan must contain the exact typed field set",
                    "maker.risk_plan",
                )
            )
        entries = risk.get("entries") if isinstance(risk.get("entries"), list) else []
        allocations = (
            risk.get("entry_allocations_pct")
            if isinstance(risk.get("entry_allocations_pct"), list)
            else []
        )
        stop = _number(risk.get("stop"))
        tp1 = _number(risk.get("tp1"))
        tp2 = _number(risk.get("tp2"))
        leverage = _number(risk.get("leverage"))
        cancel_before_fill = _number(risk.get("cancel_before_fill"))
        entry_values = [_number(value) for value in entries]
        minimum_levels = int(risk_policy["minimum_entry_levels"])
        maximum_levels = int(risk_policy["maximum_entry_levels"])
        if not minimum_levels <= len(entries) <= maximum_levels:
            defects.append(
                Defect(
                    "risk.entry_range_required",
                    f"executable Maker plan requires {minimum_levels}-{maximum_levels} entry levels",
                    "maker.risk_plan.entries",
                )
            )
        if (
            all(value is not None for value in entry_values)
            and len(set(entry_values)) != len(entries)
        ):
            defects.append(
                Defect(
                    "risk.entry_levels_duplicate",
                    "Maker entry levels must be distinct",
                    "maker.risk_plan.entries",
                )
            )
        if zone_lower is None or zone_upper is None or any(
            value < zone_lower or value > zone_upper
            for value in entry_values
            if value is not None
        ):
            defects.append(
                Defect(
                    "risk.entries_outside_certified_zone",
                    "every Maker ladder entry must remain inside the current certified TradingView entry zone",
                    "maker.risk_plan.entries",
                )
            )
        allocation_values = [_number(value) for value in allocations]
        if (
            len(allocations) != len(entries)
            or any(value is None or value <= 0 for value in allocation_values)
            or sum(
                (value for value in allocation_values if value is not None),
                Decimal("0"),
            )
            != _number(risk_policy["entry_allocation_total_pct"])
        ):
            defects.append(
                Defect(
                    "risk.entry_allocations_invalid",
                    "entry allocations must align one-to-one, be positive, and total 100%",
                    "maker.risk_plan.entry_allocations_pct",
                )
            )
        reference_source = _text(execution_basis.get("reference_source"))
        reference_timeframe = _text(execution_basis.get("reference_timeframe"))
        reference_price = _number(execution_basis.get("reference_price"))
        reference_entry = _number(execution_basis.get("reference_entry"))
        entry_distance = _number(execution_basis.get("entry_distance"))
        reach_direction = _text(execution_basis.get("reach_direction"))
        if probability_is_applicable and (
            reference_source != "TradingView" or reference_timeframe != "1h"
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.reference_contract",
                    "executable probability basis must use the certified TradingView 1h price",
                    "maker.entry_reach_probability_basis",
                )
            )
        tradingview_observations = [
            item
            for item in reasoning_observations.values()
            if _text(item.get("source")) == "TradingView"
        ]
        certified_reference_price = None
        if len(tradingview_observations) == 1:
            metrics = tradingview_observations[0].get("metrics")
            timeframes = metrics.get("timeframes") if isinstance(metrics, dict) else {}
            timeframe_metrics = (
                timeframes.get(reference_timeframe)
                if isinstance(timeframes, dict)
                else {}
            )
            certified_reference_price = _number(
                timeframe_metrics.get("price")
                if isinstance(timeframe_metrics, dict)
                else None
            )
        if probability_is_applicable and (
            reference_price is None
            or certified_reference_price is None
            or reference_price != certified_reference_price
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.reference_price",
                    "reference_price must equal the certified TradingView 1h price",
                    "maker.entry_reach_probability_basis.reference_price",
                )
            )
        if probability_is_applicable and (
            reference_entry is None or reference_entry not in entry_values
        ):
            defects.append(
                Defect(
                    "entry_reach_probability.reference_entry",
                    "reference_entry must equal one executable entry",
                    "maker.entry_reach_probability_basis.reference_entry",
                )
            )
        if (
            probability_is_applicable
            and reference_entry is not None
            and reference_price is not None
        ):
            expected_distance = abs(reference_entry - reference_price)
            expected_direction = (
                "up_to_entry"
                if reference_entry > reference_price
                else "down_to_entry"
                if reference_entry < reference_price
                else "at_entry"
            )
            if entry_distance != expected_distance:
                defects.append(
                    Defect(
                        "entry_reach_probability.entry_distance",
                        f"entry_distance must equal abs(reference_entry-reference_price) ({expected_distance})",
                        "maker.entry_reach_probability_basis.entry_distance",
                    )
                )
            if reach_direction != expected_direction:
                defects.append(
                    Defect(
                        "entry_reach_probability.reach_direction",
                        f"reach_direction must be {expected_direction}",
                        "maker.entry_reach_probability_basis.reach_direction",
                    )
                )
            valid_entry_values = [
                value for value in entry_values if value is not None and value > 0
            ]
            entries_match_reach = (
                expected_direction == "up_to_entry"
                and all(value > reference_price for value in valid_entry_values)
            ) or (
                expected_direction == "down_to_entry"
                and all(value < reference_price for value in valid_entry_values)
            )
            if not valid_entry_values or not entries_match_reach:
                defects.append(
                    Defect(
                        "risk.entry_reach_geometry",
                        "every Maker entry level must lie on the certified reach side of the current reference price",
                        "maker.risk_plan.entries",
                    )
                )
        if stop is None or tp1 is None or tp2 is None or cancel_before_fill is None:
            defects.append(Defect("risk.values_invalid", "stop, tp1, tp2 and cancel_before_fill are required", "maker.risk_plan"))
        if leverage != _number(risk_policy["maker_fixed_leverage"]):
            defects.append(Defect("risk.leverage_drift", "Maker leverage must equal the canonical fixed leverage", "maker.risk_plan.leverage"))
        if _number(risk.get("tp1_close_pct")) != _number(risk_policy["tp1_close_pct"]):
            defects.append(Defect("risk.tp1_close_pct", "TP1 must close exactly 50%", "maker.risk_plan.tp1_close_pct"))
        if _number(risk.get("tp2_close_pct")) != _number(risk_policy["tp2_close_pct"]):
            defects.append(Defect("risk.tp2_close_pct", "TP2 must close the remaining 50%", "maker.risk_plan.tp2_close_pct"))
        entry_numbers = [
            value for value in entry_values if value is not None and value > 0
        ]
        allocation_numbers = [
            value for value in allocation_values if value is not None and value > 0
        ]
        if (
            maker_structural_stop_valid
            and
            len(entry_numbers) == len(entries)
            and len(allocation_numbers) == len(entries)
            and stop is not None
            and tp1 is not None
            and tp2 is not None
            and leverage is not None
            and leverage > 0
        ):
            try:
                scenario_facts = maker_fill_scenarios(
                    entries=entry_numbers,
                    allocations=allocation_numbers,
                    direction=direction,
                    stop=stop,
                    tp1=tp1,
                    tp2=tp2,
                    leverage=leverage,
                )
            except (ArithmeticError, InvalidOperation, ValueError) as exc:
                defects.append(
                    Defect(
                        "risk.geometry_invalid",
                        str(exc),
                        "maker.risk_plan",
                    )
                )
            else:
                minimum_rr = _number(risk_policy["minimum_rr_to_tp1"])
                maximum_risk = _number(risk_policy["maximum_nominal_risk_pct"])
                for scenario in scenario_facts:
                    rr = _number(scenario["rr_to_tp1"])
                    nominal = _number(scenario["nominal_risk_pct"])
                    path = (
                        "maker.risk_plan.fill_scenarios["
                        f"{scenario['filled_levels']}]"
                    )
                    if rr is None or minimum_rr is None or rr < minimum_rr:
                        defects.append(
                            Defect(
                                "risk.rr_below_minimum",
                                f"TP1 risk/reward is {rr}, below {risk_policy['minimum_rr_to_tp1']}",
                                path,
                            )
                        )
                    if (
                        nominal is None
                        or maximum_risk is None
                        or nominal > maximum_risk
                    ):
                        defects.append(
                            Defect(
                                "risk.nominal_above_maximum",
                                f"nominal risk is {nominal}%, above {risk_policy['maximum_nominal_risk_pct']}%",
                                path,
                            )
                        )
    else:
        if expected_constructibility_reason == "no_certified_entry_zone" and maker.get("position_notional_usdt") not in {None, 0}:
            defects.append(Defect("maker.non_executable_fields", "a Maker observation with no certified entry zone cannot claim a position notional", "maker.position_notional_usdt"))
        if run_mode == "production" and (
            continuity_action not in {"cancel", "observe", "reconcile_filled"}
            or after != 0
        ):
            defects.append(Defect("continuity.non_executable_action_conflict", "non-executable Maker decision must leave zero active orders", "continuity_contract.current_plan.action"))
    return scenario_facts


def evaluate_decision(
    payload: dict[str, Any],
    *,
    reasoning: dict[str, Any],
    run: dict[str, Any],
    pretrade_gate: dict[str, Any] | None,
    root: Path,
) -> GateResult:
    defects: list[Defect] = []
    (
        maker_policy,
        conviction_policy,
        risk_policy,
        reasoning_hash,
        run_mode,
        live_execution_allowed,
        reasoning_observations,
        reasoning_claims,
        claim_sources,
        validate_claim_refs,
        reject_narrative_second_truth,
    ) = _prepare_decision_validation(
        payload,
        reasoning,
        run,
        pretrade_gate,
        root,
        defects,
    )
    _validate_main_account_decision(
        payload,
        reasoning,
        reasoning_claims,
        reasoning_observations,
        risk_policy,
        defects,
    )
    (
        maker,
        strategy_type,
        maker_position_notional,
        maker_direction,
        non_directional_maker,
        cannot_do_code,
        continuity,
    ) = _prepare_maker_decision(
        payload,
        reasoning_claims,
        reasoning_hash,
        risk_policy,
        run,
        run_mode,
        defects,
    )
    after, continuity_action = _validate_decision_continuity(
        continuity,
        defects,
        payload,
        reasoning_observations,
        risk_policy,
        root,
    )
    (
        orderflow,
        certified_orderflow,
        chart_total,
        claimed_total_value,
        win_rate,
        rubric,
        anchor_claim_ids,
        anchor_value,
    ) = _validate_decision_scorecard(
        claim_sources,
        conviction_policy,
        defects,
        maker,
        maker_policy,
        reasoning,
        reasoning_claims,
        reasoning_observations,
        validate_claim_refs,
    )
    (
        adjustment_total,
        adjustments,
        seen_typed_owner_signatures,
    ) = _validate_decision_adjustments(
        anchor_claim_ids,
        claim_sources,
        conviction_policy,
        defects,
        maker,
        maker_direction,
        reasoning_claims,
        reasoning_observations,
        reject_narrative_second_truth,
        rubric,
        validate_claim_refs,
    )
    _validate_decision_dispositions(
        adjustment_total,
        adjustments,
        anchor_value,
        conviction_policy,
        defects,
        reasoning,
        reasoning_claims,
        rubric,
        seen_typed_owner_signatures,
        win_rate,
    )
    (
        entry_reach_probability,
        execution_basis,
        direction,
        risk,
        required_risk_fields,
        expected_threshold_eligible,
        constructibility,
        tradingview_rows,
        certified_zone_available,
        zone_lower,
        zone_upper,
        zone_status,
        zone_kind,
        zone_role,
        entry_type,
        maker_stop_entries,
        maker_structural_stop_valid,
        risk_plan_valid,
        defense,
    ) = _prepare_decision_risk(
        claimed_total_value,
        conviction_policy,
        defects,
        maker,
        maker_direction,
        maker_policy,
        maker_position_notional,
        non_directional_maker,
        reasoning_claims,
        reasoning_observations,
        risk_policy,
        validate_claim_refs,
        win_rate,
    )
    (
        candidate_assessment,
        expected_plan_constructible,
        expected_constructibility_reason,
        expected_plan_state,
        expected_execution_action,
        probability_is_applicable,
        execution_action,
    ) = _validate_decision_risk_certification(
        cannot_do_code,
        certified_zone_available,
        constructibility,
        continuity_action,
        defects,
        defense,
        direction,
        entry_reach_probability,
        entry_type,
        execution_basis,
        expected_threshold_eligible,
        live_execution_allowed,
        maker,
        maker_stop_entries,
        maker_structural_stop_valid,
        non_directional_maker,
        risk,
        risk_plan_valid,
        risk_policy,
        run_mode,
        strategy_type,
        tradingview_rows,
        zone_kind,
        zone_lower,
        zone_role,
        zone_status,
        zone_upper,
    )
    scenario_facts = _validate_decision_scenario_facts(
        after,
        continuity_action,
        defects,
        direction,
        entry_type,
        execution_action,
        execution_basis,
        expected_constructibility_reason,
        expected_plan_constructible,
        maker,
        maker_structural_stop_valid,
        probability_is_applicable,
        reasoning_observations,
        required_risk_fields,
        risk,
        risk_policy,
        run_mode,
        zone_lower,
        zone_upper,
    )

    main = payload.get("main_account") if isinstance(payload.get("main_account"), dict) else {}
    if main.get("direction") not in {"long", "short", "neutral"}:
        defects.append(Defect("main.direction_invalid", "main-account direction is invalid", "main_account.direction"))
    claim_types = {
        claim_id: _text(item.get("claim_type"))
        for claim_id, item in reasoning_claims.items()
    }
    main_claim_id = _text(main.get("claim_id"))
    maker_claim_id = _text(maker.get("claim_id"))
    if claim_types.get(main_claim_id) != "main_account_thesis":
        defects.append(Defect("main.claim_binding", "main-account decision must bind main_account_thesis", "main_account.claim_id"))
    elif reasoning_claims[main_claim_id].get("direction") != main.get("direction"):
        defects.append(Defect("main.direction_drift", "main-account decision direction differs from its certified thesis", "main_account.direction"))
    if claim_types.get(maker_claim_id) != "maker_thesis":
        defects.append(Defect("maker.claim_binding", "Maker decision must bind maker_thesis", "maker.claim_id"))
    elif reasoning_claims[maker_claim_id].get("direction") != maker.get("direction"):
        defects.append(Defect("maker.direction_drift", "Maker decision direction differs from its certified thesis", "maker.direction"))
    if certified_orderflow is not None:
        orderflow_claim = next(
            (
                item
                for item in reasoning_claims.values()
                if item.get("claim_type") == "orderflow_interpretation"
            ),
            {},
        )
        maker_thesis_direction = _text(
            reasoning_claims.get(maker_claim_id, {}).get("direction")
        )
        # A directional Maker thesis must preserve the certified orderflow
        # direction.  An explicit observe thesis is a typed disposition of the
        # same evidence, not a claim that orderflow itself became "observe".
        if (
            maker_thesis_direction in {"long", "short"}
            and maker.get("direction") != orderflow_claim.get("direction")
        ):
            defects.append(Defect("maker.orderflow_direction_drift", "Maker direction differs from the certified orderflow interpretation", "maker.direction"))

    expected_hash = decision_model_sha256(payload)
    if payload.get("decision_sha256") and payload.get("decision_sha256") != expected_hash:
        defects.append(Defect("decision.hash_mismatch", "decision hash differs from content", "decision_sha256"))
    return _result(
        "risk_execution",
        defects,
        decision_sha256=expected_hash,
        chart_score=chart_total,
        total_score=orderflow + chart_total,
        expected_plan_state=expected_plan_state,
        expected_execution_action=expected_execution_action,
        live_execution_allowed=live_execution_allowed,
        risk_scenarios=scenario_facts,
        maker_candidate_failure_codes=list(candidate_assessment.failure_codes),
    )

__all__ = ["decision_model_sha256", "evaluate_decision", "maker_fill_scenarios"]
