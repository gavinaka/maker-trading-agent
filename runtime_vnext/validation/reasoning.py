"""Reasoning-stage production validation owner."""

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

from runtime.golden_methodology import (
    derive_etf_price_relation,
    evaluate_methodology,
)

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
    validate_methodology_submission_shape,
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
from .evidence import (
    SemanticIssue,
    _extreme_proof_failures,
    _fedwatch_is_plan_c,
    _validate_blockbeats,
    _validate_coinglass,
    _validate_common_observation,
    _validate_exocharts,
    _validate_farside,
    _validate_fedwatch,
    _validate_observation_server_projection,
    _validate_tradingview,
    _validate_tradingview_profile_sidecar_binding,
    evaluate_evidence,
)

def _reachable_claim_types(
    claim_id: str,
    claims: dict[str, dict[str, Any]],
) -> set[str]:
    found: set[str] = set()
    stack = list(claims.get(claim_id, {}).get("support_ids") or [])
    visited: set[str] = set()
    while stack:
        current = _text(stack.pop())
        if current in visited or current not in claims:
            continue
        visited.add(current)
        found.add(_text(claims[current].get("claim_type")))
        stack.extend(claims[current].get("support_ids") or [])
    return found


def _claim_reaches(
    start_claim_id: str,
    target_claim_id: str,
    claims: dict[str, dict[str, Any]],
) -> bool:
    """Return whether a support-only path reaches the target claim.

    Counter and invalidation edges are control edges, not evidence ancestry, so
    they are deliberately excluded from this traversal.
    """

    stack = list(claims.get(start_claim_id, {}).get("support_ids") or [])
    visited: set[str] = set()
    while stack:
        current = _text(stack.pop())
        if current == target_claim_id:
            return True
        if current in visited or current not in claims:
            continue
        visited.add(current)
        stack.extend(claims[current].get("support_ids") or [])
    return False


def _validate_claim_layers(
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    root: Path,
    full_policy: dict[str, Any],
    issues: list[SemanticIssue],
    submission_contract: dict[str, Any] | None = None,
) -> None:
    by_type: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for claim_id, claim in claims.items():
        by_type.setdefault(_text(claim.get("claim_type")), []).append((claim_id, claim))
    contract = submission_contract or load_reasoning_submission_contract(root=root)
    topology = contract["claim_topology"]
    exact_direct_sources = {
        claim_type: set(sources)
        for claim_type, sources in topology[
            "exact_direct_observation_sources_by_claim_type"
        ].items()
    }
    direct_types = set(exact_direct_sources)
    for claim_id, claim in claims.items():
        claim_type = _text(claim.get("claim_type"))
        support_ids = [_text(value) for value in claim.get("support_ids", [])]
        direct_sources = {
            _text(observations[value].get("source"))
            for value in support_ids
            if value in observations
        }
        if claim_type in exact_direct_sources and direct_sources != exact_direct_sources[claim_type]:
            issues.append(SemanticIssue("claim.direct_source_boundary", f"{claim_type} direct sources must be {sorted(exact_direct_sources[claim_type])}", f"claims.{claim_id}.support_ids"))
        if claim_type not in direct_types and direct_sources:
            issues.append(SemanticIssue("claim.layer_bypass", f"{claim_type} must consume certified claims rather than raw observations", f"claims.{claim_id}.support_ids"))

    requirements = {
        claim_type: set(required)
        for claim_type, required in topology[
            "required_reachable_claim_types_by_claim_type"
        ].items()
    }
    for claim_type, required in requirements.items():
        for claim_id, _ in by_type.get(claim_type, []):
            reachable = _reachable_claim_types(claim_id, claims)
            for missing in sorted(required - reachable):
                issues.append(SemanticIssue("claim.layer_missing", f"{claim_type} must consume {missing}", f"claims.{claim_id}.support_ids"))

    required_direct_claim_types = {
        claim_type: set(required)
        for claim_type, required in topology[
            "required_direct_claim_types_by_claim_type"
        ].items()
    }
    for claim_type, required_direct_types in required_direct_claim_types.items():
        for claim_id, claim in by_type.get(claim_type, []):
            direct_claim_types = {
                _text(claims.get(_text(support_id), {}).get("claim_type"))
                for support_id in claim.get("support_ids", [])
            }
            missing_direct_types = sorted(
                required_direct_types - direct_claim_types
            )
            if missing_direct_types:
                issues.append(SemanticIssue(
                        "claim.direct_claim_boundary",
                        f"{claim_type} must directly bind "
                        + ", ".join(missing_direct_types),
                        f"claims.{claim_id}.support_ids",
                ))

    realization_states = set(
        full_policy["gold_methodology"]["fundamental_realization_states"]
    )
    for claim_id, claim in by_type.get("fundamental_price_realization", []):
        realization_state = claim.get("realization_state")
        if realization_state not in realization_states:
            issues.append(SemanticIssue(
                    "fundamental.realization_owner_invalid",
                    "fundamental_price_realization claim must own one typed cross-source realization_state",
                    f"claims.{claim_id}.realization_state",
            ))

    coinglass = next((item for item in observations.values() if item.get("source") == "Coinglass"), None)
    farside = next((item for item in observations.values() if item.get("source") == "Farside"), None)
    price_direction = _text(((coinglass or {}).get("metrics") or {}).get("price_direction"))
    flow_direction = _text(((farside or {}).get("metrics") or {}).get("flow_direction"))
    try:
        expected_etf_relation = derive_etf_price_relation(
            price_direction,
            flow_direction,
            full_policy["gold_methodology"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(SemanticIssue(
                "etf.price_relation_policy_invalid",
                f"ETF price relation policy is invalid: {exc}",
                "scoring.gold_methodology.etf_price_relation_truth_table",
        ))
        expected_etf_relation = "neutral"
    for claim_id, claim in by_type.get("etf_confirmation", []):
        price_relation = claim.get("price_relation")
        if price_relation != expected_etf_relation:
            issues.append(SemanticIssue(
                    "etf.price_relation_drift",
                    f"ETF price_relation must be {expected_etf_relation} for the certified price/flow pair",
                    f"claims.{claim_id}.price_relation",
            ))

    orderflow_claims = by_type.get("orderflow_interpretation", [])
    exocharts = next((item for item in observations.values() if item.get("source") == "Exocharts"), None)
    tradingview = next((item for item in observations.values() if item.get("source") == "TradingView"), None)
    manual_profile = (((tradingview or {}).get("metrics") or {}).get("volume_profile") or {})
    allowed_liquidation_results = set(
        full_policy["gold_methodology"]["liquidation_confirmation_results"]
    )
    for claim_id, claim in by_type.get("liquidation_confirmation", []):
        confirmation_result = _text(claim.get("confirmation_result"))
        if confirmation_result not in allowed_liquidation_results:
            issues.append(SemanticIssue(
                    "liquidation.confirmation_invalid",
                    "liquidation_confirmation claim must own one closed typed confirmation_result",
                    f"claims.{claim_id}.confirmation_result",
            ))
        if (
            isinstance(manual_profile, dict)
            and manual_profile.get("status") == "insufficient"
            and confirmation_result != "neutral"
        ):
            issues.append(SemanticIssue(
                    "liquidation.manual_profile_substitution",
                    "an insufficient manual profile requires a neutral liquidation confirmation",
                    f"claims.{claim_id}.confirmation_result",
            ))
    for claim_id, claim in orderflow_claims:
        assessment = claim.get("score_assessment") if isinstance(claim.get("score_assessment"), dict) else {}
        score = assessment.get("score")
        orderflow_policy = full_policy["maker_score"]["orderflow"]
        minimum_score = orderflow_policy["minimum_score"]
        non_extreme_max = orderflow_policy["non_extreme_max"]
        extreme_score = orderflow_policy["extreme_score"]
        score_is_integer = isinstance(score, int) and not isinstance(score, bool)
        score_is_allowed = score_is_integer and (
            minimum_score <= score <= non_extreme_max or score == extreme_score
        )
        if not score_is_allowed:
            issues.append(SemanticIssue(
                    "orderflow.score_invalid",
                    (
                        "orderflow score must be an integer from "
                        f"{minimum_score} to {non_extreme_max}, or {extreme_score} "
                        "when the extreme contract is satisfied"
                    ),
                    f"claims.{claim_id}.score_assessment.score",
            ))
        extreme = assessment.get("extreme_confirmed")
        if not isinstance(extreme, bool):
            issues.append(SemanticIssue("orderflow.extreme_type", "extreme_confirmed must be boolean", f"claims.{claim_id}.score_assessment.extreme_confirmed"))
        rationale = _text(assessment.get("rationale"))
        if len(rationale) < 20 or not _contains_cjk(rationale):
            issues.append(SemanticIssue("orderflow.score_rationale", "orderflow score requires at least 20 Chinese-readable characters", f"claims.{claim_id}.score_assessment.rationale"))
        coinglass_metrics = ((coinglass or {}).get("metrics") or {})
        exocharts_metrics = ((exocharts or {}).get("metrics") or {})
        combination = _text(coinglass_metrics.get("combination_id"))
        if score == extreme_score:
            candidate_direction = _text(
                (orderflow_policy.get("extreme_candidate_directions") or {}).get(
                    combination
                )
            )
            expected_semantic_direction = {
                "long": "bullish",
                "short": "bearish",
            }.get(candidate_direction)
            extreme_failures: list[str] = []
            if extreme is not True:
                extreme_failures.append("extreme flag")
            if combination not in orderflow_policy["extreme_candidate_combinations"]:
                extreme_failures.append("candidate combination")
            if _text(claim.get("direction")) != candidate_direction:
                extreme_failures.append("orderflow direction")
            expected_semantics = (
                orderflow_policy.get("extreme_candidate_semantics") or {}
            ).get(combination)
            if not isinstance(expected_semantics, dict):
                extreme_failures.append("canonical candidate semantics")
            else:
                for field in (
                    "cvd_direction",
                    "price_direction",
                    "oi_direction",
                    "funding_direction",
                    "funding_sign",
                    "price_break_status",
                    "oi_price_context",
                    "main_triad_direction",
                    "final_direction",
                ):
                    if coinglass_metrics.get(field) != expected_semantics.get(field):
                        extreme_failures.append(f"exact {field}")
                if coinglass_metrics.get("effect_divergence") != expected_semantics.get(
                    "effect_divergence"
                ):
                    extreme_failures.append("exact effect divergence")
            divergence = coinglass_metrics.get("effect_divergence")
            divergence_interpretation = _text(
                divergence.get("interpretation")
                if isinstance(divergence, dict)
                else ""
            )
            if divergence_interpretation != expected_semantic_direction:
                extreme_failures.append("effect divergence")
            if _text(coinglass_metrics.get("main_triad_direction")) != expected_semantic_direction:
                extreme_failures.append("main triad")
            if _text(coinglass_metrics.get("final_direction")) != expected_semantic_direction:
                extreme_failures.append("final direction")
            if _text(coinglass_metrics.get("funding_effect")) != "strengthen":
                extreme_failures.append("funding modifier")
            if _text(exocharts_metrics.get("cross_check_result")) != "confirm":
                extreme_failures.append("Exocharts confirmation")
            extreme_failures.extend(
                _extreme_proof_failures(
                    orderflow_policy=orderflow_policy,
                )
            )

            maker_closures = []
            for maker_id, maker_claim in by_type.get("maker_thesis", []):
                if not _claim_reaches(maker_id, claim_id, claims):
                    continue
                counter_ids = maker_claim.get("counter_ids") or []
                counter_bound = any(
                    _text(claims.get(_text(value), {}).get("claim_type"))
                    == "strongest_counterevidence"
                    and _text(claims.get(_text(value), {}).get("account"))
                    == "maker"
                    for value in counter_ids
                )
                invalidation_id = _text(maker_claim.get("invalidation_id"))
                invalidation_bound = (
                    _text(claims.get(invalidation_id, {}).get("claim_type"))
                    == "invalidation_path"
                    and _text(claims.get(invalidation_id, {}).get("account"))
                    == "maker"
                )
                maker_closures.append(
                    _text(maker_claim.get("direction")) == candidate_direction
                    and counter_bound
                    and invalidation_bound
                )
            if not any(maker_closures):
                extreme_failures.append("Maker counter/invalidation closure")
            if extreme_failures:
                issues.append(SemanticIssue(
                        "orderflow.extreme_unproven",
                        "70 requires mechanical proof; missing or inconsistent: "
                        + ", ".join(extreme_failures),
                        f"claims.{claim_id}.score_assessment",
                ))
        elif extreme is True:
            issues.append(SemanticIssue("orderflow.extreme_score_mismatch", "extreme_confirmed is valid only for score 70", f"claims.{claim_id}.score_assessment"))
        expected_direction = (
            full_policy["maker_score"]["orderflow"][
                "final_direction_to_claim_direction"
            ].get(_text(coinglass_metrics.get("final_direction")))
        )
        direction = _text(claim.get("direction"))
        if expected_direction and direction != expected_direction:
            issues.append(SemanticIssue("orderflow.direction_drift", f"orderflow direction must preserve the certified triad as {expected_direction}", f"claims.{claim_id}.direction"))


_SERVER_PROJECTION_MISSING = object()


def _server_projection_nested_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _SERVER_PROJECTION_MISSING
        current = current[part]
    return current


def _server_projection_unique_claim(
    claims: dict[str, dict[str, Any]],
    *,
    claim_type: str,
    account: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in claims.values()
        if item.get("claim_type") == claim_type and item.get("account") == account
    ]
    return matches[0] if len(matches) == 1 else None


def _server_projection_unique_observation(
    observations: dict[str, dict[str, Any]],
    *,
    source: str,
) -> dict[str, Any] | None:
    matches = [
        item for item in observations.values() if item.get("source") == source
    ]
    return matches[0] if len(matches) == 1 else None


def _server_projection_policy_value(
    full_policy: dict[str, Any],
    path: str,
) -> Any:
    current: Any = full_policy
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _SERVER_PROJECTION_MISSING
        current = current[part]
    return current


def _expected_methodology_server_value(
    binding: dict[str, Any],
    *,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    full_policy: dict[str, Any],
) -> Any:
    """Independently derive one projection value for Gate verification."""

    resolver = binding.get("resolver")
    if resolver == "literal":
        return binding.get("value")
    if resolver == "single_policy_value":
        values = _server_projection_policy_value(
            full_policy,
            _text(binding.get("policy_path")),
        )
        return (
            values[0]
            if isinstance(values, list) and len(values) == 1
            else None
        )
    if resolver in {"observation_id", "observation_field"}:
        observation = _server_projection_unique_observation(
            observations,
            source=_text(binding.get("source")),
        )
        if observation is None:
            return None
        if resolver == "observation_id":
            return observation.get("id")
        value = _server_projection_nested_value(
            observation,
            _text(binding.get("field_path")),
        )
        return None if value is _SERVER_PROJECTION_MISSING else value
    if resolver in {"unique_claim_id", "unique_claim_field"}:
        claim = _server_projection_unique_claim(
            claims,
            claim_type=_text(binding.get("claim_type")),
            account=_text(binding.get("account")),
        )
        if claim is None:
            return None
        if resolver == "unique_claim_id":
            return claim.get("id")
        value = _server_projection_nested_value(
            claim,
            _text(binding.get("field_path")),
        )
        return None if value is _SERVER_PROJECTION_MISSING else value
    if resolver == "ordered_unique_claim_ids":
        values: list[str | None] = []
        for item in binding.get("bindings") or []:
            claim = _server_projection_unique_claim(
                claims,
                claim_type=_text(item.get("claim_type")),
                account=_text(item.get("account")),
            )
            claim_id = claim.get("id") if isinstance(claim, dict) else None
            values.append(claim_id if isinstance(claim_id, str) and claim_id else None)
        if any(value is None for value in values) or len(set(values)) != len(values):
            return []
        return values
    return _SERVER_PROJECTION_MISSING


def _validate_methodology_server_projection(
    methodology: Any,
    *,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    full_policy: dict[str, Any],
    submission_contract: dict[str, Any],
) -> list[SemanticIssue]:
    """Verify assembler-owned methodology leaves without trusting assembler code."""

    if not isinstance(methodology, dict):
        return []
    ownership = (
        (submission_contract.get("server_projection") or {}).get(
            "methodology_leaf_ownership"
        )
        or {}
    )
    bindings = ownership.get("server_owned_bindings")
    if not isinstance(bindings, dict):
        return [
            SemanticIssue(
                "methodology.server_projection_policy",
                "methodology server projection ownership is missing",
                "server_projection.methodology_leaf_ownership",
            )
        ]

    issues: list[SemanticIssue] = []
    for path, binding in bindings.items():
        if not isinstance(binding, dict):
            issues.append(SemanticIssue(
                    "methodology.server_projection_policy",
                    "methodology server projection binding is invalid",
                    path,
            ))
            continue
        if "[*]" not in path:
            actual = _server_projection_nested_value(
                methodology,
                path.removeprefix("methodology."),
            )
            if actual is _SERVER_PROJECTION_MISSING:
                continue
            expected = _expected_methodology_server_value(
                binding,
                observations=observations,
                claims=claims,
                full_policy=full_policy,
            )
            if expected is _SERVER_PROJECTION_MISSING:
                issues.append(SemanticIssue(
                        "methodology.server_projection_policy",
                        "methodology server projection resolver is unsupported",
                        path,
                ))
            elif actual != expected:
                issues.append(SemanticIssue(
                        "methodology.server_projection_drift",
                        "methodology value differs from its deterministic server projection",
                        path,
                ))
            continue

        prefix, field = path.split("[*].", 1)
        items = methodology.get(prefix.removeprefix("methodology."))
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict) or field not in item:
                continue
            exact_path = path.replace("[*]", f"[{index}]")
            if binding.get("resolver") == "event_realization_claim_id":
                key_value = item.get(_text(binding.get("key_field")))
                matches = [
                    claim
                    for claim in claims.values()
                    if claim.get("claim_type") == binding.get("claim_type")
                    and claim.get("account") == binding.get("account")
                    and claim.get(_text(binding.get("claim_match_field")))
                    == key_value
                    and isinstance(key_value, str)
                    and key_value
                ]
                expected = (
                    matches[0].get("id")
                    if len(matches) == 1
                    and isinstance(matches[0].get("id"), str)
                    and matches[0].get("id")
                    else None
                )
            else:
                expected = _expected_methodology_server_value(
                    binding,
                    observations=observations,
                    claims=claims,
                    full_policy=full_policy,
                )
            if expected is _SERVER_PROJECTION_MISSING:
                issues.append(SemanticIssue(
                        "methodology.server_projection_policy",
                        "methodology server projection resolver is unsupported",
                        exact_path,
                ))
            elif item.get(field) != expected:
                issues.append(SemanticIssue(
                        "methodology.server_projection_drift",
                        "methodology value differs from its deterministic server projection",
                        exact_path,
                ))
    return issues


def validate_reasoning_semantics(
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    *,
    evidence: dict[str, Any],
    root: Path,
    full_policy: dict[str, Any],
    methodology: Any,
    submission_contract: dict[str, Any],
    visual_review_not_after: datetime | None = None,
) -> list[SemanticIssue]:
    """Return the complete semantic defect set for one reasoning candidate."""

    issues: list[SemanticIssue] = []
    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in observations.values():
        by_source.setdefault(_text(item.get("source")), []).append(item)
    for source in POLICY_SOURCE_KEYS:
        matches = by_source.get(source, [])
        if len(matches) != 1:
            issues.append(SemanticIssue("observation.source_cardinality", f"{source} requires exactly one current-slot observation", "observations"))
            continue
        contract_source = (
            "FedWatchPlanC"
            if source == "FedWatch" and _fedwatch_is_plan_c(evidence)
            else source
        )
        structured_artifact_filename = submission_contract["server_projection"][
            "observation_mechanical_ownership"
        ]["structured_artifact_filename_by_contract_source"].get(contract_source)
        _validate_common_observation(
            matches[0],
            source=source,
            evidence=evidence,
            root=root,
            structured_artifact_filename=structured_artifact_filename,
            visual_review_not_after=visual_review_not_after,
            issues=issues,
        )
        _validate_observation_server_projection(
            matches[0],
            source=source,
            evidence=evidence,
            submission_contract=submission_contract,
            issues=issues,
        )

    policy = full_policy["gold_methodology"]
    if len(by_source.get("BlockBeats", [])) == 1:
        _validate_blockbeats(by_source["BlockBeats"][0], evidence, root, policy, issues)
    if len(by_source.get("Farside", [])) == 1:
        _validate_farside(by_source["Farside"][0], evidence, root, policy, issues)
    if len(by_source.get("FedWatch", [])) == 1:
        _validate_fedwatch(
            by_source["FedWatch"][0], policy, evidence, root, issues
        )
    if len(by_source.get("Coinglass", [])) == 1:
        _validate_coinglass(by_source["Coinglass"][0], evidence, full_policy, issues)
    if len(by_source.get("Exocharts", [])) == 1:
        _validate_exocharts(by_source["Exocharts"][0], policy, issues)
    if len(by_source.get("TradingView", [])) == 1:
        tradingview = by_source["TradingView"][0]
        _validate_tradingview(tradingview, full_policy, issues)
        _validate_tradingview_profile_sidecar_binding(
            tradingview,
            evidence,
            root,
            full_policy["tradingview_profile_policy"],
            issues,
        )
    _validate_claim_layers(
        observations,
        claims,
        evidence,
        root,
        full_policy,
        issues,
        submission_contract=submission_contract,
    )

    translated_observations = {
        item_id: {
            **item,
            "source": POLICY_SOURCE_KEYS.get(_text(item.get("source")), ""),
            "values": item.get("metrics"),
        }
        for item_id, item in observations.items()
    }
    methodology_shape_issues = validate_methodology_submission_shape(
        methodology,
        contract=submission_contract,
        full_policy=full_policy,
    )
    issues.extend(
        SemanticIssue(item.code, item.message, item.path)
        for item in methodology_shape_issues
    )
    projection_issues = _validate_methodology_server_projection(
        methodology,
        observations=observations,
        claims=claims,
        full_policy=full_policy,
        submission_contract=submission_contract,
    )
    issues.extend(projection_issues)
    evaluation = evaluate_methodology(
        methodology,
        translated_observations,
        claims,
        policy,
        profile_policy=full_policy["tradingview_profile_policy"],
        mode="collect_all",
        blocked_paths=tuple(
            item.path
            for item in (*methodology_shape_issues, *projection_issues)
        ),
    )
    issues.extend(
        SemanticIssue(
            item.code,
            f"golden methodology rejected the reasoning: {item.message}",
            item.path,
        )
        for item in evaluation.issues
    )
    normalized = evaluation.normalized
    if normalized is not None:
        realization_claim = next(
            (
                item
                for item in claims.values()
                if item.get("claim_type") == "fundamental_price_realization"
            ),
            {},
        )
        etf_claim = next(
            (
                item
                for item in claims.values()
                if item.get("claim_type") == "etf_confirmation"
            ),
            {},
        )
        liquidation_claim = next(
            (
                item
                for item in claims.values()
                if item.get("claim_type") == "liquidation_confirmation"
            ),
            {},
        )
        comparisons = [
            (
                normalized["fundamental_price_realization"]["realization_state"],
                realization_claim.get("realization_state"),
                "methodology.fundamental_price_realization.realization_state",
            ),
            (
                normalized["footprint_cross_check"]["relationship"],
                ((by_source.get("Exocharts") or [{}])[0].get("metrics") or {}).get("cross_check_result"),
                "methodology.footprint_cross_check.relationship",
            ),
            (
                normalized["volume_profile_liquidity"]["liquidation_confirmation"],
                liquidation_claim.get("confirmation_result"),
                "methodology.volume_profile_liquidity.liquidation_confirmation",
            ),
            (
                normalized["etf_flow_relation"]["price_relation"],
                etf_claim.get("price_relation"),
                "methodology.etf_flow_relation.price_relation",
            ),
        ]
        for left, right, path in comparisons:
            if left != right:
                issues.append(SemanticIssue("methodology.owner_drift", "methodology value differs from its certified typed owner", path))
    return issues


def certified_orderflow_assessment(
    reasoning: dict[str, Any],
) -> dict[str, Any] | None:
    matches = [
        item.get("score_assessment")
        for item in reasoning.get("claims", [])
        if isinstance(item, dict)
        and item.get("claim_type") == "orderflow_interpretation"
        and isinstance(item.get("score_assessment"), dict)
    ]
    return matches[0] if len(matches) == 1 else None


def certified_chart_components(
    reasoning: dict[str, Any],
) -> dict[str, int] | None:
    matches = [
        (item.get("metrics") or {}).get("chart_component_scores")
        for item in reasoning.get("observations", [])
        if isinstance(item, dict)
        and item.get("source") == "TradingView"
        and isinstance(item.get("metrics"), dict)
    ]
    return matches[0] if len(matches) == 1 and isinstance(matches[0], dict) else None

ALLOWED_CLAIM_TYPES = set(REQUIRED_CLAIM_TYPES)
TRACEABLE_REPORT_SECTIONS = (
    REQUIRED_REPORT_SECTIONS - NON_TRACEABLE_REPORT_SECTIONS
)
TOOL_WRAPPER_RE = re.compile(
    r"(?im)^\s*(?:Exit code:|Wall time:|Output:|Script running with cell ID|Warning: truncated output)"
)
ACCOUNT_LABEL_RE = {
    "main": re.compile(r"主账户"),
    "maker": re.compile(r"Maker", re.I),
}
ACCOUNT_CAUSAL_MARKER_RE = re.compile(
    r"因此|所以|据此|因为|由于|基于|依据|依赖|取决于|决定|跟随|同步|"
    r"沿用|引用|参照|照搬|反推|推导|驱动|导致|约束|影响|互推"
)
BOUNDARY_CONNECTOR_RE = re.compile(r"因此|所以|据此|因为|由于|从而|进而|导致|使得")
BOUNDARY_LOOKBACK_RE = re.compile(
    r"决定|跟随|同步|沿用|引用|参照|照搬|反推|推导|驱动|约束|影响|依赖|取决于|互推"
)
INDEPENDENT_BOUNDARY_RE = re.compile(
    r"独立|解耦|互不干扰|不联动|互不(?:引用|推导|反推|决定|约束)|"
    r"不互相(?:引用|推导|反推|决定|约束)|不强制同向|不可互推|不得互推|"
    r"不能互推"
)
STRONG_CLAUSE_SPLIT_RE = re.compile(r"[。！？；;\n]+")
MINOR_CLAUSE_SPLIT_RE = re.compile(r"[，,:：]+")

def _validate_trigger_logic(
    claim_id: str,
    claim: dict[str, Any],
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    defects: list[Defect],
    trigger_policy: dict[str, Any],
) -> dict[str, Any]:
    """Validate counter/invalidation triggers as closed, typed clauses."""

    claim_type = _text(claim.get("claim_type"))
    account = _text(claim.get("account"))
    path = f"claims.{claim_id}.trigger_logic"
    trigger = claim.get("trigger_logic")
    metadata: dict[str, Any] = {
        "sources": set(),
        "claim_types": set(),
        "targets": [],
        "clause_targets": [],
    }
    if not isinstance(trigger, dict):
        defects.append(Defect(
                "claim.trigger_logic_missing",
                f"{claim_type}/{account} requires typed trigger_logic",
                path,
        ))
        return metadata
    if set(trigger) != {"mode", "effect", "clauses"}:
        defects.append(Defect(
                "claim.trigger_logic_schema",
                "trigger_logic must contain only mode, effect and clauses",
                path,
        ))
    raw_mode = trigger.get("mode")
    mode = _text(raw_mode)
    if (
        not _canonical_closed_string(raw_mode)
        or mode not in set(trigger_policy["allowed_modes"])
    ):
        defects.append(Defect("claim.trigger_mode_invalid", "trigger mode must be all or any", f"{path}.mode"))
    if claim_type == "invalidation_path" and mode != trigger_policy["invalidation_mode"]:
        defects.append(Defect(
                "claim.invalidation_trigger_mode",
                "invalidation_path requires all typed clauses; one variable cannot invalidate the account thesis",
                f"{path}.mode",
        ))
    expected_effect = trigger_policy["claim_effects"][claim_type]
    if trigger.get("effect") != expected_effect:
        defects.append(Defect(
                "claim.trigger_effect_invalid",
                f"{claim_type} trigger effect must be {expected_effect}",
                f"{path}.effect",
        ))
    clauses = trigger.get("clauses")
    minimum_clause_count = int(trigger_policy["minimum_clause_count"])
    if not isinstance(clauses, list) or len(clauses) < minimum_clause_count:
        defects.append(Defect(
                "claim.trigger_clauses_thin",
                    f"counter/invalidation trigger requires at least {minimum_clause_count} typed clauses",
                f"{path}.clauses",
        ))
        return metadata
    reachable = _reachable_trigger_owners(
        list(claim.get("support_ids") or []),
        observations,
        claims,
    )
    seen: set[tuple[str, str, str, str]] = set()
    conjunctive_target_sets: dict[tuple[str, str, str], list[Any]] = {}
    for index, clause in enumerate(clauses):
        clause_path = f"{path}.clauses[{index}]"
        if not isinstance(clause, dict):
            defects.append(Defect("claim.trigger_clause_invalid", "trigger clause must be an object", clause_path))
            continue
        raw_operator = clause.get("operator")
        operator = _text(raw_operator)
        if not _canonical_closed_string(raw_operator):
            defects.append(Defect(
                    "claim.trigger_clause_schema",
                    "trigger operator must be an exact closed-schema string",
                    f"{clause_path}.operator",
            ))
            continue
        expected_fields = (
            {"owner_type", "owner_id", "field", "operator", "value"}
            if operator in set(trigger_policy["allowed_operators"])
            and operator in {"becomes", "equals_at_trigger"}
            else {"owner_type", "owner_id", "field", "operator", "values"}
            if operator in set(trigger_policy["allowed_operators"])
            and operator == "one_of_at_trigger"
            else set()
        )
        if not expected_fields or set(clause) != expected_fields:
            defects.append(Defect(
                    "claim.trigger_clause_schema",
                    "trigger clause must use the exact typed schema for becomes, equals_at_trigger or one_of_at_trigger",
                    clause_path,
            ))
            continue
        raw_owner_type = clause.get("owner_type")
        raw_owner_id = clause.get("owner_id")
        raw_field = clause.get("field")
        owner_type = _text(raw_owner_type)
        owner_id = _text(raw_owner_id)
        field = _text(raw_field)
        if not all(
            _canonical_closed_string(value)
            for value in (raw_owner_type, raw_owner_id, raw_field)
        ):
            defects.append(Defect(
                    "claim.trigger_identifier_noncanonical",
                    "trigger owner_type, owner_id and field must be exact closed-schema strings",
                    clause_path,
            ))
            continue
        source = ""
        owner_claim_type = ""
        if owner_id not in reachable:
            defects.append(Defect(
                    "claim.trigger_owner_unbound",
                    "trigger owner must be reachable from the claim support DAG",
                    f"{clause_path}.owner_id",
            ))
        allowed_values: set[Any] = set()
        current_found = False
        current_value: Any = None
        if owner_type == "observation":
            owner = observations.get(owner_id) or {}
            source = _text(owner.get("source"))
            allowed_values = set(
                ((trigger_policy.get("observation_fields") or {}).get(source) or {}).get(field)
                or []
            )
            current_found, current_value = _nested_value(owner.get("metrics") or {}, field)
            if source:
                metadata["sources"].add(source)
        elif owner_type == "claim":
            owner = claims.get(owner_id) or {}
            owner_claim_type = _text(owner.get("claim_type"))
            owner_account = _text(owner.get("account"))
            allowed_values = set(
                ((trigger_policy.get("claim_fields") or {}).get(owner_claim_type) or {}).get(field)
                or []
            )
            current_found, current_value = _nested_value(owner, field)
            if owner_account not in {"shared", account}:
                defects.append(Defect(
                        "claim.trigger_cross_account",
                        "trigger clause cannot consume the other account",
                        f"{clause_path}.owner_id",
                ))
            if owner_claim_type:
                metadata["claim_types"].add(owner_claim_type)
        else:
            defects.append(Defect(
                    "claim.trigger_owner_type_invalid",
                    "trigger owner_type must be observation or claim",
                    f"{clause_path}.owner_type",
            ))
        if not allowed_values:
            defects.append(Defect(
                    "claim.trigger_field_forbidden",
                    "trigger field is not an approved typed control owner",
                    f"{clause_path}.field",
            ))
            continue
        if not current_found:
            defects.append(Defect(
                    "claim.trigger_field_missing",
                    "trigger field is absent from the certified owner",
                    f"{clause_path}.field",
            ))
        raw_targets = clause.get("values")
        target_shape_valid = (
            isinstance(raw_targets, list) and bool(raw_targets)
            if operator == "one_of_at_trigger"
            else True
        )
        targets = (
            list(raw_targets)
            if operator == "one_of_at_trigger" and isinstance(raw_targets, list)
            else []
            if operator == "one_of_at_trigger"
            else [clause.get("value")]
        )
        targets_valid = target_shape_valid and bool(targets) and all(
            _typed_domain_contains(allowed_values, target) for target in targets
        )
        if not targets_valid:
            defects.append(Defect(
                    "claim.trigger_target_invalid",
                    "trigger target shape, exact type, or value is outside the typed field domain",
                    clause_path,
            ))
        if (
            operator == "becomes"
            and current_found
            and len(targets) == 1
            and type(targets[0]) is type(current_value)
            and targets[0] == current_value
        ):
            defects.append(Defect(
                    "claim.trigger_no_state_change",
                    "becomes must target a state different from the current certified value",
                    clause_path,
            ))
        signature = (owner_type, owner_id, field, json.dumps(targets, ensure_ascii=False, sort_keys=True))
        if signature in seen:
            defects.append(Defect("claim.trigger_clause_duplicate", "duplicate trigger clause", clause_path))
        seen.add(signature)
        metadata["targets"].append((owner_type, owner_id, field, targets))
        if targets_valid:
            if mode == "all":
                owner_field = (owner_type, owner_id, field)
                prior_targets = conjunctive_target_sets.get(owner_field)
                if prior_targets is None:
                    conjunctive_target_sets[owner_field] = list(targets)
                else:
                    reachable_targets = _typed_domain_intersection(
                        prior_targets, list(targets)
                    )
                    if not reachable_targets:
                        defects.append(Defect(
                                "claim.trigger_all_clause_unsatisfiable",
                                "all-mode clauses for the same typed field must retain at least one jointly reachable target state",
                                clause_path,
                        ))
                    else:
                        conjunctive_target_sets[owner_field] = reachable_targets
            metadata["clause_targets"].append(
                {
                    "index": index,
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "source": source,
                    "owner_claim_type": owner_claim_type,
                    "field": field,
                    "operator": operator,
                    "targets": list(targets),
                    "current_found": current_found,
                    "current_value": current_value,
                }
            )
    certified_clauses = [
        item
        for item in metadata["clause_targets"]
        if isinstance(item, dict) and item.get("current_found") is True
    ]
    current_truths = [
        _typed_domain_contains(
            list(item.get("targets") or []),
            item.get("current_value"),
        )
        for item in certified_clauses
    ]
    current_truth_quantifier = (
        trigger_policy["future_trigger_current_truth_quantifier_by_mode"].get(mode)
    )
    already_satisfied = (
        current_truth_quantifier == "all"
        and isinstance(clauses, list)
        and len(certified_clauses) == len(clauses)
        and all(current_truths)
    ) or (
        current_truth_quantifier == "any"
        and any(current_truths)
    )
    if already_satisfied:
        defects.append(Defect(
                "claim.trigger_already_satisfied",
                "future trigger is already satisfied by current certified state under its mode",
                f"{path}.clauses",
        ))
    return metadata

def _future_trigger_clause_polarities(
    metadata: dict[str, Any],
    *,
    mode: str,
    trigger_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify every future clause from typed fields, never from prose."""

    direct_fields = trigger_policy.get("non_directional_future_direction_fields") or {}
    direction_map = trigger_policy.get("future_direction_value_map") or {}
    relative_fields = trigger_policy.get("relative_direction_observation_fields") or {}
    clause_targets = [
        item
        for item in metadata.get("clause_targets") or []
        if isinstance(item, dict)
    ]

    def direct_directions(source: str, field: str, targets: list[Any]) -> set[str]:
        if field not in set(direct_fields.get(source) or []):
            return set()
        return {
            _text(direction_map.get(target)) or "neutral"
            for target in targets
        }

    results: list[dict[str, Any]] = []
    for item in clause_targets:
        source = _text(item.get("source"))
        field = _text(item.get("field"))
        targets = list(item.get("targets") or [])
        directions = direct_directions(source, field, targets)
        if directions:
            results.append(
                {
                    **item,
                    "polarity_kind": "absolute_direction",
                    "directions": directions,
                    "relative_bound": True,
                }
            )
            continue

        relative = ((relative_fields.get(source) or {}).get(field) or {})
        if relative:
            reference_source = _text(relative.get("reference_source"))
            reference_field = _text(relative.get("reference_field"))
            reference_operator_policy = (
                relative.get("reference_operator_policy")
                if isinstance(relative.get("reference_operator_policy"), dict)
                else {}
            )
            relative_operator = _text(relative.get("relative_operator"))
            reference_directions: set[str] = set()
            references = [
                reference
                for reference in clause_targets
                if _text(reference.get("source")) == reference_source
                and _text(reference.get("field")) == reference_field
            ]
            canonical_reference = False
            if mode == "all" and len(references) == 1:
                reference_targets = list(references[0].get("targets") or [])
                current_found = references[0].get("current_found") is True
                current_value = references[0].get("current_value")
                same_state = (
                    current_found
                    and len(reference_targets) == 1
                    and type(reference_targets[0]) is type(current_value)
                    and reference_targets[0] == current_value
                )
                expected_operator = _text(
                    reference_operator_policy.get(
                        "target_equals_current"
                        if same_state
                        else "target_differs_from_current"
                    )
                )
                canonical_reference = (
                    current_found
                    and len(reference_targets) == 1
                    and _text(references[0].get("operator"))
                    == expected_operator
                )
            if canonical_reference:
                reference_directions.update(
                    direct_directions(
                        reference_source,
                        reference_field,
                        list(references[0].get("targets") or []),
                    )
                )
            bound = (
                len(reference_directions) == 1
                and next(iter(reference_directions), "") in {"long", "short"}
            )
            if bound:
                reference_direction = next(iter(reference_directions))
                inverse = {"long": "short", "short": "long"}
                relation_map = relative.get("relation_map") or {}
                for target in targets:
                    relation = _text(relation_map.get(target))
                    if relation == "same_as_reference":
                        directions.add(reference_direction)
                    elif relation == "opposite_of_reference":
                        directions.add(inverse[reference_direction])
                    else:
                        directions.add("neutral")
            results.append(
                {
                    **item,
                    "polarity_kind": "relative_direction",
                    "directions": directions,
                    "relative_bound": bound,
                    "relative_operator_canonical": (
                        _text(item.get("operator")) == relative_operator
                    ),
                }
            )
            continue

        results.append(
            {
                **item,
                "polarity_kind": "neutral_auxiliary",
                "directions": {"neutral"},
                "relative_bound": True,
            }
        )
    return results

def _validate_current_basis(
    claim_id: str,
    claim: dict[str, Any],
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    defects: list[Defect],
    policy: dict[str, Any],
    *,
    subject_direction: str,
) -> dict[str, Any]:
    """Bind counter/invalidation owners to current typed values, not triggers."""

    account = _text(claim.get("account"))
    path = f"claims.{claim_id}.current_basis"
    metadata: dict[str, Any] = {
        "sources": set(),
        "claim_types": set(),
        "polarities": [],
    }
    basis = claim.get("current_basis")
    required_fields = set(policy.get("required_fields") or [])
    if not isinstance(basis, dict) or set(basis) != required_fields:
        defects.append(Defect(
                "claim.current_basis_schema",
                "counter/invalidation claims require the exact typed current_basis schema",
                path,
        ))
        return metadata
    raw_mode = basis.get("mode")
    mode = _text(raw_mode)
    if (
        not _canonical_closed_string(raw_mode)
        or mode not in set(policy.get("allowed_modes") or [])
    ):
        defects.append(Defect(
                "claim.current_basis_mode",
                "current_basis mode is outside the closed authority vocabulary",
                f"{path}.mode",
        ))
    clauses = basis.get("clauses")
    minimum = int(policy.get("minimum_clause_count") or 0)
    if not isinstance(clauses, list) or len(clauses) < minimum:
        defects.append(Defect(
                "claim.current_basis_clauses_thin",
                f"current_basis requires at least {minimum} typed current-value clauses",
                f"{path}.clauses",
        ))
        return metadata
    reachable = _reachable_trigger_owners(
        list(claim.get("support_ids") or []),
        observations,
        claims,
    )
    required_clause_fields = set(policy.get("clause_required_fields") or [])
    allowed_operators = set(policy.get("allowed_operators") or [])
    seen: set[tuple[str, str, str]] = set()
    for index, clause in enumerate(clauses):
        clause_path = f"{path}.clauses[{index}]"
        if not isinstance(clause, dict) or set(clause) != required_clause_fields:
            defects.append(Defect(
                    "claim.current_basis_clause_schema",
                    "current_basis clause differs from the exact typed field set",
                    clause_path,
            ))
            continue
        raw_owner_type = clause.get("owner_type")
        raw_owner_id = clause.get("owner_id")
        raw_field = clause.get("field")
        raw_operator = clause.get("operator")
        owner_type = _text(raw_owner_type)
        owner_id = _text(raw_owner_id)
        field = _text(raw_field)
        if not all(
            _canonical_closed_string(value)
            for value in (raw_owner_type, raw_owner_id, raw_field, raw_operator)
        ):
            defects.append(Defect(
                    "claim.current_basis_identifier_noncanonical",
                    "current_basis identifiers must be exact closed-schema strings",
                    clause_path,
            ))
            continue
        if raw_operator not in allowed_operators:
            defects.append(Defect(
                    "claim.current_basis_operator",
                    "current_basis operator must be equals",
                    f"{clause_path}.operator",
            ))
        if owner_id not in reachable:
            defects.append(Defect(
                    "claim.current_basis_owner_unbound",
                    "current_basis owner must be reachable from the claim support DAG",
                    f"{clause_path}.owner_id",
            ))
        owner_found = False
        current_value: Any = None
        allowed_values: set[Any] = set()
        if owner_type == "observation":
            owner = observations.get(owner_id) or {}
            source = _text(owner.get("source"))
            allowed_values = set(
                ((policy.get("observation_fields") or {}).get(source) or {}).get(field)
                or []
            )
            owner_found, current_value = _nested_value(owner.get("metrics") or {}, field)
            if source:
                metadata["sources"].add(source)
        elif owner_type == "claim":
            owner = claims.get(owner_id) or {}
            owner_claim_type = _text(owner.get("claim_type"))
            owner_account = _text(owner.get("account"))
            allowed_values = set(
                ((policy.get("claim_fields") or {}).get(owner_claim_type) or {}).get(field)
                or []
            )
            owner_found, current_value = _nested_value(owner, field)
            if owner_account not in {"shared", account}:
                defects.append(Defect(
                        "claim.current_basis_cross_account",
                        "current_basis cannot consume the other account",
                        f"{clause_path}.owner_id",
                ))
            if owner_claim_type:
                metadata["claim_types"].add(owner_claim_type)
        else:
            defects.append(Defect(
                    "claim.current_basis_owner_type",
                    "current_basis owner_type must be observation or claim",
                    f"{clause_path}.owner_type",
            ))
        if not allowed_values:
            defects.append(Defect(
                    "claim.current_basis_field_forbidden",
                    "current_basis field is outside the closed typed-owner policy",
                    f"{clause_path}.field",
            ))
        elif not owner_found:
            defects.append(Defect(
                    "claim.current_basis_field_missing",
                    "current_basis field is absent from the certified owner",
                    f"{clause_path}.field",
            ))
        value = clause.get("value")
        if not _typed_domain_contains(allowed_values, value):
            defects.append(Defect(
                    "claim.current_basis_value_domain",
                    "current_basis value is outside the typed field domain",
                    f"{clause_path}.value",
            ))
        if owner_found and not (
            type(value) is type(current_value) and value == current_value
        ):
            defects.append(Defect(
                    "claim.current_basis_value_drift",
                    "current_basis value must mechanically equal the current certified owner field",
                    f"{clause_path}.value",
            ))
        signature = (owner_type, owner_id, field)
        if signature in seen:
            defects.append(Defect(
                    "claim.current_basis_clause_duplicate",
                    "duplicate current_basis typed owner",
                    clause_path,
            ))
        seen.add(signature)
        polarity_policy = policy.get("evidence_polarity") or {}
        evidence_direction = "neutral"
        if owner_type == "observation":
            direct_fields = set(
                ((polarity_policy.get("direct_direction_observation_fields") or {}).get(source))
                or []
            )
            if field in direct_fields:
                evidence_direction = _text(
                    (polarity_policy.get("direction_value_map") or {}).get(value)
                ) or "neutral"
            elif (
                source == "Exocharts"
                and field == polarity_policy.get("relative_exocharts_field")
            ):
                reference_source = _text(
                    polarity_policy.get("relative_exocharts_reference_source")
                )
                reference_field = _text(
                    polarity_policy.get("relative_exocharts_reference_field")
                )
                reference_directions: set[str] = set()
                for reachable_id in reachable:
                    reference = observations.get(reachable_id) or {}
                    if reference.get("source") != reference_source:
                        continue
                    found, reference_value = _nested_value(
                        reference.get("metrics") or {}, reference_field
                    )
                    if found:
                        mapped = _text(
                            (polarity_policy.get("direction_value_map") or {}).get(
                                reference_value
                            )
                        )
                        if mapped:
                            reference_directions.add(mapped)
                if len(reference_directions) != 1:
                    defects.append(Defect(
                            "claim.current_basis_relative_reference",
                            "Exocharts polarity requires exactly one reachable typed Coinglass direction",
                            clause_path,
                    ))
                else:
                    reference_direction = next(iter(reference_directions))
                    relation = _text(
                        (polarity_policy.get("relative_exocharts_map") or {}).get(value)
                    )
                    if relation == "same_as_reference":
                        evidence_direction = reference_direction
                    elif relation == "opposite_of_reference":
                        evidence_direction = {
                            "long": "short",
                            "short": "long",
                        }.get(reference_direction, "neutral")
                    else:
                        evidence_direction = "neutral"
        try:
            polarity = classify_evidence_polarity(
                subject_direction=subject_direction,
                evidence_direction=evidence_direction,
            )
        except ValueError:
            defects.append(Defect(
                    "claim.current_basis_subject_direction",
                    "current_basis requires a certified long/short/neutral/observe direction from the same account thesis",
                    path,
            ))
        else:
            metadata["polarities"].append(polarity.as_dict())
            if (
                claim.get("claim_type") == "strongest_counterevidence"
                and polarity.effect
                != polarity_policy.get("strongest_counter_required_effect")
            ):
                defects.append(Defect(
                        "claim.current_basis_polarity",
                        "strongest counterevidence may contain only typed clauses that oppose the current account thesis",
                        clause_path,
                ))
    polarity_policy = policy.get("evidence_polarity") or {}
    non_directional_subjects = set(
        polarity_policy.get("non_directional_subject_directions") or []
    )
    if (
        claim.get("claim_type") == "strongest_counterevidence"
        and subject_direction in non_directional_subjects
        and polarity_policy.get(
            "non_directional_counter_requires_one_coherent_alternative_direction"
        )
        is True
    ):
        alternative_directions = {
            _text(item.get("evidence_direction"))
            for item in metadata["polarities"]
            if _text(item.get("effect")) == "counter"
        }
        if len(alternative_directions) != 1:
            defects.append(Defect(
                    "claim.current_basis_counter_direction_incoherent",
                    "a non-directional thesis requires one coherent directional alternative in its strongest counter",
                    path,
            ))
    return metadata

def _validate_structural_noise_buffer(
    claim_id: str,
    claim: dict[str, Any],
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    defects: list[Defect],
    *,
    buffer_policy: dict[str, Any],
    stop_policy: dict[str, Any],
    direction: str,
) -> None:
    """Certify an evidence-bound noise envelope before decision risk math."""

    path = f"claims.{claim_id}.structural_noise_buffer"
    value = claim.get("structural_noise_buffer")
    required_fields = set(buffer_policy.get("required_fields") or [])
    if not isinstance(value, dict) or not required_fields or set(value) != required_fields:
        defects.append(Defect(
                "claim.structural_noise_buffer_schema",
                "invalidation_path requires the exact sealed structural-noise buffer schema",
                path,
        ))
        return
    if (
        value.get("schema_version") != buffer_policy.get("schema_version")
        or value.get("method_code") != buffer_policy.get("method_code")
        or value.get("risk_budget_input_used") is not False
        or buffer_policy.get("risk_budget_input_used") is not False
        or buffer_policy.get("compiler_may_infer") is not False
    ):
        defects.append(Defect(
                "claim.structural_noise_buffer_method",
                "structural-noise buffer must be selected in reasoning before risk math and may not consume the risk budget",
                path,
        ))
    observation_id = _text(value.get("observation_id"))
    observation = observations.get(observation_id) or {}
    reachable = _reachable_trigger_owners(
        list(claim.get("support_ids") or []), observations, claims
    )
    if (
        observation.get("source") != buffer_policy.get("source")
        or observation_id not in reachable
    ):
        defects.append(Defect(
                "claim.structural_noise_buffer_owner",
                "structural-noise buffer must bind a reachable current-run TradingView observation",
                f"{path}.observation_id",
        ))
    visual_evidence_ref = _text(value.get("visual_evidence_ref"))
    evidence_refs = {
        _text(item) for item in observation.get("evidence_refs") or [] if _text(item)
    }
    visual_citations = [
        item
        for item in observation.get("visual_citations") or []
        if isinstance(item, dict)
    ]
    if (
        not visual_evidence_ref
        or visual_evidence_ref not in evidence_refs
        or not any(
            _text(item.get("evidence_ref")) == visual_evidence_ref
            for item in visual_citations
        )
    ):
        defects.append(Defect(
                "claim.structural_noise_buffer_visual_binding",
                "structural-noise basis must bind a cited current-run TradingView image",
                f"{path}.visual_evidence_ref",
        ))
    timeframe = _text(value.get("timeframe")).lower()
    allowed_timeframes = {
        _text(item).lower() for item in stop_policy.get("allowed_timeframes") or []
    }
    if not timeframe or timeframe not in allowed_timeframes:
        defects.append(Defect(
                "claim.structural_noise_buffer_timeframe",
                "structural-noise buffer timeframe is outside the account stop policy",
                f"{path}.timeframe",
        ))
    status = _text(value.get("status"))
    if status not in set(buffer_policy.get("allowed_statuses") or []):
        defects.append(Defect(
                "claim.structural_noise_buffer_status",
                "structural-noise status is outside the closed authority vocabulary",
                f"{path}.status",
        ))
        return
    non_directional_subjects = set(
        buffer_policy.get("non_directional_subject_directions") or []
    )
    non_directional_reason = _text(
        buffer_policy.get("non_directional_reason_code")
    )
    if status == "insufficient":
        if value.get("insufficiency_reason_code") not in set(
            buffer_policy.get("insufficient_reason_codes") or []
        ):
            defects.append(Defect(
                    "claim.structural_noise_buffer_insufficient_reason",
                    "insufficient structural noise requires a closed reason code",
                    f"{path}.insufficiency_reason_code",
            ))
        if (
            direction in non_directional_subjects
            and value.get("insufficiency_reason_code") != non_directional_reason
        ) or (
            direction not in non_directional_subjects
            and value.get("insufficiency_reason_code") == non_directional_reason
        ):
            defects.append(Defect(
                    "claim.structural_noise_buffer_direction_applicability",
                    "non-directional theses must use the closed non-directional N/A reason; directional theses may not use it",
                    f"{path}.insufficiency_reason_code",
            ))
        null_fields = set(
            buffer_policy.get("insufficient_numeric_fields_must_be_null") or []
        ) | {"anchor_kind", "anchor_source_field"}
        if any(value.get(field) is not None for field in null_fields):
            defects.append(Defect(
                    "claim.structural_noise_buffer_insufficient_fabrication",
                    "an insufficient or non-directional noise basis may not fabricate an anchor, boundary or distance",
                    path,
            ))
        return
    if direction in non_directional_subjects:
        defects.append(Defect(
                "claim.structural_noise_buffer_direction_applicability",
                "a non-directional thesis cannot certify a directional structural stop; use the closed N/A insufficient result",
                f"{path}.status",
        ))
        return
    if value.get("insufficiency_reason_code") is not None:
        defects.append(Defect(
                "claim.structural_noise_buffer_certified_reason",
                "a certified structural-noise basis must not carry an insufficiency reason",
                f"{path}.insufficiency_reason_code",
        ))
    anchor_kind = _text(value.get("anchor_kind"))
    anchor_source_field = _text(value.get("anchor_source_field"))
    if anchor_kind not in set(stop_policy.get("allowed_anchor_kinds") or []) or not _matches_policy_path(
        anchor_source_field,
        list(stop_policy.get("allowed_anchor_source_fields") or []),
    ):
        defects.append(Defect(
                "claim.structural_noise_buffer_anchor_contract",
                "reasoning-owned noise anchor is outside the structural-stop authority",
                f"{path}.anchor_source_field",
        ))
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
        defects.append(Defect(
                "claim.structural_noise_buffer_anchor_direction",
                "reasoning-owned noise anchor does not face outward for the same-account thesis",
                f"{path}.anchor_kind",
        ))
    anchor_price = _json_number(value.get("anchor_price"))
    certified_anchor = None
    if anchor_source_field:
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
        defects.append(Defect(
                "claim.structural_noise_buffer_anchor_value",
                "reasoning-owned anchor_price must equal its cited TradingView field",
                f"{path}.anchor_price",
        ))
    cited_metric_path = anchor_source_field.removeprefix("metrics.")
    if cited_metric_path and not any(
        _text(item.get("evidence_ref")) == visual_evidence_ref
        and cited_metric_path in set(item.get("metric_paths") or [])
        for item in visual_citations
    ):
        defects.append(Defect(
                "claim.structural_noise_buffer_anchor_visual_citation",
                "the selected image must cite the exact TradingView anchor field",
                f"{path}.visual_evidence_ref",
        ))
    zone_timeframe_field = re.sub(
        r"\.(?:upper_bound|lower_bound)$", ".timeframe", anchor_source_field
    )
    try:
        certified_timeframe = _text(
            _resolve_concrete_value_path(observation, zone_timeframe_field)
        ).lower()
    except ValueError:
        certified_timeframe = ""
    if certified_timeframe != timeframe:
        defects.append(Defect(
                "claim.structural_noise_buffer_timeframe_binding",
                "structural-noise timeframe must equal the cited anchor zone timeframe",
                f"{path}.timeframe",
        ))
    price_distance = _json_number(value.get("price_distance"))
    if price_distance is None or price_distance <= 0:
        defects.append(Defect(
                "claim.structural_noise_buffer_distance",
                "structural-noise buffer price_distance must be a positive Arabic-numeric distance",
                f"{path}.price_distance",
        ))
    noise_outer_boundary = _json_number(value.get("noise_outer_boundary"))
    if noise_outer_boundary is None or noise_outer_boundary <= 0:
        defects.append(Defect(
                "claim.structural_noise_buffer_boundary",
                "certified noise_outer_boundary must be a positive visible price",
                f"{path}.noise_outer_boundary",
        ))
    envelope_is_outward = structural_noise_stop_is_outside(
        direction=direction,
        anchor_price=anchor_price,
        noise_outer_boundary=noise_outer_boundary,
        price_distance=price_distance,
    )
    if not envelope_is_outward:
        defects.append(Defect(
                "claim.structural_noise_buffer_economic_insufficiency",
                "the reasoning-owned stop distance must place the stop strictly outside the visible noise envelope",
                path,
        ))

def _source_role_action_leak(source: str, value: Any) -> bool:
    text = _text(value)
    if source not in set(REQUIRED_SOURCES):
        return False
    account_action = re.compile(
        r"(?:Maker|主账户).{0,24}?"
        r"(?P<action>做多|做空|开仓|下单|挂单|买入|卖出|追多|追空|翻多|翻空|翻向|立即执行)",
        re.I,
    )
    directive_action = re.compile(
        r"(?:立即|同步|直接|应当|应该|建议|要求|计划|据此).{0,12}?"
        r"(?P<action>做多|做空|开仓|下单|挂单|买入|卖出|追多|追空|翻多|翻空|翻向|执行)",
        re.I,
    )
    for clause in STRONG_CLAUSE_SPLIT_RE.split(text):
        for pattern in (account_action, directive_action):
            for marker in pattern.finditer(clause):
                action_start = marker.start("action")
                if _action_marker_is_negated(clause, action_start):
                    continue
                return True
    return False

def _action_marker_is_negated(clause: str, marker_start: int) -> bool:
    prefix = clause[max(0, marker_start - 32):marker_start]
    return bool(
        re.search(
            r"(?:不|未|无|非|没有|禁止|不得|不可|不能|不应|不会|不允许|避免|拒绝)"
            r".{0,24}$",
            prefix,
        )
    )


_EXECUTION_PARAMETER_MARKER_RE = re.compile(
    r"(?:单价|委托价|保护价|挂单价|目标价|代表入场|入场|开仓|下单|挂单|成交(?!量)|"
    r"(?:Maker|主账户|账户|计划).{0,8}(?:买入|卖出)|止损|止盈|"
    r"取消价|TP1|TP2|杠杆|仓位|(?:计划|账户)持仓|名义本金|倍杠杆)",
    re.I,
)
_EXECUTION_NUMBER_RE = re.compile(
    r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?!\s*(?:[HhMmDd]|分钟|小时|天|%|％|分|个百分点))"
)
_EXECUTION_CHINESE_NUMBER_RE = re.compile(
    r"[零〇一二两三四五六七八九十百千万亿]{2,}(?!\s*(?:分钟|小时|天|分|个百分点))"
)
_SMA20_PERIOD_PATTERN = (
    r"(?<![A-Za-z0-9])"
    r"(?:SMA\s*20(?![A-Za-z0-9])|(?:20|二十)\s*(?:周期|期)\s*均线)"
)
_NON_EXECUTION_SMA20_PERIOD_RE = re.compile(
    _SMA20_PERIOD_PATTERN,
    re.I,
)
_NEGATED_SMA20_EXECUTION_PREFIX_RE = re.compile(
    r"(?:不|不得|禁止|不可|不能|不应|不该|严禁)\s*(?:将|以)?\s*$",
    re.I,
)
_EXECUTION_PRICE_ROLE_PATTERN = (
    r"(?:入场(?:价|价格|区|区域)?|止损(?:价|价格)?|取消价|挂单价|"
    r"委托价|保护价|目标价|止盈(?:价|价格)?|TP1|TP2)"
)
_EXECUTION_SMA20_ANCHOR_RE = re.compile(
    rf"(?:"
    rf"{_EXECUTION_PRICE_ROLE_PATTERN}\s*"
    rf"(?:设在|设为|为|按照|按|取自|锚定(?:于|为)?|跟随|参考|采用|使用)\s*"
    rf"{_SMA20_PERIOD_PATTERN}"
    rf"|(?:将|以)?\s*{_SMA20_PERIOD_PATTERN}\s*"
    rf"(?:作为|用作|当作|设为|确定为|充当|视为)\s*"
    rf"{_EXECUTION_PRICE_ROLE_PATTERN}"
    rf"|{_SMA20_PERIOD_PATTERN}\s*(?:时|后|则|即|即刻|便)\s*"
    rf"(?:执行)?\s*(?:入场|开仓|下单|挂单|止损|取消)"
    rf")",
    re.I,
)
_EXECUTION_ABSOLUTE_PHRASE_RE = re.compile(
    r"(?:单一价格|代表入场|一次性(?:满仓|开仓|下单|挂单)|满仓|all[- ]?in)",
    re.I,
)
_SCORE_SECOND_TRUTH_RE = re.compile(
    r"(?:(?:盘口|盘面|总分|评分|分数).{0,16}"
    r"(?:\d{1,3}(?:\s*/\s*\d{1,3})?\s*分?|[零〇一二两三四五六七八九十百]{1,6}\s*分)"
    r"|(?:\d{1,3}|[零〇一二两三四五六七八九十百]{1,6})\s*分.{0,16}"
    r"(?:盘口|盘面|评分|分数))"
)

def _execution_parameter_leak(value: Any) -> str | None:
    """Return a forbidden execution token found outside its typed owner."""

    text = _text(value)
    absolute = _EXECUTION_ABSOLUTE_PHRASE_RE.search(text)
    if absolute:
        return absolute.group(0)
    for dynamic_indicator_anchor in _EXECUTION_SMA20_ANCHOR_RE.finditer(text):
        indicator = _NON_EXECUTION_SMA20_PERIOD_RE.search(
            dynamic_indicator_anchor.group(0)
        )
        indicator_start = (
            dynamic_indicator_anchor.start()
            if indicator is None
            else dynamic_indicator_anchor.start() + indicator.start()
        )
        negation_prefix = text[max(0, indicator_start - 12) : indicator_start]
        if _NEGATED_SMA20_EXECUTION_PREFIX_RE.search(negation_prefix):
            continue
        return dynamic_indicator_anchor.group(0)
    markers = list(_EXECUTION_PARAMETER_MARKER_RE.finditer(text))
    if not markers:
        return None
    indicator_period_spans = [
        match.span() for match in _NON_EXECUTION_SMA20_PERIOD_RE.finditer(text)
    ]
    for number in [
        *_EXECUTION_NUMBER_RE.finditer(text),
        *_EXECUTION_CHINESE_NUMBER_RE.finditer(text),
    ]:
        if any(
            start <= number.start() and number.end() <= end
            for start, end in indicator_period_spans
        ):
            continue
        if any(abs(number.start() - marker.start()) <= 24 for marker in markers):
            return text[number.start():number.end()]
    return None

def _score_second_truth(value: Any) -> bool:
    return bool(_SCORE_SECOND_TRUTH_RE.search(_text(value)))


_DIRECTION_TERM_MAP = {
    "做多": "long",
    "偏多": "long",
    "看多": "long",
    "看涨": "long",
    "转多": "long",
    "多头": "long",
    "多方": "long",
    "上涨方向": "long",
    "上行方向": "long",
    "做空": "short",
    "偏空": "short",
    "看空": "short",
    "看跌": "short",
    "转空": "short",
    "空头": "short",
    "空方": "short",
    "下跌方向": "short",
    "下行方向": "short",
    "中性": "neutral",
    "观望": "neutral",
    "观察": "neutral",
}
_DIRECTION_TERM_PATTERN = "|".join(
    sorted((re.escape(item) for item in _DIRECTION_TERM_MAP), key=len, reverse=True)
)
_DIRECTION_TARGET_BY_CLAIM_TYPE = {
    "orderflow_interpretation": r"(?:订单流|盘口|同锚点主腿)",
    "main_account_thesis": r"(?:主账户|中线)",
    "maker_thesis": r"(?:Maker|日内)",
}

def _direction_assertion_is_inactive(clause: str, start: int, end: int) -> bool:
    """Return whether a direction token is conditional, negated or historical."""

    prefix = clause[max(0, start - 24):start]
    suffix = clause[end:min(len(clause), end + 24)]
    if re.search(
        r"(?:若|如果|一旦|除非|假如|倘若|当(?!前|下)).{0,20}$",
        prefix,
    ):
        return True
    if re.search(
        r"(?:并非|不是|不再|不|未|非|没有|禁止|不得|不能|不会|无须|无需|"
        r"取消|拒绝|避免)(?:再|会|应当|应该|立即|继续|仍然|计划|选择|改为|转为|\s){0,4}$",
        prefix,
    ):
        return True
    if re.search(
        r"(?:不把|不将|不得把|不得将|不能把|不能将).{0,18}"
        r"(?:误?写成|视为|解释为|当作|作为).{0,6}$",
        prefix,
    ):
        return True
    if re.search(
        r"(?:信号|证据|条件|力量|意愿|订单|人群|参与者|回补|清算|止损|平仓|挤压)",
        suffix[:8],
    ):
        return True
    if (
        re.search(r"(?:原|此前|先前|上一轮|旧).{0,10}$", prefix)
        and re.search(r"(?:结论|判断|方向)?.{0,8}(?:取消|失效|废止|不再沿用)", suffix)
    ):
        return True
    return False

def _active_claim_direction_assertions(
    value: Any,
    *,
    claim_type: str,
) -> tuple[str, ...]:
    """Extract only active direction assertions owned by the current claim.

    Bare participant nouns such as ``空头回补`` and local evidence such as
    ``15m偏空`` are not direction owners.  The typed ``direction`` field stays
    authoritative; this parser only rejects an explicit prose second truth.
    """

    text = _text(value)
    target_pattern = _DIRECTION_TARGET_BY_CLAIM_TYPE.get(claim_type, r"(?!)")
    patterns = (
        re.compile(
            rf"(?:最终|当前|本轮|同锚点)?(?:的)?(?:主判|结论|方向)"
            rf"(?:仍|继续|已经|已|将|明确|维持|保持|改为|转为|偏向|为|是|=|：|:|\s){{0,8}}"
            rf"(?P<term>{_DIRECTION_TERM_PATTERN})",
            re.I,
        ),
        re.compile(
            rf"{target_pattern}.{{0,10}}?(?:维持|保持|改为|转为|选择|计划|决定|仍|继续|明确|呈现|表现为)"
            rf".{{0,6}}?(?P<term>{_DIRECTION_TERM_PATTERN})",
            re.I,
        ),
        re.compile(
            rf"{target_pattern}.{{0,6}}?(?P<term>{_DIRECTION_TERM_PATTERN})",
            re.I,
        ),
        re.compile(
            rf"(?:最终|主判|结论|而是|立即|改为|转为|维持|保持|选择|计划|决定|应当|应该)"
            rf".{{0,8}}?(?P<term>{_DIRECTION_TERM_PATTERN})",
            re.I,
        ),
        re.compile(r"(?P<term>做多|做空)", re.I),
    )
    assertions: list[tuple[int, str]] = []
    offset = 0
    for strong_clause in STRONG_CLAUSE_SPLIT_RE.split(text):
        strong_start = text.find(strong_clause, offset)
        if strong_start < 0:
            strong_start = offset
        minor_offset = 0
        for clause in MINOR_CLAUSE_SPLIT_RE.split(strong_clause):
            clause_start = strong_clause.find(clause, minor_offset)
            if clause_start < 0:
                clause_start = minor_offset
            stripped = clause.strip()
            leading = len(clause) - len(clause.lstrip())
            if stripped and not re.match(r"^(?:若|如果|一旦|除非|假如|倘若)", stripped):
                seen_spans: set[tuple[int, int]] = set()
                for pattern in patterns:
                    for match in pattern.finditer(clause):
                        term_start, term_end = match.span("term")
                        span = (term_start, term_end)
                        if span in seen_spans or _direction_assertion_is_inactive(
                            clause, term_start, term_end
                        ):
                            continue
                        seen_spans.add(span)
                        term = match.group("term")
                        direction = _DIRECTION_TERM_MAP.get(term)
                        if direction:
                            assertions.append(
                                (
                                    strong_start + clause_start + leading + term_start,
                                    direction,
                                )
                            )
            minor_offset = clause_start + len(clause)
        offset = strong_start + len(strong_clause)
    return tuple(direction for _, direction in sorted(set(assertions)))

def _typed_direction_prose_issue(
    value: Any,
    expected_direction: str,
    *,
    claim_type: str,
) -> str | None:
    """Detect an active prose direction opposite to the typed owner."""

    assertions = set(
        _active_claim_direction_assertions(value, claim_type=claim_type)
    )
    if expected_direction in {"long", "bullish"}:
        if "short" in assertions or "neutral" in assertions:
            return "opposite_bearish_marker"
    elif expected_direction in {"short", "bearish"}:
        if "long" in assertions or "neutral" in assertions:
            return "opposite_bullish_marker"
    elif expected_direction in {"neutral", "observe"} and assertions & {
        "long",
        "short",
    }:
        return "direction_marker_for_non_directional_owner"
    return None

def _causal_marker_is_negated(clause: str, marker_start: int) -> bool:
    prefix = clause[max(0, marker_start - 24):marker_start]
    immediate_negation = re.search(
        r"(?:不|未|非|无须|无需|不得|不可|不能|不会|禁止|拒绝|避免|互不|"
        r"不互相|不得互相|不可互相|不能互相)"
        r"(?:再|会|应当|应该|直接|强制|相互|互相|继续|仍然|\s){0,3}$",
        prefix,
    )
    scoped_denial = re.search(
        r"(?:不以|不得以|不可用|不能用|不把|不将|禁止用|拒绝以|"
        r"不因|不会因|不得因|不受|不由).{0,18}$",
        prefix,
    )
    return bool(immediate_negation or scoped_denial)

def _account_causal_leak(value: Any, account: str) -> str | None:
    """Return the first causal marker that makes one account consume the other.

    Account metadata supplies the subject, so an account-specific claim or
    section does not need to repeat its own label.  Mentioning the other
    account is allowed for an explicit non-causal boundary such as "independent
    and not mutually referenced", but never as a decision input.
    """

    text = _text(value)
    opposite = "maker" if account == "main" else "main"
    for clause in STRONG_CLAUSE_SPLIT_RE.split(text):
        if not ACCOUNT_LABEL_RE[opposite].search(clause):
            continue
        for marker in ACCOUNT_CAUSAL_MARKER_RE.finditer(clause):
            if not _causal_marker_is_negated(clause, marker.start()):
                return marker.group(0)
    return None

def _independent_boundary_issue(value: Any) -> str | None:
    """Validate that a two-account comparison remains post-hoc and non-causal."""

    text = _text(value)
    if not INDEPENDENT_BOUNDARY_RE.search(text):
        return "missing_explicit_independence"
    for clause in STRONG_CLAUSE_SPLIT_RE.split(text):
        has_main = bool(ACCOUNT_LABEL_RE["main"].search(clause))
        has_maker = bool(ACCOUNT_LABEL_RE["maker"].search(clause))
        if not (has_main and has_maker):
            continue
        for marker in BOUNDARY_CONNECTOR_RE.finditer(clause):
            if not _causal_marker_is_negated(clause, marker.start()):
                return marker.group(0)

        minor_clauses = [
            item for item in MINOR_CLAUSE_SPLIT_RE.split(clause) if item.strip()
        ]
        seen_accounts: set[str] = set()
        for minor in minor_clauses:
            minor_accounts = {
                name for name, pattern in ACCOUNT_LABEL_RE.items() if pattern.search(minor)
            }
            for marker in ACCOUNT_CAUSAL_MARKER_RE.finditer(minor):
                if _causal_marker_is_negated(minor, marker.start()):
                    continue
                if len(minor_accounts) == 2:
                    return marker.group(0)
                if minor_accounts and seen_accounts - minor_accounts and BOUNDARY_LOOKBACK_RE.fullmatch(marker.group(0)):
                    return marker.group(0)
            seen_accounts.update(minor_accounts)
    return None

def _required_observation_metrics(root: Path | None) -> dict[str, set[str]]:
    required = {
        source: set(values) for source, values in MINIMUM_OBSERVATION_METRICS.items()
    }
    if root is None:
        return required
    policy = load_scoring_policy(root=root)
    source_roles = ((policy.get("gold_methodology") or {}).get("source_roles") or {})
    for source, policy_key in POLICY_SOURCE_KEYS.items():
        role = source_roles.get(policy_key)
        if not isinstance(role, dict):
            raise ValueError(f"scoring contract source role is missing: {policy_key}")
        paths = role.get("required_value_paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"scoring contract required_value_paths is missing: {policy_key}")
        required[source].update(_text(item) for item in paths if _text(item))
    return required

def _minimum_sources_by_claim_type(root: Path | None) -> dict[str, int]:
    if root is None:
        return {}
    policy = load_scoring_policy(root=root)
    values = (
        (policy.get("gold_methodology") or {}).get(
            "minimum_independent_sources_by_claim_type"
        )
        or {}
    )
    if not isinstance(values, dict):
        raise ValueError("minimum source policy must be an object")
    result: dict[str, int] = {}
    for claim_type, minimum in values.items():
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
            raise ValueError(f"invalid minimum source policy: {claim_type}")
        result[str(claim_type)] = minimum
    return result

def _trigger_logic_policy(root: Path | None) -> dict[str, Any]:
    policy_root = root or Path(__file__).resolve().parents[1]
    policy = load_scoring_policy(root=policy_root)
    trigger = ((policy.get("gold_methodology") or {}).get("account_trigger_logic"))
    if not isinstance(trigger, dict):
        raise ValueError("account_trigger_logic policy must be an object")
    expected = account_trigger_logic_projection()
    if set(trigger) != set(expected):
        raise ValueError("account_trigger_logic policy has an invalid field set")
    if trigger != expected:
        raise ValueError("account_trigger_logic differs from the domain registry")
    return trigger

def _current_basis_policy(root: Path | None) -> dict[str, Any]:
    policy_root = root or Path(__file__).resolve().parents[1]
    policy = load_scoring_policy(root=policy_root)
    current_basis = (
        (policy.get("gold_methodology") or {}).get("account_current_basis")
    )
    if not isinstance(current_basis, dict):
        raise ValueError("account_current_basis policy must be an object")
    expected = account_current_basis_projection()
    if set(current_basis) != set(expected):
        raise ValueError("account_current_basis policy has an invalid field set")
    if current_basis != expected:
        raise ValueError("account_current_basis differs from the domain registry")
    return current_basis

def _fundamental_event_policy(root: Path | None) -> dict[str, Any]:
    policy_root = root or Path(__file__).resolve().parents[1]
    policy = load_scoring_policy(root=policy_root)
    event_policy = (
        (policy.get("gold_methodology") or {}).get(
            "fundamental_event_assessment_policy"
        )
    )
    if not isinstance(event_policy, dict):
        raise ValueError("fundamental_event_assessment_policy must be an object")
    if event_policy.get("schema_version") != "fundamental-event-assessment-v1":
        raise ValueError("fundamental_event_assessment_policy version is unsupported")
    if (
        event_policy.get("load_bearing_allowed") is not False
        or event_policy.get("observation_only_reason_code")
        != "event_price_attribution_unavailable"
        or set(event_policy.get("forbidden_load_bearing_uses") or [])
        != {
            "winrate_adjustment",
            "account_current_basis",
            "account_trigger_logic",
        }
        or event_policy.get("price_attribution_basis_required_to_reenable")
        is not True
    ):
        raise ValueError(
            "fundamental-event-assessment-v1 must remain observation-only"
        )
    return event_policy

def reasoning_model_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("reasoning_sha256", None)
    return canonical_sha256(clean)

def _reachable_observations(
    claim_id: str,
    claims: dict[str, dict[str, Any]],
    observation_ids: set[str],
) -> set[str]:
    pending = [claim_id]
    visited: set[str] = set()
    found: set[str] = set()
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        if node in observation_ids:
            found.add(node)
            continue
        claim = claims.get(node) or {}
        pending.extend(_text(item) for item in claim.get("support_ids", []) if _text(item))
    return found

def _reachable_claim_ids(
    claim_id: str,
    claims: dict[str, dict[str, Any]],
) -> set[str]:
    found: set[str] = set()
    stack = list(claims.get(claim_id, {}).get("support_ids") or [])
    while stack:
        current = _text(stack.pop())
        if current in found or current not in claims:
            continue
        found.add(current)
        stack.extend(claims[current].get("support_ids") or [])
    return found

def _prepare_reasoning_validation(payload, evidence, reasoning_authority_sha256, evidence_root, methodology_root, defects):
    semantic_root = methodology_root or Path(__file__).resolve().parents[1]
    submission_contract = load_reasoning_submission_contract(root=semantic_root)
    expected_reasoning_fields = set(submission_contract["top_level"]["field_order"])
    observation_fields_by_source = {
        source: set(fields)
        for source, fields in submission_contract[
            "observation_fields_by_source"
        ].items()
        if source != "FedWatchPlanC"
    }
    fedwatch_plan_c_observation_fields = set(
        submission_contract["observation_fields_by_source"]["FedWatchPlanC"]
    )
    claim_fields_by_type = {
        claim_type: set(fields)
        for claim_type, fields in submission_contract[
            "claim_fields_by_type"
        ].items()
    }
    scenario_fields = set(submission_contract["scenario_fields"])
    evidence_result = evaluate_evidence(evidence, root=evidence_root)
    for defect in evidence_result.defects:
        defects.append(Defect(
                "binding.evidence_drift",
                f"certified evidence no longer validates: {defect.message}",
                defect.path,
        ))
    expected_evidence_hash = evidence_result.facts["snapshot_sha256"]
    expected_schema_version = REGISTRY.reasoning_model_schema_version
    if payload.get("schema_version") != expected_schema_version:
        defects.append(Defect("schema.invalid", f"expected {expected_schema_version}", "schema_version"))
    actual_reasoning_fields = set(payload) - {"reasoning_sha256"}
    if actual_reasoning_fields != expected_reasoning_fields:
        defects.append(Defect(
                "reasoning.schema_fields",
                f"{expected_schema_version} must use the exact typed field set; report_sections is forbidden",
                "reasoning",
        ))
    for key in ("trading_date", "slot"):
        if payload.get(key) != evidence.get(key):
            defects.append(Defect("binding.mismatch", f"reasoning {key} differs from evidence", key))
    if payload.get("evidence_snapshot_sha256") != expected_evidence_hash:
        defects.append(Defect("binding.evidence", "reasoning is not bound to the evidence snapshot", "evidence_snapshot_sha256"))
    if "methodology_sha256" in payload:
        defects.append(Defect(
                "binding.legacy_methodology_field",
                "reasoning must not use the ambiguous legacy methodology_sha256 field",
                "methodology_sha256",
        ))
    if payload.get("reasoning_authority_sha256") != reasoning_authority_sha256:
        defects.append(Defect(
                "binding.reasoning_authority",
                "reasoning is not bound to the sealed reasoning-phase authority",
                "reasoning_authority_sha256",
        ))

    evidence_paths = {
        _text(record.get("path"))
        for source in (evidence.get("sources") or {}).values()
        if isinstance(source, dict)
        for record in _record_paths(source)
        if _text(record.get("path"))
    }
    blockbeats_meta = (
        ((evidence.get("sources") or {}).get("BlockBeats") or {}).get("meta")
        or {}
    )
    expected_blockbeats_count = blockbeats_meta.get("selected_row_count")
    expected_blockbeats_window = blockbeats_meta.get("capture_window_hours")
    required_metrics = _required_observation_metrics(methodology_root)
    minimum_sources = _minimum_sources_by_claim_type(methodology_root)
    trigger_policy = _trigger_logic_policy(methodology_root)
    current_basis_policy = _current_basis_policy(methodology_root)
    event_policy = _fundamental_event_policy(methodology_root)
    scoring_policy = load_scoring_policy(
        root=methodology_root or Path(__file__).resolve().parents[1]
    )
    risk_execution_policy = scoring_policy.get("risk_execution") or {}
    structural_noise_buffer_policy = (
        risk_execution_policy.get("structural_noise_buffer_judgment") or {}
    )
    observations_payload = payload.get("observations")
    if not isinstance(observations_payload, list):
        defects.append(Defect("observations.invalid", "observations must be an array", "observations"))
        observations_payload = []
    observations: dict[str, dict[str, Any]] = {}
    observed_sources: set[str] = set()
    for index, item in enumerate(observations_payload):
        path = f"observations[{index}]"
        if not isinstance(item, dict):
            defects.append(Defect("observation.invalid", "observation must be an object", path))
            continue
        item_id = _text(item.get("id"))
        if not item_id or item_id in observations:
            defects.append(Defect("observation.id_invalid", "observation id is missing or duplicated", f"{path}.id"))
            continue
        observations[item_id] = item
        source = _text(item.get("source"))
        if source not in REQUIRED_SOURCES:
            defects.append(Defect("observation.source_invalid", f"invalid observation source: {source}", f"{path}.source"))
        else:
            observed_sources.add(source)
            expected_observation_fields = observation_fields_by_source[source]
            if source == "FedWatch":
                fedwatch_meta = (
                    (((evidence.get("sources") or {}).get("FedWatch") or {}).get("meta"))
                    or {}
                )
                if fedwatch_meta.get("selection_mode") == "kalshi_plan_c_fallback":
                    expected_observation_fields = fedwatch_plan_c_observation_fields
            if set(item) != expected_observation_fields:
                defects.append(Defect(
                        "observation.schema_fields",
                        f"{source} observation must use its exact closed field set",
                        path,
                ))
        if len(_text(item.get("fact"))) < 8:
            defects.append(Defect("observation.fact_thin", "observation fact is too short", f"{path}.fact"))
        elif not _contains_cjk(item.get("fact")):
            defects.append(Defect("observation.language", "observation fact must be Chinese-readable", f"{path}.fact"))
        if _source_role_action_leak(source, item.get("fact")):
            defects.append(Defect(
                    "observation.source_role_action_leak",
                    f"{source} fact cannot directly decide a main-account or Maker action",
                    f"{path}.fact",
            ))
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        for metric in sorted(required_metrics.get(source, set())):
            if metric not in metrics or not _text(metrics.get(metric)):
                defects.append(Defect("observation.metric_missing", f"{source} observation requires metric: {metric}", f"{path}.metrics.{metric}"))
        if source == "BlockBeats":
            try:
                selected_count_matches = (
                    int(metrics.get("selected_event_count"))
                    == int(expected_blockbeats_count)
                )
            except (TypeError, ValueError):
                selected_count_matches = False
            if not selected_count_matches:
                defects.append(Defect(
                        "blockbeats.selected_count_drift",
                        "BlockBeats reasoning selected-event count must equal the certified evidence count",
                        f"{path}.metrics.selected_event_count",
                ))
            try:
                window_matches = (
                    int(metrics.get("event_window_hours"))
                    == int(expected_blockbeats_window)
                )
            except (TypeError, ValueError):
                window_matches = False
            if not window_matches:
                defects.append(Defect(
                        "blockbeats.window_drift",
                        "BlockBeats reasoning window must equal the certified evidence window",
                        f"{path}.metrics.event_window_hours",
                ))
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            defects.append(Defect("observation.evidence_missing", "observation requires evidence_refs", f"{path}.evidence_refs"))
        else:
            for ref in refs:
                if _text(ref) not in evidence_paths:
                    defects.append(Defect("observation.evidence_outside_snapshot", f"unknown evidence ref: {ref}", f"{path}.evidence_refs"))

    for source in sorted(set(REQUIRED_SOURCES) - observed_sources):
        defects.append(Defect("observation.source_missing", f"reasoning requires an observation from {source}", "observations"))

    claims_payload = payload.get("claims")
    if not isinstance(claims_payload, list):
        defects.append(Defect("claims.invalid", "claims must be an array", "claims"))
        claims_payload = []
    claims: dict[str, dict[str, Any]] = {}
    return (semantic_root, submission_contract, claim_fields_by_type, scenario_fields, minimum_sources, trigger_policy, current_basis_policy, event_policy, scoring_policy, risk_execution_policy, structural_noise_buffer_policy, observations, claims_payload, claims)


def _validate_reasoning_claim_graph(claim_fields_by_type, claims, claims_payload, defects, event_policy, observations, structural_noise_buffer_policy):
    known_nodes = set(observations)
    claim_types: set[str] = set()
    for index, item in enumerate(claims_payload):
        path = f"claims[{index}]"
        if not isinstance(item, dict):
            defects.append(Defect("claim.invalid", "claim must be an object", path))
            continue
        item_id = _text(item.get("id"))
        if not item_id or item_id in claims or item_id in observations:
            defects.append(Defect("claim.id_invalid", "claim id is missing or duplicated", f"{path}.id"))
            continue
        claim_type = _text(item.get("claim_type"))
        claim_types.add(claim_type)
        if claim_type not in ALLOWED_CLAIM_TYPES:
            defects.append(Defect("claim.type_invalid", f"unsupported claim type: {claim_type}", f"{path}.claim_type"))
        elif set(item) != claim_fields_by_type[claim_type]:
            defects.append(Defect(
                    "claim.schema_fields",
                    f"{claim_type} must use its exact closed field set",
                    path,
            ))
        allowed_accounts = CLAIM_ACCOUNT_SCOPES.get(claim_type, set())
        account = _text(item.get("account"))
        if allowed_accounts and account not in allowed_accounts:
            defects.append(Defect(
                    "claim.account_drift",
                    f"{claim_type} account must be one of {sorted(allowed_accounts)}",
                    f"{path}.account",
            ))
        if claim_type == event_policy.get("event_realization_claim_type"):
            expected_event_claim_fields = {
                "id",
                "claim_type",
                "account",
                "selected_event_sha256",
                "realization_state",
                "conclusion",
                "support_ids",
                "counter_ids",
                "invalidation",
            }
            if set(item) != expected_event_claim_fields:
                defects.append(Defect(
                        "fundamental.event_claim_schema",
                        "fundamental_event_realization must use the exact typed claim field set",
                        path,
                ))
            if not re.fullmatch(
                r"[0-9a-f]{64}",
                _text(item.get("selected_event_sha256")),
            ):
                defects.append(Defect(
                        "fundamental.event_claim_hash",
                        "event realization requires one lowercase selected-event SHA-256",
                        f"{path}.selected_event_sha256",
                ))
            if item.get("realization_state") not in set(
                event_policy.get("event_realization_states") or []
            ):
                defects.append(Defect(
                        "fundamental.event_claim_state",
                        "event realization state is outside the closed authority vocabulary",
                        f"{path}.realization_state",
                ))
        support_ids = item.get("support_ids") if isinstance(item.get("support_ids"), list) else []
        counter_ids = item.get("counter_ids") if isinstance(item.get("counter_ids"), list) else []
        if not support_ids:
            defects.append(Defect("claim.support_missing", "claim requires support_ids", f"{path}.support_ids"))
        for ref in [*support_ids, *counter_ids]:
            if _text(ref) not in known_nodes:
                defects.append(Defect("claim.forward_or_missing_ref", f"claim reference must point to an earlier node: {ref}", path))
        if claim_type == event_policy.get("event_realization_claim_type"):
            direct_support_types = {
                _text(claims.get(_text(ref), {}).get("claim_type"))
                for ref in support_ids
            }
            missing_event_support = set(
                event_policy.get("event_realization_support_claim_types") or []
            ) - direct_support_types
            if missing_event_support:
                defects.append(Defect(
                        "fundamental.event_claim_support",
                        "event realization must directly bind fundamental_context and chart_interpretation",
                        f"{path}.support_ids",
                ))
        if claim_type in HIGH_IMPACT_CLAIMS and not counter_ids:
            defects.append(Defect("claim.counter_missing", f"{claim_type} requires explicit counterevidence", f"{path}.counter_ids"))
        if claim_type in HIGH_IMPACT_CLAIMS and not any(
            claims.get(_text(ref), {}).get("claim_type") == "strongest_counterevidence"
            and claims.get(_text(ref), {}).get("account") == account
            for ref in counter_ids
        ):
            defects.append(Defect("claim.counter_binding", f"{claim_type} must bind strongest_counterevidence", f"{path}.counter_ids"))
        if len(_text(item.get("conclusion"))) < 8:
            defects.append(Defect("claim.conclusion_thin", "claim conclusion is too short", f"{path}.conclusion"))
        elif not _contains_cjk(item.get("conclusion")):
            defects.append(Defect("claim.language", "claim conclusion must be Chinese-readable", f"{path}.conclusion"))
        if len(_text(item.get("invalidation"))) < 8:
            defects.append(Defect("claim.invalidation_missing", f"{claim_type} requires an invalidation condition", f"{path}.invalidation"))
        elif not _contains_cjk(item.get("invalidation")):
            defects.append(Defect("claim.invalidation_language", "claim invalidation must be Chinese-readable", f"{path}.invalidation"))
        if (
            claim_type != structural_noise_buffer_policy.get("required_claim_type")
            and "structural_noise_buffer" in item
        ):
            defects.append(Defect(
                    "claim.structural_noise_buffer_wrong_owner",
                    "structural_noise_buffer is owned only by invalidation_path",
                    f"{path}.structural_noise_buffer",
            ))
        for field in ("conclusion", "invalidation"):
            leak = _execution_parameter_leak(item.get(field))
            if leak:
                defects.append(Defect(
                        "claim.execution_parameter_second_truth",
                        f"claim prose cannot own an execution parameter outside the typed decision model: {leak}",
                        f"{path}.{field}",
                ))
            if _score_second_truth(item.get(field)):
                defects.append(Defect(
                        "claim.score_second_truth",
                        "claim prose cannot self-report a score; the typed score assessment is the only owner",
                        f"{path}.{field}",
                ))
        source_owner = SOURCE_ROLE_CLAIM_OWNER.get(claim_type)
        if source_owner:
            for field in ("conclusion", "invalidation"):
                if _source_role_action_leak(source_owner, item.get(field)):
                    defects.append(Defect(
                            "claim.source_role_action_leak",
                            f"{claim_type} cannot directly decide a main-account or Maker action",
                            f"{path}.{field}",
                    ))
        if account in {"main", "maker"}:
            for field in ("conclusion", "invalidation"):
                causal_marker = _account_causal_leak(item.get(field), account)
                if causal_marker:
                    opposite_label = "Maker" if account == "main" else "主账户"
                    defects.append(Defect(
                            "claim.cross_account_causal_text",
                            f"{account} claim cannot use {opposite_label} as a causal decision input: {causal_marker}",
                            f"{path}.{field}",
                    ))
        if claim_type == "main_account_thesis" and item.get("direction") not in {"long", "short", "neutral"}:
            defects.append(Defect("claim.direction_invalid", "main-account thesis requires long, short or neutral direction", f"{path}.direction"))
        if claim_type == "maker_thesis" and item.get("direction") not in {"long", "short", "observe"}:
            defects.append(Defect("claim.direction_invalid", "Maker thesis requires long, short or observe direction", f"{path}.direction"))
        if claim_type in {
            "orderflow_interpretation",
            "main_account_thesis",
            "maker_thesis",
        }:
            direction_conflict = _typed_direction_prose_issue(
                item.get("conclusion"),
                _text(item.get("direction")),
                claim_type=claim_type,
            )
            if direction_conflict:
                defects.append(Defect(
                        "claim.typed_direction_text_conflict",
                        "claim prose contradicts its typed direction owner",
                        f"{path}.conclusion",
                ))
        if claim_type == "orderflow_interpretation":
            assessment = (
                item.get("score_assessment")
                if isinstance(item.get("score_assessment"), dict)
                else {}
            )
            rationale_leak = _execution_parameter_leak(assessment.get("rationale"))
            if rationale_leak:
                defects.append(Defect(
                        "claim.score_rationale_second_truth",
                        f"score rationale cannot own execution parameters: {rationale_leak}",
                        f"{path}.score_assessment.rationale",
                ))
            if _score_second_truth(assessment.get("rationale")):
                defects.append(Defect(
                        "claim.score_rationale_second_truth",
                        "score rationale must explain evidence without declaring a second numeric score",
                        f"{path}.score_assessment.rationale",
                ))
            if _typed_direction_prose_issue(
                assessment.get("rationale"),
                _text(item.get("direction")),
                claim_type="orderflow_interpretation",
            ):
                defects.append(Defect(
                        "claim.score_rationale_direction_conflict",
                        "orderflow score rationale contradicts its typed direction owner",
                        f"{path}.score_assessment.rationale",
                ))
        if claim_type == "cannot_do" and _text(item.get("prohibition")) not in CANNOT_DO_CODES:
            defects.append(Defect(
                    "cannot_do.prohibition_invalid",
                    "cannot_do requires one standardized Maker prohibition code",
                    f"{path}.prohibition",
            ))
        invalidation_id = _text(item.get("invalidation_id"))
        if claim_type in HIGH_IMPACT_CLAIMS and (
            claims.get(invalidation_id, {}).get("claim_type") != "invalidation_path"
            or claims.get(invalidation_id, {}).get("account") != account
        ):
            defects.append(Defect("claim.invalidation_binding", f"{claim_type} must bind its own account invalidation_path", f"{path}.invalidation_id"))
        claims[item_id] = item
        known_nodes.add(item_id)

    for claim_type in sorted(REQUIRED_CLAIM_TYPES - claim_types):
        defects.append(Defect("claim.type_missing", f"required claim type is missing: {claim_type}", "claims"))

    claim_keys: dict[tuple[str, str], list[str]] = {}
    for claim_id, claim in claims.items():
        key = (_text(claim.get("claim_type")), _text(claim.get("account")))
        claim_keys.setdefault(key, []).append(claim_id)
    for (claim_type, account), ids in sorted(claim_keys.items()):
        if claim_type == event_policy.get("event_realization_claim_type"):
            continue
        if len(ids) > 1:
            defects.append(Defect(
                    "claim.account_cardinality",
                    f"{claim_type}/{account} must have exactly one certified claim",
                    "claims",
            ))
    event_claim_type = _text(event_policy.get("event_realization_claim_type"))
    blockbeats_observation = next(
        (
            item
            for item in observations.values()
            if item.get("source") == "BlockBeats"
        ),
        {},
    )
    expected_event_hashes = (
        (blockbeats_observation.get("metrics") or {}).get("selected_event_sha256")
        if isinstance(blockbeats_observation.get("metrics"), dict)
        else None
    )
    normalized_expected_event_hashes = (
        [_text(value) for value in expected_event_hashes]
        if isinstance(expected_event_hashes, list)
        else []
    )
    event_claims = [
        item
        for item in claims.values()
        if item.get("claim_type") == event_claim_type
    ]
    event_claim_counts: dict[str, int] = {}
    for item in event_claims:
        event_hash = _text(item.get("selected_event_sha256"))
        event_claim_counts[event_hash] = event_claim_counts.get(event_hash, 0) + 1
    if (
        len(normalized_expected_event_hashes) != 3
        or len(set(normalized_expected_event_hashes)) != 3
        or len(event_claims) != len(normalized_expected_event_hashes)
        or set(event_claim_counts) != set(normalized_expected_event_hashes)
        or any(count != 1 for count in event_claim_counts.values())
    ):
        defects.append(Defect(
                "fundamental.event_claim_cardinality",
                "each sealed BlockBeats top3 hash requires exactly one shared fundamental_event_realization claim",
                "claims",
        ))
    for claim_type in sorted(ACCOUNT_LOOP_CLAIM_TYPES):
        for account in ("main", "maker"):
            if (claim_type, account) not in claim_keys:
                defects.append(Defect(
                        "claim.account_loop_missing",
                        f"{account} requires its own {claim_type}",
                        "claims",
                ))


def _validate_reasoning_claim_semantics(claims, current_basis_policy, defects, event_policy, observations, risk_execution_policy, structural_noise_buffer_policy, trigger_policy):
    thesis_direction = {
        "main": next(
            (
                _text(item.get("direction"))
                for item in claims.values()
                if item.get("claim_type") == "main_account_thesis"
            ),
            "neutral",
        ),
        "maker": next(
            (
                _text(item.get("direction"))
                for item in claims.values()
                if item.get("claim_type") == "maker_thesis"
            ),
            "observe",
        ),
    }
    current_basis_claim_types = set(
        current_basis_policy.get("required_claim_types") or []
    )
    current_basis_metadata_by_claim_id: dict[str, dict[str, Any]] = {}
    for claim_id, claim in claims.items():
        claim_type = _text(claim.get("claim_type"))
        if claim_type not in current_basis_claim_types:
            if "current_basis" in claim:
                defects.append(Defect(
                        "claim.current_basis_wrong_owner",
                        "current_basis is owned only by counter/invalidation claims",
                        f"claims.{claim_id}.current_basis",
                ))
            continue
        account = _text(claim.get("account"))
        metadata = _validate_current_basis(
            claim_id,
            claim,
            observations,
            claims,
            defects,
            current_basis_policy,
            subject_direction=thesis_direction.get(account, ""),
        )
        current_basis_metadata_by_claim_id[claim_id] = metadata
        if (
            event_policy.get("load_bearing_allowed") is False
            and event_policy.get("aggregate_realization_claim_type")
            in set(metadata["claim_types"])
        ):
            defects.append(Defect(
                    "fundamental.event_observation_only_current_basis",
                    "fundamental-event-assessment-v1 lacks an event-aligned price basis and cannot own account current_basis",
                    f"claims.{claim_id}.current_basis",
            ))
    for claim_id, claim in claims.items():
        if claim.get("claim_type") != structural_noise_buffer_policy.get(
            "required_claim_type"
        ):
            continue
        account = _text(claim.get("account"))
        stop_policy_name = (
            "main_initial_stop_policy"
            if account == "main"
            else "maker_initial_stop_policy"
        )
        _validate_structural_noise_buffer(
            claim_id,
            claim,
            observations,
            claims,
            defects,
            buffer_policy=structural_noise_buffer_policy,
            stop_policy=risk_execution_policy.get(stop_policy_name) or {},
            direction=thesis_direction.get(account, ""),
        )
    for claim_id, claim in claims.items():
        claim_type = _text(claim.get("claim_type"))
        if claim_type not in TRIGGER_CONTROL_CLAIM_TYPES:
            continue
        account = _text(claim.get("account"))
        metadata = _validate_trigger_logic(
            claim_id,
            claim,
            observations,
            claims,
            defects,
            trigger_policy,
        )
        if (
            event_policy.get("load_bearing_allowed") is False
            and event_policy.get("aggregate_realization_claim_type")
            in set(metadata["claim_types"])
        ):
            defects.append(Defect(
                    "fundamental.event_observation_only_trigger",
                    "fundamental-event-assessment-v1 lacks an event-aligned price basis and cannot own account trigger_logic",
                    f"claims.{claim_id}.trigger_logic",
            ))
        sources = set(metadata["sources"])
        claim_owner_types = set(metadata["claim_types"])
        requirement_key = (
            "main"
            if account == "main"
            else "maker_counter"
            if claim_type == "strongest_counterevidence"
            else "maker_invalidation"
        )
        requirements = trigger_policy["account_source_requirements"][requirement_key]
        missing_always = set(requirements.get("always") or []) - sources
        if missing_always:
            defects.append(Defect(
                    "claim.trigger_required_owner_missing",
                    f"{claim_type}/{account} is missing typed owner(s): {sorted(missing_always)}",
                    f"claims.{claim_id}.trigger_logic.clauses",
            ))
        one_of_sources = set(requirements.get("one_of_sources") or [])
        one_of_claim_types = set(requirements.get("one_of_claim_types") or [])
        if (one_of_sources or one_of_claim_types) and not (
            one_of_sources & sources or one_of_claim_types & claim_owner_types
        ):
            defects.append(Defect(
                    "claim.trigger_priority_owner_missing",
                    f"{claim_type}/{account} lacks its required typed priority domain",
                    f"claims.{claim_id}.trigger_logic.clauses",
            ))
        direction = thesis_direction.get(account, "")
        opposite = (
            "bullish"
            if direction == "short"
            else "bearish"
            if direction == "long"
            else ""
        )
        if trigger_policy.get("opposite_state_required") and opposite and not any(
            opposite in targets
            and (
                field.startswith("timeframes.")
                or field == "final_direction"
            )
            for _, _, field, targets in metadata["targets"]
        ):
            defects.append(Defect(
                    "claim.trigger_opposite_state_missing",
                    f"{claim_type}/{account} must name the typed opposite state for the current account direction",
                    f"claims.{claim_id}.trigger_logic.clauses",
            ))
        non_directional_subjects = set(
            trigger_policy.get("non_directional_subject_directions") or []
        )
        trigger = (
            claim.get("trigger_logic")
            if isinstance(claim.get("trigger_logic"), dict)
            else {}
        )
        trigger_mode = _text(trigger.get("mode"))
        clause_polarities = _future_trigger_clause_polarities(
            metadata,
            mode=trigger_mode,
            trigger_policy=trigger_policy,
        )
        future_alternative_directions = {
            item_direction
            for item in clause_polarities
            if item.get("polarity_kind") == "absolute_direction"
            for item_direction in set(item.get("directions") or set())
            if item_direction in {"long", "short"}
        }
        if (
            direction in non_directional_subjects
            and trigger_policy.get(
                "non_directional_future_requires_one_coherent_alternative_direction"
            )
            is True
        ):
            if len(future_alternative_directions) != 1:
                defects.append(Defect(
                        "claim.trigger_non_directional_alternative_incoherent",
                        f"{claim_type}/{account} must name exactly one typed long or short alternative for a non-directional thesis",
                        f"claims.{claim_id}.trigger_logic.clauses",
                ))
            elif (
                claim_type == "strongest_counterevidence"
                and trigger_policy.get(
                    "non_directional_counter_future_must_match_current_counter_direction"
                )
                is True
            ):
                current_alternative_directions = {
                    _text(item.get("evidence_direction"))
                    for item in (
                        current_basis_metadata_by_claim_id.get(claim_id, {}).get(
                            "polarities"
                        )
                        or []
                    )
                    if _text(item.get("effect")) == "counter"
                    and _text(item.get("evidence_direction")) in {"long", "short"}
                }
                if current_alternative_directions != future_alternative_directions:
                    defects.append(Defect(
                            "claim.trigger_non_directional_counter_direction_drift",
                            "a non-directional strongest-counter trigger must preserve the one directional alternative certified by current_basis",
                            f"claims.{claim_id}.trigger_logic.clauses",
                    ))

        expected_counter_direction = {
            "long": "short",
            "short": "long",
        }.get(direction, "")
        current_alternative_directions = {
            _text(item.get("evidence_direction"))
            for item in (
                current_basis_metadata_by_claim_id.get(claim_id, {}).get(
                    "polarities"
                )
                or []
            )
            if _text(item.get("effect")) == "counter"
            and _text(item.get("evidence_direction")) in {"long", "short"}
        }
        if (
            not expected_counter_direction
            and claim_type == "strongest_counterevidence"
            and len(current_alternative_directions) == 1
        ):
            expected_counter_direction = next(iter(current_alternative_directions))
        if (
            not expected_counter_direction
            and claim_type == "invalidation_path"
            and len(future_alternative_directions) == 1
        ):
            expected_counter_direction = next(iter(future_alternative_directions))

        for item in clause_polarities:
            clause_index = int(item.get("index", 0))
            clause_path = f"claims.{claim_id}.trigger_logic.clauses[{clause_index}]"
            polarity_kind = _text(item.get("polarity_kind"))
            directions = set(item.get("directions") or set())
            if (
                polarity_kind == "relative_direction"
                and item.get("relative_operator_canonical") is not True
            ):
                defects.append(Defect(
                        (
                            "claim.exocharts_counter_polarity"
                            if account == "maker"
                            and claim_type == "strongest_counterevidence"
                            else "claim.trigger_relative_operator_noncanonical"
                        ),
                        "a relative future-direction clause requires the canonical equals_at_trigger operator",
                        clause_path,
                ))
            if polarity_kind == "relative_direction" and item.get(
                "relative_bound"
            ) is not True:
                defects.append(Defect(
                        (
                            "claim.exocharts_counter_polarity"
                            if (
                                account == "maker"
                                and claim_type == "strongest_counterevidence"
                                and "confirm" in set(item.get("targets") or [])
                            )
                            else "claim.trigger_relative_direction_unbound"
                        ),
                        "a relative future-direction clause requires an all-mode trigger with one bound Coinglass future direction",
                        clause_path,
                ))
                continue
            if (
                trigger_policy.get(
                    "one_of_direction_targets_must_have_single_polarity"
                )
                is True
                and _text(item.get("operator")) == "one_of_at_trigger"
                and polarity_kind in {
                    "absolute_direction",
                    "relative_direction",
                }
                and len(directions) != 1
            ):
                defects.append(Defect(
                        "claim.trigger_direction_incoherent",
                        "one_of_at_trigger directional targets must resolve to one typed polarity",
                        clause_path,
                ))
                continue
            if not expected_counter_direction:
                continue
            if (
                trigger_mode == "any"
                and trigger_policy.get(
                    "any_clause_requires_independent_counter_polarity"
                )
                is True
                and directions != {expected_counter_direction}
            ):
                defects.append(Defect(
                        "claim.trigger_any_clause_not_counter",
                        "every any-mode clause must independently express the same typed counter direction",
                        clause_path,
                ))
                continue
            if (
                trigger_mode == "all"
                and trigger_policy.get(
                    "all_directional_clauses_must_match_counter_polarity"
                )
                is True
                and polarity_kind in {
                    "absolute_direction",
                    "relative_direction",
                }
                and (
                    (
                        polarity_kind == "absolute_direction"
                        and directions != {expected_counter_direction}
                    )
                    or (
                        polarity_kind == "relative_direction"
                        and not directions.issubset(
                            {expected_counter_direction, "neutral"}
                        )
                    )
                )
            ):
                defects.append(Defect(
                        "claim.trigger_direction_incoherent",
                        "all-mode directional clauses must preserve one typed counter direction; neutral auxiliaries may not introduce support or mixed direction",
                        clause_path,
                ))

    # Account-specific conclusions may consume shared evidence-layer claims or
    # claims from their own account only.  Shared claims may consume only
    # observations and other shared claims.  This prevents a shared node from
    # laundering a main conclusion into Maker (or vice versa).
    for claim_id, claim in claims.items():
        account = _text(claim.get("account"))
        refs = [
            *claim.get("support_ids", []),
            *claim.get("counter_ids", []),
        ]
        if _text(claim.get("invalidation_id")):
            refs.append(claim.get("invalidation_id"))
        for ref in refs:
            referenced = claims.get(_text(ref))
            if not referenced:
                continue
            referenced_account = _text(referenced.get("account"))
            if account == "shared" and referenced_account != "shared":
                defects.append(Defect(
                        "claim.shared_account_leak",
                        f"shared claim cannot depend on {referenced_account} claim: {ref}",
                        f"claims.{claim_id}",
                ))
            elif account in {"main", "maker"} and referenced_account not in {"shared", account}:
                defects.append(Defect(
                        "claim.cross_account_dependency",
                        f"{account} claim cannot depend on {referenced_account} claim: {ref}",
                        f"claims.{claim_id}",
                ))


def _validate_reasoning_certification(claims, defects, evidence, evidence_root, minimum_sources, observations, payload, scoring_policy, semantic_root, submission_contract, visual_review_not_after):
    evidence_files_root = evidence_root or semantic_root
    try:
        full_policy = load_scoring_policy(root=semantic_root)
        semantic_issues = validate_reasoning_semantics(
            observations,
            claims,
            evidence=evidence,
            root=evidence_files_root,
            full_policy=full_policy,
            methodology=payload.get("methodology"),
            submission_contract=submission_contract,
            visual_review_not_after=visual_review_not_after,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        defects.append(Defect(
                "semantic.validator_failed",
                f"semantic validator could not load its canonical policy: {exc}",
                "methodology",
        ))
    else:
        defects.extend(Defect(item.code, item.message, item.path) for item in semantic_issues)

    observation_ids = set(observations)
    tradingview_observation = next(
        (item for item in observations.values() if item.get("source") == "TradingView"),
        {},
    )
    manual_profile = (
        (tradingview_observation.get("metrics") or {}).get("volume_profile")
        if isinstance(tradingview_observation.get("metrics"), dict)
        else {}
    )
    manual_profile_status = (
        _text(manual_profile.get("status")) if isinstance(manual_profile, dict) else ""
    )
    for claim_id, claim in claims.items():
        source_ids = _reachable_observations(claim_id, claims, observation_ids)
        sources = {observations[item]["source"] for item in source_ids if item in observations}
        claim_type = _text(claim.get("claim_type"))
        minimum = minimum_sources.get(claim_type)
        if minimum is not None and len(sources) < minimum:
            defects.append(Defect("claim.source_count", f"{claim_type} requires at least {minimum} independent source(s)", f"claims.{claim_id}"))
        reachable_claims = _reachable_claim_ids(claim_id, claims)
        reachable_types = {
            _text(claims[item].get("claim_type"))
            for item in reachable_claims
        }
        if claim_type == "maker_thesis":
            for required in ("Coinglass", "Exocharts"):
                if required not in sources:
                    defects.append(Defect("maker.orderflow_source_missing", f"Maker thesis requires {required}", f"claims.{claim_id}"))
            orderflow_rows = [
                observations[item]
                for item in source_ids
                if observations[item].get("source") in {"Coinglass", "Exocharts"}
            ]
            coinglass_rows = [item for item in orderflow_rows if item.get("source") == "Coinglass"]
            exocharts_rows = [item for item in orderflow_rows if item.get("source") == "Exocharts"]
            pivots = {_text(item.get("pivot_id")) for item in coinglass_rows}
            frames = {_text(item.get("timeframe")) for item in coinglass_rows}
            subjects = {_text(item.get("subject")) for item in coinglass_rows}
            if "" in pivots or len(pivots) != 1:
                defects.append(Defect("maker.pivot_mismatch", "Coinglass must expose one explicit same-pivot anchor", f"claims.{claim_id}"))
            if frames != {"1H"}:
                defects.append(Defect("maker.timeframe_mismatch", "Coinglass orderflow pivot must use 1H", f"claims.{claim_id}"))
            if subjects != {"BTC"}:
                defects.append(Defect("maker.subject_mismatch", "Coinglass orderflow observation must use BTC", f"claims.{claim_id}"))
            exocharts_frames = {_text(item.get("timeframe")) for item in exocharts_rows}
            exocharts_subjects = {_text(item.get("subject")) for item in exocharts_rows}
            if exocharts_frames != {"D"}:
                defects.append(Defect("maker.exocharts_timeframe_mismatch", "Exocharts footprint confirmation must use the Daily baseline", f"claims.{claim_id}"))
            if exocharts_subjects != {"BTC"}:
                defects.append(Defect("maker.exocharts_subject_mismatch", "Exocharts footprint confirmation must use BTC", f"claims.{claim_id}"))
            tags = {_text(item) for item in claim.get("method_tags", [])}
            for dimension in (
                "orderflow.pivot",
                "orderflow.price_cvd",
                "orderflow.oi",
                "orderflow.funding",
                "orderflow.footprint_confirmation",
            ):
                if dimension not in tags:
                    defects.append(Defect("maker.dimension_missing", f"Maker thesis missing method dimension: {dimension}", f"claims.{claim_id}.method_tags"))
            if "liquidity_hunt" not in reachable_types:
                defects.append(Defect("maker.liquidity_binding", "Maker thesis must use the certified liquidity-hunt claim", f"claims.{claim_id}.support_ids"))
        elif claim_type == "main_account_thesis":
            for required in ("BlockBeats", "FedWatch"):
                if required not in sources:
                    defects.append(Defect(
                            "main.fundamental_source_missing",
                            f"main-account thesis requires {required}",
                            f"claims.{claim_id}",
                    ))
            if "TradingView" not in sources:
                defects.append(Defect("main.chart_source_missing", "main-account thesis requires TradingView structure", f"claims.{claim_id}"))
            if "etf_confirmation" not in reachable_types:
                defects.append(Defect("main.etf_binding", "main-account thesis must use the certified ETF confirmation claim", f"claims.{claim_id}.support_ids"))
        elif claim_type == "etf_confirmation":
            tags = {_text(item) for item in claim.get("method_tags", [])}
            if sources != {"Coinglass", "Farside"}:
                defects.append(Defect("etf.source_boundary", "ETF confirmation must trace exactly to Coinglass price direction and Farside flow", f"claims.{claim_id}"))
            if "etf.confirmation_only" not in tags:
                defects.append(Defect("etf.role_drift", "ETF flow must be tagged confirmation-only", f"claims.{claim_id}.method_tags"))
        elif claim_type == "liquidation_confirmation":
            tags = {_text(item) for item in claim.get("method_tags", [])}
            liquidation_support_ids = [
                _text(ref) for ref in claim.get("support_ids", [])
            ]
            direct_observation_sources = {
                _text(observations.get(_text(ref), {}).get("source"))
                for ref in claim.get("support_ids", [])
                if _text(ref) in observations
            }
            direct_claim_types = {
                _text(claims.get(_text(ref), {}).get("claim_type"))
                for ref in claim.get("support_ids", [])
                if _text(ref) in claims
            }
            if (
                len(liquidation_support_ids) != 2
                or len(set(liquidation_support_ids)) != 2
                or sources != {"Coinglass", "TradingView"}
                or direct_observation_sources != {"Coinglass"}
                or direct_claim_types != {"chart_interpretation"}
            ):
                defects.append(Defect(
                        "liquidation.source_boundary",
                        "liquidation confirmation must directly bind one Coinglass observation and the certified TradingView chart claim",
                        f"claims.{claim_id}.support_ids",
                ))
            confirmation_result = _text(claim.get("confirmation_result"))
            allowed_confirmation_results = set(
                (scoring_policy.get("gold_methodology") or {}).get(
                    "liquidation_confirmation_results"
                )
                or []
            )
            if confirmation_result not in allowed_confirmation_results:
                defects.append(Defect(
                        "liquidation.confirmation_invalid",
                        "liquidation confirmation result is outside the closed authority vocabulary",
                        f"claims.{claim_id}.confirmation_result",
                ))
            if (
                manual_profile_status == "insufficient"
                and confirmation_result != "neutral"
            ):
                defects.append(Defect(
                        "liquidation.manual_profile_substitution",
                        "an insufficient manual profile requires a neutral liquidation confirmation",
                        f"claims.{claim_id}.confirmation_result",
                ))
            if "liquidation.auxiliary_only" not in tags:
                defects.append(Defect("liquidation.role_drift", "liquidation map must remain auxiliary-only", f"claims.{claim_id}.method_tags"))
        elif claim_type == "liquidity_hunt":
            tags = {_text(item) for item in claim.get("method_tags", [])}
            expected_profile_tag = f"manual_vrvp.{manual_profile_status}"
            if (
                "TradingView" not in sources
                or "VRVP.user_drawn_manual_only" not in tags
                or expected_profile_tag not in tags
                or "liquidity.probability_not_direction" not in tags
            ):
                defects.append(Defect("liquidity.vrvp_boundary", "liquidity-hunt claim requires TradingView, the user-drawn manual-profile status and probability-only tags", f"claims.{claim_id}"))
            if "liquidation_confirmation" not in reachable_types:
                defects.append(Defect("liquidity.liquidation_binding", "liquidity-hunt claim must use the certified liquidation-map confirmation", f"claims.{claim_id}.support_ids"))
            if manual_profile_status == "insufficient":
                conclusion = _text(claim.get("conclusion"))
                if "证据不足" not in conclusion or not re.search(r"不推断|不替代|不生成", conclusion):
                    defects.append(Defect("liquidity.insufficient_disclosure", "insufficient manual profile claim must disclose that no profile location/probability is inferred", f"claims.{claim_id}.conclusion"))
    return observation_ids


def _validate_reasoning_scenarios(claims, defects, payload, scenario_fields, submission_contract):
    scenarios = payload.get("scenario_tree")
    if not isinstance(scenarios, list):
        defects.append(Defect(
                "scenario_tree.invalid",
                "scenario_tree must be an array",
                "scenario_tree",
        ))
        scenarios = []
    ownership_contract = submission_contract.get("scenario_ownership") or {}
    ownership_items = ownership_contract.get("items") or []
    expected_scenarios = {
        (_text(item.get("account")), _text(item.get("scenario_type"))): item
        for item in ownership_items
        if isinstance(item, dict)
    }
    transition_code_by_type = (
        ownership_contract.get("transition_code_by_type") or {}
    )
    scenario_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    scenario_ids: set[str] = set()
    for index, item in enumerate(scenarios):
        path = f"scenario_tree[{index}]"
        if not isinstance(item, dict):
            defects.append(
                Defect("scenario.invalid", "scenario must be an object", path)
            )
            continue
        if set(item) != scenario_fields:
            defects.append(Defect(
                    "scenario.schema_fields",
                    "scenario must use the exact closed typed ownership field set",
                    path,
            ))
        raw_scenario_id = item.get("id")
        raw_scenario_type = item.get("scenario_type")
        raw_account = item.get("account")
        raw_owner_claim_id = item.get("owner_claim_id")
        scenario_id = _text(raw_scenario_id)
        scenario_type = _text(raw_scenario_type)
        account = _text(raw_account)
        owner_claim_id = _text(raw_owner_claim_id)
        if not all(
            _canonical_closed_string(value)
            for value in (
                raw_scenario_id,
                raw_scenario_type,
                raw_account,
                raw_owner_claim_id,
            )
        ):
            defects.append(Defect(
                    "scenario.identifier_noncanonical",
                    "scenario id, account, scenario_type and owner_claim_id must be exact closed-schema strings",
                    path,
            ))
        if not scenario_id or scenario_id in scenario_ids:
            defects.append(Defect(
                    "scenario.id_invalid",
                    "scenario id is missing or duplicated",
                    f"{path}.id",
            ))
        else:
            scenario_ids.add(scenario_id)
        key = (account, scenario_type)
        expected = expected_scenarios.get(key)
        if expected is None:
            defects.append(Defect(
                    "scenario.account_type_invalid",
                    "scenario account/type is outside the exact ownership matrix",
                    path,
            ))
            continue
        if key in scenario_by_key:
            defects.append(Defect(
                    "scenario.account_type_duplicate",
                    f"duplicate {account}/{scenario_type} scenario",
                    path,
            ))
        else:
            scenario_by_key[key] = item
        if scenario_id != expected.get("id"):
            defects.append(Defect(
                    "scenario.id_binding",
                    "scenario id must match its exact account/type ownership row",
                    f"{path}.id",
            ))
        owner_claim = claims.get(owner_claim_id)
        if not isinstance(owner_claim, dict):
            defects.append(Defect(
                    "scenario.owner_claim_unknown",
                    f"scenario owner claim is unknown: {owner_claim_id}",
                    f"{path}.owner_claim_id",
            ))
            continue
        if (
            _text(owner_claim.get("account")) != account
            or _text(owner_claim.get("claim_type"))
            != _text(expected.get("owner_claim_type"))
        ):
            defects.append(Defect(
                    "scenario.owner_claim_binding",
                    "scenario owner must be the exact same-account typed claim required by the ownership matrix",
                    f"{path}.owner_claim_id",
            ))
    if set(scenario_by_key) != set(expected_scenarios):
        defects.append(Defect(
                "scenario.matrix_incomplete",
                "scenario tree must exactly cover Main/Maker base/counter/invalidation",
                "scenario_tree",
        ))

    methodology_scenarios = (
        (payload.get("methodology") or {}).get("scenario_tree")
        if isinstance(payload.get("methodology"), dict)
        else None
    )
    methodology_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(methodology_scenarios, list):
        defects.append(Defect(
                "methodology.scenario_tree_missing",
                "methodology requires an account-scoped scenario tree",
                "methodology.scenario_tree",
        ))
        methodology_scenarios = []
    for index, scenario in enumerate(methodology_scenarios):
        path = f"methodology.scenario_tree[{index}]"
        if not isinstance(scenario, dict):
            defects.append(Defect(
                    "methodology.scenario_invalid",
                    "methodology scenario must be an object",
                    path,
            ))
            continue
        expected_fields = {
            "account",
            "kind",
            "claim_id",
            "trigger_claim_ids",
            "action",
        }
        if set(scenario) != expected_fields:
            defects.append(Defect(
                    "methodology.scenario_schema_fields",
                    "methodology scenario must use the exact compatibility field set",
                    path,
            ))
        raw_account = scenario.get("account")
        raw_kind = scenario.get("kind")
        raw_claim_id = scenario.get("claim_id")
        raw_action = scenario.get("action")
        account = _text(raw_account)
        kind = _text(raw_kind)
        claim_id = _text(raw_claim_id)
        action = _text(raw_action)
        if not all(
            _canonical_closed_string(value)
            for value in (raw_account, raw_kind, raw_claim_id, raw_action)
        ):
            defects.append(Defect(
                    "methodology.scenario_identifier_noncanonical",
                    "methodology scenario identifiers and transition code must be canonical",
                    path,
            ))
        key = (account, kind)
        if key not in expected_scenarios:
            defects.append(Defect(
                    "methodology.scenario_account_type",
                    "methodology scenario requires an exact Main/Maker ownership row",
                    path,
            ))
            continue
        if key in methodology_by_key:
            defects.append(Defect(
                    "methodology.scenario_duplicate",
                    f"duplicate methodology scenario: {account}/{kind}",
                    path,
            ))
        else:
            methodology_by_key[key] = scenario
        top_level_owner = _text(
            scenario_by_key.get(key, {}).get("owner_claim_id")
        )
        if not top_level_owner or claim_id != top_level_owner:
            defects.append(Defect(
                    "methodology.scenario_owner_drift",
                    "methodology scenario claim_id must equal the top-level typed owner",
                    f"{path}.claim_id",
            ))
        if action != _text(transition_code_by_type.get(kind)):
            defects.append(Defect(
                    "methodology.scenario_transition_code",
                    "methodology scenario action must equal the authority transition code",
                    f"{path}.action",
            ))
        trigger_ids = (
            scenario.get("trigger_claim_ids")
            if isinstance(scenario.get("trigger_claim_ids"), list)
            else []
        )
        expected_trigger_ids = derive_methodology_trigger_claim_ids(
            claim_id,
            claims,
        )
        if trigger_ids != expected_trigger_ids:
            defects.append(Defect(
                    "methodology.scenario_trigger_projection",
                    (
                        "methodology trigger_claim_ids must exactly equal the "
                        "typed owner's direct claim supports in owner order"
                    ),
                    f"{path}.trigger_claim_ids",
            ))
        owner_ancestors = _reachable_claim_ids(claim_id, claims)
        for trigger_id in trigger_ids:
            raw_trigger_id = trigger_id
            trigger_id = _text(raw_trigger_id)
            if not _canonical_closed_string(raw_trigger_id):
                defects.append(Defect(
                        "methodology.scenario_trigger_noncanonical",
                        "methodology trigger_claim_ids must contain canonical claim ids",
                        f"{path}.trigger_claim_ids",
                ))
            trigger_account = _text(claims.get(trigger_id, {}).get("account"))
            if trigger_account not in {"shared", account}:
                defects.append(Defect(
                        "methodology.scenario_trigger_account",
                        "methodology scenario trigger must be shared or same-account",
                        f"{path}.trigger_claim_ids",
                ))
            if trigger_id not in owner_ancestors:
                defects.append(Defect(
                        "methodology.scenario_trigger_ancestry",
                        "methodology trigger must be reachable from its typed owner support DAG",
                        f"{path}.trigger_claim_ids",
                ))
    if set(methodology_by_key) != set(expected_scenarios):
        defects.append(Defect(
                "methodology.scenario_account_coverage",
                "methodology scenarios must exactly cover the ownership matrix",
                "methodology.scenario_tree",
        ))
    return scenarios


def _validate_reasoning_cannot_do_closure(claims, defects, observation_ids, observations, payload, scenarios):
    cannot_ids = [
        claim_id
        for claim_id, claim in claims.items()
        if _text(claim.get("claim_type")) == "cannot_do"
    ]
    cannot_do_closure: dict[str, Any] = {}
    if len(cannot_ids) != 1:
        defects.append(Defect(
                "cannot_do.cardinality",
                "reasoning requires exactly one Maker cannot_do claim",
                "claims",
        ))
    else:
        cannot_id = cannot_ids[0]
        if list(claims)[-1:] != [cannot_id]:
            defects.append(Defect(
                    "cannot_do.not_last",
                    "cannot_do must be the final reasoning claim",
                    f"claims.{cannot_id}",
            ))
        for claim_id, claim in claims.items():
            if claim_id == cannot_id:
                continue
            control_refs = [
                *claim.get("support_ids", []),
                *claim.get("counter_ids", []),
            ]
            if _text(claim.get("invalidation_id")):
                control_refs.append(claim.get("invalidation_id"))
            if cannot_id in {_text(value) for value in control_refs}:
                defects.append(Defect(
                        "cannot_do.used_as_reasoning_input",
                        "cannot_do cannot support, counter, invalidate or flip another reasoning claim",
                        f"claims.{claim_id}",
                ))

        reachable_claims = _reachable_claim_ids(cannot_id, claims)
        reachable_types = {
            _text(claims[item].get("claim_type"))
            for item in reachable_claims
            if item in claims
        }
        required_closure_types = {
            "maker_thesis",
            "strongest_counterevidence",
            "invalidation_path",
            "market_regime",
        }
        for missing in sorted(required_closure_types - reachable_types):
            defects.append(Defect(
                    "cannot_do.closure_claim_missing",
                    f"cannot_do closure is missing Maker {missing}",
                    f"claims.{cannot_id}.support_ids",
            ))
        source_ids = _reachable_observations(cannot_id, claims, observation_ids)
        closure_sources = {
            _text(observations[item].get("source"))
            for item in source_ids
            if item in observations
        }
        for missing_source in sorted(set(REQUIRED_SOURCES) - closure_sources):
            defects.append(Defect(
                    "cannot_do.source_closure_missing",
                    f"cannot_do closure is missing source ancestry: {missing_source}",
                    f"claims.{cannot_id}.support_ids",
            ))

        required_scenario_claim_types = {
            "base": "maker_thesis",
            "counter": "strongest_counterevidence",
            "invalidation": "invalidation_path",
        }
        maker_scenario_bindings: dict[str, str] = {}
        for index, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict) or scenario.get("account") != "maker":
                continue
            scenario_type = _text(scenario.get("scenario_type"))
            owner_claim_id = _text(scenario.get("owner_claim_id"))
            maker_scenario_bindings[scenario_type] = owner_claim_id
            if cannot_id == owner_claim_id:
                defects.append(Defect(
                        "cannot_do.used_as_scenario_input",
                        "Maker scenarios must be complete before cannot_do and cannot cite it as an input",
                        f"scenario_tree[{index}].owner_claim_id",
                ))
            required_type = required_scenario_claim_types.get(scenario_type)
            if required_type and not (
                _text(claims.get(owner_claim_id, {}).get("claim_type"))
                == required_type
                and _text(claims.get(owner_claim_id, {}).get("account"))
                == "maker"
            ):
                defects.append(Defect(
                        "cannot_do.scenario_closure_missing",
                        f"Maker {scenario_type} scenario must bind its {required_type}",
                        f"scenario_tree[{index}].owner_claim_id",
                ))
        methodology_scenarios = (
            (payload.get("methodology") or {}).get("scenario_tree")
            if isinstance(payload.get("methodology"), dict)
            else []
        )
        if isinstance(methodology_scenarios, list):
            for index, scenario in enumerate(methodology_scenarios):
                if not isinstance(scenario, dict):
                    continue
                methodology_inputs = {
                    _text(scenario.get("claim_id")),
                    *(
                        _text(value)
                        for value in scenario.get("trigger_claim_ids", [])
                        if _text(value)
                    ),
                }
                if cannot_id in methodology_inputs:
                    defects.append(Defect(
                            "cannot_do.used_as_methodology_scenario_input",
                            "methodology scenarios must be complete before cannot_do and cannot cite the final closure",
                            f"methodology.scenario_tree[{index}]",
                    ))
        cannot_do_closure = {
            "claim_id": cannot_id,
            "ancestor_claim_ids": sorted(reachable_claims),
            "source_coverage": sorted(closure_sources),
            "maker_scenarios": {
                key: maker_scenario_bindings.get(key, "")
                for key in sorted(REQUIRED_SCENARIO_TYPES)
            },
        }
    return cannot_do_closure


def _validate_reasoning_report_sections(claims, defects, payload):
    legacy_report_sections = payload.get("schema_version") == "reasoning-model-v2"
    sections = payload.get("report_sections") if legacy_report_sections else {}
    if legacy_report_sections and not isinstance(sections, dict):
        defects.append(Defect("report_sections.invalid", "report_sections must be an object", "report_sections"))
        sections = {}
    required_sections = set(REQUIRED_REPORT_SECTIONS) if legacy_report_sections else set()
    if legacy_report_sections and payload.get("slot") == "evening":
        required_sections.add("defense_core")
    for name in sorted(required_sections):
        value = sections.get(name)
        path = f"report_sections.{name}"
        if not isinstance(value, dict):
            defects.append(Defect("report_section.missing", f"report section missing: {name}", path))
            continue
        text = _text(value.get("text"))
        if not text:
            defects.append(Defect("report_section.text_missing", f"report section text missing: {name}", f"{path}.text"))
        elif name in TRACEABLE_REPORT_SECTIONS and len(text) < 8:
            defects.append(Defect("report_section.text_thin", f"report section is too short: {name}", f"{path}.text"))
        elif not _contains_cjk(text):
            defects.append(Defect("report_section.language", f"report section must be Chinese-readable: {name}", f"{path}.text"))
        if TOOL_WRAPPER_RE.search(text):
            defects.append(Defect("report_section.tool_leak", f"tool wrapper text in section: {name}", f"{path}.text"))
        if name in NON_ACTION_REPORT_SECTIONS and _source_role_action_leak(
            "BlockBeats", text
        ):
            defects.append(Defect(
                    "report_section.source_role_action_leak",
                    f"{name} cannot directly decide a main-account or Maker action",
                    f"{path}.text",
            ))
        section_account = {"strategy": "main", "maker_strategy": "maker"}.get(name)
        if section_account:
            causal_marker = _account_causal_leak(text, section_account)
            if causal_marker:
                opposite_label = "Maker" if section_account == "main" else "主账户"
                defects.append(Defect(
                        "report_section.cross_account_causal_text",
                        f"{name} cannot use {opposite_label} as a causal decision input: {causal_marker}",
                        f"{path}.text",
                ))
        elif name == "independent_boundary":
            boundary_issue = _independent_boundary_issue(text)
            if boundary_issue:
                defects.append(Defect(
                        "report_section.independent_boundary_invalid",
                        "independent_boundary must be an explicit post-hoc comparison without cross-account causation",
                        f"{path}.text",
                ))
        claim_ids = value.get("claim_ids") if isinstance(value.get("claim_ids"), list) else []
        if name in TRACEABLE_REPORT_SECTIONS and not claim_ids:
            defects.append(Defect("report_section.trace_missing", f"report section lacks claim_ids: {name}", f"{path}.claim_ids"))
        for claim_id in claim_ids:
            if _text(claim_id) not in claims:
                defects.append(Defect("report_section.claim_missing", f"report section references unknown claim: {claim_id}", f"{path}.claim_ids"))
        bound_types = {
            _text(claims[_text(claim_id)].get("claim_type"))
            for claim_id in claim_ids
            if _text(claim_id) in claims
        }
        required_types = SECTION_REQUIRED_CLAIM_TYPES.get(name, set())
        for claim_type in sorted(required_types - bound_types):
            defects.append(Defect("report_section.claim_type_missing", f"report section {name} requires claim type: {claim_type}", f"{path}.claim_ids"))
        if name == "cannot_do" and not any(
            claims.get(_text(claim_id), {}).get("claim_type") == "cannot_do"
            for claim_id in claim_ids
        ):
            defects.append(Defect("report_section.cannot_do_binding", "cannot_do section must bind the certified cannot_do claim", f"{path}.claim_ids"))

    first_defense = _text((sections.get("defense_first") or {}).get("text"))
    required_first_markers = ("成交后", "后续", "确认", "极点")
    if legacy_report_sections and (not re.search(r"(?i)4\s*h", first_defense) or any(
        marker not in first_defense for marker in required_first_markers
    )):
        defects.append(Defect(
                "defense.first_semantics",
                "first defense operation must use a post-fill, subsequently formed and confirmed 4H structural extreme",
                "report_sections.defense_first.text",
        ))
    if legacy_report_sections and re.search(r"(?i)(?:1\s*h|15\s*m|1\s*d|1小时|15分钟|日线)", first_defense):
        defects.append(Defect(
                "defense.first_timeframe_drift",
                "first defense operation cannot substitute another timeframe for 4H",
                "report_sections.defense_first.text",
        ))

    # Reuse the existing actual-position boundary before reasoning is sealed.
    # The final report lint remains defense in depth, but must not be the first
    # place this deterministic semantic defect can appear.
    coupling_lines = [
        *(
            f"{_text(claim.get('conclusion'))} {_text(claim.get('invalidation'))}"
            for claim in claims.values()
        ),
        *(
            _text(section.get("text"))
            for section in sections.values()
            if isinstance(section, dict)
        ),
    ]
    for line_no, description, matched, _ in coupling_check(coupling_lines):
        defects.append(Defect(
                "reasoning.actual_position_coupling",
                f"{description}: {matched}",
                f"reasoning_text[{line_no}]",
        ))
    first_without_4h = re.sub(r"(?i)4\s*h", "", first_defense)
    if legacy_report_sections and re.search(r"\d", first_without_4h):
        defects.append(Defect(
                "defense.first_numeric_leak",
                "reasoning may describe the first defense operation but decision-model-v7 owns its trigger price",
                "report_sections.defense_first.text",
        ))

    second_defense = _text((sections.get("defense_second") or {}).get("text"))
    if legacy_report_sections and ("仅" not in second_defense or "保本损" not in second_defense):
        defects.append(Defect(
                "defense.second_semantics",
                "second defense operation must only move the remaining stop to breakeven",
                "report_sections.defense_second.text",
        ))
    if legacy_report_sections and re.search(r"减仓|平仓|清仓|止盈|TP", second_defense, re.IGNORECASE):
        defects.append(Defect(
                "defense.second_position_mutation",
                "second defense operation cannot contain position reduction or take-profit actions",
                "report_sections.defense_second.text",
        ))
    if legacy_report_sections and re.search(r"\d", second_defense):
        defects.append(Defect(
                "defense.second_numeric_leak",
                "reasoning may describe the second defense operation but decision-model-v7 owns its trigger price",
                "report_sections.defense_second.text",
        ))

    maker_tp_text = _text((sections.get("maker_tp") or {}).get("text"))
    if legacy_report_sections and (not re.search(r"(?i)TP\s*1", maker_tp_text) or not re.search(r"(?i)TP\s*2", maker_tp_text)):
        defects.append(Defect(
                "risk.tp_ledger_missing",
                "Maker take-profit reasoning must cover both TP1 and TP2; decision-model-v7 owns the exact values and 50/50 ledger",
                "report_sections.maker_tp.text",
        ))


def evaluate_reasoning(
    payload: dict[str, Any],
    *,
    evidence: dict[str, Any],
    reasoning_authority_sha256: str,
    evidence_root: Path | None = None,
    methodology_root: Path | None = None,
    visual_review_not_after: datetime | None = None,
) -> GateResult:
    defects: list[Defect] = []
    (
        semantic_root,
        submission_contract,
        claim_fields_by_type,
        scenario_fields,
        minimum_sources,
        trigger_policy,
        current_basis_policy,
        event_policy,
        scoring_policy,
        risk_execution_policy,
        structural_noise_buffer_policy,
        observations,
        claims_payload,
        claims,
    ) = _prepare_reasoning_validation(
        payload,
        evidence,
        reasoning_authority_sha256,
        evidence_root,
        methodology_root,
        defects,
    )
    _validate_reasoning_claim_graph(
        claim_fields_by_type,
        claims,
        claims_payload,
        defects,
        event_policy,
        observations,
        structural_noise_buffer_policy,
    )
    _validate_reasoning_claim_semantics(
        claims,
        current_basis_policy,
        defects,
        event_policy,
        observations,
        risk_execution_policy,
        structural_noise_buffer_policy,
        trigger_policy,
    )
    observation_ids = _validate_reasoning_certification(
        claims,
        defects,
        evidence,
        evidence_root,
        minimum_sources,
        observations,
        payload,
        scoring_policy,
        semantic_root,
        submission_contract,
        visual_review_not_after,
    )
    scenarios = _validate_reasoning_scenarios(
        claims,
        defects,
        payload,
        scenario_fields,
        submission_contract,
    )
    cannot_do_closure = _validate_reasoning_cannot_do_closure(
        claims,
        defects,
        observation_ids,
        observations,
        payload,
        scenarios,
    )
    _validate_reasoning_report_sections(claims, defects, payload)

    pipeline_issues, pipeline_certification = validate_reasoning_pipeline(payload)
    defects.extend(
        Defect(issue.code, issue.message, issue.path) for issue in pipeline_issues
    )
    expected_hash = reasoning_model_sha256(payload)
    if payload.get("reasoning_sha256") and payload.get("reasoning_sha256") != expected_hash:
        defects.append(Defect("reasoning.hash_mismatch", "reasoning hash differs from content", "reasoning_sha256"))
    return _result(
        "reasoning_consistency",
        defects,
        reasoning_sha256=expected_hash,
        observation_count=len(observations),
        claim_count=len(claims),
        scenario_count=len(scenarios),
        pipeline_certification=pipeline_certification,
        cannot_do_closure_sha256=(
            canonical_sha256(cannot_do_closure)
            if cannot_do_closure
            else ""
        ),
    )

__all__ = ["evaluate_reasoning", "reasoning_model_sha256"]
