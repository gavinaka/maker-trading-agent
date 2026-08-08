"""Validate the learned 2026-06-22..26 reasoning method as typed data.

Historical reports never enter production.  This module validates only the
method and user-intent invariants distilled during maintenance.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,79}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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


@dataclass(frozen=True)
class MethodologyIssue:
    """One independently evaluable golden-methodology business defect."""

    code: str
    message: str
    path: str


@dataclass(frozen=True)
class MethodologyEvaluation:
    """Result of the vNext collect-all evaluator."""

    normalized: dict[str, Any] | None
    issues: tuple[MethodologyIssue, ...]


_UNAVAILABLE = object()


def _methodology_inventory_leaf_paths(
    objects: dict[str, Any],
    arrays: dict[str, Any],
) -> set[str]:
    leaves = {
        f"methodology.{block}.{field}"
        for block, spec in objects.items()
        for field in spec["field_order"]
    }
    leaves.update(
        f"methodology.{block}[*].{field}"
        for block, spec in arrays.items()
        for field in spec["item"]["field_order"]
    )
    return leaves


def _valid_methodology_server_binding(binding: Any) -> bool:
    if not isinstance(binding, dict):
        return False
    resolver = binding.get("resolver")
    exact_keys = {
        "literal": {"resolver", "value"},
        "single_policy_value": {"resolver", "policy_path"},
        "observation_id": {"resolver", "source"},
        "observation_field": {"resolver", "source", "field_path"},
        "unique_claim_id": {"resolver", "claim_type", "account"},
        "unique_claim_field": {
            "resolver",
            "claim_type",
            "account",
            "field_path",
        },
        "event_realization_claim_id": {
            "resolver",
            "claim_type",
            "account",
            "key_field",
            "claim_match_field",
        },
        "ordered_unique_claim_ids": {"resolver", "bindings"},
    }
    if (
        not isinstance(resolver, str)
        or resolver not in exact_keys
        or set(binding) != exact_keys[resolver]
    ):
        return False
    if resolver == "literal":
        return True
    if resolver == "ordered_unique_claim_ids":
        bindings = binding.get("bindings")
        return (
            isinstance(bindings, list)
            and bool(bindings)
            and all(
                isinstance(item, dict)
                and set(item) == {"claim_type", "account"}
                and all(
                    isinstance(item.get(key), str) and item.get(key)
                    for key in ("claim_type", "account")
                )
                for item in bindings
            )
            and len(
                {
                    (str(item["claim_type"]), str(item["account"]))
                    for item in bindings
                }
            )
            == len(bindings)
        )
    return all(
        isinstance(value, str) and value
        for key, value in binding.items()
        if key != "resolver"
    )


def _validate_methodology_leaf_ownership(
    ownership: dict[str, Any],
    *,
    objects: dict[str, Any],
    arrays: dict[str, Any],
) -> None:
    all_leaves = _methodology_inventory_leaf_paths(objects, arrays)
    bindings = ownership.get("server_owned_bindings")
    subtrees = ownership.get("server_owned_subtrees")
    model_owned = ownership.get("model_owned_paths")
    producer_keys = ownership.get("producer_key_paths")
    if (
        ownership.get("schema_version")
        != "methodology-leaf-ownership-v1"
        or not isinstance(bindings, dict)
        or not isinstance(subtrees, list)
        or not isinstance(model_owned, list)
        or not isinstance(producer_keys, list)
        or any(not isinstance(path, str) or not path for path in bindings)
        or any(not isinstance(path, str) or not path for path in subtrees)
        or any(not isinstance(path, str) or not path for path in model_owned)
        or any(not isinstance(path, str) or not path for path in producer_keys)
        or any(
            not _valid_methodology_server_binding(binding)
            for binding in bindings.values()
        )
        or ownership.get("unclassified_leaf_policy")
        != "preflight_hard_stop"
    ):
        raise ValueError("methodology leaf ownership inventory is invalid")

    binding_paths = set(bindings)
    model_paths = set(model_owned)
    key_paths = set(producer_keys)
    subtree_paths = {
        leaf
        for leaf in all_leaves
        if any(
            leaf.startswith(f"{subtree}.")
            or leaf.startswith(f"{subtree}[*].")
            for subtree in subtrees
        )
    }
    server_paths = binding_paths | subtree_paths
    if (
        len(binding_paths) != len(bindings)
        or len(model_paths) != len(model_owned)
        or len(key_paths) != len(producer_keys)
        or len(set(subtrees)) != len(subtrees)
        or any(
            not any(
                leaf.startswith(f"{subtree}.")
                or leaf.startswith(f"{subtree}[*].")
                for leaf in all_leaves
            )
            for subtree in subtrees
        )
        or not binding_paths <= all_leaves
        or not model_paths <= all_leaves
        or not key_paths <= all_leaves
        or server_paths & model_paths
        or server_paths & key_paths
        or model_paths & key_paths
        or server_paths | model_paths | key_paths != all_leaves
    ):
        raise ValueError(
            "methodology leaf ownership must classify every leaf exactly once"
        )
    if ownership.get("leaf_count") != len(all_leaves):
        raise ValueError("methodology leaf ownership count is invalid")


def _methodology_object_inventory() -> dict[str, Any]:

    return {
        "independent_synthesis": {
            "field_order": [
                "market_stage_claim_id",
                "dominant_leg",
                "primary_evidence_claim_ids",
                "strongest_counter_claim_id",
                "action_claim_id",
            ],
            "string_fields": [
                "market_stage_claim_id",
                "strongest_counter_claim_id",
                "action_claim_id",
            ],
            "string_array_fields": {
                "primary_evidence_claim_ids": {"min_items": 2}
            },
            "enum_fields": {
                "dominant_leg": {
                    "policy_path": "gold_methodology.dominant_legs"
                }
            },
        },
        "fundamental_price_realization": {
            "field_order": [
                "fundamental_claim_id",
                "price_claim_id",
                "realization_claim_id",
                "realization_state",
                "historical_market_fact_used",
            ],
            "string_fields": [
                "fundamental_claim_id",
                "price_claim_id",
                "realization_claim_id",
            ],
            "boolean_fields": ["historical_market_fact_used"],
            "exact_values": {"historical_market_fact_used": False},
            "enum_fields": {
                "realization_state": {
                    "policy_path": (
                        "gold_methodology.fundamental_realization_states"
                    )
                }
            },
        },
        "same_pivot_orderflow": {
            "field_order": [
                "observation_id",
                "claim_id",
                "leg_selected",
                "pullback_anchor_checked",
                "four_dimensions_same_anchor",
            ],
            "string_fields": ["observation_id", "claim_id"],
            "boolean_fields": [
                "leg_selected",
                "pullback_anchor_checked",
                "four_dimensions_same_anchor",
            ],
            "exact_values": {
                "leg_selected": True,
                "pullback_anchor_checked": True,
                "four_dimensions_same_anchor": True,
            },
        },
        "footprint_cross_check": {
            "field_order": ["observation_id", "claim_id", "relationship"],
            "string_fields": ["observation_id", "claim_id"],
            "enum_fields": {
                "relationship": {
                    "policy_path": "gold_methodology.cross_check_results"
                }
            },
        },
        "multi_timeframe_transition": {
            "field_order": [
                "observation_id",
                "claim_id",
                "transition_summary",
            ],
            "string_fields": [
                "observation_id",
                "claim_id",
                "transition_summary",
            ],
            "string_min_lengths": {"transition_summary": 20},
        },
        "volume_profile_liquidity": {
            "field_order": [
                "claim_id",
                "liquidation_observation_id",
                "user_drawn_profile_primary",
                "liquidation_auxiliary",
                "liquidation_confirmation",
            ],
            "string_fields": ["claim_id", "liquidation_observation_id"],
            "boolean_fields": [
                "user_drawn_profile_primary",
                "liquidation_auxiliary",
            ],
            "exact_values": {
                "user_drawn_profile_primary": True,
                "liquidation_auxiliary": True,
            },
            "enum_fields": {
                "liquidation_confirmation": {
                    "policy_path": (
                        "gold_methodology.liquidation_confirmation_results"
                    )
                }
            },
        },
        "etf_flow_relation": {
            "field_order": ["observation_id", "claim_id", "price_relation"],
            "string_fields": ["observation_id", "claim_id"],
            "enum_fields": {
                "price_relation": {
                    "policy_path": "gold_methodology.price_relations"
                }
            },
        },
        "account_separation": {
            "field_order": [
                "main_priority",
                "maker_priority",
                "main_claim_id",
                "maker_claim_id",
                "main_regime_claim_id",
                "maker_regime_claim_id",
                "main_counter_claim_id",
                "maker_counter_claim_id",
                "main_invalidation_claim_id",
                "maker_invalidation_claim_id",
                "conflict_policy",
                "forced_consensus",
            ],
            "string_fields": [
                "main_claim_id",
                "maker_claim_id",
                "main_regime_claim_id",
                "maker_regime_claim_id",
                "main_counter_claim_id",
                "maker_counter_claim_id",
                "main_invalidation_claim_id",
                "maker_invalidation_claim_id",
                "conflict_policy",
            ],
            "boolean_fields": ["forced_consensus"],
            "exact_values": {"forced_consensus": False},
            "exact_policy_values": {
                "main_priority": "gold_methodology.main_account_priority",
                "maker_priority": "gold_methodology.maker_priority",
                "conflict_policy": (
                    "gold_methodology.account_independence.conflict_policy"
                ),
            },
        },
        "cannot_do_derivation": {
            "field_order": ["claim_id", "basis_claim_ids"],
            "string_fields": ["claim_id"],
            "string_array_fields": {"basis_claim_ids": {"min_items": 3}},
        },
    }

def _methodology_array_inventory(
    *, event_field: str, event_fields: list[Any], event_policy: dict[str, Any]
) -> dict[str, Any]:
    from runtime_vnext.domain_ir.registry import (
        METHODOLOGY_SCENARIO_FIELD_ORDER,
        SCENARIO_ACCOUNT_ORDER,
        SCENARIO_TRANSITION_CODES,
        SCENARIO_TYPE_ORDER,
    )

    scenario_count = len(SCENARIO_ACCOUNT_ORDER) * len(SCENARIO_TYPE_ORDER)
    return {
        event_field: {
            "min_items": 3,
            "max_items": 3,
            "item": {
                "field_order": [str(item) for item in event_fields],
                "string_fields": [
                    "selected_event_sha256",
                    "realization_claim_id",
                ],
                "string_array_fields": {
                    "counter_claim_ids": {
                        "min_items": int(
                            event_policy.get("minimum_counter_claim_ids") or 1
                        )
                    }
                },
                "enum_fields": {
                    "impact_channel": {
                        "policy_path": (
                            "gold_methodology."
                            "fundamental_event_assessment_policy.impact_channels"
                        )
                    },
                    "expected_effect": {
                        "policy_path": (
                            "gold_methodology."
                            "fundamental_event_assessment_policy.expected_effects"
                        )
                    },
                    "boundary_code": {
                        "policy_path": (
                            "gold_methodology."
                            "fundamental_event_assessment_policy.boundary_codes"
                        )
                    },
                },
            },
        },
        "scenario_tree": {
            "min_items": scenario_count,
            "max_items": scenario_count,
            "item": {
                "field_order": list(METHODOLOGY_SCENARIO_FIELD_ORDER),
                "string_fields": ["claim_id"],
                "string_array_fields": {
                    "trigger_claim_ids": {"min_items": 1}
                },
                "enum_fields": {
                    "account": {"values": list(SCENARIO_ACCOUNT_ORDER)},
                    "kind": {"values": list(SCENARIO_TYPE_ORDER)},
                    "action": {"values": list(SCENARIO_TRANSITION_CODES.values())},
                },
                "exact_account_kind_matrix": True,
            },
        },
    }

def _methodology_leaf_ownership_inventory(
    *, event_field: str, event_policy: dict[str, Any]
) -> dict[str, Any]:

    return {
        "schema_version": "methodology-leaf-ownership-v1",
        "server_owned_subtrees": [
            "methodology.account_separation",
            "methodology.scenario_tree",
        ],
        "server_owned_bindings": {
            "methodology.independent_synthesis.dominant_leg": {
                "resolver": "observation_field",
                "source": "Coinglass",
                "field_path": "metrics.pivot.dominant_leg",
            },
            "methodology.fundamental_price_realization.fundamental_claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "fundamental_context",
                "account": "shared",
            },
            "methodology.fundamental_price_realization.price_claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "chart_interpretation",
                "account": "shared",
            },
            "methodology.fundamental_price_realization.realization_claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "fundamental_price_realization",
                "account": "shared",
            },
            "methodology.fundamental_price_realization.realization_state": {
                "resolver": "unique_claim_field",
                "claim_type": "fundamental_price_realization",
                "account": "shared",
                "field_path": "realization_state",
            },
            "methodology.fundamental_price_realization.historical_market_fact_used": {
                "resolver": "literal",
                "value": False,
            },
            f"methodology.{event_field}[*].realization_claim_id": {
                "resolver": "event_realization_claim_id",
                "claim_type": str(
                    event_policy["event_realization_claim_type"]
                ),
                "account": str(
                    event_policy["event_realization_claim_account"]
                ),
                "key_field": "selected_event_sha256",
                "claim_match_field": "selected_event_sha256",
            },
            f"methodology.{event_field}[*].boundary_code": {
                "resolver": "single_policy_value",
                "policy_path": (
                    "gold_methodology.fundamental_event_assessment_policy."
                    "boundary_codes"
                ),
            },
            "methodology.same_pivot_orderflow.observation_id": {
                "resolver": "observation_id",
                "source": "Coinglass",
            },
            "methodology.same_pivot_orderflow.claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "orderflow_interpretation",
                "account": "shared",
            },
            "methodology.same_pivot_orderflow.leg_selected": {
                "resolver": "literal",
                "value": True,
            },
            "methodology.same_pivot_orderflow.pullback_anchor_checked": {
                "resolver": "literal",
                "value": True,
            },
            "methodology.same_pivot_orderflow.four_dimensions_same_anchor": {
                "resolver": "literal",
                "value": True,
            },
            "methodology.footprint_cross_check.observation_id": {
                "resolver": "observation_id",
                "source": "Exocharts",
            },
            "methodology.footprint_cross_check.claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "orderflow_interpretation",
                "account": "shared",
            },
            "methodology.footprint_cross_check.relationship": {
                "resolver": "observation_field",
                "source": "Exocharts",
                "field_path": "metrics.cross_check_result",
            },
            "methodology.multi_timeframe_transition.observation_id": {
                "resolver": "observation_id",
                "source": "TradingView",
            },
            "methodology.multi_timeframe_transition.claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "chart_interpretation",
                "account": "shared",
            },
            "methodology.volume_profile_liquidity.claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "chart_interpretation",
                "account": "shared",
            },
            "methodology.volume_profile_liquidity.liquidation_observation_id": {
                "resolver": "observation_id",
                "source": "Coinglass",
            },
            "methodology.volume_profile_liquidity.user_drawn_profile_primary": {
                "resolver": "literal",
                "value": True,
            },
            "methodology.volume_profile_liquidity.liquidation_auxiliary": {
                "resolver": "literal",
                "value": True,
            },
            "methodology.volume_profile_liquidity.liquidation_confirmation": {
                "resolver": "unique_claim_field",
                "claim_type": "liquidation_confirmation",
                "account": "shared",
                "field_path": "confirmation_result",
            },
            "methodology.etf_flow_relation.observation_id": {
                "resolver": "observation_id",
                "source": "Farside",
            },
            "methodology.etf_flow_relation.claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "etf_confirmation",
                "account": "shared",
            },
            "methodology.etf_flow_relation.price_relation": {
                "resolver": "unique_claim_field",
                "claim_type": "etf_confirmation",
                "account": "shared",
                "field_path": "price_relation",
            },
            "methodology.cannot_do_derivation.claim_id": {
                "resolver": "unique_claim_id",
                "claim_type": "cannot_do",
                "account": "maker",
            },
            "methodology.cannot_do_derivation.basis_claim_ids": {
                "resolver": "ordered_unique_claim_ids",
                "bindings": [
                    {
                        "claim_type": "maker_thesis",
                        "account": "maker",
                    },
                    {
                        "claim_type": "strongest_counterevidence",
                        "account": "maker",
                    },
                    {
                        "claim_type": "invalidation_path",
                        "account": "maker",
                    },
                ],
            },
        },
        "model_owned_paths": [
            "methodology.independent_synthesis.market_stage_claim_id",
            "methodology.independent_synthesis.primary_evidence_claim_ids",
            "methodology.independent_synthesis.strongest_counter_claim_id",
            "methodology.independent_synthesis.action_claim_id",
            f"methodology.{event_field}[*].impact_channel",
            f"methodology.{event_field}[*].expected_effect",
            f"methodology.{event_field}[*].counter_claim_ids",
            "methodology.multi_timeframe_transition.transition_summary",
        ],
        "producer_key_paths": [
            f"methodology.{event_field}[*].selected_event_sha256",
        ],
        "unclassified_leaf_policy": "preflight_hard_stop",
        "leaf_count": 54,
    }

def get_methodology_runtime_inventory(
    *,
    policy: dict[str, Any],
    profile: str = "vnext_submission",
) -> dict[str, Any]:
    """Return the golden evaluator's exact producer-input inventory.

    ``normalize_methodology`` remains the frozen legacy fail-fast entry point.
    This inventory describes the narrower raw producer shape used by vNext,
    including the explicit account overlay on methodology scenarios.  Derived
    normalizer output fields are recorded separately and are never exposed as
    model-writable input.
    """

    if profile != "vnext_submission":
        raise ValueError(f"unsupported methodology inventory profile: {profile}")
    event_policy = policy.get("fundamental_event_assessment_policy")
    if not isinstance(event_policy, dict):
        raise ValueError("fundamental_event_assessment_policy must be an object")
    event_field = str(event_policy.get("methodology_field") or "")
    event_fields = event_policy.get("required_item_fields")
    if not event_field or not isinstance(event_fields, list) or not event_fields:
        raise ValueError(
            "fundamental event assessment runtime inventory is incomplete"
        )
    if len(event_fields) != len(set(str(item) for item in event_fields)):
        raise ValueError(
            "fundamental event assessment runtime inventory contains duplicate fields"
        )
    objects = _methodology_object_inventory()
    arrays = _methodology_array_inventory(
        event_field=event_field,
        event_fields=event_fields,
        event_policy=event_policy,
    )
    field_order = [
        "independent_synthesis",
        "fundamental_price_realization",
        event_field,
        "same_pivot_orderflow",
        "footprint_cross_check",
        "multi_timeframe_transition",
        "volume_profile_liquidity",
        "etf_flow_relation",
        "account_separation",
        "scenario_tree",
        "cannot_do_derivation",
    ]
    leaf_ownership = _methodology_leaf_ownership_inventory(
        event_field=event_field,
        event_policy=event_policy,
    )
    _validate_methodology_leaf_ownership(
        leaf_ownership,
        objects=objects,
        arrays=arrays,
    )
    return {
        "schema_version": "golden-methodology-runtime-inventory-v2",
        "profile": profile,
        "field_order": field_order,
        "objects": copy.deepcopy(objects),
        "arrays": copy.deepcopy(arrays),
        "leaf_ownership": copy.deepcopy(leaf_ownership),
        "dependencies": {
            "fundamental_price_realization": ["source.blockbeats"],
            event_field: [
                "source.blockbeats",
                "fundamental_price_realization",
            ],
            "etf_flow_relation": [
                "source.farside_btc_etf",
                "same_pivot_orderflow.price_direction",
            ],
            "volume_profile_liquidity": [
                "source.tradingview.volume_profile",
                "source.coinglass.liquidation_map",
            ],
            "cannot_do_derivation.scenario_closure": ["scenario_tree"],
        },
        "accepted_input_variants": {
            "fundamental_price_realization": {
                "producer": objects["fundamental_price_realization"][
                    "field_order"
                ],
                "normalized_replay": (
                    objects["fundamental_price_realization"]["field_order"]
                    + [
                        "blockbeats_observation_id",
                        "event_window_hours",
                        "selected_event_count",
                    ]
                ),
            },
            "scenario_tree": {
                "legacy_core_fields": [
                    "kind",
                    "claim_id",
                    "trigger_claim_ids",
                    "action",
                ],
                "vnext_overlay_fields": ["account"],
            },
        },
        "derived_output_only": [
            "source_methodology",
            "source_calibration",
        ],
        "policy_bindings": {
            "event_methodology_field": event_field,
            "event_required_item_fields": [str(item) for item in event_fields],
            "legacy_minimum_scenario_count": int(
                policy.get("minimum_scenario_count") or 0
            ),
            "vnext_scenario_count": arrays["scenario_tree"]["min_items"],
        },
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


def derive_combination_id(
    cvd: str,
    price: str,
    oi: str,
    funding_sign: str,
    policy: dict[str, Any],
) -> str:
    """Public deterministic C01-C81 derivation shared by every runtime."""

    return _combination_id(cvd, price, oi, funding_sign, policy)


def derive_etf_price_relation(
    price_direction: str,
    flow_direction: str,
    policy: dict[str, Any],
) -> str:
    """Derive ETF confirmation from the single machine-readable truth table."""

    table = policy.get("etf_price_relation_truth_table")
    expected_price_keys = {"up", "down", "flat"}
    expected_flow_keys = {"inflow", "outflow", "flat"}
    allowed_relations = set(policy.get("price_relations") or [])
    if not isinstance(table, dict) or set(table) != expected_price_keys:
        raise ValueError("ETF price relation truth table must define up/down/flat")
    for price_key in expected_price_keys:
        row = table.get(price_key)
        if not isinstance(row, dict) or set(row) != expected_flow_keys:
            raise ValueError(
                "ETF price relation truth table rows must define inflow/outflow/flat"
            )
        if any(value not in allowed_relations for value in row.values()):
            raise ValueError("ETF price relation truth table contains an invalid relation")
    if price_direction not in expected_price_keys:
        raise ValueError("ETF price direction must be up, down or flat")
    if flow_direction not in expected_flow_keys:
        raise ValueError("ETF flow direction must be inflow, outflow or flat")
    return str(table[price_direction][flow_direction])


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


def validate_effect_divergence(
    value: Any,
    *,
    cvd_direction: str,
    price_direction: str,
    policy: dict[str, Any],
) -> dict[str, str]:
    """Public parity validator for the effect-divergence semantic unit."""

    return _normalize_effect_divergence(
        value,
        cvd_direction=cvd_direction,
        price_direction=price_direction,
        policy=policy,
    )


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


def validate_oi_price_context(
    value: Any,
    *,
    price_direction: str,
    oi_direction: str,
    price_break_status: str,
    policy: dict[str, Any],
) -> str:
    """Public parity validator for OI/price context classification."""

    return _normalize_oi_price_context(
        value,
        price_direction=price_direction,
        oi_direction=oi_direction,
        price_break_status=price_break_status,
        policy=policy,
    )


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


def _account_claim(
    item_id: Any,
    claims: dict[str, dict[str, Any]],
    field: str,
    claim_type: str,
    account: str,
) -> str:
    ref = _claim(item_id, claims, field, claim_type)
    recorded_account = claims[ref].get("account")
    if recorded_account != account:
        raise ValueError(f"{field} must reference the {account} account")
    return ref


def _numeric_dict(value: Any, field: str) -> dict[str, int | float]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field} must be a non-empty numeric object")
    return {str(key): _decimal(item, f"{field}.{key}") for key, item in value.items()}


def _number_list(value: Any, field: str) -> list[int | float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty numeric array")
    return [_decimal(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _normalize_manual_profile(
    value: Any,
    profile_policy: dict[str, Any],
) -> dict[str, Any]:
    field = "TradingView volume_profile"
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    source_mode = _enum(
        value.get("source_mode"),
        {str(profile_policy["source_mode"])},
        f"{field}.source_mode",
    )
    status = _enum(
        value.get("status"),
        set(profile_policy["allowed_statuses"]),
        f"{field}.status",
    )
    platform_state = _enum(
        value.get("platform_indicator_state"),
        set(profile_policy["allowed_platform_indicator_states"]),
        f"{field}.platform_indicator_state",
    )
    if value.get("platform_vrvp_used") is not False:
        raise ValueError("TradingView platform VRVP must never be used")
    if value.get("automated_values_used") is not False:
        raise ValueError("TradingView automated profile values are forbidden")
    forbidden = {
        "poc", "vah", "val", "hvn", "lvn", "hvn_levels", "lvn_levels",
        "value_area_position", "automated_poc", "automated_vah", "automated_val",
    }
    if forbidden & set(value):
        raise ValueError(
            "TradingView volume_profile forbids platform point values: "
            + ", ".join(sorted(forbidden & set(value)))
        )
    raw_zones = value.get("zones")
    if not isinstance(raw_zones, list):
        raise ValueError(f"{field}.zones must be an array")
    zones: list[dict[str, Any]] = []
    for index, item in enumerate(raw_zones):
        if not isinstance(item, dict):
            raise ValueError(f"{field}.zones[{index}] must be an object")
        lower = _decimal(item.get("lower_bound"), f"{field}.zones[{index}].lower_bound")
        upper = _decimal(item.get("upper_bound"), f"{field}.zones[{index}].upper_bound")
        if lower <= 0 or upper <= 0 or lower >= upper:
            raise ValueError(f"{field}.zones[{index}] must have positive lower_bound < upper_bound")
        zones.append({
            "lower_bound": lower,
            "upper_bound": upper,
            "timeframe": _enum(
                str(item.get("timeframe", "")).lower(),
                set(profile_policy["allowed_zone_timeframes"]),
                f"{field}.zones[{index}].timeframe",
            ),
            "role": _enum(
                item.get("role"),
                set(profile_policy["allowed_zone_roles"]),
                f"{field}.zones[{index}].role",
            ),
        })
    reason = str(value.get("reason") or "").strip()
    if status == "readable":
        if platform_state not in set(profile_policy["readable_platform_indicator_states"]):
            raise ValueError("readable manual profile requires platform VRVP hidden or absent")
        if not zones:
            raise ValueError("readable manual profile requires at least one user-drawn zone")
    else:
        if zones:
            raise ValueError("insufficient manual profile must use zones=[]")
        if len(reason) < 8:
            raise ValueError("insufficient manual profile requires an explicit reason")
    return {
        "source_mode": source_mode,
        "status": status,
        "platform_indicator_state": platform_state,
        "platform_vrvp_used": False,
        "automated_values_used": False,
        "zones": zones,
        "reason": reason,
    }


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


def _normalize_methodology_foundation(
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
    expected_realization_fields = {
        "fundamental_claim_id",
        "price_claim_id",
        "realization_claim_id",
        "realization_state",
        "historical_market_fact_used",
    }
    normalized_realization_fields = expected_realization_fields | {
        "blockbeats_observation_id",
        "event_window_hours",
        "selected_event_count",
    }
    if set(realization) not in {
        frozenset(expected_realization_fields),
        frozenset(normalized_realization_fields),
    }:
        raise ValueError(
            "methodology.fundamental_price_realization must use the exact "
            "typed-owner field set"
        )
    if set(realization) == normalized_realization_fields and (
        realization.get("blockbeats_observation_id") != blockbeats["id"]
        or realization.get("event_window_hours") != 12
        or realization.get("selected_event_count") != 3
    ):
        raise ValueError(
            "normalized fundamental_price_realization differs from current BlockBeats calibration"
        )
    fundamental_claim_id = _claim(
        realization.get("fundamental_claim_id"), claims,
        "methodology.fundamental_price_realization.fundamental_claim_id",
        "fundamental_context",
    )
    price_claim_id = _claim(
        realization.get("price_claim_id"), claims,
        "methodology.fundamental_price_realization.price_claim_id",
        "chart_interpretation",
    )
    realization_claim_id = _claim(
        realization.get("realization_claim_id"), claims,
        "methodology.fundamental_price_realization.realization_claim_id",
        "fundamental_price_realization",
    )
    aggregate_claims = [
        claim
        for claim in claims.values()
        if claim.get("claim_type") == "fundamental_price_realization"
    ]
    if (
        len(aggregate_claims) != 1
        or aggregate_claims[0].get("id") != realization_claim_id
        or aggregate_claims[0].get("account") != "shared"
    ):
        raise ValueError(
            "fundamental_price_realization must have exactly one shared aggregate claim"
        )
    realization_state = _enum(
        realization.get("realization_state"),
        set(policy["fundamental_realization_states"]),
        "methodology.fundamental_price_realization.realization_state",
    )
    realization_owner = claims[realization_claim_id]
    realization_support = set(realization_owner.get("support_ids") or [])
    if not {fundamental_claim_id, price_claim_id}.issubset(realization_support):
        raise ValueError(
            "fundamental_price_realization claim must directly bind the current "
            "fundamental_context and chart_interpretation claims"
        )
    owner_state = realization_owner.get("realization_state")
    if owner_state != realization_state:
        raise ValueError(
            "methodology fundamental realization state differs from its typed owner"
        )
    normalized_realization = {
        "blockbeats_observation_id": blockbeats["id"],
        "fundamental_claim_id": fundamental_claim_id,
        "price_claim_id": price_claim_id,
        "realization_claim_id": realization_claim_id,
        "event_window_hours": 12,
        "selected_event_count": 3,
        "realization_state": realization_state,
        "historical_market_fact_used": False,
    }
    if realization.get("historical_market_fact_used") is not False:
        raise ValueError("fundamental price realization must use current-slot facts only")

    event_policy = policy.get("fundamental_event_assessment_policy")
    if not isinstance(event_policy, dict):
        raise ValueError("fundamental_event_assessment_policy must be an object")
    event_field = str(event_policy.get("methodology_field") or "")
    event_assessments = payload.get(event_field)
    if not isinstance(event_assessments, list):
        raise ValueError(f"methodology.{event_field} must be an array")
    selected_event_hashes = bv.get("selected_event_sha256")
    if (
        not isinstance(selected_event_hashes, list)
        or len(selected_event_hashes) != 3
        or len(set(selected_event_hashes)) != len(selected_event_hashes)
        or any(
            not isinstance(value, str) or not SHA256_RE.fullmatch(value)
            for value in selected_event_hashes
        )
    ):
        raise ValueError(
            "BlockBeats selected_event_sha256 must contain three unique certified hashes"
        )
    event_claim_type = str(event_policy.get("event_realization_claim_type") or "")
    event_claim_list = [
        claim
        for claim in claims.values()
        if claim.get("claim_type") == event_claim_type
    ]
    event_claims_by_hash: dict[str, list[dict[str, Any]]] = {}
    for claim in event_claim_list:
        event_claims_by_hash.setdefault(
            str(claim.get("selected_event_sha256") or ""), []
        ).append(claim)
    if (
        len(event_claim_list) != len(selected_event_hashes)
        or set(event_claims_by_hash) != set(selected_event_hashes)
        or any(len(items) != 1 for items in event_claims_by_hash.values())
    ):
        raise ValueError(
            "fundamental_event_realization must have exactly one shared claim "
            "per sealed BlockBeats top3 hash"
        )
    event_claims = {
        event_hash: items[0]
        for event_hash, items in event_claims_by_hash.items()
    }
    required_event_support_types = set(
        event_policy.get("event_realization_support_claim_types") or []
    )
    allowed_event_states = set(event_policy.get("event_realization_states") or [])
    for event_hash, event_claim in event_claims.items():
        if (
            event_claim.get("account")
            != event_policy.get("event_realization_claim_account")
            or event_claim.get("realization_state") not in allowed_event_states
        ):
            raise ValueError(
                "fundamental_event_realization account/state differs from authority"
            )
        direct_support_types = {
            claims[support_id].get("claim_type")
            for support_id in event_claim.get("support_ids") or []
            if support_id in claims
        }
        if not required_event_support_types.issubset(direct_support_types):
            raise ValueError(
                "fundamental_event_realization must directly support both "
                "fundamental_context and chart_interpretation"
            )
    reachable_from_aggregate: set[str] = set()
    pending = list(realization_owner.get("support_ids") or [])
    while pending:
        support_id = str(pending.pop())
        if support_id in reachable_from_aggregate:
            continue
        reachable_from_aggregate.add(support_id)
        if support_id in claims:
            pending.extend(claims[support_id].get("support_ids") or [])
    event_claim_ids = {
        str(claim.get("id") or "") for claim in event_claims.values()
    }
    if not event_claim_ids.issubset(reachable_from_aggregate):
        raise ValueError(
            "aggregate fundamental_price_realization must reach all event realization claims"
        )
    required_event_fields = set(event_policy.get("required_item_fields") or [])
    normalized_events_by_hash: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(event_assessments):
        item_path = f"methodology.{event_field}[{index}]"
        if not isinstance(item, dict) or set(item) != required_event_fields:
            raise ValueError(
                f"{item_path} differs from the exact event-assessment schema"
            )
        event_hash = str(item.get("selected_event_sha256") or "")
        if (
            event_hash not in selected_event_hashes
            or event_hash in normalized_events_by_hash
        ):
            raise ValueError(
                f"{item_path}.selected_event_sha256 must cover one sealed "
                "BlockBeats top3 hash exactly once"
            )
        event_realization_id = _claim(
            item.get("realization_claim_id"),
            claims,
            f"{item_path}.realization_claim_id",
            event_claim_type,
        )
        if claims[event_realization_id].get("account") != event_policy.get(
            "event_realization_claim_account"
        ):
            raise ValueError(f"{item_path}.realization_claim_id must be shared")
        if claims[event_realization_id].get("selected_event_sha256") != event_hash:
            raise ValueError(
                f"{item_path}.realization_claim_id must bind the same selected-event hash"
            )
        counter_ids = _refs(
            item.get("counter_claim_ids"),
            claim_ids,
            f"{item_path}.counter_claim_ids",
            int(event_policy.get("minimum_counter_claim_ids") or 1),
        )
        allowed_counter_types = set(
            event_policy.get("allowed_counter_claim_types") or []
        )
        if any(
            claims[counter_id].get("claim_type") not in allowed_counter_types
            or claims[counter_id].get("account")
            != event_policy.get("counter_claim_account")
            for counter_id in counter_ids
        ):
            raise ValueError(
                f"{item_path}.counter_claim_ids must reference only approved "
                "shared counter domains"
            )
        normalized_events_by_hash[event_hash] = {
            "selected_event_sha256": event_hash,
            "impact_channel": _enum(
                item.get("impact_channel"),
                set(event_policy.get("impact_channels") or []),
                f"{item_path}.impact_channel",
            ),
            "expected_effect": _enum(
                item.get("expected_effect"),
                set(event_policy.get("expected_effects") or []),
                f"{item_path}.expected_effect",
            ),
            "realization_claim_id": event_realization_id,
            "counter_claim_ids": counter_ids,
            "boundary_code": _enum(
                item.get("boundary_code"),
                set(event_policy.get("boundary_codes") or []),
                f"{item_path}.boundary_code",
            ),
        }
    return {
        "blockbeats_tier": blockbeats_tier,
        "claim_ids": claim_ids,
        "event_field": event_field,
        "farside_date": farside_date,
        "farside_direction": farside_direction,
        "farside_total": farside_total,
        "fed_as_of": fed_as_of,
        "fed_changes": fed_changes,
        "fed_current": fed_current,
        "next_fomc_date": next_fomc_date,
        "normalized_events_by_hash": normalized_events_by_hash,
        "normalized_realization": normalized_realization,
        "normalized_source_roles": normalized_source_roles,
        "normalized_synthesis": normalized_synthesis,
        "selected_event_hashes": selected_event_hashes,
    }


def _normalize_methodology_technical(
    payload: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    *,
    profile_policy: dict[str, Any],
    foundation: dict[str, Any],
) -> dict[str, Any]:
    event_field = foundation["event_field"]
    normalized_events_by_hash = foundation["normalized_events_by_hash"]
    normalized_synthesis = foundation["normalized_synthesis"]
    selected_event_hashes = foundation["selected_event_hashes"]
    if set(normalized_events_by_hash) != set(selected_event_hashes):
        raise ValueError(
            f"methodology.{event_field} must cover every sealed BlockBeats top3 hash exactly once"
        )
    normalized_event_assessments = [
        normalized_events_by_hash[event_hash]
        for event_hash in selected_event_hashes
    ]

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
    start_price = normalized_pivot_values["start_price"]
    end_price = normalized_pivot_values["end_price"]
    geometric_price_direction = (
        "up" if end_price > start_price else "down" if end_price < start_price else "flat"
    )
    geometric_dominant_leg = {
        "up": "up",
        "down": "down",
        "flat": "range",
    }[geometric_price_direction]
    if price_direction != geometric_price_direction:
        raise ValueError(
            "Coinglass price_direction conflicts with pivot start/end geometry"
        )
    if normalized_pivot_values["dominant_leg"] != geometric_dominant_leg:
        raise ValueError(
            "Coinglass dominant_leg conflicts with pivot start/end geometry"
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
    if (
        price_break_status == "new_high_or_breakout" and price_direction != "up"
    ) or (
        price_break_status == "new_low_or_breakdown" and price_direction != "down"
    ):
        raise ValueError(
            "Coinglass price_break_status conflicts with price direction"
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
    relationship = _enum(
        footprint.get("relationship"), set(policy["cross_check_results"]),
        "methodology.footprint_cross_check.relationship"
    )
    observed_relationship = _enum(
        ev.get("cross_check_result"), set(policy["cross_check_results"]),
        "Exocharts cross_check_result"
    )
    if relationship != observed_relationship:
        raise ValueError(
            "methodology footprint relationship differs from Exocharts cross_check_result"
        )
    normalized_footprint = {
        "observation_id": exocharts["id"],
        "claim_id": _claim(
            footprint.get("claim_id"), claims,
            "methodology.footprint_cross_check.claim_id", "orderflow_interpretation"
        ),
        "relationship": relationship,
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
        normalized_frame = {
            "price": _decimal(item.get("price"), f"TradingView {timeframe}.price"),
            "structure": _enum(
                item.get("structure"), {"bullish", "bearish", "range"},
                f"TradingView {timeframe}.structure"
            ),
        }
        # 15m is an execution-only timeframe for Maker price action and
        # intraday support/resistance. SMA20 belongs to the scored 1D/4H/1H
        # structure chain and has never been a required 15m trading input.
        if timeframe != "15m" or item.get("sma20") is not None:
            normalized_frame["sma20"] = _decimal(
                item.get("sma20"), f"TradingView {timeframe}.sma20"
            )
        normalized_frames[timeframe] = normalized_frame
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
    normalized_profile = _normalize_manual_profile(profile, profile_policy)
    if policy.get("liquidation_map_source") != "coinglass":
        raise ValueError("liquidation map source must be Coinglass")
    liquidation_observation = _observation(
        liquidity.get("liquidation_observation_id"),
        "coinglass",
        observations,
        "methodology.volume_profile_liquidity.liquidation_observation_id",
    )
    heatmap = liquidation_observation["values"].get("liquidation_map")
    if not isinstance(heatmap, dict):
        raise ValueError("Coinglass values.liquidation_map must be an object")
    if heatmap.get("role") != policy["liquidation_map_role"]:
        raise ValueError("liquidation map must remain auxiliary_only")
    threshold = _decimal(heatmap.get("threshold"), "Coinglass liquidation_map.threshold")
    if threshold != _decimal(
        policy["liquidation_map_threshold"], "liquidation map policy threshold"
    ):
        raise ValueError("Coinglass liquidation map threshold must match policy")
    captured_timeframes = heatmap.get("captured_timeframes")
    if not isinstance(captured_timeframes, list) or not captured_timeframes:
        raise ValueError("Coinglass liquidation map requires captured_timeframes")
    clean_timeframes = [str(item).lower() for item in captured_timeframes]
    if len(clean_timeframes) != len(set(clean_timeframes)):
        raise ValueError("Coinglass liquidation map timeframes must be unique")
    observed_date = date.fromisoformat(str(liquidation_observation["observed_at"])[:10])
    window_kind = "weekend" if observed_date.weekday() >= 5 else "weekday"
    required_windows = [
        str(item).lower()
        for item in policy["liquidation_capture_windows"][window_kind]
    ]
    if clean_timeframes != required_windows:
        raise ValueError(
            f"Coinglass liquidation map requires {required_windows} on {window_kind}"
        )
    current_price = _decimal(
        heatmap.get("current_price"), "Coinglass liquidation_map.current_price"
    )
    levels = heatmap.get("levels")
    if not isinstance(levels, list) or not levels:
        raise ValueError("liquidation map requires at least one evidenced level")
    normalized_levels = []
    for index, item in enumerate(levels):
        if not isinstance(item, dict):
            raise ValueError(f"liquidation map levels[{index}] must be an object")
        side = _enum(
            item.get("side"), {"above", "below"},
            f"liquidation level {index}.side",
        )
        price = _decimal(item.get("price"), f"liquidation level {index}.price")
        timeframe = _enum(
            str(item.get("timeframe", "")).lower(), set(clean_timeframes),
            f"liquidation level {index}.timeframe",
        )
        if (side == "above" and price <= current_price) or (
            side == "below" and price >= current_price
        ):
            raise ValueError(
                f"liquidation level {index} side conflicts with current price"
            )
        normalized_levels.append({
            "side": side,
            "price": price,
            "timeframe": timeframe,
            "strength": _enum(
                item.get("strength"), {"strong", "medium", "weak"},
                f"liquidation level {index}.strength",
            ),
        })
    return {
        "clean_timeframes": clean_timeframes,
        "current_price": current_price,
        "levels": levels,
        "liquidation_observation": liquidation_observation,
        "liquidity": liquidity,
        "normalized_event_assessments": normalized_event_assessments,
        "normalized_footprint": normalized_footprint,
        "normalized_levels": normalized_levels,
        "normalized_multi": normalized_multi,
        "normalized_pivot": normalized_pivot,
        "normalized_profile": normalized_profile,
        "price_direction": price_direction,
        "threshold": threshold,
        "tradingview": tradingview,
    }


def _normalize_methodology_closure(
    payload: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    *,
    foundation: dict[str, Any],
    technical: dict[str, Any],
) -> dict[str, Any]:
    blockbeats_tier = foundation["blockbeats_tier"]
    claim_ids = foundation["claim_ids"]
    farside_date = foundation["farside_date"]
    farside_direction = foundation["farside_direction"]
    farside_total = foundation["farside_total"]
    fed_as_of = foundation["fed_as_of"]
    fed_changes = foundation["fed_changes"]
    fed_current = foundation["fed_current"]
    next_fomc_date = foundation["next_fomc_date"]
    normalized_realization = foundation["normalized_realization"]
    normalized_source_roles = foundation["normalized_source_roles"]
    normalized_synthesis = foundation["normalized_synthesis"]
    clean_timeframes = technical["clean_timeframes"]
    current_price = technical["current_price"]
    levels = technical["levels"]
    liquidation_observation = technical["liquidation_observation"]
    liquidity = technical["liquidity"]
    normalized_event_assessments = technical["normalized_event_assessments"]
    normalized_footprint = technical["normalized_footprint"]
    normalized_levels = technical["normalized_levels"]
    normalized_multi = technical["normalized_multi"]
    normalized_pivot = technical["normalized_pivot"]
    normalized_profile = technical["normalized_profile"]
    price_direction = technical["price_direction"]
    threshold = technical["threshold"]
    tradingview = technical["tradingview"]

    if liquidity.get("user_drawn_profile_primary") is not True:
        raise ValueError("user-drawn manual profile must remain the primary liquidity-hunt method")
    if liquidity.get("liquidation_auxiliary") is not True:
        raise ValueError("Coinglass liquidation map must remain auxiliary")
    liquidation_confirmation = _enum(
        liquidity.get("liquidation_confirmation"),
        set(policy["liquidation_confirmation_results"]),
        "methodology.volume_profile_liquidity.liquidation_confirmation",
    )
    if normalized_profile["status"] == "insufficient" and liquidation_confirmation != "neutral":
        raise ValueError("Coinglass cannot confirm, weaken or replace an insufficient manual profile")
    normalized_liquidity = {
        "tradingview_observation_id": tradingview["id"],
        "liquidation_observation_id": liquidation_observation["id"],
        "claim_id": _claim(
            liquidity.get("claim_id"), claims,
            "methodology.volume_profile_liquidity.claim_id", "chart_interpretation"
        ),
        "profile": normalized_profile,
        "source_mode": normalized_profile["source_mode"],
        "profile_status": normalized_profile["status"],
        "zones": normalized_profile["zones"],
        "insufficient_reason": normalized_profile["reason"],
        "user_drawn_profile_primary": True,
        "liquidation_map_role": policy["liquidation_map_role"],
        "liquidation_map_source": "coinglass",
        "liquidation_auxiliary": True,
        "liquidation_threshold": threshold,
        "liquidation_capture_windows": clean_timeframes,
        "liquidation_current_price": current_price,
        "liquidation_confirmation": liquidation_confirmation,
        "liquidation_levels": normalized_levels,
    }

    etf = payload.get("etf_flow_relation")
    if not isinstance(etf, dict):
        raise ValueError("methodology.etf_flow_relation must be an object")
    farside = _observation(
        etf.get("observation_id"), "farside_btc_etf", observations,
        "methodology.etf_flow_relation.observation_id"
    )
    etf_price_relation = _enum(
        etf.get("price_relation"), set(policy["price_relations"]),
        "methodology.etf_flow_relation.price_relation"
    )
    expected_etf_relation = derive_etf_price_relation(
        price_direction,
        farside_direction,
        policy,
    )
    if etf_price_relation != expected_etf_relation:
        raise ValueError(
            "methodology.etf_flow_relation.price_relation must be derived from "
            "the certified same-pivot price direction and ETF flow direction"
        )
    etf_claim_id = _claim(
        etf.get("claim_id"),
        claims,
        "methodology.etf_flow_relation.claim_id",
        "etf_confirmation",
    )
    etf_claim = claims[etf_claim_id]
    if etf_claim.get("account") != "shared":
        raise ValueError("methodology.etf_flow_relation.claim_id must be shared")
    if etf_claim.get("price_relation") != etf_price_relation:
        raise ValueError(
            "ETF confirmation price_relation differs from the deterministic truth table"
        )
    if _claim_sources(etf_claim_id, observations, claims) != {
        "coinglass",
        "farside_btc_etf",
    }:
        raise ValueError(
            "ETF confirmation must trace exactly to current Coinglass price "
            "direction and Farside flow evidence"
        )
    normalized_etf = {
        "observation_id": farside["id"],
        "claim_id": etf_claim_id,
        "latest_complete_date": farside_date,
        "latest_total_usd_m": farside_total,
        "flow_direction": farside_direction,
        "price_relation": etf_price_relation,
    }

    account = payload.get("account_separation")
    if not isinstance(account, dict):
        raise ValueError("methodology.account_separation must be an object")
    expected_account_fields = {
        "main_priority",
        "maker_priority",
        "main_claim_id",
        "maker_claim_id",
        "main_regime_claim_id",
        "maker_regime_claim_id",
        "main_counter_claim_id",
        "maker_counter_claim_id",
        "main_invalidation_claim_id",
        "maker_invalidation_claim_id",
        "conflict_policy",
        "forced_consensus",
    }
    if set(account) != expected_account_fields:
        raise ValueError(
            "methodology.account_separation must use the exact independent-loop field set"
        )
    if account.get("main_priority") != policy["main_account_priority"]:
        raise ValueError("main account priority differs from constitution")
    if account.get("maker_priority") != policy["maker_priority"]:
        raise ValueError("Maker priority differs from constitution")
    if account.get("forced_consensus") is not False:
        raise ValueError("main account and Maker must not be forced into one direction")
    independence_policy = policy["account_independence"]
    expected_conflict_policy = independence_policy["conflict_policy"]
    if account.get("conflict_policy") != expected_conflict_policy:
        raise ValueError(
            "account conflict policy must preserve independently derived outputs"
        )
    normalized_account = {
        "main_priority": list(policy["main_account_priority"]),
        "maker_priority": list(policy["maker_priority"]),
        "main_claim_id": _account_claim(
            account.get("main_claim_id"), claims,
            "methodology.account_separation.main_claim_id", "main_account_thesis", "main"
        ),
        "maker_claim_id": _account_claim(
            account.get("maker_claim_id"), claims,
            "methodology.account_separation.maker_claim_id", "maker_thesis", "maker"
        ),
        "main_regime_claim_id": _account_claim(
            account.get("main_regime_claim_id"), claims,
            "methodology.account_separation.main_regime_claim_id", "market_regime", "main"
        ),
        "maker_regime_claim_id": _account_claim(
            account.get("maker_regime_claim_id"), claims,
            "methodology.account_separation.maker_regime_claim_id", "market_regime", "maker"
        ),
        "main_counter_claim_id": _account_claim(
            account.get("main_counter_claim_id"), claims,
            "methodology.account_separation.main_counter_claim_id",
            "strongest_counterevidence", "main"
        ),
        "maker_counter_claim_id": _account_claim(
            account.get("maker_counter_claim_id"), claims,
            "methodology.account_separation.maker_counter_claim_id",
            "strongest_counterevidence", "maker"
        ),
        "main_invalidation_claim_id": _account_claim(
            account.get("main_invalidation_claim_id"), claims,
            "methodology.account_separation.main_invalidation_claim_id",
            "invalidation_path", "main"
        ),
        "maker_invalidation_claim_id": _account_claim(
            account.get("maker_invalidation_claim_id"), claims,
            "methodology.account_separation.maker_invalidation_claim_id",
            "invalidation_path", "maker"
        ),
        "conflict_policy": str(expected_conflict_policy),
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
    if set(cannot) != {"claim_id", "basis_claim_ids"}:
        raise ValueError(
            "cannot_do_derivation must contain only claim_id and basis_claim_ids; "
            "model self-attestation is not accepted"
        )
    cannot_claim_id = _claim(
        cannot.get("claim_id"), claims,
        "methodology.cannot_do_derivation.claim_id", "cannot_do"
    )
    cannot_basis_ids = _refs(
        cannot.get("basis_claim_ids"), claim_ids,
        "methodology.cannot_do_derivation.basis_claim_ids", 3
    )
    required_basis_types = {
        "maker_thesis",
        "strongest_counterevidence",
        "invalidation_path",
    }
    actual_basis_types = {
        str(claims[claim_id].get("claim_type", ""))
        for claim_id in cannot_basis_ids
    }
    if not required_basis_types.issubset(actual_basis_types):
        raise ValueError(
            "cannot_do_derivation must bind the Maker thesis, strongest "
            "counterevidence and invalidation path"
        )
    normalized_cannot = {
        "claim_id": cannot_claim_id,
        "basis_claim_ids": cannot_basis_ids,
    }
    for index, scenario in enumerate(normalized_scenarios):
        if cannot_claim_id == scenario["claim_id"] or cannot_claim_id in scenario["trigger_claim_ids"]:
            raise ValueError(
                "methodology scenario_tree cannot use cannot_do as a claim or trigger; "
                f"cannot_do is the final closure (scenario {index})"
            )

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
        "fundamental_event_assessments": normalized_event_assessments,
        "same_pivot_orderflow": normalized_pivot,
        "footprint_cross_check": normalized_footprint,
        "multi_timeframe_transition": normalized_multi,
        "volume_profile_liquidity": normalized_liquidity,
        "etf_flow_relation": normalized_etf,
        "account_separation": normalized_account,
        "scenario_tree": normalized_scenarios,
        "cannot_do_derivation": normalized_cannot,
    }


def normalize_methodology(
    payload: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    *,
    profile_policy: dict[str, Any],
) -> dict[str, Any]:
    foundation = _normalize_methodology_foundation(
        payload, observations, claims, policy
    )
    technical = _normalize_methodology_technical(
        payload,
        observations,
        claims,
        policy,
        profile_policy=profile_policy,
        foundation=foundation,
    )
    return _normalize_methodology_closure(
        payload,
        observations,
        claims,
        policy,
        foundation=foundation,
        technical=technical,
    )


def _methodology_issue_path(message: str, fallback: str) -> str:
    """Map a frozen legacy error message to its smallest actionable path."""

    exact = {
        "methodology fundamental realization state differs from its typed owner": (
            "methodology.fundamental_price_realization.realization_state"
        ),
        (
            "methodology footprint relationship differs from Exocharts "
            "cross_check_result"
        ): "methodology.footprint_cross_check.relationship",
        (
            "account conflict policy must preserve independently derived outputs"
        ): "methodology.account_separation.conflict_policy",
        "main account priority differs from constitution": (
            "methodology.account_separation.main_priority"
        ),
        "Maker priority differs from constitution": (
            "methodology.account_separation.maker_priority"
        ),
        "main account and Maker must not be forced into one direction": (
            "methodology.account_separation.forced_consensus"
        ),
        (
            "fundamental price realization must use current-slot facts only"
        ): (
            "methodology.fundamental_price_realization."
            "historical_market_fact_used"
        ),
        (
            "user-drawn manual profile must remain the primary "
            "liquidity-hunt method"
        ): "methodology.volume_profile_liquidity.user_drawn_profile_primary",
        "Coinglass liquidation map must remain auxiliary": (
            "methodology.volume_profile_liquidity.liquidation_auxiliary"
        ),
    }
    if message in exact:
        return exact[message]
    match = re.search(
        r"(methodology\.[a-z_]+(?:\.[a-z_]+)*)",
        message,
    )
    if match:
        return match.group(1)
    return fallback


class _MethodologyCollector:
    """Collect independent vNext business defects without changing legacy."""

    def __init__(
        self,
        payload: Any,
        observations: dict[str, dict[str, Any]],
        claims: dict[str, dict[str, Any]],
        policy: dict[str, Any],
        *,
        profile_policy: dict[str, Any],
        blocked_paths: tuple[str, ...],
    ) -> None:
        self.payload = payload
        self.observations = observations
        self.claims = claims
        self.policy = policy
        self.profile_policy = profile_policy
        self.blocked_paths = blocked_paths
        self.issues: list[MethodologyIssue] = []
        self._issue_keys: set[tuple[str, str, str]] = set()

    def _blocked(self, path: str) -> bool:
        return any(
            path == blocked
            or path.startswith(f"{blocked}.")
            or path.startswith(f"{blocked}[")
            for blocked in self.blocked_paths
        )

    def _block(self, name: str) -> dict[str, Any] | object:
        path = f"methodology.{name}"
        if self._blocked(path) or not isinstance(self.payload, dict):
            return _UNAVAILABLE
        value = self.payload.get(name, _UNAVAILABLE)
        return value if isinstance(value, dict) else _UNAVAILABLE

    def _value(
        self,
        block: dict[str, Any] | object,
        name: str,
        field: str,
    ) -> Any:
        path = f"methodology.{name}.{field}"
        if (
            block is _UNAVAILABLE
            or self._blocked(path)
            or field not in block
        ):
            return _UNAVAILABLE
        return block[field]

    def _add(self, message: str, path: str) -> None:
        key = ("methodology.parity_failed", path, message)
        if key in self._issue_keys:
            return
        self._issue_keys.add(key)
        self.issues.append(
            MethodologyIssue(
                code="methodology.parity_failed",
                message=message,
                path=path,
            )
        )

    def _claim(self, value: Any) -> dict[str, Any] | object:
        if value is _UNAVAILABLE or not isinstance(value, str):
            return _UNAVAILABLE
        item = self.claims.get(value)
        return item if isinstance(item, dict) else _UNAVAILABLE

    def _observation(
        self,
        value: Any,
        source: str,
    ) -> dict[str, Any] | object:
        if value is _UNAVAILABLE or not isinstance(value, str):
            return _UNAVAILABLE
        item = self.observations.get(value)
        if (
            not isinstance(item, dict)
            or item.get("source") != source
            or not isinstance(item.get("values"), dict)
        ):
            return _UNAVAILABLE
        return item

    def _realization(self) -> None:
        name = "fundamental_price_realization"
        block = self._block(name)
        state = self._value(block, name, "realization_state")
        owner = self._claim(
            self._value(block, name, "realization_claim_id")
        )
        if (
            state is not _UNAVAILABLE
            and owner is not _UNAVAILABLE
            and owner.get("realization_state") != state
        ):
            self._add(
                (
                    "methodology fundamental realization state differs "
                    "from its typed owner"
                ),
                f"methodology.{name}.realization_state",
            )
        historical = self._value(
            block, name, "historical_market_fact_used"
        )
        if historical is not _UNAVAILABLE and historical is not False:
            self._add(
                "fundamental price realization must use current-slot facts only",
                f"methodology.{name}.historical_market_fact_used",
            )

    def _same_pivot(self) -> str | object:
        name = "same_pivot_orderflow"
        block = self._block(name)
        if block is _UNAVAILABLE:
            return _UNAVAILABLE
        for field in (
            "leg_selected",
            "pullback_anchor_checked",
            "four_dimensions_same_anchor",
        ):
            value = self._value(block, name, field)
            if value is not _UNAVAILABLE and value is not True:
                self._add(
                    f"methodology.same_pivot_orderflow.{field} must be true",
                    f"methodology.{name}.{field}",
                )
        observation = self._observation(
            self._value(block, name, "observation_id"),
            "coinglass",
        )
        if observation is _UNAVAILABLE:
            return _UNAVAILABLE
        values = observation["values"]
        price_direction = values.get("price_direction", _UNAVAILABLE)
        if price_direction not in set(self.policy.get("directions") or []):
            return _UNAVAILABLE
        pivot = values.get("pivot")
        if isinstance(pivot, dict):
            try:
                start = _decimal(
                    pivot.get("start_price"), "Coinglass pivot.start_price"
                )
                end = _decimal(
                    pivot.get("end_price"), "Coinglass pivot.end_price"
                )
            except ValueError:
                return _UNAVAILABLE
            geometric = (
                "up" if end > start else "down" if end < start else "flat"
            )
            if price_direction != geometric:
                self._add(
                    (
                        "Coinglass price_direction conflicts with pivot "
                        "start/end geometry"
                    ),
                    "methodology.same_pivot_orderflow.observation_id",
                )
                return _UNAVAILABLE
        return str(price_direction)

    def _footprint(self) -> None:
        name = "footprint_cross_check"
        block = self._block(name)
        relationship = self._value(block, name, "relationship")
        observation = self._observation(
            self._value(block, name, "observation_id"),
            "exocharts",
        )
        if relationship is _UNAVAILABLE or observation is _UNAVAILABLE:
            return
        observed = observation["values"].get(
            "cross_check_result", _UNAVAILABLE
        )
        if observed is not _UNAVAILABLE and relationship != observed:
            self._add(
                (
                    "methodology footprint relationship differs from "
                    "Exocharts cross_check_result"
                ),
                f"methodology.{name}.relationship",
            )

    def _liquidity(self) -> None:
        name = "volume_profile_liquidity"
        block = self._block(name)
        primary = self._value(
            block, name, "user_drawn_profile_primary"
        )
        if primary is not _UNAVAILABLE and primary is not True:
            self._add(
                (
                    "user-drawn manual profile must remain the primary "
                    "liquidity-hunt method"
                ),
                f"methodology.{name}.user_drawn_profile_primary",
            )
        auxiliary = self._value(
            block, name, "liquidation_auxiliary"
        )
        if auxiliary is not _UNAVAILABLE and auxiliary is not True:
            self._add(
                "Coinglass liquidation map must remain auxiliary",
                f"methodology.{name}.liquidation_auxiliary",
            )
        result = self._value(
            block, name, "liquidation_confirmation"
        )
        owners = [
            item
            for item in self.claims.values()
            if isinstance(item, dict)
            and item.get("claim_type") == "liquidation_confirmation"
        ]
        owner = owners[0] if len(owners) == 1 else _UNAVAILABLE
        if (
            result is not _UNAVAILABLE
            and owner is not _UNAVAILABLE
            and owner.get("confirmation_result") != result
        ):
            self._add(
                (
                    "methodology liquidation confirmation differs from "
                    "its typed owner"
                ),
                f"methodology.{name}.liquidation_confirmation",
            )

    def _etf(self, price_direction: str | object) -> None:
        name = "etf_flow_relation"
        block = self._block(name)
        relation = self._value(block, name, "price_relation")
        observation = self._observation(
            self._value(block, name, "observation_id"),
            "farside_btc_etf",
        )
        if (
            relation is _UNAVAILABLE
            or observation is _UNAVAILABLE
            or price_direction is _UNAVAILABLE
        ):
            return
        flow_direction = observation["values"].get(
            "flow_direction", _UNAVAILABLE
        )
        if flow_direction not in {"inflow", "outflow", "flat"}:
            return
        try:
            expected = derive_etf_price_relation(
                str(price_direction),
                str(flow_direction),
                self.policy,
            )
        except (KeyError, TypeError, ValueError):
            return
        if relation != expected:
            self._add(
                (
                    "methodology.etf_flow_relation.price_relation must be "
                    "derived from the certified same-pivot price direction "
                    "and ETF flow direction"
                ),
                f"methodology.{name}.price_relation",
            )
            return
        owner = self._claim(self._value(block, name, "claim_id"))
        if (
            owner is not _UNAVAILABLE
            and owner.get("price_relation") != relation
        ):
            self._add(
                (
                    "ETF confirmation price_relation differs from the "
                    "deterministic truth table"
                ),
                f"methodology.{name}.price_relation",
            )

    def _account(self) -> None:
        name = "account_separation"
        block = self._block(name)
        checks = (
            (
                "main_priority",
                self.policy.get("main_account_priority", _UNAVAILABLE),
                "main account priority differs from constitution",
            ),
            (
                "maker_priority",
                self.policy.get("maker_priority", _UNAVAILABLE),
                "Maker priority differs from constitution",
            ),
            (
                "forced_consensus",
                False,
                (
                    "main account and Maker must not be forced into one "
                    "direction"
                ),
            ),
        )
        for field, expected, message in checks:
            value = self._value(block, name, field)
            if (
                value is not _UNAVAILABLE
                and expected is not _UNAVAILABLE
                and value != expected
            ):
                self._add(message, f"methodology.{name}.{field}")
        independence = self.policy.get("account_independence")
        expected_conflict = (
            independence.get("conflict_policy", _UNAVAILABLE)
            if isinstance(independence, dict)
            else _UNAVAILABLE
        )
        conflict = self._value(block, name, "conflict_policy")
        if (
            conflict is not _UNAVAILABLE
            and conflict != expected_conflict
        ):
            self._add(
                (
                    "account conflict policy must preserve independently "
                    "derived outputs"
                ),
                f"methodology.{name}.conflict_policy",
            )
        claim_bindings = (
            ("main_claim_id", "main_account_thesis", "main"),
            ("maker_claim_id", "maker_thesis", "maker"),
            ("main_regime_claim_id", "market_regime", "main"),
            ("maker_regime_claim_id", "market_regime", "maker"),
            (
                "main_counter_claim_id",
                "strongest_counterevidence",
                "main",
            ),
            (
                "maker_counter_claim_id",
                "strongest_counterevidence",
                "maker",
            ),
            (
                "main_invalidation_claim_id",
                "invalidation_path",
                "main",
            ),
            (
                "maker_invalidation_claim_id",
                "invalidation_path",
                "maker",
            ),
        )
        for field, claim_type, account in claim_bindings:
            claim = self._claim(self._value(block, name, field))
            if claim is _UNAVAILABLE:
                continue
            if claim.get("claim_type") != claim_type:
                self._add(
                    (
                        f"methodology.account_separation.{field} must "
                        f"reference claim type {claim_type}"
                    ),
                    f"methodology.{name}.{field}",
                )
            elif claim.get("account") != account:
                self._add(
                    (
                        f"methodology.account_separation.{field} must "
                        f"reference the {account} account"
                    ),
                    f"methodology.{name}.{field}",
                )

    def collect(self) -> MethodologyEvaluation:
        self._realization()
        price_direction = self._same_pivot()
        self._footprint()
        self._liquidity()
        self._etf(price_direction)
        self._account()

        if self.issues or self.blocked_paths:
            return MethodologyEvaluation(
                normalized=None,
                issues=tuple(self.issues),
            )
        try:
            normalized = normalize_methodology(
                self.payload,
                self.observations,
                self.claims,
                self.policy,
                profile_policy=self.profile_policy,
            )
        except (KeyError, TypeError, ValueError) as exc:
            message = str(exc)
            return MethodologyEvaluation(
                normalized=None,
                issues=(
                    MethodologyIssue(
                        code="methodology.parity_failed",
                        message=message,
                        path=_methodology_issue_path(message, "methodology"),
                    ),
                ),
            )
        return MethodologyEvaluation(normalized=normalized, issues=())


def evaluate_methodology(
    payload: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    *,
    profile_policy: dict[str, Any],
    mode: str,
    blocked_paths: tuple[str, ...] = (),
) -> MethodologyEvaluation:
    """Evaluate methodology in frozen legacy or vNext collect-all mode."""

    if mode == "fail_fast":
        return MethodologyEvaluation(
            normalized=normalize_methodology(
                payload,
                observations,
                claims,
                policy,
                profile_policy=profile_policy,
            ),
            issues=(),
        )
    if mode != "collect_all":
        raise ValueError(f"unsupported methodology evaluation mode: {mode}")
    return _MethodologyCollector(
        payload,
        observations,
        claims,
        policy,
        profile_policy=profile_policy,
        blocked_paths=tuple(blocked_paths),
    ).collect()


def collect_methodology_issues(
    payload: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    *,
    profile_policy: dict[str, Any],
    blocked_paths: tuple[str, ...] = (),
) -> tuple[MethodologyIssue, ...]:
    """Convenience API for consumers that need only the defect tuple."""

    return evaluate_methodology(
        payload,
        observations,
        claims,
        policy,
        profile_policy=profile_policy,
        mode="collect_all",
        blocked_paths=blocked_paths,
    ).issues


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
    tradingview = _only_source_observation("tradingview", observations)
    profile = tradingview.get("values", {}).get("volume_profile")
    profile_status = str(profile.get("status", "")) if isinstance(profile, dict) else ""
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
        if "代表入场" in text:
            raise ValueError(
                f"report projection {item_id}.text contains lint-forbidden representative entry wording"
            )
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
        if unit == "volume_profile_liquidity":
            profile_paths = {
                (item["observation_id"], item["path"])
                for item in normalized_values
                if item["observation_id"] == tradingview["id"]
                and item["path"].startswith("volume_profile.zones.")
            }
            if profile_status == "readable":
                has_lower = any(path.endswith(".lower_bound") for _, path in profile_paths)
                has_upper = any(path.endswith(".upper_bound") for _, path in profile_paths)
                if not (has_lower and has_upper):
                    raise ValueError(
                        f"report projection {item_id} must bind a user-drawn zone lower and upper bound"
                    )
            elif profile_status == "insufficient":
                if normalized_values:
                    raise ValueError(
                        f"report projection {item_id} cannot bind numeric liquidity locations when manual profile is insufficient"
                    )
                if "用户手绘" not in text or not re.search(r"证据不足|不可读|无法确认", text):
                    raise ValueError(
                        f"report projection {item_id} must disclose insufficient user-drawn profile evidence"
                    )
                if re.search(r"(?:POC|VAH|VAL|HVN|LVN|价值区)[^。；\n]{0,24}\d{4,}", text, re.I):
                    raise ValueError(
                        f"report projection {item_id} invents a forbidden profile location while evidence is insufficient"
                    )
        numeric_required = unit in NUMERIC_UNITS and not (
            unit == "volume_profile_liquidity" and profile_status == "insufficient"
        )
        if numeric_required and not normalized_values:
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
