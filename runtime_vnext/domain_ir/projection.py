"""Generated JSON/runtime projections of the code-owned domain registry."""

from __future__ import annotations

import copy
from typing import Any

from .registry import (
    ACCOUNT_CLAIM_BINDINGS,
    CLAIM_FIELD_ORDER_BY_TYPE,
    CLAIM_TOPOLOGY,
    CLAIM_TYPES,
    CONTRACT_SOURCES,
    CURRENT_BASIS_ALLOWED_OPERATORS,
    DIRECT_DIRECTION_OBSERVATION_FIELDS,
    DIRECTION_VALUE_MAP,
    EVIDENCE_EFFECT_ORDER,
    EVIDENCE_SUBJECT_DIRECTION_ORDER,
    MAKER_FAILURE_ORDER,
    MAKER_ORDER_LIFECYCLE_FIELD_ORDER,
    NON_DIRECTIONAL_SUBJECT_DIRECTION_ORDER,
    OBSERVATION_FIELD_ORDER_BY_CONTRACT_SOURCE,
    OBSERVATION_ID_BY_SOURCE,
    OBSERVATION_KIND_BY_CONTRACT_SOURCE,
    OBSERVATION_MECHANICAL_OWNERSHIP,
    ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION,
    ORDER_LIFECYCLE_APPLICABILITY,
    PIPELINE_UNIT_FIELD_ORDER,
    PIPELINE_UNIT_ORDER,
    REASONING_OBSERVATION_SOURCE_ORDER,
    RELATIVE_EXOCHARTS_DIRECTION,
    RELATIVE_TRIGGER_OPERATOR_PROJECTION,
    REGISTRY,
    SCAFFOLD_POLICY,
    SCENARIO_ACCOUNT_ORDER,
    SCENARIO_FIELD_ORDER,
    SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT,
    SCENARIO_TRANSITION_CODES,
    SCENARIO_TYPE_ORDER,
    TOP_LEVEL_CERTIFICATION_ONLY_FIELDS,
    TOP_LEVEL_CONTROLLER_REBOUND_FIELDS,
    TOP_LEVEL_FIELD_ORDER,
    TOP_LEVEL_PRODUCER_COLLECTION_FIELDS,
    TRIGGER_ACCOUNT_SOURCE_REQUIREMENTS,
    TRIGGER_CLAIM_FIELDS,
    TRIGGER_CONTROL_CLAIM_TYPE_ORDER,
    TRIGGER_EFFECT_BY_CLAIM_TYPE,
    TRIGGER_LOGIC_ALLOWED_OPERATORS,
    TRIGGER_LOGIC_MODES,
    TRIGGER_OBSERVATION_FIELDS,
    TRIGGER_SCALAR_CLAUSE_FIELD_ORDER,
    TYPED_NARRATIVE_OWNERSHIP,
    VISUAL_CITATION_POLICY,
)


def _json_view(value: Any) -> Any:
    """Return a mutable JSON-compatible projection without changing ownership."""

    if isinstance(value, dict):
        return {key: _json_view(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_view(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_view(item) for item in value)
    return copy.deepcopy(value)


def scenario_control_binding_projection() -> dict[str, Any]:
    return {
        "schema_version": "scenario-control-binding-v2",
        "ownership_contract_schema_version": (
            REGISTRY.scenario_ownership_schema_version
        ),
        "compiler_condition_source_by_type": {
            "base": "bound_owner_claim.typed_state",
            "counter": "bound_owner_claim.trigger_logic",
            "invalidation": "bound_owner_claim.trigger_logic",
        },
        "compiler_transition_source": (
            "scenario_ownership.transition_code_by_type"
        ),
        "methodology_trigger_claim_ids_source": (
            "bound_owner_claim.direct_support_claim_ids"
        ),
        "methodology_trigger_order": "owner_support_order_first_occurrence",
        "methodology_trigger_observation_ids_excluded": True,
        "methodology_trigger_owner_self_reference_allowed": False,
        "producer_free_prose_allowed": False,
        "execution_lifecycle_owner": "decision_and_continuity",
    }


def account_trigger_logic_projection() -> dict[str, Any]:
    return {
        "schema_version": "account-trigger-logic-v5",
        "claim_effects": dict(TRIGGER_EFFECT_BY_CLAIM_TYPE),
        "allowed_modes": list(TRIGGER_LOGIC_MODES),
        "invalidation_mode": TRIGGER_LOGIC_MODES[0],
        "minimum_clause_count": 2,
        "allowed_operators": list(TRIGGER_LOGIC_ALLOWED_OPERATORS),
        "observation_fields": _json_view(TRIGGER_OBSERVATION_FIELDS),
        "claim_fields": _json_view(TRIGGER_CLAIM_FIELDS),
        "account_source_requirements": _json_view(
            TRIGGER_ACCOUNT_SOURCE_REQUIREMENTS
        ),
        "opposite_state_required": True,
        "non_directional_subject_directions": list(
            NON_DIRECTIONAL_SUBJECT_DIRECTION_ORDER
        ),
        "non_directional_future_direction_fields": _json_view(
            DIRECT_DIRECTION_OBSERVATION_FIELDS
        ),
        "future_direction_value_map": dict(DIRECTION_VALUE_MAP),
        "relative_direction_observation_fields": {
            RELATIVE_TRIGGER_OPERATOR_PROJECTION["relative_source"]: {
                "cross_check_result": _json_view(
                    RELATIVE_EXOCHARTS_DIRECTION
                )
            }
        },
        "future_trigger_current_truth_quantifier_by_mode": {
            "all": "all",
            "any": "any",
        },
        "non_directional_future_requires_one_coherent_alternative_direction": True,
        "non_directional_counter_future_must_match_current_counter_direction": True,
        "any_clause_requires_independent_counter_polarity": True,
        "all_directional_clauses_must_match_counter_polarity": True,
        "one_of_direction_targets_must_have_single_polarity": True,
        "exocharts_confirm_counter_policy": (
            "confirm_is_valid_only_in_all_mode_with_one_canonical_"
            "coinglass_final_direction_reference"
        ),
        "scenario_control_binding": scenario_control_binding_projection(),
        "compiler_may_infer_missing_conditions": False,
    }


def account_current_basis_projection() -> dict[str, Any]:
    claim_fields = _json_view(TRIGGER_CLAIM_FIELDS)
    claim_fields["etf_confirmation"] = {
        "price_relation": ["confirm", "weaken", "neutral"]
    }
    return {
        "schema_version": "account-current-basis-v2",
        "required_claim_types": list(TRIGGER_CONTROL_CLAIM_TYPE_ORDER),
        "required_fields": ["mode", "clauses"],
        "allowed_modes": list(TRIGGER_LOGIC_MODES),
        "minimum_clause_count": 1,
        "clause_required_fields": list(TRIGGER_SCALAR_CLAUSE_FIELD_ORDER),
        "allowed_operators": list(CURRENT_BASIS_ALLOWED_OPERATORS),
        "observation_fields": _json_view(TRIGGER_OBSERVATION_FIELDS),
        "claim_fields": claim_fields,
        "evidence_polarity": {
            "schema_version": "evidence-polarity-v1",
            "allowed_subject_directions": list(EVIDENCE_SUBJECT_DIRECTION_ORDER),
            "non_directional_subject_directions": list(
                NON_DIRECTIONAL_SUBJECT_DIRECTION_ORDER
            ),
            "effects": list(EVIDENCE_EFFECT_ORDER),
            "strongest_counter_required_effect": "counter",
            "non_directional_counter_requires_one_coherent_alternative_direction": True,
            "direct_direction_observation_fields": _json_view(
                DIRECT_DIRECTION_OBSERVATION_FIELDS
            ),
            "direction_value_map": dict(DIRECTION_VALUE_MAP),
            "relative_exocharts_field": RELATIVE_TRIGGER_OPERATOR_PROJECTION[
                "relative_field"
            ],
            "relative_exocharts_reference_source": RELATIVE_EXOCHARTS_DIRECTION[
                "reference_source"
            ],
            "relative_exocharts_reference_field": RELATIVE_EXOCHARTS_DIRECTION[
                "reference_field"
            ],
            "relative_exocharts_map": _json_view(
                RELATIVE_EXOCHARTS_DIRECTION["relation_map"]
            ),
            "all_other_allowed_owner_fields": "neutral",
            "source_diversity_cannot_be_satisfied_by_support_or_neutral_padding": True,
        },
        "owner_must_be_reachable_from_support_dag": True,
        "owner_account_must_be_shared_or_same_account": True,
        "value_must_equal_current_owner_field": True,
        "separate_from_future_trigger_logic": True,
        "compiler_may_infer_missing_current_basis": False,
    }


def maker_entry_semantics_projection() -> dict[str, Any]:
    return {
        "schema_version": "maker-entry-semantics-v1",
        "resting_order_relation": {
            "short": "all_entries_strictly_above_current_price",
            "long": "all_entries_strictly_below_current_price",
        },
        "required_reach_direction": {
            "short": "up_to_entry",
            "long": "down_to_entry",
        },
        "structure_zone_roles": {
            "short": ["resistance", "breakdown_retest"],
            "long": ["support", "breakout_retest"],
        },
        "manual_profile_role_directional_use": False,
        "cancel_path_rule": (
            "prefill_cancel_must_be_on_the_opposite_branch_from_current_to_every_entry"
        ),
        "failure_order": list(MAKER_FAILURE_ORDER[1:]),
        "single_primary_reason_may_hide_other_failures": False,
    }


def maker_order_lifecycle_projection() -> dict[str, Any]:
    return {
        "schema_version": "maker-order-lifecycle-v1",
        "required_fields": list(MAKER_ORDER_LIFECYCLE_FIELD_ORDER),
        "states": list(ORDER_LIFECYCLE_APPLICABILITY),
        "gate_derives_exact_object": True,
        "actual_fill_probability_is_not_estimated": True,
        "compiler_may_infer_or_rewrite": False,
    }


def scoring_contract_registry_views() -> dict[tuple[str, ...], Any]:
    """Return the code-owned subtrees materialized in scoring_contract.json."""

    return {
        ("gold_methodology", "account_trigger_logic"): (
            account_trigger_logic_projection()
        ),
        ("gold_methodology", "account_current_basis"): (
            account_current_basis_projection()
        ),
        ("maker_score", "orderflow", "final_direction_to_claim_direction"): dict(
            ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION
        ),
        ("risk_execution", "maker_plan_constructibility_reason_codes"): [
            "constructible",
            *MAKER_FAILURE_ORDER,
        ],
        ("risk_execution", "maker_entry_semantics"): (
            maker_entry_semantics_projection()
        ),
        ("risk_execution", "maker_order_lifecycle"): (
            maker_order_lifecycle_projection()
        ),
    }


def scenario_ownership_projection() -> dict[str, Any]:
    items = []
    for account in SCENARIO_ACCOUNT_ORDER:
        for scenario_type in SCENARIO_TYPE_ORDER:
            owner_claim_type = SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT[account][
                scenario_type
            ]
            items.append(
                {
                    "id": f"scenario_{account}_{scenario_type}",
                    "account": account,
                    "scenario_type": scenario_type,
                    "owner_claim_type": owner_claim_type,
                }
            )
    return {
        "schema_version": REGISTRY.scenario_ownership_schema_version,
        "items": items,
        "transition_code_by_type": dict(SCENARIO_TRANSITION_CODES),
        "producer_free_prose_allowed": False,
        "execution_lifecycle_owner": "decision_and_continuity",
    }


def reference_trigger_operator(current_value: Any, target_value: Any) -> str:
    """Project the reference operator with strict JSON scalar type identity."""

    same_state = (
        type(target_value) is type(current_value) and target_value == current_value
    )
    return RELATIVE_TRIGGER_OPERATOR_PROJECTION[
        "reference_operator_when_target_equals_current"
        if same_state
        else "reference_operator_when_target_differs_current"
    ]


def server_projection(
    *, methodology_leaf_ownership: dict[str, Any]
) -> dict[str, Any]:
    """Project deterministic server ownership around policy-derived leaves."""

    leaf_ownership = copy.deepcopy(methodology_leaf_ownership)
    return {
        "schema_version": "reasoning-server-projection-v4",
        "server_owned_paths": [
            "schema_version",
            "trading_date",
            "slot",
            "evidence_snapshot_sha256",
            "reasoning_authority_sha256",
            "observations[*].id",
            "observations[*].kind",
            "observations[*].source",
            "observations[*].observed_at",
            "observations[*].evidence_refs",
            "observations[kind=structured_observation].structured_binding",
            "observations[kind=visual_judgment].visual_review.metrics_sha256",
            "observations[kind=visual_judgment].visual_review.evidence_sha256",
            *leaf_ownership["server_owned_subtrees"],
            *leaf_ownership["server_owned_bindings"],
            "scenario_tree",
            "claims[claim_type=orderflow_interpretation].direction",
            (
                "claims[claim_type=strongest_counterevidence|invalidation_path]."
                "trigger_logic.clauses[source=Coinglass,field=final_direction,"
                "paired_with=Exocharts].operator"
            ),
            (
                "claims[claim_type=strongest_counterevidence|invalidation_path]."
                "trigger_logic.clauses[source=Exocharts,"
                "field=cross_check_result].operator"
            ),
            "pipeline_units",
        ],
        "observation_source_order": list(REASONING_OBSERVATION_SOURCE_ORDER),
        "observation_id_by_source": copy.deepcopy(OBSERVATION_ID_BY_SOURCE),
        "observation_kind_by_contract_source": copy.deepcopy(
            OBSERVATION_KIND_BY_CONTRACT_SOURCE
        ),
        "observation_mechanical_ownership": copy.deepcopy(
            OBSERVATION_MECHANICAL_OWNERSHIP
        ),
        "account_claim_bindings": copy.deepcopy(ACCOUNT_CLAIM_BINDINGS),
        "methodology_leaf_ownership": leaf_ownership,
        "methodology_trigger_claim_ids_policy_path": (
            "gold_methodology.account_trigger_logic.scenario_control_binding."
            "methodology_trigger_claim_ids_source"
        ),
        "orderflow_direction_policy_path": (
            "maker_score.orderflow.final_direction_to_claim_direction"
        ),
        "relative_trigger_operator_projection": _json_view(
            RELATIVE_TRIGGER_OPERATOR_PROJECTION
        ),
        "producer_values_at_server_owned_paths_authoritative": False,
        "projection_must_run_inside_reasoning_attempt": True,
        "business_judgment_repair_forbidden": True,
    }


def deterministic_contract_sections(
    *, methodology_leaf_ownership: dict[str, Any]
) -> dict[str, Any]:
    """Return every deterministic section projected into the v6 JSON contract."""

    return {
        "schema_version": "reasoning-submission-contract-v6",
        "certified_schema_version": "reasoning-model-v5",
        "additional_fields_allowed": False,
        "top_level": {
            "field_order": list(TOP_LEVEL_FIELD_ORDER),
            "controller_rebound_fields": list(
                TOP_LEVEL_CONTROLLER_REBOUND_FIELDS
            ),
            "producer_collection_fields": list(
                TOP_LEVEL_PRODUCER_COLLECTION_FIELDS
            ),
            "certification_only_fields": list(
                TOP_LEVEL_CERTIFICATION_ONLY_FIELDS
            ),
        },
        "observation_sources": sorted(CONTRACT_SOURCES),
        "observation_fields_by_source": _json_view(
            OBSERVATION_FIELD_ORDER_BY_CONTRACT_SOURCE
        ),
        "claim_types": sorted(CLAIM_TYPES),
        "claim_fields_by_type": _json_view(CLAIM_FIELD_ORDER_BY_TYPE),
        "claim_topology": copy.deepcopy(CLAIM_TOPOLOGY),
        "typed_narrative_ownership": copy.deepcopy(TYPED_NARRATIVE_OWNERSHIP),
        "server_projection": server_projection(
            methodology_leaf_ownership=methodology_leaf_ownership
        ),
        "visual_citation_policy": copy.deepcopy(VISUAL_CITATION_POLICY),
        "scaffold_policy": copy.deepcopy(SCAFFOLD_POLICY),
        "scenario_ownership": scenario_ownership_projection(),
        "scenario_fields": list(SCENARIO_FIELD_ORDER),
        "scenario_accounts": list(SCENARIO_ACCOUNT_ORDER),
        "scenario_types": list(SCENARIO_TYPE_ORDER),
        "scenario_transition_codes": list(SCENARIO_TRANSITION_CODES.values()),
        "pipeline_unit_fields": list(PIPELINE_UNIT_FIELD_ORDER),
        "pipeline_unit_order": list(PIPELINE_UNIT_ORDER),
    }
