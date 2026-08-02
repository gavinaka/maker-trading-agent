"""Unique deterministic owner for the vNext typed domain contract.

Everything in this module is code-owned and may be projected into JSON,
runtime compatibility views, documentation and tests.  No model-authored
semantic value is synthesized here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from .canonical import canonical_json_bytes, canonical_sha256
from .types import (
    Account,
    ClaimType,
    ContinuityAction,
    ContinuityPriorStatus,
    ContractSource,
    Direction,
    EntryType,
    EvidenceEffect,
    EvidenceSource,
    MakerPlanState,
    MakerSemanticState,
    ObservationKind,
    OrderLifecycleState,
    ReachDirection,
    ScenarioType,
    TriggerOperator,
)


def _value(item: str | Enum) -> str:
    return str(item.value if isinstance(item, Enum) else item)


def _values(items: Iterable[str | Enum]) -> tuple[str, ...]:
    return tuple(_value(item) for item in items)


EVIDENCE_SOURCE_ORDER = _values(
    (
        EvidenceSource.BLOCKBEATS,
        EvidenceSource.COINGLASS,
        EvidenceSource.EXOCHARTS,
        EvidenceSource.FEDWATCH,
        EvidenceSource.FARSIDE,
        EvidenceSource.TRADINGVIEW,
    )
)

REASONING_OBSERVATION_SOURCE_ORDER = _values(
    (
        ContractSource.BLOCKBEATS,
        ContractSource.FEDWATCH,
        ContractSource.FARSIDE,
        ContractSource.COINGLASS,
        ContractSource.EXOCHARTS,
        ContractSource.TRADINGVIEW,
    )
)

CONTRACT_SOURCES = frozenset(_values(ContractSource))

SOURCE_ROLES = {
    EvidenceSource.BLOCKBEATS.value: "fundamental_context",
    EvidenceSource.FEDWATCH.value: "macro_context_not_direction",
    EvidenceSource.FARSIDE.value: "spot_liquidity_confirmation",
    EvidenceSource.COINGLASS.value: "orderflow_and_liquidation",
    EvidenceSource.EXOCHARTS.value: "footprint_orderflow_confirmation",
    EvidenceSource.TRADINGVIEW.value: "chart_structure_and_user_drawn_profile",
}

POLICY_SOURCE_KEYS = {
    EvidenceSource.BLOCKBEATS.value: "blockbeats",
    EvidenceSource.COINGLASS.value: "coinglass",
    EvidenceSource.EXOCHARTS.value: "exocharts",
    EvidenceSource.FEDWATCH.value: "fedwatch",
    EvidenceSource.FARSIDE.value: "farside_btc_etf",
    EvidenceSource.TRADINGVIEW.value: "tradingview",
}

OBSERVATION_MECHANICAL_OWNERSHIP = {
    "schema_version": "observation-mechanical-ownership-v1",
    "evidence_refs_semantics": (
        "sealed_same_source_artifact_inventory_not_visual_read_proof"
    ),
    "structured_artifact_filename_by_contract_source": {
        ContractSource.BLOCKBEATS.value: "blockbeats.json",
        ContractSource.FARSIDE.value: "farside_btc_etf.json",
        ContractSource.FEDWATCH_PLAN_C.value: "fedwatch.json",
    },
    "structured_binding_fields": [
        "artifact_path",
        "artifact_sha256",
        "metrics_sha256",
    ],
    "visual_review_hash_fields": ["metrics_sha256", "evidence_sha256"],
    "model_owned_visual_proof_paths": [
        "observations[*].visual_citations[*].evidence_ref",
        "observations[*].visual_citations[*].metric_paths",
        "observations[*].visual_citations[*].crop",
        (
            "claims[claim_type=invalidation_path].structural_noise_buffer."
            "visual_evidence_ref"
        ),
    ],
}

SCAFFOLD_POLICY = {
    "schema_version": "reasoning-submission-scaffold-v6",
    "business_semantics_checked": False,
    "attempt_created": False,
    "null_means_producer_must_supply": False,
    "model_owned_null_means_producer_must_supply": True,
    "server_owned_null_means_pending_projection": True,
    "authority_constants_may_be_prefilled": True,
    "business_direction_or_action_may_be_prefilled": False,
    "authority_transition_codes_may_be_prefilled": True,
    "server_projection_is_authoritative": True,
    "claim_topology_visible_before_attempt": True,
    "typed_narrative_ownership_visible_before_attempt": True,
}

VISUAL_CITATION_POLICY = {
    "schema_version": "visual-citation-leaf-policy-v1",
    "empty_collections_are_metric_leaves": True,
    "empty_collection_semantics": "observable_absence_requires_bounded_citation",
}

MINIMUM_OBSERVATION_METRICS = {
    EvidenceSource.BLOCKBEATS.value: frozenset(),
    EvidenceSource.COINGLASS.value: frozenset(),
    EvidenceSource.EXOCHARTS.value: frozenset({"cross_check_result"}),
    EvidenceSource.FEDWATCH.value: frozenset(),
    EvidenceSource.FARSIDE.value: frozenset(),
    EvidenceSource.TRADINGVIEW.value: frozenset(),
}

TRADINGVIEW_TIMEFRAMES = ("1D", "4H", "1H", "15m")

ACCOUNT_CURRENT_BASIS_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "required_claim_types",
        "required_fields",
        "allowed_modes",
        "minimum_clause_count",
        "clause_required_fields",
        "allowed_operators",
        "observation_fields",
        "claim_fields",
        "evidence_polarity",
        "owner_must_be_reachable_from_support_dag",
        "owner_account_must_be_shared_or_same_account",
        "value_must_equal_current_owner_field",
        "separate_from_future_trigger_logic",
        "compiler_may_infer_missing_current_basis",
    }
)

CLAIM_TYPES = frozenset(_values(ClaimType))
HIGH_IMPACT_CLAIMS = frozenset(
    {
        ClaimType.MAIN_ACCOUNT_THESIS.value,
        ClaimType.MAKER_THESIS.value,
    }
)

CLAIM_ACCOUNT_SCOPES = {
    ClaimType.FUNDAMENTAL_CONTEXT.value: frozenset({Account.SHARED.value}),
    ClaimType.FUNDAMENTAL_EVENT_REALIZATION.value: frozenset(
        {Account.SHARED.value}
    ),
    ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value: frozenset(
        {Account.SHARED.value}
    ),
    ClaimType.ORDERFLOW_INTERPRETATION.value: frozenset({Account.SHARED.value}),
    ClaimType.CHART_INTERPRETATION.value: frozenset({Account.SHARED.value}),
    ClaimType.ETF_CONFIRMATION.value: frozenset({Account.SHARED.value}),
    ClaimType.LIQUIDATION_CONFIRMATION.value: frozenset({Account.SHARED.value}),
    ClaimType.LIQUIDITY_HUNT.value: frozenset({Account.SHARED.value}),
    ClaimType.MARKET_REGIME.value: frozenset(
        {Account.MAIN.value, Account.MAKER.value}
    ),
    ClaimType.STRONGEST_COUNTEREVIDENCE.value: frozenset(
        {Account.MAIN.value, Account.MAKER.value}
    ),
    ClaimType.INVALIDATION_PATH.value: frozenset(
        {Account.MAIN.value, Account.MAKER.value}
    ),
    ClaimType.MAIN_ACCOUNT_THESIS.value: frozenset({Account.MAIN.value}),
    ClaimType.MAKER_THESIS.value: frozenset({Account.MAKER.value}),
    ClaimType.CANNOT_DO.value: frozenset({Account.MAKER.value}),
}

ACCOUNT_LOOP_CLAIM_TYPES = frozenset(
    {
        ClaimType.MARKET_REGIME.value,
        ClaimType.STRONGEST_COUNTEREVIDENCE.value,
        ClaimType.INVALIDATION_PATH.value,
    }
)
TRIGGER_CONTROL_CLAIM_TYPE_ORDER = (
    ClaimType.STRONGEST_COUNTEREVIDENCE.value,
    ClaimType.INVALIDATION_PATH.value,
)
TRIGGER_CONTROL_CLAIM_TYPES = frozenset(TRIGGER_CONTROL_CLAIM_TYPE_ORDER)
TRIGGER_EFFECT_BY_CLAIM_TYPE = {
    ClaimType.STRONGEST_COUNTEREVIDENCE.value: ScenarioType.COUNTER.value,
    ClaimType.INVALIDATION_PATH.value: "invalidate",
}
TRIGGER_SCALAR_CLAUSE_FIELD_ORDER = (
    "owner_type",
    "owner_id",
    "field",
    "operator",
    "value",
)
TRIGGER_SCALAR_CLAUSE_FIELDS = frozenset(TRIGGER_SCALAR_CLAUSE_FIELD_ORDER)

TRIGGER_LOGIC_MODES = ("all", "any")
TRIGGER_LOGIC_ALLOWED_OPERATORS = _values(
    (
        TriggerOperator.BECOMES,
        TriggerOperator.EQUALS_AT_TRIGGER,
        TriggerOperator.ONE_OF_AT_TRIGGER,
    )
)
CURRENT_BASIS_ALLOWED_OPERATORS = _values((TriggerOperator.EQUALS,))

TRIGGER_OBSERVATION_FIELDS = {
    ContractSource.TRADINGVIEW.value: {
        "timeframes.1d.structure": ("bullish", "bearish", "range"),
        "timeframes.4h.structure": ("bullish", "bearish", "range"),
        "timeframes.1h.structure": ("bullish", "bearish", "range"),
        "timeframes.15m.structure": ("bullish", "bearish", "range"),
    },
    ContractSource.FARSIDE.value: {
        "flow_direction": ("inflow", "outflow", "flat")
    },
    ContractSource.COINGLASS.value: {
        "final_direction": ("bullish", "bearish", "neutral", "mixed"),
        "pivot.anchor_reset": (True, False),
    },
    ContractSource.EXOCHARTS.value: {
        "cross_check_result": ("confirm", "weaken", "contradict")
    },
}

TRIGGER_CLAIM_FIELDS = {
    ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value: {
        "realization_state": (
            "realized",
            "partially_realized",
            "not_realized",
            "conflicted",
        )
    }
}

DIRECTION_VALUE_MAP = {
    "bullish": Direction.LONG.value,
    "bearish": Direction.SHORT.value,
    "range": Direction.NEUTRAL.value,
    "neutral": Direction.NEUTRAL.value,
    "mixed": Direction.NEUTRAL.value,
}

DIRECT_DIRECTION_OBSERVATION_FIELDS = {
    ContractSource.TRADINGVIEW.value: (
        "timeframes.1d.structure",
        "timeframes.4h.structure",
        "timeframes.1h.structure",
        "timeframes.15m.structure",
    ),
    ContractSource.COINGLASS.value: ("final_direction",),
}

RELATIVE_EXOCHARTS_DIRECTION = {
    "reference_source": ContractSource.COINGLASS.value,
    "reference_field": "final_direction",
    "reference_operator_policy": {
        "target_equals_current": TriggerOperator.EQUALS_AT_TRIGGER.value,
        "target_differs_from_current": TriggerOperator.BECOMES.value,
    },
    "relative_operator": TriggerOperator.EQUALS_AT_TRIGGER.value,
    "relation_map": {
        "confirm": "same_as_reference",
        "contradict": "opposite_of_reference",
        "weaken": Direction.NEUTRAL.value,
    },
}

RELATIVE_TRIGGER_OPERATOR_PROJECTION = {
    "schema_version": "relative-trigger-operator-projection-v1",
    "claim_types": TRIGGER_CONTROL_CLAIM_TYPE_ORDER,
    "required_mode": TRIGGER_LOGIC_MODES[0],
    "relative_source": ContractSource.EXOCHARTS.value,
    "relative_field": "cross_check_result",
    "relative_operator": TriggerOperator.EQUALS_AT_TRIGGER.value,
    "reference_source": ContractSource.COINGLASS.value,
    "reference_field": "final_direction",
    "reference_operator_when_target_equals_current": (
        TriggerOperator.EQUALS_AT_TRIGGER.value
    ),
    "reference_operator_when_target_differs_current": TriggerOperator.BECOMES.value,
    "projection_scope": "operators_only",
    "missing_or_ambiguous_behavior": "leave_unmodified_for_gate_rejection",
    "clause_presence_order_target_and_relation_mutation_forbidden": True,
}

TRIGGER_ACCOUNT_SOURCE_REQUIREMENTS = {
    Account.MAIN.value: {
        "always": (ContractSource.TRADINGVIEW.value,),
        "one_of_sources": (ContractSource.FARSIDE.value,),
        "one_of_claim_types": (
            ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value,
        ),
    },
    "maker_counter": {
        "always": (ContractSource.TRADINGVIEW.value,),
        "one_of_sources": (
            ContractSource.COINGLASS.value,
            ContractSource.EXOCHARTS.value,
        ),
    },
    "maker_invalidation": {
        "always": (
            ContractSource.TRADINGVIEW.value,
            ContractSource.COINGLASS.value,
        )
    },
}

SOURCE_ROLE_CLAIM_OWNER = {
    ClaimType.FUNDAMENTAL_CONTEXT.value: EvidenceSource.BLOCKBEATS.value,
    ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value: EvidenceSource.BLOCKBEATS.value,
    ClaimType.ETF_CONFIRMATION.value: EvidenceSource.FARSIDE.value,
    ClaimType.CHART_INTERPRETATION.value: EvidenceSource.TRADINGVIEW.value,
    ClaimType.LIQUIDATION_CONFIRMATION.value: EvidenceSource.COINGLASS.value,
    ClaimType.LIQUIDITY_HUNT.value: EvidenceSource.TRADINGVIEW.value,
}

SCENARIO_TYPES = frozenset(_values(ScenarioType))
SCENARIO_TYPE_ORDER = _values(
    (ScenarioType.BASE, ScenarioType.COUNTER, ScenarioType.INVALIDATION)
)
SCENARIO_ACCOUNT_ORDER = _values((Account.MAIN, Account.MAKER))
SCENARIO_FIELD_ORDER = ("id", "account", "scenario_type", "owner_claim_id")
SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT = {
    Account.MAIN.value: {
        ScenarioType.BASE.value: ClaimType.MAIN_ACCOUNT_THESIS.value,
        ScenarioType.COUNTER.value: ClaimType.STRONGEST_COUNTEREVIDENCE.value,
        ScenarioType.INVALIDATION.value: ClaimType.INVALIDATION_PATH.value,
    },
    Account.MAKER.value: {
        ScenarioType.BASE.value: ClaimType.MAKER_THESIS.value,
        ScenarioType.COUNTER.value: ClaimType.STRONGEST_COUNTEREVIDENCE.value,
        ScenarioType.INVALIDATION.value: ClaimType.INVALIDATION_PATH.value,
    },
}
SCENARIO_TRANSITION_CODES = {
    ScenarioType.BASE.value: "retain_certified_assessment",
    ScenarioType.COUNTER.value: "reassess_on_typed_counter",
    ScenarioType.INVALIDATION.value: "invalidate_and_recollect_evidence",
}
CANNOT_DO_CODES = frozenset({"做多", "追多", "做空", "追空", "追多空"})
CONTINUITY_ACTIONS = frozenset(_values(ContinuityAction))
CONTINUITY_PRIOR_STATUSES = frozenset(_values(ContinuityPriorStatus))

REPORT_SECTIONS = frozenset(
    {
        "opening_quote",
        "cannot_do",
        "fundamentals",
        "orderflow_label",
        "orderflow_text",
        "interpretation",
        "chart_label",
        "daily_line",
        "hourly_line",
        "trend_confirmation",
        "support_resistance",
        "strategy",
        "maker_strategy",
        "maker_tp",
        "maker_sl",
        "defense_first",
        "defense_second",
        "defense_note",
        "defense_cancel",
        "independent_boundary",
    }
)
NON_TRACEABLE_REPORT_SECTIONS = frozenset(
    {"opening_quote", "orderflow_label", "chart_label"}
)
NON_ACTION_REPORT_SECTIONS = frozenset(
    {
        "opening_quote",
        "fundamentals",
        "orderflow_label",
        "orderflow_text",
        "chart_label",
        "daily_line",
        "hourly_line",
        "support_resistance",
    }
)
SECTION_REQUIRED_CLAIM_TYPES = {
    "cannot_do": frozenset({ClaimType.CANNOT_DO.value}),
    "fundamentals": frozenset({ClaimType.MAIN_ACCOUNT_THESIS.value}),
    "orderflow_text": frozenset({ClaimType.MAKER_THESIS.value}),
    "interpretation": frozenset(
        {
            ClaimType.MAKER_THESIS.value,
            ClaimType.STRONGEST_COUNTEREVIDENCE.value,
        }
    ),
    "daily_line": frozenset({ClaimType.MAIN_ACCOUNT_THESIS.value}),
    "hourly_line": frozenset({ClaimType.LIQUIDITY_HUNT.value}),
    "trend_confirmation": frozenset(
        {ClaimType.MAIN_ACCOUNT_THESIS.value, ClaimType.MAKER_THESIS.value}
    ),
    "support_resistance": frozenset(
        {ClaimType.LIQUIDITY_HUNT.value, ClaimType.INVALIDATION_PATH.value}
    ),
    "strategy": frozenset({ClaimType.MAIN_ACCOUNT_THESIS.value}),
    "maker_strategy": frozenset({ClaimType.MAKER_THESIS.value}),
    "maker_tp": frozenset({ClaimType.MAKER_THESIS.value}),
    "maker_sl": frozenset({ClaimType.INVALIDATION_PATH.value}),
    "defense_first": frozenset({ClaimType.INVALIDATION_PATH.value}),
    "defense_second": frozenset({ClaimType.MAKER_THESIS.value}),
    "defense_note": frozenset({ClaimType.MAKER_THESIS.value}),
    "defense_cancel": frozenset({ClaimType.INVALIDATION_PATH.value}),
    "independent_boundary": frozenset(
        {ClaimType.MAIN_ACCOUNT_THESIS.value, ClaimType.MAKER_THESIS.value}
    ),
    "defense_core": frozenset(
        {ClaimType.MAKER_THESIS.value, ClaimType.INVALIDATION_PATH.value}
    ),
}

MAKER_FAILURE_ORDER = (
    "non_directional_thesis",
    "no_certified_entry_zone",
    "entry_zone_binding_invalid",
    "entry_zone_role_invalid",
    "maker_order_marketable",
    "entry_semantics_invalid",
    "cannot_do_conflict",
    "order_lifecycle_invalid",
    "structural_stop_invalid",
    "risk_math_invalid",
    "defense_trigger_invalid",
)
MAKER_SEMANTIC_STATES = frozenset(_values(MakerSemanticState))
MAKER_PLAN_STATES = frozenset(_values(MakerPlanState))
DIRECTIONAL_DIRECTIONS = frozenset(
    {Direction.LONG.value, Direction.SHORT.value}
)
MAKER_DIRECTIONS = frozenset(
    {*DIRECTIONAL_DIRECTIONS, Direction.OBSERVE.value}
)
EVIDENCE_SUBJECT_DIRECTIONS = frozenset(
    {*MAKER_DIRECTIONS, Direction.NEUTRAL.value}
)
EVIDENCE_DIRECTIONS = frozenset(
    {*DIRECTIONAL_DIRECTIONS, Direction.NEUTRAL.value}
)
EVIDENCE_SUBJECT_DIRECTION_ORDER = _values(
    (Direction.LONG, Direction.SHORT, Direction.NEUTRAL, Direction.OBSERVE)
)
NON_DIRECTIONAL_SUBJECT_DIRECTION_ORDER = _values(
    (Direction.NEUTRAL, Direction.OBSERVE)
)
ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION = {
    "bullish": Direction.LONG.value,
    "bearish": Direction.SHORT.value,
    "neutral": Direction.OBSERVE.value,
    "mixed": Direction.OBSERVE.value,
}
ENTRY_TYPES = frozenset({EntryType.LEFT.value, EntryType.RIGHT.value})
ORDER_LIFECYCLE_APPLICABILITY = {
    OrderLifecycleState.FILLABLE.value: "not_estimated_lifecycle_only",
    OrderLifecycleState.CANCEL_BLOCKS_ALL_ENTRIES.value: (
        "not_applicable_no_legal_fill_path"
    ),
    OrderLifecycleState.ENTRY_BEFORE_CANCEL.value: (
        "not_applicable_invalid_prefill_cancel"
    ),
    OrderLifecycleState.INVALID_GEOMETRY.value: "not_applicable_invalid_geometry",
    OrderLifecycleState.NOT_APPLICABLE_NO_CANDIDATE_GEOMETRY.value: (
        "not_applicable_no_candidate_geometry"
    ),
}
ORDER_LIFECYCLE_PATH_FLAGS = {
    OrderLifecycleState.FILLABLE.value: {
        "legal_fill_path_exists": True,
        "legal_cancel_path_exists": True,
    },
    OrderLifecycleState.CANCEL_BLOCKS_ALL_ENTRIES.value: {
        "legal_fill_path_exists": False,
        "legal_cancel_path_exists": True,
    },
    OrderLifecycleState.ENTRY_BEFORE_CANCEL.value: {
        "legal_fill_path_exists": True,
        "legal_cancel_path_exists": False,
    },
    OrderLifecycleState.INVALID_GEOMETRY.value: {
        "legal_fill_path_exists": False,
        "legal_cancel_path_exists": False,
    },
    OrderLifecycleState.NOT_APPLICABLE_NO_CANDIDATE_GEOMETRY.value: {
        "legal_fill_path_exists": False,
        "legal_cancel_path_exists": False,
    },
}
ORDER_LIFECYCLE_DISPLAY_BY_STATE = {
    OrderLifecycleState.FILLABLE.value: (
        "存在合法入场路径；撤单位于反方向分支。实际成交概率未估计"
    ),
    OrderLifecycleState.CANCEL_BLOCKS_ALL_ENTRIES.value: (
        "撤单价会先于所有入场档触发，订单没有可成交路径"
    ),
    OrderLifecycleState.ENTRY_BEFORE_CANCEL.value: (
        "至少一档会先成交后才触及撤单价，不属于成交前撤单"
    ),
    OrderLifecycleState.INVALID_GEOMETRY.value: (
        "价格几何冲突，无法形成合法订单生命周期"
    ),
    OrderLifecycleState.NOT_APPLICABLE_NO_CANDIDATE_GEOMETRY.value: (
        "无完整候选价格几何，订单生命周期不适用"
    ),
}
MAKER_ORDER_LIFECYCLE_FIELD_ORDER = (
    "schema_version",
    "state",
    "legal_fill_path_exists",
    "legal_cancel_path_exists",
    "fill_probability",
    "fill_probability_applicability",
    "reason_code",
)
REACH_DIRECTION_CODES = frozenset(_values(ReachDirection))
EVIDENCE_EFFECTS = frozenset(_values(EvidenceEffect))
EVIDENCE_EFFECT_ORDER = _values(
    (EvidenceEffect.SUPPORT, EvidenceEffect.COUNTER, EvidenceEffect.NEUTRAL)
)
CANNOT_DO_ABSOLUTE_DIRECTION_CONFLICTS = frozenset(
    {("做多", Direction.LONG.value), ("做空", Direction.SHORT.value)}
)
CANNOT_DO_PURSUIT_DIRECTION = {
    "追多": Direction.LONG.value,
    "追空": Direction.SHORT.value,
}
CANNOT_DO_BOTH_PURSUIT = "追多空"

TOP_LEVEL_FIELD_ORDER = (
    "schema_version",
    "trading_date",
    "slot",
    "evidence_snapshot_sha256",
    "reasoning_authority_sha256",
    "observations",
    "claims",
    "methodology",
    "scenario_tree",
    "pipeline_units",
)
TOP_LEVEL_CONTROLLER_REBOUND_FIELDS = (
    "schema_version",
    "trading_date",
    "slot",
    "evidence_snapshot_sha256",
    "reasoning_authority_sha256",
)
TOP_LEVEL_PRODUCER_COLLECTION_FIELDS = ("observations", "claims")
TOP_LEVEL_CERTIFICATION_ONLY_FIELDS = ("reasoning_sha256",)

DECISION_MODEL_FIELD_ORDER = (
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
)

REPORT_MODEL_FIELD_ORDER = (
    "schema_version",
    "presentation_contract_version",
    "presentation_contract_sha256",
    "run_id",
    "run_sha256",
    "run_mode",
    "execution_authorization",
    "trading_date",
    "slot",
    "methodology_sha256",
    "report_contract_sha256",
    "evidence_snapshot_sha256",
    "reasoning_sha256",
    "decision_sha256",
    "blockbeats_cards",
    "frontstage",
    "maker_summary",
    "main_summary",
    "audit",
    "model_sha256",
)
REPORT_BINDINGS_SCHEMA_VERSION = "report-section-bindings-v1"
REPORT_BINDING_SECTION_MODEL_PATHS = (
    ("blockbeats_cards", ("blockbeats_cards",)),
    ("frontstage", ("frontstage",)),
    ("maker_summary", ("maker_summary",)),
    ("main_summary", ("main_summary",)),
    ("audit", ("audit",)),
)
BLOCKBEATS_CARDS_SCHEMA_VERSION = "blockbeats-cards-vnext-v1"
SHADOW_CONTINUITY_SCHEMA_VERSION = "shadow-execution-continuity-vnext-v1"
SHADOW_CONTINUITY_FIELDS = frozenset(
    {
        "schema_version",
        "reasoning_sha256",
        "run_sha256",
        "live_state_read",
        "order_mutation_attempted",
        "execution_action",
        "plan_valid_until",
        "reason_code",
    }
)
EXECUTION_AUTHORIZATION_FIELDS = frozenset(
    {
        "source_kind",
        "source_sha256",
        "live_execution_allowed",
        "reason_code",
    }
)
SCENARIO_OWNERSHIP_SCHEMA_VERSION = "scenario-ownership-v1"
SCENARIO_PROJECTION_SCHEMA_VERSION = "scenario-projection-v1"
SCENARIO_CONDITION_OWNER_BY_TYPE = {
    ScenarioType.BASE.value: "bound_owner_claim.typed_state",
    ScenarioType.COUNTER.value: "bound_owner_claim.trigger_logic",
    ScenarioType.INVALIDATION.value: "bound_owner_claim.trigger_logic",
}
SCENARIO_TRANSITION_OWNER = "scenario_ownership.transition_code_by_type"
SCENARIO_FREE_PROSE_PROJECTABLE = False


def scenario_condition_owner_summary() -> str:
    """Derive the compact presentation owner from the per-type registry owner."""

    ordered_owners = tuple(
        dict.fromkeys(
            SCENARIO_CONDITION_OWNER_BY_TYPE[scenario_type]
            for scenario_type in SCENARIO_TYPE_ORDER
        )
    )
    namespaces_and_leaves = tuple(owner.rsplit(".", 1) for owner in ordered_owners)
    if not namespaces_and_leaves or any(
        len(parts) != 2 or not all(parts) for parts in namespaces_and_leaves
    ):
        raise ValueError("scenario condition owners must be non-empty dotted paths")
    namespaces = {parts[0] for parts in namespaces_and_leaves}
    if len(namespaces) != 1:
        raise ValueError("scenario condition owners must share one namespace")
    namespace = namespaces_and_leaves[0][0]
    leaves = "_or_".join(parts[1] for parts in namespaces_and_leaves)
    return f"{namespace}.{leaves}"
SCENARIO_CANONICAL_AUDIT_FIELD_ORDER = (
    "id",
    "account",
    "scenario_type",
    "owner_claim_id",
    "transition_code",
    "condition",
    "expected_path",
    "action",
)
SCENARIO_BASE_CONDITION_BY_ACCOUNT_DIRECTION = {
    Account.MAIN.value: {
        Direction.LONG.value: "主账户当前认证方向为偏多且绑定证据链有效",
        Direction.SHORT.value: "主账户当前认证方向为偏空且绑定证据链有效",
        Direction.NEUTRAL.value: "主账户当前认证方向为中性且绑定证据链有效",
    },
    Account.MAKER.value: {
        Direction.LONG.value: "Maker当前认证方向为偏多且绑定证据链有效",
        Direction.SHORT.value: "Maker当前认证方向为偏空且绑定证据链有效",
        Direction.OBSERVE.value: "Maker当前认证方向为观察且绑定证据链有效",
    },
}
SCENARIO_VISIBLE_PROJECTION_BY_ACCOUNT_AND_TRANSITION_CODE = {
    Account.MAIN.value: {
        SCENARIO_TRANSITION_CODES[ScenarioType.BASE.value]: {
            "expected_path": "主账户继续保留当前认证判断",
            "action": "主账户等待下一正式评分时点重新认证",
        },
        SCENARIO_TRANSITION_CODES[ScenarioType.COUNTER.value]: {
            "expected_path": "主账户当前认证判断进入重新评估",
            "action": "主账户按触发后的类型化证据重新完成评估",
        },
        SCENARIO_TRANSITION_CODES[ScenarioType.INVALIDATION.value]: {
            "expected_path": "主账户当前认证判断失效",
            "action": "主账户重新采集证据并重建推理",
        },
    },
    Account.MAKER.value: {
        SCENARIO_TRANSITION_CODES[ScenarioType.BASE.value]: {
            "expected_path": "Maker继续保留当前认证判断",
            "action": "Maker等待下一正式评分时点重新认证",
        },
        SCENARIO_TRANSITION_CODES[ScenarioType.COUNTER.value]: {
            "expected_path": "Maker当前认证判断进入重新评估",
            "action": "Maker按触发后的类型化证据重新完成评估",
        },
        SCENARIO_TRANSITION_CODES[ScenarioType.INVALIDATION.value]: {
            "expected_path": "Maker当前认证判断失效",
            "action": "Maker重新采集证据并重建推理",
        },
    },
}
SCENARIO_EXECUTION_LIFECYCLE_OWNER = "decision_and_continuity"
MAKER_SEMANTIC_STATE_SCHEMA_VERSION = "maker-semantic-state-v1"
TIMEFRAME_DISPLAY_SCHEMA_VERSION = "timeframe-display-v1"

PIPELINE_SCHEMA_VERSION = "reasoning-pipeline-certification-v2"
PIPELINE_UNIT_FIELD_ORDER = (
    "unit_id",
    "sequence",
    "unit_type",
    "account_scope",
    "source_scope",
    "depends_on_unit_ids",
    "input_node_ids",
    "output_node_ids",
)
PIPELINE_UNIT_FIELDS = frozenset(PIPELINE_UNIT_FIELD_ORDER)
PIPELINE_UNIT_ROWS = (
    ("source.blockbeats", 1, "source_analysis", Account.SHARED.value),
    ("source.fedwatch", 2, "source_analysis", Account.SHARED.value),
    ("source.farside", 3, "source_analysis", Account.SHARED.value),
    ("source.coinglass", 4, "source_analysis", Account.SHARED.value),
    ("source.exocharts", 5, "source_analysis", Account.SHARED.value),
    ("source.tradingview", 6, "source_analysis", Account.SHARED.value),
    ("join.fundamental_context", 7, "cross_source_join", Account.SHARED.value),
    ("join.orderflow_footprint", 8, "cross_source_join", Account.SHARED.value),
    ("join.chart_trend", 9, "cross_source_join", Account.SHARED.value),
    ("join.etf_relation", 10, "cross_source_join", Account.SHARED.value),
    ("join.intraday_location", 11, "cross_source_join", Account.SHARED.value),
    ("join.fundamental_realization", 12, "cross_source_join", Account.SHARED.value),
    ("main.controls", 13, "account_control", Account.MAIN.value),
    ("main.strategy", 14, "account_strategy", Account.MAIN.value),
    ("maker.controls", 15, "account_control", Account.MAKER.value),
    ("maker.thesis_score_basis", 16, "account_strategy", Account.MAKER.value),
    ("maker.cannot_do_closure", 17, "closure", Account.MAKER.value),
)
PIPELINE_UNIT_ORDER = tuple(row[0] for row in PIPELINE_UNIT_ROWS)
PIPELINE_SOURCE_UNIT_BY_NAME = {
    source: f"source.{source.lower()}" for source in REASONING_OBSERVATION_SOURCE_ORDER
}
PIPELINE_SHARED_CLAIM_OWNER = {
    ClaimType.FUNDAMENTAL_CONTEXT.value: "join.fundamental_context",
    ClaimType.ORDERFLOW_INTERPRETATION.value: "join.orderflow_footprint",
    ClaimType.CHART_INTERPRETATION.value: "join.chart_trend",
    ClaimType.ETF_CONFIRMATION.value: "join.etf_relation",
    ClaimType.LIQUIDATION_CONFIRMATION.value: "join.intraday_location",
    ClaimType.LIQUIDITY_HUNT.value: "join.intraday_location",
    ClaimType.FUNDAMENTAL_EVENT_REALIZATION.value: "join.fundamental_realization",
    ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value: "join.fundamental_realization",
}
PIPELINE_ACCOUNT_CONTROL_CLAIM_TYPES = frozenset(
    {
        ClaimType.MARKET_REGIME.value,
        ClaimType.STRONGEST_COUNTEREVIDENCE.value,
        ClaimType.INVALIDATION_PATH.value,
    }
)
PIPELINE_ACCOUNT_STRATEGY_OWNER = {
    Account.MAIN.value: "main.strategy",
    Account.MAKER.value: "maker.thesis_score_basis",
}

OBSERVATION_ID_BY_SOURCE = {
    ContractSource.BLOCKBEATS.value: "obs_bb",
    ContractSource.FEDWATCH.value: "obs_fw",
    ContractSource.FARSIDE.value: "obs_fs",
    ContractSource.COINGLASS.value: "obs_cg",
    ContractSource.EXOCHARTS.value: "obs_exo",
    ContractSource.TRADINGVIEW.value: "obs_tv",
}

OBSERVATION_KIND_BY_CONTRACT_SOURCE = {
    ContractSource.BLOCKBEATS.value: ObservationKind.STRUCTURED.value,
    ContractSource.FEDWATCH.value: ObservationKind.VISUAL.value,
    ContractSource.FEDWATCH_PLAN_C.value: ObservationKind.STRUCTURED.value,
    ContractSource.FARSIDE.value: ObservationKind.STRUCTURED.value,
    ContractSource.COINGLASS.value: ObservationKind.VISUAL.value,
    ContractSource.EXOCHARTS.value: ObservationKind.VISUAL.value,
    ContractSource.TRADINGVIEW.value: ObservationKind.VISUAL.value,
}

STRUCTURED_EVIDENCE_SOURCES = frozenset(
    source
    for source in EVIDENCE_SOURCE_ORDER
    if OBSERVATION_KIND_BY_CONTRACT_SOURCE[source]
    == ObservationKind.STRUCTURED.value
)
VISUAL_EVIDENCE_SOURCES = frozenset(
    source
    for source in EVIDENCE_SOURCE_ORDER
    if OBSERVATION_KIND_BY_CONTRACT_SOURCE[source] == ObservationKind.VISUAL.value
)

_observation_base_fields = (
    "id",
    "kind",
    "source",
    "observed_at",
    "fact",
    "metrics",
    "evidence_refs",
    "uncertainty",
)
_visual_observation_tail_fields = (
    "alternate_interpretation",
    "visual_citations",
    "visual_review",
)
OBSERVATION_FIELD_ORDER_BY_CONTRACT_SOURCE = {
    ContractSource.BLOCKBEATS.value: (
        *_observation_base_fields,
        "structured_binding",
    ),
    ContractSource.FARSIDE.value: (
        *_observation_base_fields,
        "structured_binding",
    ),
    ContractSource.FEDWATCH.value: (
        *_observation_base_fields,
        *_visual_observation_tail_fields,
    ),
    ContractSource.FEDWATCH_PLAN_C.value: (
        *_observation_base_fields,
        "structured_binding",
    ),
    ContractSource.COINGLASS.value: (
        *_observation_base_fields,
        "subject",
        "timeframe",
        "pivot_id",
        *_visual_observation_tail_fields,
    ),
    ContractSource.EXOCHARTS.value: (
        *_observation_base_fields,
        "subject",
        "timeframe",
        *_visual_observation_tail_fields,
    ),
    ContractSource.TRADINGVIEW.value: (
        *_observation_base_fields,
        "subject",
        "timeframe",
        *_visual_observation_tail_fields,
    ),
}

_claim_base_fields = (
    "id",
    "claim_type",
    "account",
    "conclusion",
    "support_ids",
    "counter_ids",
    "invalidation",
)
CLAIM_FIELD_ORDER_BY_TYPE = {
    ClaimType.FUNDAMENTAL_CONTEXT.value: _claim_base_fields,
    ClaimType.FUNDAMENTAL_EVENT_REALIZATION.value: (
        *_claim_base_fields,
        "selected_event_sha256",
        "realization_state",
    ),
    ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value: (
        *_claim_base_fields,
        "realization_state",
    ),
    ClaimType.ORDERFLOW_INTERPRETATION.value: (
        *_claim_base_fields,
        "direction",
        "score_assessment",
    ),
    ClaimType.CHART_INTERPRETATION.value: _claim_base_fields,
    ClaimType.ETF_CONFIRMATION.value: (
        *_claim_base_fields,
        "price_relation",
        "method_tags",
    ),
    ClaimType.LIQUIDATION_CONFIRMATION.value: (
        *_claim_base_fields,
        "confirmation_result",
        "method_tags",
    ),
    ClaimType.LIQUIDITY_HUNT.value: (*_claim_base_fields, "method_tags"),
    ClaimType.MARKET_REGIME.value: _claim_base_fields,
    ClaimType.STRONGEST_COUNTEREVIDENCE.value: (
        *_claim_base_fields,
        "current_basis",
        "trigger_logic",
    ),
    ClaimType.INVALIDATION_PATH.value: (
        *_claim_base_fields,
        "current_basis",
        "trigger_logic",
        "structural_noise_buffer",
    ),
    ClaimType.MAIN_ACCOUNT_THESIS.value: (
        *_claim_base_fields,
        "direction",
        "invalidation_id",
    ),
    ClaimType.MAKER_THESIS.value: (
        *_claim_base_fields,
        "direction",
        "invalidation_id",
        "method_tags",
    ),
    ClaimType.CANNOT_DO.value: (*_claim_base_fields, "prohibition"),
}

ACCOUNT_CLAIM_BINDINGS = {
    "main_claim_id": {
        "claim_type": ClaimType.MAIN_ACCOUNT_THESIS.value,
        "account": Account.MAIN.value,
    },
    "maker_claim_id": {
        "claim_type": ClaimType.MAKER_THESIS.value,
        "account": Account.MAKER.value,
    },
    "main_regime_claim_id": {
        "claim_type": ClaimType.MARKET_REGIME.value,
        "account": Account.MAIN.value,
    },
    "maker_regime_claim_id": {
        "claim_type": ClaimType.MARKET_REGIME.value,
        "account": Account.MAKER.value,
    },
    "main_counter_claim_id": {
        "claim_type": ClaimType.STRONGEST_COUNTEREVIDENCE.value,
        "account": Account.MAIN.value,
    },
    "maker_counter_claim_id": {
        "claim_type": ClaimType.STRONGEST_COUNTEREVIDENCE.value,
        "account": Account.MAKER.value,
    },
    "main_invalidation_claim_id": {
        "claim_type": ClaimType.INVALIDATION_PATH.value,
        "account": Account.MAIN.value,
    },
    "maker_invalidation_claim_id": {
        "claim_type": ClaimType.INVALIDATION_PATH.value,
        "account": Account.MAKER.value,
    },
}

CLAIM_TOPOLOGY = {
    "schema_version": "claim-topology-v1",
    "support_selection_owner": "model",
    "server_support_edge_injection_allowed": False,
    "direct_observation_support_policy": (
        "exact_for_listed_claim_types_claim_only_otherwise"
    ),
    "exact_direct_observation_sources_by_claim_type": {
        ClaimType.FUNDAMENTAL_CONTEXT.value: [
            EvidenceSource.BLOCKBEATS.value,
            EvidenceSource.FEDWATCH.value,
            EvidenceSource.FARSIDE.value,
        ],
        ClaimType.ORDERFLOW_INTERPRETATION.value: [
            EvidenceSource.COINGLASS.value,
            EvidenceSource.EXOCHARTS.value,
        ],
        ClaimType.CHART_INTERPRETATION.value: [EvidenceSource.TRADINGVIEW.value],
        ClaimType.ETF_CONFIRMATION.value: [
            EvidenceSource.COINGLASS.value,
            EvidenceSource.FARSIDE.value,
        ],
        ClaimType.LIQUIDATION_CONFIRMATION.value: [
            EvidenceSource.COINGLASS.value
        ],
    },
    "required_reachable_claim_types_by_claim_type": {
        ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value: [
            ClaimType.FUNDAMENTAL_CONTEXT.value,
            ClaimType.CHART_INTERPRETATION.value,
        ],
        ClaimType.MARKET_REGIME.value: [
            ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value,
            ClaimType.ORDERFLOW_INTERPRETATION.value,
            ClaimType.CHART_INTERPRETATION.value,
        ],
        ClaimType.LIQUIDATION_CONFIRMATION.value: [
            ClaimType.CHART_INTERPRETATION.value
        ],
        ClaimType.LIQUIDITY_HUNT.value: [
            ClaimType.CHART_INTERPRETATION.value,
            ClaimType.LIQUIDATION_CONFIRMATION.value,
        ],
        ClaimType.MAIN_ACCOUNT_THESIS.value: [
            ClaimType.MARKET_REGIME.value,
            ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value,
            ClaimType.ETF_CONFIRMATION.value,
        ],
        ClaimType.MAKER_THESIS.value: [
            ClaimType.MARKET_REGIME.value,
            ClaimType.ORDERFLOW_INTERPRETATION.value,
            ClaimType.CHART_INTERPRETATION.value,
            ClaimType.LIQUIDITY_HUNT.value,
        ],
        ClaimType.STRONGEST_COUNTEREVIDENCE.value: [ClaimType.MARKET_REGIME.value],
        ClaimType.INVALIDATION_PATH.value: [ClaimType.MARKET_REGIME.value],
        ClaimType.CANNOT_DO.value: [
            ClaimType.MAKER_THESIS.value,
            ClaimType.STRONGEST_COUNTEREVIDENCE.value,
            ClaimType.INVALIDATION_PATH.value,
            ClaimType.MARKET_REGIME.value,
        ],
    },
    "required_direct_claim_types_by_claim_type": {
        ClaimType.FUNDAMENTAL_EVENT_REALIZATION.value: [
            ClaimType.FUNDAMENTAL_CONTEXT.value,
            ClaimType.CHART_INTERPRETATION.value,
        ],
        ClaimType.FUNDAMENTAL_PRICE_REALIZATION.value: [
            ClaimType.FUNDAMENTAL_CONTEXT.value,
            ClaimType.CHART_INTERPRETATION.value,
        ],
        ClaimType.LIQUIDATION_CONFIRMATION.value: [
            ClaimType.CHART_INTERPRETATION.value
        ],
    },
}

TYPED_NARRATIVE_OWNERSHIP = {
    "schema_version": "typed-narrative-ownership-v1",
    "typed_control_paths": [
        "claims[claim_type=fundamental_price_realization].realization_state",
        "claims[claim_type=etf_confirmation].price_relation",
        "claims[claim_type=liquidation_confirmation].confirmation_result",
        "observations[source=TradingView].metrics.chart_scoring_basis",
    ],
    "audit_narrative_paths": [
        "claims[claim_type=fundamental_price_realization].conclusion",
        "claims[claim_type=etf_confirmation].conclusion",
        "claims[claim_type=liquidation_confirmation].conclusion",
        "observations[source=TradingView].metrics.chart_component_rationales",
    ],
    "prose_keyword_inference_allowed": False,
    "compiler_typed_projection_required": True,
}

MODEL_OWNED_SEMANTIC_SURFACES = (
    "observations[kind=visual_judgment].fact",
    "observations[kind=visual_judgment].metrics",
    "observations[*].uncertainty",
    "claims[*].conclusion",
    "claims[*].supports",
    "claims[claim_type=main_account_thesis]",
    "claims[claim_type=maker_thesis]",
    "claims[claim_type=strongest_counterevidence]",
    "claims[claim_type=invalidation_path]",
    "methodology.*[model_owned_paths]",
    "report.audit.source_explanations",
    "report.audit.reasoning_proof",
)


DOMAIN_ENUM_VOCABULARIES = {
    enum_type.__name__: _values(enum_type)
    for enum_type in (
        Account,
        EvidenceSource,
        ContractSource,
        ObservationKind,
        ClaimType,
        ScenarioType,
        TriggerOperator,
        Direction,
        MakerPlanState,
        EntryType,
        OrderLifecycleState,
        ReachDirection,
        EvidenceEffect,
        MakerSemanticState,
        ContinuityAction,
        ContinuityPriorStatus,
    )
}

# Every module-level deterministic owner must be classified here.  The identity
# payload is materialized from this exact inventory, while the companion test
# compares it with the module's uppercase assignments.  Adding a new owner
# without deciding whether it belongs to semantic identity therefore fails
# closed instead of silently preserving the old authority epoch.
SEMANTIC_COMPONENT_NAMES = frozenset(
    {
        "ACCOUNT_CLAIM_BINDINGS",
        "ACCOUNT_CURRENT_BASIS_POLICY_FIELDS",
        "ACCOUNT_LOOP_CLAIM_TYPES",
        "CANNOT_DO_ABSOLUTE_DIRECTION_CONFLICTS",
        "CANNOT_DO_BOTH_PURSUIT",
        "CANNOT_DO_CODES",
        "CANNOT_DO_PURSUIT_DIRECTION",
        "CLAIM_ACCOUNT_SCOPES",
        "CLAIM_FIELD_ORDER_BY_TYPE",
        "CLAIM_TOPOLOGY",
        "CLAIM_TYPES",
        "CONTINUITY_ACTIONS",
        "CONTINUITY_PRIOR_STATUSES",
        "CONTRACT_SOURCES",
        "CURRENT_BASIS_ALLOWED_OPERATORS",
        "DIRECT_DIRECTION_OBSERVATION_FIELDS",
        "DIRECTION_VALUE_MAP",
        "DIRECTIONAL_DIRECTIONS",
        "DECISION_MODEL_FIELD_ORDER",
        "DOMAIN_ENUM_VOCABULARIES",
        "ENTRY_TYPES",
        "EVIDENCE_DIRECTIONS",
        "EVIDENCE_EFFECT_ORDER",
        "EVIDENCE_EFFECTS",
        "EVIDENCE_SOURCE_ORDER",
        "EVIDENCE_SUBJECT_DIRECTION_ORDER",
        "EVIDENCE_SUBJECT_DIRECTIONS",
        "HIGH_IMPACT_CLAIMS",
        "MAKER_DIRECTIONS",
        "MAKER_FAILURE_ORDER",
        "MAKER_ORDER_LIFECYCLE_FIELD_ORDER",
        "MAKER_PLAN_STATES",
        "MAKER_SEMANTIC_STATES",
        "MINIMUM_OBSERVATION_METRICS",
        "MODEL_OWNED_SEMANTIC_SURFACES",
        "NON_ACTION_REPORT_SECTIONS",
        "NON_DIRECTIONAL_SUBJECT_DIRECTION_ORDER",
        "NON_TRACEABLE_REPORT_SECTIONS",
        "OBSERVATION_FIELD_ORDER_BY_CONTRACT_SOURCE",
        "OBSERVATION_ID_BY_SOURCE",
        "OBSERVATION_KIND_BY_CONTRACT_SOURCE",
        "OBSERVATION_MECHANICAL_OWNERSHIP",
        "ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION",
        "ORDER_LIFECYCLE_APPLICABILITY",
        "ORDER_LIFECYCLE_DISPLAY_BY_STATE",
        "ORDER_LIFECYCLE_PATH_FLAGS",
        "PIPELINE_ACCOUNT_CONTROL_CLAIM_TYPES",
        "PIPELINE_ACCOUNT_STRATEGY_OWNER",
        "PIPELINE_SCHEMA_VERSION",
        "PIPELINE_SHARED_CLAIM_OWNER",
        "PIPELINE_SOURCE_UNIT_BY_NAME",
        "PIPELINE_UNIT_FIELD_ORDER",
        "PIPELINE_UNIT_FIELDS",
        "PIPELINE_UNIT_ORDER",
        "PIPELINE_UNIT_ROWS",
        "POLICY_SOURCE_KEYS",
        "REACH_DIRECTION_CODES",
        "REASONING_OBSERVATION_SOURCE_ORDER",
        "RELATIVE_EXOCHARTS_DIRECTION",
        "RELATIVE_TRIGGER_OPERATOR_PROJECTION",
        "REPORT_BINDING_SECTION_MODEL_PATHS",
        "REPORT_BINDINGS_SCHEMA_VERSION",
        "REPORT_MODEL_FIELD_ORDER",
        "REPORT_SECTIONS",
        "BLOCKBEATS_CARDS_SCHEMA_VERSION",
        "EXECUTION_AUTHORIZATION_FIELDS",
        "MAKER_SEMANTIC_STATE_SCHEMA_VERSION",
        "SCENARIO_TYPES",
        "SCENARIO_ACCOUNT_ORDER",
        "SCENARIO_BASE_CONDITION_BY_ACCOUNT_DIRECTION",
        "SCENARIO_CANONICAL_AUDIT_FIELD_ORDER",
        "SCENARIO_CONDITION_OWNER_BY_TYPE",
        "SCENARIO_EXECUTION_LIFECYCLE_OWNER",
        "SCENARIO_FIELD_ORDER",
        "SCENARIO_FREE_PROSE_PROJECTABLE",
        "SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT",
        "SCENARIO_OWNERSHIP_SCHEMA_VERSION",
        "SCENARIO_PROJECTION_SCHEMA_VERSION",
        "SCENARIO_TRANSITION_CODES",
        "SCENARIO_TRANSITION_OWNER",
        "SCENARIO_TYPE_ORDER",
        "SCENARIO_VISIBLE_PROJECTION_BY_ACCOUNT_AND_TRANSITION_CODE",
        "SCAFFOLD_POLICY",
        "SECTION_REQUIRED_CLAIM_TYPES",
        "SHADOW_CONTINUITY_FIELDS",
        "SHADOW_CONTINUITY_SCHEMA_VERSION",
        "SOURCE_ROLES",
        "SOURCE_ROLE_CLAIM_OWNER",
        "STRUCTURED_EVIDENCE_SOURCES",
        "TOP_LEVEL_CERTIFICATION_ONLY_FIELDS",
        "TOP_LEVEL_CONTROLLER_REBOUND_FIELDS",
        "TOP_LEVEL_FIELD_ORDER",
        "TOP_LEVEL_PRODUCER_COLLECTION_FIELDS",
        "TRADINGVIEW_TIMEFRAMES",
        "TRIGGER_CLAIM_FIELDS",
        "TRIGGER_ACCOUNT_SOURCE_REQUIREMENTS",
        "TRIGGER_CONTROL_CLAIM_TYPES",
        "TRIGGER_CONTROL_CLAIM_TYPE_ORDER",
        "TRIGGER_EFFECT_BY_CLAIM_TYPE",
        "TRIGGER_LOGIC_ALLOWED_OPERATORS",
        "TRIGGER_LOGIC_MODES",
        "TRIGGER_OBSERVATION_FIELDS",
        "TRIGGER_SCALAR_CLAUSE_FIELD_ORDER",
        "TRIGGER_SCALAR_CLAUSE_FIELDS",
        "TYPED_NARRATIVE_OWNERSHIP",
        "TIMEFRAME_DISPLAY_SCHEMA_VERSION",
        "VISUAL_CITATION_POLICY",
        "VISUAL_EVIDENCE_SOURCES",
    }
)

SEMANTIC_IDENTITY_METADATA_NAMES = frozenset(
    {
        "REGISTRY",
        "SEMANTIC_COMPONENT_NAMES",
        "SEMANTIC_IDENTITY_METADATA_NAMES",
    }
)


def _semantic_component_payload() -> dict[str, Any]:
    public_constants = {name for name in globals() if name.isupper()}
    classified = SEMANTIC_COMPONENT_NAMES | SEMANTIC_IDENTITY_METADATA_NAMES
    unclassified = sorted(public_constants - classified)
    missing = sorted(SEMANTIC_COMPONENT_NAMES - public_constants)
    if unclassified or missing:
        raise RuntimeError(
            "domain registry semantic owner classification is incomplete: "
            f"unclassified={unclassified}; missing={missing}"
        )
    raw = {name: globals()[name] for name in sorted(SEMANTIC_COMPONENT_NAMES)}
    return json.loads(canonical_json_bytes(raw).decode("utf-8"))


@dataclass(frozen=True)
class DomainRegistry:
    schema_version: str = "vnext-domain-registry-v2"
    reasoning_submission_schema_version: str = "reasoning-submission-contract-v6"
    reasoning_model_schema_version: str = "reasoning-model-v5"
    decision_model_schema_version: str = "decision-model-v7"
    report_model_schema_version: str = "canonical-report-model-v11"
    maker_order_lifecycle_schema_version: str = "maker-order-lifecycle-v1"
    evidence_polarity_schema_version: str = "evidence-polarity-v1"
    report_bindings_schema_version: str = REPORT_BINDINGS_SCHEMA_VERSION
    blockbeats_cards_schema_version: str = BLOCKBEATS_CARDS_SCHEMA_VERSION
    shadow_continuity_schema_version: str = SHADOW_CONTINUITY_SCHEMA_VERSION
    scenario_ownership_schema_version: str = SCENARIO_OWNERSHIP_SCHEMA_VERSION
    scenario_projection_schema_version: str = SCENARIO_PROJECTION_SCHEMA_VERSION
    maker_semantic_state_schema_version: str = MAKER_SEMANTIC_STATE_SCHEMA_VERSION
    timeframe_display_schema_version: str = TIMEFRAME_DISPLAY_SCHEMA_VERSION
    report_model_field_order: tuple[str, ...] = REPORT_MODEL_FIELD_ORDER
    reasoning_model_field_order: tuple[str, ...] = TOP_LEVEL_FIELD_ORDER
    decision_model_field_order: tuple[str, ...] = DECISION_MODEL_FIELD_ORDER

    @property
    def report_binding_section_model_paths(
        self,
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return REPORT_BINDING_SECTION_MODEL_PATHS

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_schema_versions": {
                "decision_model": self.decision_model_schema_version,
                "evidence_polarity": self.evidence_polarity_schema_version,
                "maker_order_lifecycle": (
                    self.maker_order_lifecycle_schema_version
                ),
                "reasoning_model": self.reasoning_model_schema_version,
                "reasoning_submission": self.reasoning_submission_schema_version,
                "report_model": self.report_model_schema_version,
                "report_bindings": self.report_bindings_schema_version,
                "blockbeats_cards": self.blockbeats_cards_schema_version,
                "shadow_continuity": self.shadow_continuity_schema_version,
                "scenario_ownership": self.scenario_ownership_schema_version,
                "scenario_projection": self.scenario_projection_schema_version,
                "maker_semantic_state": self.maker_semantic_state_schema_version,
                "timeframe_display": self.timeframe_display_schema_version,
            },
            "semantic_components": _semantic_component_payload(),
        }

    @property
    def semantic_contract_sha256(self) -> str:
        return canonical_sha256(self.identity_payload())


REGISTRY = DomainRegistry()
