"""The four production gates for the vNext daily-report workflow.

Every gate returns the complete defect set.  Validators do not fail on the
first problem, which prevents the repair-one-error/restart/find-next-error loop
that made the legacy workflow expensive and fragile.
"""

from __future__ import annotations

import json
import re
import struct
import zipfile
import zlib
from itertools import combinations
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .methodology import canonical_sha256, load_scoring_policy, sha256_file
from .plan_semantics import (
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
from .pretrade_gate import validate_pretrade_gate_contract
from .rate_expectation import (
    RateExpectationError,
    canonical_json_sha256 as rate_canonical_sha256,
    normalize_kalshi_payload,
    validate_cme_result,
    validate_rate_provenance,
)
from .reasoning_pipeline import validate_reasoning_pipeline
from .reasoning_submission import (
    derive_methodology_trigger_claim_ids,
    load_reasoning_submission_contract,
)
from .delivery_renderer import (
    ALLOWED_BACKENDS as WORD_QA_ALLOWED_BACKENDS,
    PASSED_WORD_QA_FIELDS,
    WORD_QA_SCHEMA,
    passed_word_qa_checklist_is_valid,
    passed_word_qa_run_paths_are_valid,
)
from .semantic_validation import (
    certified_chart_components,
    certified_orderflow_assessment,
    validate_reasoning_semantics,
    validate_visual_artifacts,
)
from outputs.report_lint import coupling_check


REQUIRED_SOURCES = (
    "BlockBeats",
    "Coinglass",
    "Exocharts",
    "FedWatch",
    "Farside",
    "TradingView",
)
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
TRADINGVIEW_TIMEFRAMES = ("1D", "4H", "1H", "15m")
SOURCE_ROLES = {
    "BlockBeats": "fundamental_context",
    "FedWatch": "macro_context_not_direction",
    "Farside": "spot_liquidity_confirmation",
    "Coinglass": "orderflow_and_liquidation",
    "Exocharts": "footprint_orderflow_confirmation",
    "TradingView": "chart_structure_and_user_drawn_profile",
}
MINIMUM_OBSERVATION_METRICS = {
    "BlockBeats": set(),
    "Coinglass": set(),
    "Exocharts": {"cross_check_result"},
    "FedWatch": set(),
    "Farside": set(),
    "TradingView": set(),
}
POLICY_SOURCE_KEYS = {
    "BlockBeats": "blockbeats",
    "Coinglass": "coinglass",
    "Exocharts": "exocharts",
    "FedWatch": "fedwatch",
    "Farside": "farside_btc_etf",
    "TradingView": "tradingview",
}
HIGH_IMPACT_CLAIMS = {"main_account_thesis", "maker_thesis"}
REQUIRED_CLAIM_TYPES = {
    "cannot_do",
    "chart_interpretation",
    "etf_confirmation",
    "fundamental_context",
    "fundamental_event_realization",
    "fundamental_price_realization",
    "liquidation_confirmation",
    "liquidity_hunt",
    "main_account_thesis",
    "maker_thesis",
    "market_regime",
    "orderflow_interpretation",
    "strongest_counterevidence",
    "invalidation_path",
}
CLAIM_ACCOUNT_SCOPES = {
    # Source interpretation is certified once and may be consumed by either
    # account.  It must never depend on an account-specific conclusion.
    "fundamental_context": {"shared"},
    "fundamental_event_realization": {"shared"},
    "fundamental_price_realization": {"shared"},
    "orderflow_interpretation": {"shared"},
    "chart_interpretation": {"shared"},
    "etf_confirmation": {"shared"},
    "liquidation_confirmation": {"shared"},
    "liquidity_hunt": {"shared"},
    # Decision control nodes are deliberately duplicated per account.  A
    # shared regime/counter/invalidation would silently couple the two loops.
    "market_regime": {"main", "maker"},
    "strongest_counterevidence": {"main", "maker"},
    "invalidation_path": {"main", "maker"},
    "main_account_thesis": {"main"},
    "maker_thesis": {"maker"},
    # Constitution: cannot-do is the Maker intraday closure, never a main-
    # account control surface.
    "cannot_do": {"maker"},
}
ACCOUNT_LOOP_CLAIM_TYPES = {
    "market_regime",
    "strongest_counterevidence",
    "invalidation_path",
}
ALLOWED_CLAIM_TYPES = set(REQUIRED_CLAIM_TYPES)
TRIGGER_CONTROL_CLAIM_TYPES = {"strongest_counterevidence", "invalidation_path"}
TRIGGER_EFFECT_BY_CLAIM_TYPE = {
    "strongest_counterevidence": "counter",
    "invalidation_path": "invalidate",
}
TRIGGER_OBSERVATION_FIELDS = {
    "TradingView": {
        "timeframes.1d.structure": {"bullish", "bearish", "range"},
        "timeframes.4h.structure": {"bullish", "bearish", "range"},
        "timeframes.1h.structure": {"bullish", "bearish", "range"},
        "timeframes.15m.structure": {"bullish", "bearish", "range"},
    },
    "Farside": {
        "flow_direction": {"inflow", "outflow", "flat"},
    },
    "Coinglass": {
        "final_direction": {"bullish", "bearish", "neutral", "mixed"},
        "pivot.anchor_reset": {True, False},
    },
    "Exocharts": {
        "cross_check_result": {"confirm", "weaken", "contradict"},
    },
}
TRIGGER_CLAIM_FIELDS = {
    "fundamental_price_realization": {
        "realization_state": {
            "realized",
            "partially_realized",
            "not_realized",
            "conflicted",
        },
    },
}
SOURCE_ROLE_CLAIM_OWNER = {
    "fundamental_context": "BlockBeats",
    "fundamental_price_realization": "BlockBeats",
    "etf_confirmation": "Farside",
    "chart_interpretation": "TradingView",
    "liquidation_confirmation": "Coinglass",
    "liquidity_hunt": "TradingView",
}
REQUIRED_SCENARIO_TYPES = {"base", "counter", "invalidation"}
CANNOT_DO_CODES = {"做多", "追多", "做空", "追空", "追多空"}
CONTINUITY_ACTIONS = {
    "new",
    "keep",
    "cancel_replace",
    "cancel",
    "observe",
    "reconcile_filled",
}
CONTINUITY_PRIOR_STATUSES = {
    "none",
    "pending",
    "open",
    "filled",
    "cancelled",
    "stopped",
    "expired",
}
REQUIRED_REPORT_SECTIONS = {
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
TRACEABLE_REPORT_SECTIONS = REQUIRED_REPORT_SECTIONS - {
    "opening_quote",
    "orderflow_label",
    "chart_label",
}
NON_ACTION_REPORT_SECTIONS = {
    "opening_quote",
    "fundamentals",
    "orderflow_label",
    "orderflow_text",
    "chart_label",
    "daily_line",
    "hourly_line",
    "support_resistance",
}
SECTION_REQUIRED_CLAIM_TYPES = {
    "cannot_do": {"cannot_do"},
    "fundamentals": {"main_account_thesis"},
    "orderflow_text": {"maker_thesis"},
    "interpretation": {"maker_thesis", "strongest_counterevidence"},
    "daily_line": {"main_account_thesis"},
    "hourly_line": {"liquidity_hunt"},
    "trend_confirmation": {"main_account_thesis", "maker_thesis"},
    "support_resistance": {"liquidity_hunt", "invalidation_path"},
    "strategy": {"main_account_thesis"},
    "maker_strategy": {"maker_thesis"},
    "maker_tp": {"maker_thesis"},
    "maker_sl": {"invalidation_path"},
    "defense_first": {"invalidation_path"},
    "defense_second": {"maker_thesis"},
    "defense_note": {"maker_thesis"},
    "defense_cancel": {"invalidation_path"},
    "independent_boundary": {"main_account_thesis", "maker_thesis"},
    "defense_core": {"maker_thesis", "invalidation_path"},
}
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


@dataclass(frozen=True)
class Defect:
    code: str
    message: str
    path: str = ""
    severity: str = "hard"


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    defects: tuple[Defect, ...]
    facts: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "defects": [asdict(item) for item in self.defects],
            "facts": self.facts,
        }


def _result(gate: str, defects: list[Defect], **facts: Any) -> GateResult:
    return GateResult(gate, not defects, tuple(defects), facts)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _contains_cjk(value: Any) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", _text(value)))


def _nested_value(payload: Any, field: str) -> tuple[bool, Any]:
    current = payload
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _typed_domain_contains(allowed_values: Any, value: Any) -> bool:
    """Match a closed JSON-domain value without bool/int coercion or hashing."""

    return any(
        type(value) is type(allowed) and value == allowed
        for allowed in allowed_values
    )


def _canonical_closed_string(value: Any) -> bool:
    """Require an exact, non-empty string for closed-schema identifiers."""

    return isinstance(value, str) and bool(value) and value == value.strip()


def _typed_domain_intersection(left: list[Any], right: list[Any]) -> list[Any]:
    """Intersect JSON-domain values without bool/int coercion or hashing."""

    return [value for value in left if _typed_domain_contains(right, value)]


def _reachable_trigger_owners(
    support_ids: list[Any],
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
) -> set[str]:
    reachable: set[str] = set()
    stack = [_text(item) for item in support_ids if _text(item)]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        if node_id in claims:
            stack.extend(
                _text(item)
                for item in claims[node_id].get("support_ids", [])
                if _text(item)
            )
    return reachable & (set(observations) | set(claims))


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
        defects.append(
            Defect(
                "claim.trigger_logic_missing",
                f"{claim_type}/{account} requires typed trigger_logic",
                path,
            )
        )
        return metadata
    if set(trigger) != {"mode", "effect", "clauses"}:
        defects.append(
            Defect(
                "claim.trigger_logic_schema",
                "trigger_logic must contain only mode, effect and clauses",
                path,
            )
        )
    raw_mode = trigger.get("mode")
    mode = _text(raw_mode)
    if (
        not _canonical_closed_string(raw_mode)
        or mode not in set(trigger_policy["allowed_modes"])
    ):
        defects.append(Defect("claim.trigger_mode_invalid", "trigger mode must be all or any", f"{path}.mode"))
    if claim_type == "invalidation_path" and mode != trigger_policy["invalidation_mode"]:
        defects.append(
            Defect(
                "claim.invalidation_trigger_mode",
                "invalidation_path requires all typed clauses; one variable cannot invalidate the account thesis",
                f"{path}.mode",
            )
        )
    expected_effect = trigger_policy["claim_effects"][claim_type]
    if trigger.get("effect") != expected_effect:
        defects.append(
            Defect(
                "claim.trigger_effect_invalid",
                f"{claim_type} trigger effect must be {expected_effect}",
                f"{path}.effect",
            )
        )
    clauses = trigger.get("clauses")
    minimum_clause_count = int(trigger_policy["minimum_clause_count"])
    if not isinstance(clauses, list) or len(clauses) < minimum_clause_count:
        defects.append(
            Defect(
                "claim.trigger_clauses_thin",
                    f"counter/invalidation trigger requires at least {minimum_clause_count} typed clauses",
                f"{path}.clauses",
            )
        )
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
            defects.append(
                Defect(
                    "claim.trigger_clause_schema",
                    "trigger operator must be an exact closed-schema string",
                    f"{clause_path}.operator",
                )
            )
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
            defects.append(
                Defect(
                    "claim.trigger_clause_schema",
                    "trigger clause must use the exact typed schema for becomes, equals_at_trigger or one_of_at_trigger",
                    clause_path,
                )
            )
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
            defects.append(
                Defect(
                    "claim.trigger_identifier_noncanonical",
                    "trigger owner_type, owner_id and field must be exact closed-schema strings",
                    clause_path,
                )
            )
            continue
        source = ""
        owner_claim_type = ""
        if owner_id not in reachable:
            defects.append(
                Defect(
                    "claim.trigger_owner_unbound",
                    "trigger owner must be reachable from the claim support DAG",
                    f"{clause_path}.owner_id",
                )
            )
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
                defects.append(
                    Defect(
                        "claim.trigger_cross_account",
                        "trigger clause cannot consume the other account",
                        f"{clause_path}.owner_id",
                    )
                )
            if owner_claim_type:
                metadata["claim_types"].add(owner_claim_type)
        else:
            defects.append(
                Defect(
                    "claim.trigger_owner_type_invalid",
                    "trigger owner_type must be observation or claim",
                    f"{clause_path}.owner_type",
                )
            )
        if not allowed_values:
            defects.append(
                Defect(
                    "claim.trigger_field_forbidden",
                    "trigger field is not an approved typed control owner",
                    f"{clause_path}.field",
                )
            )
            continue
        if not current_found:
            defects.append(
                Defect(
                    "claim.trigger_field_missing",
                    "trigger field is absent from the certified owner",
                    f"{clause_path}.field",
                )
            )
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
            defects.append(
                Defect(
                    "claim.trigger_target_invalid",
                    "trigger target shape, exact type, or value is outside the typed field domain",
                    clause_path,
                )
            )
        if (
            operator == "becomes"
            and current_found
            and len(targets) == 1
            and type(targets[0]) is type(current_value)
            and targets[0] == current_value
        ):
            defects.append(
                Defect(
                    "claim.trigger_no_state_change",
                    "becomes must target a state different from the current certified value",
                    clause_path,
                )
            )
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
                        defects.append(
                            Defect(
                                "claim.trigger_all_clause_unsatisfiable",
                                "all-mode clauses for the same typed field must retain at least one jointly reachable target state",
                                clause_path,
                            )
                        )
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
        defects.append(
            Defect(
                "claim.trigger_already_satisfied",
                "future trigger is already satisfied by current certified state under its mode",
                f"{path}.clauses",
            )
        )
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
        defects.append(
            Defect(
                "claim.current_basis_schema",
                "counter/invalidation claims require the exact typed current_basis schema",
                path,
            )
        )
        return metadata
    raw_mode = basis.get("mode")
    mode = _text(raw_mode)
    if (
        not _canonical_closed_string(raw_mode)
        or mode not in set(policy.get("allowed_modes") or [])
    ):
        defects.append(
            Defect(
                "claim.current_basis_mode",
                "current_basis mode is outside the closed authority vocabulary",
                f"{path}.mode",
            )
        )
    clauses = basis.get("clauses")
    minimum = int(policy.get("minimum_clause_count") or 0)
    if not isinstance(clauses, list) or len(clauses) < minimum:
        defects.append(
            Defect(
                "claim.current_basis_clauses_thin",
                f"current_basis requires at least {minimum} typed current-value clauses",
                f"{path}.clauses",
            )
        )
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
            defects.append(
                Defect(
                    "claim.current_basis_clause_schema",
                    "current_basis clause differs from the exact typed field set",
                    clause_path,
                )
            )
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
            defects.append(
                Defect(
                    "claim.current_basis_identifier_noncanonical",
                    "current_basis identifiers must be exact closed-schema strings",
                    clause_path,
                )
            )
            continue
        if raw_operator not in allowed_operators:
            defects.append(
                Defect(
                    "claim.current_basis_operator",
                    "current_basis operator must be equals",
                    f"{clause_path}.operator",
                )
            )
        if owner_id not in reachable:
            defects.append(
                Defect(
                    "claim.current_basis_owner_unbound",
                    "current_basis owner must be reachable from the claim support DAG",
                    f"{clause_path}.owner_id",
                )
            )
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
                defects.append(
                    Defect(
                        "claim.current_basis_cross_account",
                        "current_basis cannot consume the other account",
                        f"{clause_path}.owner_id",
                    )
                )
            if owner_claim_type:
                metadata["claim_types"].add(owner_claim_type)
        else:
            defects.append(
                Defect(
                    "claim.current_basis_owner_type",
                    "current_basis owner_type must be observation or claim",
                    f"{clause_path}.owner_type",
                )
            )
        if not allowed_values:
            defects.append(
                Defect(
                    "claim.current_basis_field_forbidden",
                    "current_basis field is outside the closed typed-owner policy",
                    f"{clause_path}.field",
                )
            )
        elif not owner_found:
            defects.append(
                Defect(
                    "claim.current_basis_field_missing",
                    "current_basis field is absent from the certified owner",
                    f"{clause_path}.field",
                )
            )
        value = clause.get("value")
        if not _typed_domain_contains(allowed_values, value):
            defects.append(
                Defect(
                    "claim.current_basis_value_domain",
                    "current_basis value is outside the typed field domain",
                    f"{clause_path}.value",
                )
            )
        if owner_found and not (
            type(value) is type(current_value) and value == current_value
        ):
            defects.append(
                Defect(
                    "claim.current_basis_value_drift",
                    "current_basis value must mechanically equal the current certified owner field",
                    f"{clause_path}.value",
                )
            )
        signature = (owner_type, owner_id, field)
        if signature in seen:
            defects.append(
                Defect(
                    "claim.current_basis_clause_duplicate",
                    "duplicate current_basis typed owner",
                    clause_path,
                )
            )
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
                    defects.append(
                        Defect(
                            "claim.current_basis_relative_reference",
                            "Exocharts polarity requires exactly one reachable typed Coinglass direction",
                            clause_path,
                        )
                    )
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
            defects.append(
                Defect(
                    "claim.current_basis_subject_direction",
                    "current_basis requires a certified long/short/neutral/observe direction from the same account thesis",
                    path,
                )
            )
        else:
            metadata["polarities"].append(polarity.as_dict())
            if (
                claim.get("claim_type") == "strongest_counterevidence"
                and polarity.effect
                != polarity_policy.get("strongest_counter_required_effect")
            ):
                defects.append(
                    Defect(
                        "claim.current_basis_polarity",
                        "strongest counterevidence may contain only typed clauses that oppose the current account thesis",
                        clause_path,
                    )
                )
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
            defects.append(
                Defect(
                    "claim.current_basis_counter_direction_incoherent",
                    "a non-directional thesis requires one coherent directional alternative in its strongest counter",
                    path,
                )
            )
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
        defects.append(
            Defect(
                "claim.structural_noise_buffer_schema",
                "invalidation_path requires the exact sealed structural-noise buffer schema",
                path,
            )
        )
        return
    if (
        value.get("schema_version") != buffer_policy.get("schema_version")
        or value.get("method_code") != buffer_policy.get("method_code")
        or value.get("risk_budget_input_used") is not False
        or buffer_policy.get("risk_budget_input_used") is not False
        or buffer_policy.get("compiler_may_infer") is not False
    ):
        defects.append(
            Defect(
                "claim.structural_noise_buffer_method",
                "structural-noise buffer must be selected in reasoning before risk math and may not consume the risk budget",
                path,
            )
        )
    observation_id = _text(value.get("observation_id"))
    observation = observations.get(observation_id) or {}
    reachable = _reachable_trigger_owners(
        list(claim.get("support_ids") or []), observations, claims
    )
    if (
        observation.get("source") != buffer_policy.get("source")
        or observation_id not in reachable
    ):
        defects.append(
            Defect(
                "claim.structural_noise_buffer_owner",
                "structural-noise buffer must bind a reachable current-run TradingView observation",
                f"{path}.observation_id",
            )
        )
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
        defects.append(
            Defect(
                "claim.structural_noise_buffer_visual_binding",
                "structural-noise basis must bind a cited current-run TradingView image",
                f"{path}.visual_evidence_ref",
            )
        )
    timeframe = _text(value.get("timeframe")).lower()
    allowed_timeframes = {
        _text(item).lower() for item in stop_policy.get("allowed_timeframes") or []
    }
    if not timeframe or timeframe not in allowed_timeframes:
        defects.append(
            Defect(
                "claim.structural_noise_buffer_timeframe",
                "structural-noise buffer timeframe is outside the account stop policy",
                f"{path}.timeframe",
            )
        )
    status = _text(value.get("status"))
    if status not in set(buffer_policy.get("allowed_statuses") or []):
        defects.append(
            Defect(
                "claim.structural_noise_buffer_status",
                "structural-noise status is outside the closed authority vocabulary",
                f"{path}.status",
            )
        )
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
            defects.append(
                Defect(
                    "claim.structural_noise_buffer_insufficient_reason",
                    "insufficient structural noise requires a closed reason code",
                    f"{path}.insufficiency_reason_code",
                )
            )
        if (
            direction in non_directional_subjects
            and value.get("insufficiency_reason_code") != non_directional_reason
        ) or (
            direction not in non_directional_subjects
            and value.get("insufficiency_reason_code") == non_directional_reason
        ):
            defects.append(
                Defect(
                    "claim.structural_noise_buffer_direction_applicability",
                    "non-directional theses must use the closed non-directional N/A reason; directional theses may not use it",
                    f"{path}.insufficiency_reason_code",
                )
            )
        null_fields = set(
            buffer_policy.get("insufficient_numeric_fields_must_be_null") or []
        ) | {"anchor_kind", "anchor_source_field"}
        if any(value.get(field) is not None for field in null_fields):
            defects.append(
                Defect(
                    "claim.structural_noise_buffer_insufficient_fabrication",
                    "an insufficient or non-directional noise basis may not fabricate an anchor, boundary or distance",
                    path,
                )
            )
        return
    if direction in non_directional_subjects:
        defects.append(
            Defect(
                "claim.structural_noise_buffer_direction_applicability",
                "a non-directional thesis cannot certify a directional structural stop; use the closed N/A insufficient result",
                f"{path}.status",
            )
        )
        return
    if value.get("insufficiency_reason_code") is not None:
        defects.append(
            Defect(
                "claim.structural_noise_buffer_certified_reason",
                "a certified structural-noise basis must not carry an insufficiency reason",
                f"{path}.insufficiency_reason_code",
            )
        )
    anchor_kind = _text(value.get("anchor_kind"))
    anchor_source_field = _text(value.get("anchor_source_field"))
    if anchor_kind not in set(stop_policy.get("allowed_anchor_kinds") or []) or not _matches_policy_path(
        anchor_source_field,
        list(stop_policy.get("allowed_anchor_source_fields") or []),
    ):
        defects.append(
            Defect(
                "claim.structural_noise_buffer_anchor_contract",
                "reasoning-owned noise anchor is outside the structural-stop authority",
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
                "claim.structural_noise_buffer_anchor_direction",
                "reasoning-owned noise anchor does not face outward for the same-account thesis",
                f"{path}.anchor_kind",
            )
        )
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
        defects.append(
            Defect(
                "claim.structural_noise_buffer_anchor_value",
                "reasoning-owned anchor_price must equal its cited TradingView field",
                f"{path}.anchor_price",
            )
        )
    cited_metric_path = anchor_source_field.removeprefix("metrics.")
    if cited_metric_path and not any(
        _text(item.get("evidence_ref")) == visual_evidence_ref
        and cited_metric_path in set(item.get("metric_paths") or [])
        for item in visual_citations
    ):
        defects.append(
            Defect(
                "claim.structural_noise_buffer_anchor_visual_citation",
                "the selected image must cite the exact TradingView anchor field",
                f"{path}.visual_evidence_ref",
            )
        )
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
        defects.append(
            Defect(
                "claim.structural_noise_buffer_timeframe_binding",
                "structural-noise timeframe must equal the cited anchor zone timeframe",
                f"{path}.timeframe",
            )
        )
    price_distance = _json_number(value.get("price_distance"))
    if price_distance is None or price_distance <= 0:
        defects.append(
            Defect(
                "claim.structural_noise_buffer_distance",
                "structural-noise buffer price_distance must be a positive Arabic-numeric distance",
                f"{path}.price_distance",
            )
        )
    noise_outer_boundary = _json_number(value.get("noise_outer_boundary"))
    if noise_outer_boundary is None or noise_outer_boundary <= 0:
        defects.append(
            Defect(
                "claim.structural_noise_buffer_boundary",
                "certified noise_outer_boundary must be a positive visible price",
                f"{path}.noise_outer_boundary",
            )
        )
    envelope_is_outward = structural_noise_stop_is_outside(
        direction=direction,
        anchor_price=anchor_price,
        noise_outer_boundary=noise_outer_boundary,
        price_distance=price_distance,
    )
    if not envelope_is_outward:
        defects.append(
            Defect(
                "claim.structural_noise_buffer_economic_insufficiency",
                "the reasoning-owned stop distance must place the stop strictly outside the visible noise envelope",
                path,
            )
        )


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


def _is_iso_datetime(value: Any) -> bool:
    return _parse_iso_datetime(value) is not None


def _parse_iso_datetime(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _json_number(value: Any) -> Decimal | None:
    """Return a finite JSON number without accepting numeric strings/bools."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    return _number(value)


def _canonical_positive_decimal_string(value: Any) -> Decimal | None:
    """Decode the authority's unique, positive fixed-point string encoding."""

    if not isinstance(value, str) or re.fullmatch(
        r"^(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$",
        value,
    ) is None:
        return None
    result = _number(value)
    if result is None or result <= 0:
        return None
    if format(result.normalize(), "f") != value:
        return None
    return result


def _decimal_matches(
    actual: Decimal | None,
    expected: Decimal | None,
    *,
    tolerance: Decimal = Decimal("0.00000001"),
) -> bool:
    return (
        actual is not None
        and expected is not None
        and abs(actual - expected) <= tolerance
    )


def _resolve_concrete_value_path(value: Any, path: str) -> Any:
    """Resolve a closed dotted path with concrete zero-based array indexes."""

    current = value
    for part in path.split("."):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?", part)
        if match is None or not isinstance(current, dict):
            raise ValueError("source field is not a concrete certified value path")
        key, raw_index = match.groups()
        if key not in current:
            raise ValueError("source field does not exist in the certified observation")
        current = current[key]
        if raw_index is not None:
            index = int(raw_index)
            if not isinstance(current, list) or index >= len(current):
                raise ValueError("source field array index is outside the certified observation")
            current = current[index]
    return current


def _matches_policy_path(path: str, patterns: list[Any]) -> bool:
    for pattern_value in patterns:
        pattern = re.escape(_text(pattern_value)).replace(r"\[\*\]", r"\[\d+\]")
        if re.fullmatch(pattern, path):
            return True
    return False


def _round_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def maker_fill_scenarios(
    *,
    entries: list[Decimal],
    allocations: list[Decimal],
    direction: str,
    stop: Decimal,
    tp1: Decimal,
    tp2: Decimal,
    leverage: Decimal,
) -> list[dict[str, str]]:
    scenarios: list[dict[str, str]] = []
    for size in range(1, len(entries) + 1):
        for indexes in combinations(range(len(entries)), size):
            weight = sum((allocations[index] for index in indexes), Decimal("0"))
            weighted_entry = sum(
                (entries[index] * allocations[index] for index in indexes),
                Decimal("0"),
            ) / weight
            risk = (
                weighted_entry - stop
                if direction == "long"
                else stop - weighted_entry
            )
            reward = (
                tp1 - weighted_entry
                if direction == "long"
                else weighted_entry - tp1
            )
            reward_tp2 = (
                tp2 - weighted_entry
                if direction == "long"
                else weighted_entry - tp2
            )
            if risk <= 0 or reward <= 0 or reward_tp2 <= reward:
                raise ValueError(
                    "entry/stop/tp1/tp2 geometry conflicts with direction"
                )
            scenarios.append(
                {
                    "risk_scenario_id": "fill-" + "-".join(
                        str(index + 1) for index in indexes
                    ),
                    "filled_level_indexes": [index + 1 for index in indexes],
                    "filled_levels": ",".join(str(index + 1) for index in indexes),
                    "entry": format(weighted_entry.normalize(), "f"),
                    "rr_to_tp1": format((reward / risk).normalize(), "f"),
                    "rr_to_tp2": format((reward_tp2 / risk).normalize(), "f"),
                    "nominal_risk_pct": format(
                        (risk / weighted_entry * leverage * Decimal("100")).normalize(),
                        "f",
                    ),
                }
            )
    return scenarios


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
    required = {
        "schema_version",
        "claim_effects",
        "allowed_modes",
        "invalidation_mode",
        "minimum_clause_count",
        "allowed_operators",
        "observation_fields",
        "claim_fields",
        "account_source_requirements",
        "opposite_state_required",
        "non_directional_subject_directions",
        "non_directional_future_direction_fields",
        "future_direction_value_map",
        "relative_direction_observation_fields",
        "future_trigger_current_truth_quantifier_by_mode",
        "non_directional_future_requires_one_coherent_alternative_direction",
        "non_directional_counter_future_must_match_current_counter_direction",
        "any_clause_requires_independent_counter_polarity",
        "all_directional_clauses_must_match_counter_polarity",
        "one_of_direction_targets_must_have_single_polarity",
        "exocharts_confirm_counter_policy",
        "scenario_control_binding",
        "compiler_may_infer_missing_conditions",
    }
    if set(trigger) != required:
        raise ValueError("account_trigger_logic policy has an invalid field set")
    if trigger.get("schema_version") != "account-trigger-logic-v5":
        raise ValueError("account_trigger_logic policy version is unsupported")
    if trigger.get("claim_effects") != TRIGGER_EFFECT_BY_CLAIM_TYPE:
        raise ValueError("account_trigger_logic claim effects are invalid")
    if trigger.get("compiler_may_infer_missing_conditions") is not False:
        raise ValueError("compiler may not infer missing counter/invalidation conditions")
    if trigger.get("exocharts_confirm_counter_policy") != (
        "confirm_is_valid_only_in_all_mode_with_one_canonical_coinglass_final_direction_reference"
    ):
        raise ValueError("Exocharts confirm counter polarity policy is invalid")
    if trigger.get("opposite_state_required") is not True:
        raise ValueError("account trigger logic must require the typed opposite state")
    if trigger.get("non_directional_subject_directions") != ["neutral", "observe"]:
        raise ValueError("account trigger logic non-directional subjects are invalid")
    if trigger.get("non_directional_future_requires_one_coherent_alternative_direction") is not True:
        raise ValueError("non-directional future triggers must require one coherent direction")
    if trigger.get("non_directional_counter_future_must_match_current_counter_direction") is not True:
        raise ValueError("non-directional counter triggers must preserve their current counter direction")
    if trigger.get("any_clause_requires_independent_counter_polarity") is not True:
        raise ValueError("any trigger clauses must be independently sufficient typed counters")
    if trigger.get("all_directional_clauses_must_match_counter_polarity") is not True:
        raise ValueError("all trigger directional clauses must preserve one counter polarity")
    if trigger.get("one_of_direction_targets_must_have_single_polarity") is not True:
        raise ValueError("one-of future direction targets must have one polarity")
    if trigger.get("future_trigger_current_truth_quantifier_by_mode") != {
        "all": "all",
        "any": "any",
    }:
        raise ValueError("future trigger current truth quantifiers are invalid")
    expected_relative = {
        "Exocharts": {
            "cross_check_result": {
                "reference_source": "Coinglass",
                "reference_field": "final_direction",
                "reference_operator_policy": {
                    "target_equals_current": "equals_at_trigger",
                    "target_differs_from_current": "becomes",
                },
                "relative_operator": "equals_at_trigger",
                "relation_map": {
                    "confirm": "same_as_reference",
                    "contradict": "opposite_of_reference",
                    "weaken": "neutral",
                },
            }
        }
    }
    if trigger.get("relative_direction_observation_fields") != expected_relative:
        raise ValueError("relative future-direction policy is invalid")
    expected_scenario_binding = {
        "schema_version": "scenario-control-binding-v2",
        "ownership_contract_schema_version": "scenario-ownership-v1",
        "compiler_condition_source_by_type": {
            "base": "bound_owner_claim.typed_state",
            "counter": "bound_owner_claim.trigger_logic",
            "invalidation": "bound_owner_claim.trigger_logic",
        },
        "compiler_transition_source": "scenario_ownership.transition_code_by_type",
        "methodology_trigger_claim_ids_source": (
            "bound_owner_claim.direct_support_claim_ids"
        ),
        "methodology_trigger_order": "owner_support_order_first_occurrence",
        "methodology_trigger_observation_ids_excluded": True,
        "methodology_trigger_owner_self_reference_allowed": False,
        "producer_free_prose_allowed": False,
        "execution_lifecycle_owner": "decision_and_continuity",
    }
    if trigger.get("scenario_control_binding") != expected_scenario_binding:
        raise ValueError("scenario control binding policy is invalid")
    return trigger


def _current_basis_policy(root: Path | None) -> dict[str, Any]:
    policy_root = root or Path(__file__).resolve().parents[1]
    policy = load_scoring_policy(root=policy_root)
    current_basis = (
        (policy.get("gold_methodology") or {}).get("account_current_basis")
    )
    if not isinstance(current_basis, dict):
        raise ValueError("account_current_basis policy must be an object")
    if set(current_basis) != ACCOUNT_CURRENT_BASIS_POLICY_FIELDS:
        raise ValueError("account_current_basis policy has an invalid field set")
    if current_basis.get("schema_version") != "account-current-basis-v2":
        raise ValueError("account_current_basis policy version is unsupported")
    if current_basis.get("compiler_may_infer_missing_current_basis") is not False:
        raise ValueError("compiler may not infer missing current counter basis")
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


def _record_paths(source_payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = source_payload.get("artifacts")
    if not isinstance(records, list):
        single = source_payload.get("artifact")
        records = [single] if isinstance(single, dict) else []
    return [item for item in records if isinstance(item, dict)]


def _validate_file_record(
    record: dict[str, Any],
    *,
    path: str,
    defects: list[Defect],
    root: Path | None,
) -> None:
    relative = _text(record.get("path"))
    digest = _text(record.get("sha256"))
    size = record.get("bytes")
    if not relative:
        defects.append(Defect("artifact.path_missing", "artifact path is required", path))
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        defects.append(Defect("artifact.hash_invalid", "artifact sha256 is invalid", path))
    if not isinstance(size, int) or size <= 0:
        defects.append(Defect("artifact.bytes_invalid", "artifact byte count must be positive", path))
    if root is None or not relative:
        return
    try:
        target = (root / relative).resolve()
        target.relative_to(root.resolve())
    except (ValueError, OSError):
        defects.append(Defect("artifact.path_escape", "artifact path escapes the evidence root", path))
        return
    if not target.is_file():
        defects.append(Defect("artifact.file_missing", "artifact file is missing", path))
        return
    if re.fullmatch(r"[0-9a-f]{64}", digest) and sha256_file(target) != digest:
        defects.append(Defect("artifact.hash_mismatch", "artifact bytes differ from recorded sha256", path))
    if isinstance(size, int) and target.stat().st_size != size:
        defects.append(Defect("artifact.size_mismatch", "artifact bytes differ from recorded size", path))


def evidence_snapshot_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("snapshot_sha256", None)
    return canonical_sha256(clean)


def _validate_rate_expectation_source(
    payload: dict[str, Any],
    *,
    root: Path | None,
    defects: list[Defect],
) -> None:
    """Certify v2 CME-primary or Kalshi-Plan-C provenance and replayability."""

    source = ((payload.get("sources") or {}).get("FedWatch") or {})
    path = "sources.FedWatch"
    records = _record_paths(source)
    by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        name = Path(_text(record.get("path"))).name
        if name in by_name:
            defects.append(
                Defect(
                    "fedwatch.artifact_name_duplicate",
                    f"FedWatch artifact basename is duplicated: {name}",
                    f"{path}.artifacts",
                )
            )
        by_name[name] = record
    if root is None:
        defects.append(
            Defect(
                "fedwatch.provider_root_missing",
                "evidence v2 provider certification requires an artifact root",
                path,
            )
        )
        return

    try:
        contract_path = root / "data_sources" / "rate_expectation_provider_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if not isinstance(contract, dict):
            raise ValueError("provider contract must be an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        defects.append(
            Defect(
                "fedwatch.provider_contract_invalid",
                f"rate-expectation provider contract is unreadable: {exc}",
                "data_sources/rate_expectation_provider_contract.json",
            )
        )
        return

    def load_artifact(name: str) -> dict[str, Any]:
        record = by_name.get(name)
        if record is None:
            raise RateExpectationError(f"required artifact is missing: {name}")
        target = (root / _text(record.get("path"))).resolve()
        target.relative_to(root.resolve())
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RateExpectationError(f"artifact must be a JSON object: {name}")
        return value

    try:
        provenance = load_artifact("rate_expectation_provenance.json")
        validated_meta = validate_rate_provenance(
            provenance,
            contract,
            capture_run_id=_text(payload.get("capture_run_id")),
            artifact_names=set(by_name),
        )
        expected_provenance_keys = {
            "schema_version",
            "logical_source",
            "capture_run_id",
            "selection_mode",
            "provider_id",
            "series_ticker",
            "fallback_reason_code",
            "primary_attempt_artifact_path",
            "raw_artifact_paths",
            "normalized_artifact_path",
            "selected_artifact_paths",
            "provenance_sha256",
        }
        if set(provenance) != expected_provenance_keys:
            raise RateExpectationError("provider provenance fields differ from contract")
        if (
            provenance.get("schema_version") != contract["provenance_schema_version"]
            or provenance.get("logical_source") != contract["logical_source"]
            or provenance.get("capture_run_id") != payload.get("capture_run_id")
            or provenance.get("provenance_sha256")
            != rate_canonical_sha256(provenance, exclude="provenance_sha256")
        ):
            raise RateExpectationError("provider provenance identity or hash is invalid")
        mode = _text(provenance.get("selection_mode"))
        selection = (contract.get("selection_modes") or {}).get(mode)
        if not isinstance(selection, dict):
            raise RateExpectationError("provider selection_mode is unsupported")
        if (
            provenance.get("provider_id") != selection.get("provider_id")
            or provenance.get("series_ticker") != selection.get("series_ticker")
            or provenance.get("primary_attempt_artifact_path")
            != "cme_fedwatch_result.json"
        ):
            raise RateExpectationError("provider provenance differs from selected contract mode")

        expected_meta = {
            "provider_id": selection.get("provider_id"),
            "selection_mode": mode,
            "series_ticker": selection.get("series_ticker"),
            "acquisition_channel": selection.get("acquisition_channel"),
            "method_class": selection.get("method_class"),
            "method_equivalence": selection.get("method_equivalence"),
            "sample_source_class": selection.get("sample_source_class"),
            "quote_basis_code": selection.get("quote_basis_code"),
            "normalization_method_code": selection.get("normalization_method_code"),
            "fallback_reason_code": provenance.get("fallback_reason_code"),
            "provenance_sha256": provenance.get("provenance_sha256"),
        }
        if expected_meta != validated_meta or source.get("meta") != validated_meta:
            raise RateExpectationError("FedWatch source meta differs from sealed provider provenance")

        cme_result = load_artifact("cme_fedwatch_result.json")
        if cme_result.get("capture_run_id") != payload.get("capture_run_id"):
            raise RateExpectationError("CME result capture_run_id differs from evidence")
        if mode == "cme_primary":
            expected_names = {
                "fedwatch.png",
                "cme_fedwatch_result.json",
                "rate_expectation_provenance.json",
            }
            if set(by_name) != expected_names:
                raise RateExpectationError("CME primary artifacts differ from the exact provider set")
            if (
                provenance.get("fallback_reason_code") != "none"
                or provenance.get("raw_artifact_paths") != []
                or provenance.get("normalized_artifact_path") is not None
                or provenance.get("selected_artifact_paths")
                != ["cme_fedwatch_result.json", "fedwatch.png"]
            ):
                raise RateExpectationError("CME primary provenance contains fallback lineage")
            validate_cme_result(cme_result, contract, require_failed=False)
            screenshot = cme_result["output"]
            screenshot_record = by_name["fedwatch.png"]
            if (
                Path(_text(screenshot.get("path"))).name != "fedwatch.png"
                or screenshot.get("sha256") != screenshot_record.get("sha256")
                or screenshot.get("bytes") != screenshot_record.get("bytes")
            ):
                raise RateExpectationError("CME screenshot binding differs from immutable artifact")
            provider_observed_at = _parse_iso_datetime(cme_result.get("completed_at"))
        elif mode == "kalshi_plan_c_fallback":
            expected_names = {
                "cme_fedwatch_result.json",
                "kalshi_feddecision_raw.json",
                "fedwatch.json",
                "rate_expectation_provenance.json",
            }
            if set(by_name) != expected_names:
                raise RateExpectationError("Plan C artifacts differ from the exact provider set")
            if (
                provenance.get("fallback_reason_code")
                not in contract["cme"]["eligible_fallback_codes"]
                or provenance.get("raw_artifact_paths")
                != ["kalshi_feddecision_raw.json"]
                or provenance.get("normalized_artifact_path") != "fedwatch.json"
                or provenance.get("selected_artifact_paths")
                != [
                    "cme_fedwatch_result.json",
                    "fedwatch.json",
                    "kalshi_feddecision_raw.json",
                ]
            ):
                raise RateExpectationError("Plan C provenance lineage is incomplete or unordered")
            validate_cme_result(cme_result, contract, require_failed=True)
            if provenance.get("fallback_reason_code") != cme_result.get("defect_code"):
                raise RateExpectationError("Plan C fallback reason differs from sealed CME failure")
            raw = load_artifact("kalshi_feddecision_raw.json")
            normalized = load_artifact("fedwatch.json")
            replayed = normalize_kalshi_payload(contract, cme_result, raw)
            if normalized != replayed:
                raise RateExpectationError("fedwatch.json differs from independent raw replay")
            if normalized.get("metrics") != replayed.get("metrics"):
                raise RateExpectationError("normalized FedWatch metrics differ from raw replay")
            provider_observed_at = _parse_iso_datetime(raw.get("retrieved_at"))
        else:
            raise RateExpectationError("provider selection_mode is unsupported")
        captured_at = _parse_iso_datetime(payload.get("captured_at"))
        if provider_observed_at is None or captured_at is None:
            raise RateExpectationError("provider/capture time binding is invalid")
        provider_age = captured_at - provider_observed_at
        if provider_age < timedelta(minutes=-5) or provider_age > timedelta(hours=2):
            raise RateExpectationError("provider observation time is outside the capture window")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        RateExpectationError,
    ) as exc:
        defects.append(
            Defect(
                "fedwatch.provider_integrity",
                f"rate-expectation provider certification failed: {exc}",
                path,
            )
        )


def evaluate_evidence(
    payload: dict[str, Any],
    *,
    root: Path | None = None,
    expected_contract_sha256: str | None = None,
) -> GateResult:
    defects: list[Defect] = []
    evidence_schema = payload.get("schema_version")
    if evidence_schema not in {"evidence-snapshot-v1", "evidence-snapshot-v2"}:
        defects.append(
            Defect(
                "schema.invalid",
                "expected evidence-snapshot-v1 or evidence-snapshot-v2",
                "schema_version",
            )
        )
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", _text(payload.get("trading_date"))):
        defects.append(Defect("date.invalid", "trading_date must be ISO YYYY-MM-DD", "trading_date"))
    if payload.get("slot") not in {"morning", "midday", "evening"}:
        defects.append(Defect("slot.invalid", "slot is invalid", "slot"))
    captured_at = _parse_iso_datetime(payload.get("captured_at"))
    if captured_at is None:
        defects.append(Defect("captured_at.invalid", "captured_at must be an ISO datetime", "captured_at"))
    elif captured_at.astimezone(timezone(timedelta(hours=8))).date().isoformat() != payload.get("trading_date"):
        defects.append(Defect("captured_at.date_mismatch", "captured_at must belong to the trading date in Asia/Shanghai", "captured_at"))
    if expected_contract_sha256 is not None and payload.get("evidence_contract_sha256") != expected_contract_sha256:
        defects.append(Defect("binding.evidence_contract", "evidence snapshot is not bound to the capture contract", "evidence_contract_sha256"))

    sources = payload.get("sources")
    if not isinstance(sources, dict):
        defects.append(Defect("sources.invalid", "sources must be an object", "sources"))
        sources = {}
    missing = [name for name in REQUIRED_SOURCES if name not in sources]
    extra = [name for name in sources if name not in REQUIRED_SOURCES]
    for name in missing:
        defects.append(Defect("source.missing", f"required source is missing: {name}", f"sources.{name}"))
    for name in extra:
        defects.append(Defect("source.unexpected", f"unexpected source: {name}", f"sources.{name}"))

    artifact_paths: list[str] = []
    for name in REQUIRED_SOURCES:
        source = sources.get(name)
        path = f"sources.{name}"
        if not isinstance(source, dict):
            continue
        if source.get("status") != "valid":
            defects.append(Defect("source.invalid", f"{name} status must be valid", f"{path}.status"))
        if source.get("role") != SOURCE_ROLES[name]:
            defects.append(
                Defect(
                    "source.role_drift",
                    f"{name} role must be {SOURCE_ROLES[name]}",
                    f"{path}.role",
                )
            )
        observed_at = _parse_iso_datetime(source.get("observed_at"))
        if observed_at is None:
            defects.append(Defect("source.time_invalid", f"{name} observed_at is invalid", f"{path}.observed_at"))
        elif captured_at is not None:
            age = captured_at - observed_at
            if age < timedelta(minutes=-5) or age > timedelta(hours=2):
                defects.append(Defect("source.capture_time_drift", f"{name} artifact observation time is outside the capture window", f"{path}.observed_at"))
        records = _record_paths(source)
        if not records:
            defects.append(Defect("source.artifact_missing", f"{name} requires evidence artifacts", path))
        for index, record in enumerate(records):
            _validate_file_record(record, path=f"{path}.artifacts[{index}]", defects=defects, root=root)
            relative = _text(record.get("path"))
            if relative:
                try:
                    artifact_key = (
                        str((root / relative).resolve()).casefold()
                        if root is not None
                        else Path(relative).as_posix().casefold()
                    )
                except OSError:
                    artifact_key = Path(relative).as_posix().casefold()
                artifact_paths.append(artifact_key)
        meta = source.get("meta") if isinstance(source.get("meta"), dict) else {}
        if name == "TradingView":
            frames = source.get("timeframes")
            if not isinstance(frames, list):
                frames = []
            if len(frames) != len(set(map(_text, frames))):
                defects.append(Defect("tradingview.timeframe_duplicate", "TradingView timeframe list contains duplicates", f"{path}.timeframes"))
            for frame in sorted(set(map(_text, frames)) - set(TRADINGVIEW_TIMEFRAMES)):
                defects.append(Defect("tradingview.timeframe_unexpected", f"TradingView contains unsupported timeframe: {frame}", f"{path}.timeframes"))
            artifact_frame_counts = {
                frame: sum(_text(record.get("timeframe")) == frame for record in records)
                for frame in TRADINGVIEW_TIMEFRAMES
            }
            for frame in TRADINGVIEW_TIMEFRAMES:
                if frame not in frames:
                    defects.append(Defect("tradingview.timeframe_missing", f"TradingView missing {frame}", f"{path}.timeframes"))
                if artifact_frame_counts[frame] != 1:
                    defects.append(Defect("tradingview.artifact_count", f"TradingView requires exactly one hash-bound {frame} artifact", f"{path}.artifacts"))
        elif name == "BlockBeats":
            expected = {
                "important_only": True,
                "capture_window_hours": 12,
                "window_covered": True,
                "selected_count_required": 3,
                "selected_row_count": 3,
            }
            for key, value in expected.items():
                if meta.get(key) != value:
                    defects.append(Defect("blockbeats.contract", f"BlockBeats {key} must be {value!r}", f"{path}.meta.{key}"))
        elif name == "Farside":
            total = _number(meta.get("latest_total_usd_m"))
            if total is None:
                defects.append(Defect("farside.total_missing", "Farside requires numeric latest_total_usd_m", f"{path}.meta.latest_total_usd_m"))
            latest_text = _text(meta.get("latest_complete_date"))
            if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", latest_text):
                defects.append(Defect("farside.date_missing", "Farside requires the latest complete trading date", f"{path}.meta.latest_complete_date"))
            else:
                try:
                    latest_date = datetime.strptime(latest_text, "%Y-%m-%d").date()
                    trading_date = datetime.strptime(
                        _text(payload.get("trading_date")), "%Y-%m-%d"
                    ).date()
                    age_days = (trading_date - latest_date).days
                    if age_days < 0 or age_days > 7:
                        defects.append(Defect("farside.date_stale", "Farside latest complete date must be current and no more than seven calendar days old", f"{path}.meta.latest_complete_date"))
                except ValueError:
                    defects.append(Defect("farside.date_invalid", "Farside latest complete date is not a real calendar date", f"{path}.meta.latest_complete_date"))
            expected_direction = "inflow" if total is not None and total > 0 else "outflow" if total is not None and total < 0 else "flat"
            if meta.get("flow_direction") != expected_direction:
                defects.append(Defect("farside.direction_mismatch", "Farside flow direction must be derived from latest total", f"{path}.meta.flow_direction"))
            if root is not None:
                farside_records = [
                    record
                    for record in records
                    if Path(_text(record.get("path"))).name == "farside_btc_etf.json"
                ]
                if len(farside_records) != 1:
                    defects.append(Defect("farside.artifact_count", "Farside requires exactly one structured JSON artifact", f"{path}.artifacts"))
                else:
                    try:
                        artifact = json.loads(
                            (root / _text(farside_records[0].get("path"))).read_text(
                                encoding="utf-8"
                            )
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        artifact = None
                    latest = artifact.get("latest") if isinstance(artifact, dict) else None
                    funds = latest.get("funds") if isinstance(latest, dict) else None
                    published = (
                        [value for value in funds.values() if _number(value) is not None]
                        if isinstance(funds, dict)
                        else []
                    )
                    if not published:
                        defects.append(Defect("farside.incomplete_latest_row", "latest complete Farside row must contain at least one published fund value", f"{path}.artifacts"))
                    if isinstance(latest, dict):
                        if _text(latest.get("date_iso")) != latest_text:
                            defects.append(Defect("farside.meta_date_drift", "Farside meta date differs from the selected complete row", f"{path}.meta.latest_complete_date"))
                        if _number(latest.get("total_usd_m")) != total:
                            defects.append(Defect("farside.meta_total_drift", "Farside meta total differs from the selected complete row", f"{path}.meta.latest_total_usd_m"))
        elif name == "Coinglass":
            try:
                observed_date = datetime.strptime(
                    _text(payload.get("trading_date")), "%Y-%m-%d"
                ).date()
            except ValueError:
                observed_date = None
            expected_windows = (
                ("3d",)
                if observed_date is not None and observed_date.weekday() >= 5
                else ("48h", "24h")
            )
            liquidation_names = {
                Path(_text(record.get("path"))).name.lower()
                for record in records
                if record.get("kind") == "liquidation_map"
            }
            for window in expected_windows:
                expected_name = f"liqheatmap_{window}.png"
                if expected_name not in liquidation_names:
                    defects.append(
                        Defect(
                            "coinglass.liquidation_map_missing",
                            f"Coinglass requires hash-bound {expected_name}",
                            f"{path}.artifacts",
                        )
                    )

    legacy_manifest = payload.get("legacy_capture_manifest")
    if legacy_manifest is not None:
        if not isinstance(legacy_manifest, dict):
            defects.append(Defect("capture_manifest.invalid", "legacy capture manifest record must be an object", "legacy_capture_manifest"))
        else:
            _validate_file_record(
                legacy_manifest,
                path="legacy_capture_manifest",
                defects=defects,
                root=root,
            )
            relative = _text(legacy_manifest.get("path"))
            if relative:
                artifact_paths.append(
                    str((root / relative).resolve()).casefold()
                    if root is not None
                    else Path(relative).as_posix().casefold()
                )

    expected_hash = evidence_snapshot_sha256(payload)
    recorded_hash = _text(payload.get("snapshot_sha256"))
    if recorded_hash and recorded_hash != expected_hash:
        defects.append(Defect("snapshot.hash_mismatch", "evidence snapshot hash does not match content", "snapshot_sha256"))
    if len(artifact_paths) != len(set(artifact_paths)):
        defects.append(Defect("artifact.path_duplicate", "evidence artifact paths must be unique", "sources"))
    if evidence_schema == "evidence-snapshot-v2":
        _validate_rate_expectation_source(payload, root=root, defects=defects)
    if root is not None:
        for issue in validate_visual_artifacts(payload, root=root):
            defects.append(Defect(issue.code, issue.message, issue.path))
    return _result(
        "evidence_integrity",
        defects,
        snapshot_sha256=expected_hash,
        source_count=len(sources),
        artifact_count=len(artifact_paths),
    )


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
        defects.append(
            Defect(
                "binding.evidence_drift",
                f"certified evidence no longer validates: {defect.message}",
                defect.path,
            )
        )
    expected_evidence_hash = evidence_result.facts["snapshot_sha256"]
    if payload.get("schema_version") != "reasoning-model-v5":
        defects.append(Defect("schema.invalid", "expected reasoning-model-v5", "schema_version"))
    actual_reasoning_fields = set(payload) - {"reasoning_sha256"}
    if actual_reasoning_fields != expected_reasoning_fields:
        defects.append(
            Defect(
                "reasoning.schema_fields",
                "reasoning-model-v5 must use the exact typed field set; report_sections is forbidden",
                "reasoning",
            )
        )
    for key in ("trading_date", "slot"):
        if payload.get(key) != evidence.get(key):
            defects.append(Defect("binding.mismatch", f"reasoning {key} differs from evidence", key))
    if payload.get("evidence_snapshot_sha256") != expected_evidence_hash:
        defects.append(Defect("binding.evidence", "reasoning is not bound to the evidence snapshot", "evidence_snapshot_sha256"))
    if "methodology_sha256" in payload:
        defects.append(
            Defect(
                "binding.legacy_methodology_field",
                "reasoning must not use the ambiguous legacy methodology_sha256 field",
                "methodology_sha256",
            )
        )
    if payload.get("reasoning_authority_sha256") != reasoning_authority_sha256:
        defects.append(
            Defect(
                "binding.reasoning_authority",
                "reasoning is not bound to the sealed reasoning-phase authority",
                "reasoning_authority_sha256",
            )
        )

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
                defects.append(
                    Defect(
                        "observation.schema_fields",
                        f"{source} observation must use its exact closed field set",
                        path,
                    )
                )
        if len(_text(item.get("fact"))) < 8:
            defects.append(Defect("observation.fact_thin", "observation fact is too short", f"{path}.fact"))
        elif not _contains_cjk(item.get("fact")):
            defects.append(Defect("observation.language", "observation fact must be Chinese-readable", f"{path}.fact"))
        if _source_role_action_leak(source, item.get("fact")):
            defects.append(
                Defect(
                    "observation.source_role_action_leak",
                    f"{source} fact cannot directly decide a main-account or Maker action",
                    f"{path}.fact",
                )
            )
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
                defects.append(
                    Defect(
                        "blockbeats.selected_count_drift",
                        "BlockBeats reasoning selected-event count must equal the certified evidence count",
                        f"{path}.metrics.selected_event_count",
                    )
                )
            try:
                window_matches = (
                    int(metrics.get("event_window_hours"))
                    == int(expected_blockbeats_window)
                )
            except (TypeError, ValueError):
                window_matches = False
            if not window_matches:
                defects.append(
                    Defect(
                        "blockbeats.window_drift",
                        "BlockBeats reasoning window must equal the certified evidence window",
                        f"{path}.metrics.event_window_hours",
                    )
                )
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
            defects.append(
                Defect(
                    "claim.schema_fields",
                    f"{claim_type} must use its exact closed field set",
                    path,
                )
            )
        allowed_accounts = CLAIM_ACCOUNT_SCOPES.get(claim_type, set())
        account = _text(item.get("account"))
        if allowed_accounts and account not in allowed_accounts:
            defects.append(
                Defect(
                    "claim.account_drift",
                    f"{claim_type} account must be one of {sorted(allowed_accounts)}",
                    f"{path}.account",
                )
            )
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
                defects.append(
                    Defect(
                        "fundamental.event_claim_schema",
                        "fundamental_event_realization must use the exact typed claim field set",
                        path,
                    )
                )
            if not re.fullmatch(
                r"[0-9a-f]{64}",
                _text(item.get("selected_event_sha256")),
            ):
                defects.append(
                    Defect(
                        "fundamental.event_claim_hash",
                        "event realization requires one lowercase selected-event SHA-256",
                        f"{path}.selected_event_sha256",
                    )
                )
            if item.get("realization_state") not in set(
                event_policy.get("event_realization_states") or []
            ):
                defects.append(
                    Defect(
                        "fundamental.event_claim_state",
                        "event realization state is outside the closed authority vocabulary",
                        f"{path}.realization_state",
                    )
                )
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
                defects.append(
                    Defect(
                        "fundamental.event_claim_support",
                        "event realization must directly bind fundamental_context and chart_interpretation",
                        f"{path}.support_ids",
                    )
                )
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
            defects.append(
                Defect(
                    "claim.structural_noise_buffer_wrong_owner",
                    "structural_noise_buffer is owned only by invalidation_path",
                    f"{path}.structural_noise_buffer",
                )
            )
        for field in ("conclusion", "invalidation"):
            leak = _execution_parameter_leak(item.get(field))
            if leak:
                defects.append(
                    Defect(
                        "claim.execution_parameter_second_truth",
                        f"claim prose cannot own an execution parameter outside the typed decision model: {leak}",
                        f"{path}.{field}",
                    )
                )
            if _score_second_truth(item.get(field)):
                defects.append(
                    Defect(
                        "claim.score_second_truth",
                        "claim prose cannot self-report a score; the typed score assessment is the only owner",
                        f"{path}.{field}",
                    )
                )
        source_owner = SOURCE_ROLE_CLAIM_OWNER.get(claim_type)
        if source_owner:
            for field in ("conclusion", "invalidation"):
                if _source_role_action_leak(source_owner, item.get(field)):
                    defects.append(
                        Defect(
                            "claim.source_role_action_leak",
                            f"{claim_type} cannot directly decide a main-account or Maker action",
                            f"{path}.{field}",
                        )
                    )
        if account in {"main", "maker"}:
            for field in ("conclusion", "invalidation"):
                causal_marker = _account_causal_leak(item.get(field), account)
                if causal_marker:
                    opposite_label = "Maker" if account == "main" else "主账户"
                    defects.append(
                        Defect(
                            "claim.cross_account_causal_text",
                            f"{account} claim cannot use {opposite_label} as a causal decision input: {causal_marker}",
                            f"{path}.{field}",
                        )
                    )
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
                defects.append(
                    Defect(
                        "claim.typed_direction_text_conflict",
                        "claim prose contradicts its typed direction owner",
                        f"{path}.conclusion",
                    )
                )
        if claim_type == "orderflow_interpretation":
            assessment = (
                item.get("score_assessment")
                if isinstance(item.get("score_assessment"), dict)
                else {}
            )
            rationale_leak = _execution_parameter_leak(assessment.get("rationale"))
            if rationale_leak:
                defects.append(
                    Defect(
                        "claim.score_rationale_second_truth",
                        f"score rationale cannot own execution parameters: {rationale_leak}",
                        f"{path}.score_assessment.rationale",
                    )
                )
            if _score_second_truth(assessment.get("rationale")):
                defects.append(
                    Defect(
                        "claim.score_rationale_second_truth",
                        "score rationale must explain evidence without declaring a second numeric score",
                        f"{path}.score_assessment.rationale",
                    )
                )
            if _typed_direction_prose_issue(
                assessment.get("rationale"),
                _text(item.get("direction")),
                claim_type="orderflow_interpretation",
            ):
                defects.append(
                    Defect(
                        "claim.score_rationale_direction_conflict",
                        "orderflow score rationale contradicts its typed direction owner",
                        f"{path}.score_assessment.rationale",
                    )
                )
        if claim_type == "cannot_do" and _text(item.get("prohibition")) not in CANNOT_DO_CODES:
            defects.append(
                Defect(
                    "cannot_do.prohibition_invalid",
                    "cannot_do requires one standardized Maker prohibition code",
                    f"{path}.prohibition",
                )
            )
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
            defects.append(
                Defect(
                    "claim.account_cardinality",
                    f"{claim_type}/{account} must have exactly one certified claim",
                    "claims",
                )
            )
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
        defects.append(
            Defect(
                "fundamental.event_claim_cardinality",
                "each sealed BlockBeats top3 hash requires exactly one shared fundamental_event_realization claim",
                "claims",
            )
        )
    for claim_type in sorted(ACCOUNT_LOOP_CLAIM_TYPES):
        for account in ("main", "maker"):
            if (claim_type, account) not in claim_keys:
                defects.append(
                    Defect(
                        "claim.account_loop_missing",
                        f"{account} requires its own {claim_type}",
                        "claims",
                    )
                )

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
                defects.append(
                    Defect(
                        "claim.current_basis_wrong_owner",
                        "current_basis is owned only by counter/invalidation claims",
                        f"claims.{claim_id}.current_basis",
                    )
                )
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
            defects.append(
                Defect(
                    "fundamental.event_observation_only_current_basis",
                    "fundamental-event-assessment-v1 lacks an event-aligned price basis and cannot own account current_basis",
                    f"claims.{claim_id}.current_basis",
                )
            )
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
            defects.append(
                Defect(
                    "fundamental.event_observation_only_trigger",
                    "fundamental-event-assessment-v1 lacks an event-aligned price basis and cannot own account trigger_logic",
                    f"claims.{claim_id}.trigger_logic",
                )
            )
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
            defects.append(
                Defect(
                    "claim.trigger_required_owner_missing",
                    f"{claim_type}/{account} is missing typed owner(s): {sorted(missing_always)}",
                    f"claims.{claim_id}.trigger_logic.clauses",
                )
            )
        one_of_sources = set(requirements.get("one_of_sources") or [])
        one_of_claim_types = set(requirements.get("one_of_claim_types") or [])
        if (one_of_sources or one_of_claim_types) and not (
            one_of_sources & sources or one_of_claim_types & claim_owner_types
        ):
            defects.append(
                Defect(
                    "claim.trigger_priority_owner_missing",
                    f"{claim_type}/{account} lacks its required typed priority domain",
                    f"claims.{claim_id}.trigger_logic.clauses",
                )
            )
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
            defects.append(
                Defect(
                    "claim.trigger_opposite_state_missing",
                    f"{claim_type}/{account} must name the typed opposite state for the current account direction",
                    f"claims.{claim_id}.trigger_logic.clauses",
                )
            )
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
                defects.append(
                    Defect(
                        "claim.trigger_non_directional_alternative_incoherent",
                        f"{claim_type}/{account} must name exactly one typed long or short alternative for a non-directional thesis",
                        f"claims.{claim_id}.trigger_logic.clauses",
                    )
                )
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
                    defects.append(
                        Defect(
                            "claim.trigger_non_directional_counter_direction_drift",
                            "a non-directional strongest-counter trigger must preserve the one directional alternative certified by current_basis",
                            f"claims.{claim_id}.trigger_logic.clauses",
                        )
                    )

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
                defects.append(
                    Defect(
                        (
                            "claim.exocharts_counter_polarity"
                            if account == "maker"
                            and claim_type == "strongest_counterevidence"
                            else "claim.trigger_relative_operator_noncanonical"
                        ),
                        "a relative future-direction clause requires the canonical equals_at_trigger operator",
                        clause_path,
                    )
                )
            if polarity_kind == "relative_direction" and item.get(
                "relative_bound"
            ) is not True:
                defects.append(
                    Defect(
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
                    )
                )
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
                defects.append(
                    Defect(
                        "claim.trigger_direction_incoherent",
                        "one_of_at_trigger directional targets must resolve to one typed polarity",
                        clause_path,
                    )
                )
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
                defects.append(
                    Defect(
                        "claim.trigger_any_clause_not_counter",
                        "every any-mode clause must independently express the same typed counter direction",
                        clause_path,
                    )
                )
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
                defects.append(
                    Defect(
                        "claim.trigger_direction_incoherent",
                        "all-mode directional clauses must preserve one typed counter direction; neutral auxiliaries may not introduce support or mixed direction",
                        clause_path,
                    )
                )

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
                defects.append(
                    Defect(
                        "claim.shared_account_leak",
                        f"shared claim cannot depend on {referenced_account} claim: {ref}",
                        f"claims.{claim_id}",
                    )
                )
            elif account in {"main", "maker"} and referenced_account not in {"shared", account}:
                defects.append(
                    Defect(
                        "claim.cross_account_dependency",
                        f"{account} claim cannot depend on {referenced_account} claim: {ref}",
                        f"claims.{claim_id}",
                    )
                )

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
        defects.append(
            Defect(
                "semantic.validator_failed",
                f"semantic validator could not load its canonical policy: {exc}",
                "methodology",
            )
        )
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
                    defects.append(
                        Defect(
                            "main.fundamental_source_missing",
                            f"main-account thesis requires {required}",
                            f"claims.{claim_id}",
                        )
                    )
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
                defects.append(
                    Defect(
                        "liquidation.source_boundary",
                        "liquidation confirmation must directly bind one Coinglass observation and the certified TradingView chart claim",
                        f"claims.{claim_id}.support_ids",
                    )
                )
            confirmation_result = _text(claim.get("confirmation_result"))
            allowed_confirmation_results = set(
                (scoring_policy.get("gold_methodology") or {}).get(
                    "liquidation_confirmation_results"
                )
                or []
            )
            if confirmation_result not in allowed_confirmation_results:
                defects.append(
                    Defect(
                        "liquidation.confirmation_invalid",
                        "liquidation confirmation result is outside the closed authority vocabulary",
                        f"claims.{claim_id}.confirmation_result",
                    )
                )
            if (
                manual_profile_status == "insufficient"
                and confirmation_result != "neutral"
            ):
                defects.append(
                    Defect(
                        "liquidation.manual_profile_substitution",
                        "an insufficient manual profile requires a neutral liquidation confirmation",
                        f"claims.{claim_id}.confirmation_result",
                    )
                )
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

    scenarios = payload.get("scenario_tree")
    if not isinstance(scenarios, list):
        defects.append(
            Defect(
                "scenario_tree.invalid",
                "scenario_tree must be an array",
                "scenario_tree",
            )
        )
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
            defects.append(
                Defect(
                    "scenario.schema_fields",
                    "scenario must use the exact closed typed ownership field set",
                    path,
                )
            )
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
            defects.append(
                Defect(
                    "scenario.identifier_noncanonical",
                    "scenario id, account, scenario_type and owner_claim_id must be exact closed-schema strings",
                    path,
                )
            )
        if not scenario_id or scenario_id in scenario_ids:
            defects.append(
                Defect(
                    "scenario.id_invalid",
                    "scenario id is missing or duplicated",
                    f"{path}.id",
                )
            )
        else:
            scenario_ids.add(scenario_id)
        key = (account, scenario_type)
        expected = expected_scenarios.get(key)
        if expected is None:
            defects.append(
                Defect(
                    "scenario.account_type_invalid",
                    "scenario account/type is outside the exact ownership matrix",
                    path,
                )
            )
            continue
        if key in scenario_by_key:
            defects.append(
                Defect(
                    "scenario.account_type_duplicate",
                    f"duplicate {account}/{scenario_type} scenario",
                    path,
                )
            )
        else:
            scenario_by_key[key] = item
        if scenario_id != expected.get("id"):
            defects.append(
                Defect(
                    "scenario.id_binding",
                    "scenario id must match its exact account/type ownership row",
                    f"{path}.id",
                )
            )
        owner_claim = claims.get(owner_claim_id)
        if not isinstance(owner_claim, dict):
            defects.append(
                Defect(
                    "scenario.owner_claim_unknown",
                    f"scenario owner claim is unknown: {owner_claim_id}",
                    f"{path}.owner_claim_id",
                )
            )
            continue
        if (
            _text(owner_claim.get("account")) != account
            or _text(owner_claim.get("claim_type"))
            != _text(expected.get("owner_claim_type"))
        ):
            defects.append(
                Defect(
                    "scenario.owner_claim_binding",
                    "scenario owner must be the exact same-account typed claim required by the ownership matrix",
                    f"{path}.owner_claim_id",
                )
            )
    if set(scenario_by_key) != set(expected_scenarios):
        defects.append(
            Defect(
                "scenario.matrix_incomplete",
                "scenario tree must exactly cover Main/Maker base/counter/invalidation",
                "scenario_tree",
            )
        )

    methodology_scenarios = (
        (payload.get("methodology") or {}).get("scenario_tree")
        if isinstance(payload.get("methodology"), dict)
        else None
    )
    methodology_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(methodology_scenarios, list):
        defects.append(
            Defect(
                "methodology.scenario_tree_missing",
                "methodology requires an account-scoped scenario tree",
                "methodology.scenario_tree",
            )
        )
        methodology_scenarios = []
    for index, scenario in enumerate(methodology_scenarios):
        path = f"methodology.scenario_tree[{index}]"
        if not isinstance(scenario, dict):
            defects.append(
                Defect(
                    "methodology.scenario_invalid",
                    "methodology scenario must be an object",
                    path,
                )
            )
            continue
        expected_fields = {
            "account",
            "kind",
            "claim_id",
            "trigger_claim_ids",
            "action",
        }
        if set(scenario) != expected_fields:
            defects.append(
                Defect(
                    "methodology.scenario_schema_fields",
                    "methodology scenario must use the exact compatibility field set",
                    path,
                )
            )
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
            defects.append(
                Defect(
                    "methodology.scenario_identifier_noncanonical",
                    "methodology scenario identifiers and transition code must be canonical",
                    path,
                )
            )
        key = (account, kind)
        if key not in expected_scenarios:
            defects.append(
                Defect(
                    "methodology.scenario_account_type",
                    "methodology scenario requires an exact Main/Maker ownership row",
                    path,
                )
            )
            continue
        if key in methodology_by_key:
            defects.append(
                Defect(
                    "methodology.scenario_duplicate",
                    f"duplicate methodology scenario: {account}/{kind}",
                    path,
                )
            )
        else:
            methodology_by_key[key] = scenario
        top_level_owner = _text(
            scenario_by_key.get(key, {}).get("owner_claim_id")
        )
        if not top_level_owner or claim_id != top_level_owner:
            defects.append(
                Defect(
                    "methodology.scenario_owner_drift",
                    "methodology scenario claim_id must equal the top-level typed owner",
                    f"{path}.claim_id",
                )
            )
        if action != _text(transition_code_by_type.get(kind)):
            defects.append(
                Defect(
                    "methodology.scenario_transition_code",
                    "methodology scenario action must equal the authority transition code",
                    f"{path}.action",
                )
            )
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
            defects.append(
                Defect(
                    "methodology.scenario_trigger_projection",
                    (
                        "methodology trigger_claim_ids must exactly equal the "
                        "typed owner's direct claim supports in owner order"
                    ),
                    f"{path}.trigger_claim_ids",
                )
            )
        owner_ancestors = _reachable_claim_ids(claim_id, claims)
        for trigger_id in trigger_ids:
            raw_trigger_id = trigger_id
            trigger_id = _text(raw_trigger_id)
            if not _canonical_closed_string(raw_trigger_id):
                defects.append(
                    Defect(
                        "methodology.scenario_trigger_noncanonical",
                        "methodology trigger_claim_ids must contain canonical claim ids",
                        f"{path}.trigger_claim_ids",
                    )
                )
            trigger_account = _text(claims.get(trigger_id, {}).get("account"))
            if trigger_account not in {"shared", account}:
                defects.append(
                    Defect(
                        "methodology.scenario_trigger_account",
                        "methodology scenario trigger must be shared or same-account",
                        f"{path}.trigger_claim_ids",
                    )
                )
            if trigger_id not in owner_ancestors:
                defects.append(
                    Defect(
                        "methodology.scenario_trigger_ancestry",
                        "methodology trigger must be reachable from its typed owner support DAG",
                        f"{path}.trigger_claim_ids",
                    )
                )
    if set(methodology_by_key) != set(expected_scenarios):
        defects.append(
            Defect(
                "methodology.scenario_account_coverage",
                "methodology scenarios must exactly cover the ownership matrix",
                "methodology.scenario_tree",
            )
        )

    # `cannot_do` is the final Maker-only output of the analysis graph.  It is
    # never an input to a claim or scenario.  The proof below is generated by
    # the gate from the graph and source ancestry; no model-provided boolean is
    # accepted as evidence that full analysis happened first.
    cannot_ids = [
        claim_id
        for claim_id, claim in claims.items()
        if _text(claim.get("claim_type")) == "cannot_do"
    ]
    cannot_do_closure: dict[str, Any] = {}
    if len(cannot_ids) != 1:
        defects.append(
            Defect(
                "cannot_do.cardinality",
                "reasoning requires exactly one Maker cannot_do claim",
                "claims",
            )
        )
    else:
        cannot_id = cannot_ids[0]
        if list(claims)[-1:] != [cannot_id]:
            defects.append(
                Defect(
                    "cannot_do.not_last",
                    "cannot_do must be the final reasoning claim",
                    f"claims.{cannot_id}",
                )
            )
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
                defects.append(
                    Defect(
                        "cannot_do.used_as_reasoning_input",
                        "cannot_do cannot support, counter, invalidate or flip another reasoning claim",
                        f"claims.{claim_id}",
                    )
                )

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
            defects.append(
                Defect(
                    "cannot_do.closure_claim_missing",
                    f"cannot_do closure is missing Maker {missing}",
                    f"claims.{cannot_id}.support_ids",
                )
            )
        source_ids = _reachable_observations(cannot_id, claims, observation_ids)
        closure_sources = {
            _text(observations[item].get("source"))
            for item in source_ids
            if item in observations
        }
        for missing_source in sorted(set(REQUIRED_SOURCES) - closure_sources):
            defects.append(
                Defect(
                    "cannot_do.source_closure_missing",
                    f"cannot_do closure is missing source ancestry: {missing_source}",
                    f"claims.{cannot_id}.support_ids",
                )
            )

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
                defects.append(
                    Defect(
                        "cannot_do.used_as_scenario_input",
                        "Maker scenarios must be complete before cannot_do and cannot cite it as an input",
                        f"scenario_tree[{index}].owner_claim_id",
                    )
                )
            required_type = required_scenario_claim_types.get(scenario_type)
            if required_type and not (
                _text(claims.get(owner_claim_id, {}).get("claim_type"))
                == required_type
                and _text(claims.get(owner_claim_id, {}).get("account"))
                == "maker"
            ):
                defects.append(
                    Defect(
                        "cannot_do.scenario_closure_missing",
                        f"Maker {scenario_type} scenario must bind its {required_type}",
                        f"scenario_tree[{index}].owner_claim_id",
                    )
                )
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
                    defects.append(
                        Defect(
                            "cannot_do.used_as_methodology_scenario_input",
                            "methodology scenarios must be complete before cannot_do and cannot cite the final closure",
                            f"methodology.scenario_tree[{index}]",
                        )
                    )
        cannot_do_closure = {
            "claim_id": cannot_id,
            "ancestor_claim_ids": sorted(reachable_claims),
            "source_coverage": sorted(closure_sources),
            "maker_scenarios": {
                key: maker_scenario_bindings.get(key, "")
                for key in sorted(REQUIRED_SCENARIO_TYPES)
            },
        }

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
            defects.append(
                Defect(
                    "report_section.source_role_action_leak",
                    f"{name} cannot directly decide a main-account or Maker action",
                    f"{path}.text",
                )
            )
        section_account = {"strategy": "main", "maker_strategy": "maker"}.get(name)
        if section_account:
            causal_marker = _account_causal_leak(text, section_account)
            if causal_marker:
                opposite_label = "Maker" if section_account == "main" else "主账户"
                defects.append(
                    Defect(
                        "report_section.cross_account_causal_text",
                        f"{name} cannot use {opposite_label} as a causal decision input: {causal_marker}",
                        f"{path}.text",
                    )
                )
        elif name == "independent_boundary":
            boundary_issue = _independent_boundary_issue(text)
            if boundary_issue:
                defects.append(
                    Defect(
                        "report_section.independent_boundary_invalid",
                        "independent_boundary must be an explicit post-hoc comparison without cross-account causation",
                        f"{path}.text",
                    )
                )
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
        defects.append(
            Defect(
                "defense.first_semantics",
                "first defense operation must use a post-fill, subsequently formed and confirmed 4H structural extreme",
                "report_sections.defense_first.text",
            )
        )
    if legacy_report_sections and re.search(r"(?i)(?:1\s*h|15\s*m|1\s*d|1小时|15分钟|日线)", first_defense):
        defects.append(
            Defect(
                "defense.first_timeframe_drift",
                "first defense operation cannot substitute another timeframe for 4H",
                "report_sections.defense_first.text",
            )
        )

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
        defects.append(
            Defect(
                "reasoning.actual_position_coupling",
                f"{description}: {matched}",
                f"reasoning_text[{line_no}]",
            )
        )
    first_without_4h = re.sub(r"(?i)4\s*h", "", first_defense)
    if legacy_report_sections and re.search(r"\d", first_without_4h):
        defects.append(
            Defect(
                "defense.first_numeric_leak",
                "reasoning may describe the first defense operation but decision-model-v7 owns its trigger price",
                "report_sections.defense_first.text",
            )
        )

    second_defense = _text((sections.get("defense_second") or {}).get("text"))
    if legacy_report_sections and ("仅" not in second_defense or "保本损" not in second_defense):
        defects.append(
            Defect(
                "defense.second_semantics",
                "second defense operation must only move the remaining stop to breakeven",
                "report_sections.defense_second.text",
            )
        )
    if legacy_report_sections and re.search(r"减仓|平仓|清仓|止盈|TP", second_defense, re.IGNORECASE):
        defects.append(
            Defect(
                "defense.second_position_mutation",
                "second defense operation cannot contain position reduction or take-profit actions",
                "report_sections.defense_second.text",
            )
        )
    if legacy_report_sections and re.search(r"\d", second_defense):
        defects.append(
            Defect(
                "defense.second_numeric_leak",
                "reasoning may describe the second defense operation but decision-model-v7 owns its trigger price",
                "report_sections.defense_second.text",
            )
        )

    maker_tp_text = _text((sections.get("maker_tp") or {}).get("text"))
    if legacy_report_sections and (not re.search(r"(?i)TP\s*1", maker_tp_text) or not re.search(r"(?i)TP\s*2", maker_tp_text)):
        defects.append(
            Defect(
                "risk.tp_ledger_missing",
                "Maker take-profit reasoning must cover both TP1 and TP2; decision-model-v7 owns the exact values and 50/50 ledger",
                "report_sections.maker_tp.text",
            )
        )

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


def decision_model_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("decision_sha256", None)
    return canonical_sha256(clean)


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


def _valid_png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    offset = 8
    width = height = 0
    saw_ihdr = saw_idat = saw_iend = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(data):
            raise ValueError("truncated PNG chunk")
        chunk_data = data[data_start:data_end]
        recorded_crc = struct.unpack(">I", data[data_end:crc_end])[0]
        calculated_crc = zlib.crc32(chunk_type)
        calculated_crc = zlib.crc32(chunk_data, calculated_crc) & 0xFFFFFFFF
        if recorded_crc != calculated_crc:
            raise ValueError("invalid PNG chunk CRC")
        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13 or offset != 8:
                raise ValueError("invalid PNG IHDR")
            width, height = struct.unpack(">II", chunk_data[:8])
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            saw_idat = True
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("invalid PNG IEND")
            saw_iend = True
            offset = crc_end
            break
        offset = crc_end
    if not (saw_ihdr and saw_idat and saw_iend and width > 0 and height > 0):
        raise ValueError("incomplete PNG")
    if any(byte not in b"\x00\t\n\r " for byte in data[offset:]):
        raise ValueError("unexpected bytes after PNG IEND")
    return width, height


def evaluate_decision(
    payload: dict[str, Any],
    *,
    reasoning: dict[str, Any],
    run: dict[str, Any],
    pretrade_gate: dict[str, Any] | None,
    root: Path,
) -> GateResult:
    defects: list[Defect] = []
    policy = load_scoring_policy(root=root)
    maker_policy = policy["maker_score"]
    conviction_policy = policy["conviction"]
    risk_policy = policy["risk_execution"]
    reasoning_hash = reasoning_model_sha256(reasoning)
    if payload.get("schema_version") != "decision-model-v7":
        defects.append(Defect("schema.invalid", "expected decision-model-v7", "schema_version"))
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
    # Defense prices are a deterministic projection of a valid risk ladder.
    # If the structural stop or risk arithmetic already failed, there is no
    # certified fill geometry from which defense triggers can be evaluated.
    # Keep that failure classified as risk_math_invalid instead of cascading
    # into a second, misleading defense failure.
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


def _load_delivery_manifest(record: Any, *, root: Path) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    try:
        target = (root / str(record.get("path", ""))).resolve()
        target.relative_to(root.resolve())
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return {}


def _evaluate_local_delivery_artifacts(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None,
    expected_cards: dict[str, dict[str, Any]] | None,
) -> tuple[list[Defect], dict[str, Any], list[Any], str]:
    defects: list[Defect] = []
    render = payload.get("render") if isinstance(payload.get("render"), dict) else {}
    cards = payload.get("cards") if isinstance(payload.get("cards"), dict) else {}
    records = {
        "report": payload.get("report"),
        "docx": render.get("docx"),
        "pdf": render.get("pdf"),
        "word_qa": render.get("word_qa"),
        "cards_spec": cards.get("spec"),
    }
    for name, record in records.items():
        if not isinstance(record, dict):
            defects.append(Defect("delivery.artifact_missing", f"delivery artifact missing: {name}", name))
            continue
        _validate_file_record(record, path=name, defects=defects, root=root)

    card_images = cards.get("images")
    if not isinstance(card_images, list) or len(card_images) != 3:
        defects.append(Defect("delivery.cards_missing", "delivery requires exactly three BlockBeats card images", "cards.images"))
        card_images = []
    for index, record in enumerate(card_images, start=1):
        if not isinstance(record, dict):
            defects.append(Defect("delivery.card_invalid", "BlockBeats card record must be an object", f"cards.images[{index - 1}]"))
            continue
        _validate_file_record(record, path=f"cards.images[{index - 1}]", defects=defects, root=root)

    def artifact_path(name: str) -> Path | None:
        record = records.get(name)
        if not isinstance(record, dict):
            return None
        try:
            target = (root / str(record.get("path", ""))).resolve()
            target.relative_to(root.resolve())
            return target if target.is_file() else None
        except (ValueError, OSError):
            return None

    docx_path = artifact_path("docx")
    if docx_path is not None:
        try:
            with zipfile.ZipFile(docx_path) as archive:
                names = set(archive.namelist())
                content_types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
                relationships = ElementTree.fromstring(archive.read("_rels/.rels"))
                document = ElementTree.fromstring(archive.read("word/document.xml"))
            if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
                raise ValueError("required DOCX parts missing")
            if not content_types.tag.endswith("Types") or not relationships.tag.endswith("Relationships") or not document.tag.endswith("document"):
                raise ValueError("required DOCX XML roots are invalid")
        except (KeyError, ValueError, zipfile.BadZipFile, OSError, ElementTree.ParseError):
            defects.append(Defect("delivery.docx_invalid", "DOCX artifact is not a valid Word package", "render.docx"))
    pdf_path = artifact_path("pdf")
    if pdf_path is not None:
        data = pdf_path.read_bytes()
        page_objects = len(re.findall(rb"/Type\s*/Page\b", data))
        if (
            not data.startswith(b"%PDF-")
            or b"startxref" not in data[-4096:]
            or b"%%EOF" not in data[-1024:]
            or page_objects <= 0
        ):
            defects.append(Defect("delivery.pdf_invalid", "PDF artifact has an invalid signature", "render.pdf"))
    report_hash = _text((records.get("report") or {}).get("sha256"))
    if expected_report is not None and records.get("report") != expected_report:
        defects.append(Defect("delivery.report_record_drift", "delivery report record differs from the certified report stage", "report"))
    if expected_cards is not None:
        if records.get("cards_spec") != expected_cards.get("cards_spec"):
            defects.append(Defect("delivery.cards_spec_drift", "delivery card spec differs from the certified report stage", "cards.spec"))
        expected_image_records = [expected_cards.get(f"card_{index}") for index in range(1, 4)]
        if card_images != expected_image_records:
            defects.append(Defect("delivery.cards_drift", "delivery card images differ from the certified report stage", "cards.images"))

    word = _load_delivery_manifest(records.get("word_qa"), root=root)
    if set(word) != set(PASSED_WORD_QA_FIELDS):
        defects.append(
            Defect(
                "delivery.word_schema",
                "passed Word QA must use the exact v2 field set",
                "render.word_qa",
            )
        )
    if (
        word.get("schema_version") != WORD_QA_SCHEMA
        or word.get("status") != "passed"
        or word.get("visual_qa_pass") is not True
        or word.get("report_sha256") != report_hash
        or word.get("docx") != records.get("docx")
        or word.get("pdf") != records.get("pdf")
        or word.get("docx_sha256") != _text((records.get("docx") or {}).get("sha256"))
        or word.get("pdf_sha256") != _text((records.get("pdf") or {}).get("sha256"))
    ):
        defects.append(Defect("delivery.word_manifest", "Word QA manifest is invalid or not hash-bound", "render.word_qa"))
    if not passed_word_qa_checklist_is_valid(word):
        defects.append(
            Defect(
                "delivery.word_review_checklist",
                "passed Word QA must carry the exact semantic review checklist with every item confirmed",
                "render.word_qa.review_checklist",
            )
        )
    if (
        run.get("schema_version") != "daily-run-vnext-v2"
        or word.get("run_id") != run.get("run_id")
        or word.get("run_sha256") != run.get("run_sha256")
        or word.get("trading_date") != run.get("trading_date")
        or word.get("slot") != run.get("slot")
    ):
        defects.append(
            Defect(
                "delivery.word_identity",
                "Word QA must bind the current v2 run id/hash/date/slot",
                "render.word_qa",
            )
        )
    if not passed_word_qa_run_paths_are_valid(root, run, word):
        defects.append(
            Defect(
                "delivery.word_run_locality",
                "Word QA DOCX, PDF, and page evidence must belong to the current run and exact attempt",
                "render.word_qa",
            )
        )
    if word.get("backend") not in WORD_QA_ALLOWED_BACKENDS:
        defects.append(
            Defect(
                "delivery.word_backend",
                "Word QA backend is outside the approved Microsoft Word backends",
                "render.word_qa.backend",
            )
        )
    created_at = _parse_iso_datetime(word.get("created_at"))
    reviewed_at = _parse_iso_datetime(word.get("reviewed_at"))
    if (
        not _text(word.get("reviewer"))
        or reviewed_at is None
        or created_at is None
        or (reviewed_at is not None and created_at is not None and reviewed_at < created_at)
    ):
        defects.append(
            Defect(
                "delivery.word_review",
                "Word QA requires a named reviewer and timezone-aware review after export",
                "render.word_qa",
            )
        )
    if (
        not isinstance(word.get("attempts"), int)
        or isinstance(word.get("attempts"), bool)
        or word.get("attempts") <= 0
        or type(word.get("cache_hit")) is not bool
        or not _text(word.get("page_renderer"))
    ):
        defects.append(
            Defect(
                "delivery.word_metadata",
                "Word QA export metadata is incomplete or invalid",
                "render.word_qa",
            )
        )
    page_count = word.get("page_count")
    inspected = word.get("inspected_pages")
    page_images = word.get("page_images")
    if (
        not isinstance(page_count, int)
        or page_count <= 0
        or not isinstance(inspected, list)
        or inspected != list(range(1, page_count + 1))
        or not isinstance(page_images, list)
        or len(page_images) != page_count
    ):
        defects.append(Defect("delivery.word_pages", "every rendered page must have inspected image evidence", "render.word_qa"))
    elif isinstance(page_images, list):
        page_paths: list[str] = []
        for index, record in enumerate(page_images):
            if isinstance(record, dict):
                _validate_file_record(record, path=f"render.word_qa.page_images[{index}]", defects=defects, root=root)
                try:
                    image_path = (root / str(record.get("path", ""))).resolve()
                    image_path.relative_to(root.resolve())
                    width, height = _valid_png_dimensions(image_path)
                    if width <= 0 or height <= 0:
                        raise ValueError("invalid PNG")
                    if record.get("page") != index + 1:
                        raise ValueError("page index mismatch")
                    page_paths.append(str(image_path).casefold())
                except (FileNotFoundError, OSError, ValueError, struct.error):
                    defects.append(Defect("delivery.page_image_format", "page image is not a valid PNG", f"render.word_qa.page_images[{index}]"))
            else:
                defects.append(Defect("delivery.page_image_invalid", "page image record must be an object", f"render.word_qa.page_images[{index}]"))
        if len(page_paths) != len(set(page_paths)):
            defects.append(Defect("delivery.page_image_duplicate", "each rendered page must have a unique PNG artifact", "render.word_qa.page_images"))

    card_paths: list[str] = []
    for index, record in enumerate(card_images):
        if not isinstance(record, dict):
            continue
        try:
            card_path = (root / str(record.get("path", ""))).resolve()
            card_path.relative_to(root.resolve())
            _valid_png_dimensions(card_path)
            card_paths.append(str(card_path).casefold())
        except (FileNotFoundError, OSError, ValueError, struct.error):
            defects.append(Defect("delivery.card_format", "BlockBeats card is not a complete PNG", f"cards.images[{index}]"))
    if len(card_paths) != len(set(card_paths)):
        defects.append(Defect("delivery.card_duplicate", "BlockBeats card images must be unique", "cards.images"))

    return defects, records, card_images, report_hash


def evaluate_shadow_delivery(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None = None,
    expected_cards: dict[str, dict[str, Any]] | None = None,
) -> GateResult:
    defects, records, card_images, report_hash = _evaluate_local_delivery_artifacts(
        payload,
        root=root,
        run=run,
        expected_report=expected_report,
        expected_cards=expected_cards,
    )
    if payload.get("schema_version") != "shadow-delivery-model-v1":
        defects.append(
            Defect("schema.invalid", "expected shadow-delivery-model-v1", "schema_version")
        )
    allowed_top_level = {"schema_version", "report", "render", "cards", "publish"}
    for key in sorted(set(payload) - allowed_top_level):
        defects.append(
            Defect(
                "delivery.shadow_field_unexpected",
                f"shadow delivery contains an unexpected top-level field: {key}",
                key,
            )
        )
    publish = payload.get("publish")
    if not isinstance(publish, dict):
        defects.append(
            Defect(
                "delivery.shadow_publish_boundary",
                "shadow delivery must explicitly record that Notion publishing was not attempted",
                "publish",
            )
        )
        publish = {}
    if publish.get("status") != "not_attempted":
        defects.append(
            Defect(
                "delivery.shadow_publish_boundary",
                "shadow delivery publish status must be not_attempted",
                "publish.status",
            )
        )
    if publish.get("reason") != "shadow_mode_forbids_notion":
        defects.append(
            Defect(
                "delivery.shadow_publish_boundary",
                "shadow delivery must use the governance reason shadow_mode_forbids_notion",
                "publish.reason",
            )
        )
    forbidden_publish_fields = sorted(set(publish) - {"status", "reason"})
    for key in forbidden_publish_fields:
        defects.append(
            Defect(
                "delivery.shadow_publish_claim",
                f"shadow delivery must not contain Notion publish evidence or claims: {key}",
                f"publish.{key}",
            )
        )
    return _result(
        "shadow_delivery_integrity",
        defects,
        report_sha256=report_hash,
        artifact_count=(
            sum(isinstance(value, dict) for value in records.values())
            + sum(isinstance(value, dict) for value in card_images)
        ),
        completion_mode="shadow",
        notion_published=False,
    )


def evaluate_delivery(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None = None,
    expected_cards: dict[str, dict[str, Any]] | None = None,
) -> GateResult:
    defects, records, card_images, report_hash = _evaluate_local_delivery_artifacts(
        payload,
        root=root,
        run=run,
        expected_report=expected_report,
        expected_cards=expected_cards,
    )
    if payload.get("schema_version") != "delivery-model-v1":
        defects.append(Defect("schema.invalid", "expected delivery-model-v1", "schema_version"))
    publish_section = (
        payload.get("publish") if isinstance(payload.get("publish"), dict) else {}
    )
    publish_records = {
        "publish": publish_section.get("manifest"),
        "notion_verify": publish_section.get("verification"),
    }
    for name, record in publish_records.items():
        if not isinstance(record, dict):
            defects.append(Defect("delivery.artifact_missing", f"delivery artifact missing: {name}", name))
            continue
        _validate_file_record(record, path=name, defects=defects, root=root)

    publish = _load_delivery_manifest(publish_records.get("publish"), root=root)
    required_publish = {
        "schema_version": "publish-vnext-v1",
        "status": "passed",
        "structure_pass": True,
        "visual_contract_pass": True,
        "unique_page_count": 1,
        "report_sha256": report_hash,
        "cards_spec_sha256": _text((records.get("cards_spec") or {}).get("sha256")),
        "card_sha256s": [
            _text(record.get("sha256"))
            for record in card_images
            if isinstance(record, dict)
        ],
    }
    for key, value in required_publish.items():
        if publish.get(key) != value:
            defects.append(Defect("delivery.publish_manifest", f"publish manifest {key} must be {value!r}", "publish.manifest"))
    page_id = _text(publish.get("page_id"))
    if not re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", page_id, re.IGNORECASE):
        defects.append(Defect("delivery.page_id_missing", "published page id must be a Notion UUID", "publish.manifest"))
    if not re.fullmatch(r"[0-9a-f]{64}", _text(publish.get("children_signature_sha256"))):
        defects.append(Defect("delivery.children_signature", "Notion children signature is invalid", "publish.manifest"))
    published_at = _parse_iso_datetime(publish.get("published_at"))
    if published_at is None:
        defects.append(Defect("delivery.publish_time", "publish manifest requires a timezone-aware published_at", "publish.manifest"))
    verification = _load_delivery_manifest(publish_records.get("notion_verify"), root=root)
    required_verification = {
        "schema_version": "notion-verification-vnext-v1",
        "status": "passed",
        "structure_pass": True,
        "visual_contract_pass": True,
        "unique_page_count": 1,
        "report_sha256": report_hash,
        "page_id": page_id,
        "children_signature_sha256": publish.get("children_signature_sha256"),
        "cards_spec_sha256": publish.get("cards_spec_sha256"),
        "card_sha256s": publish.get("card_sha256s"),
    }
    for key, value in required_verification.items():
        if verification.get(key) != value:
            defects.append(Defect("delivery.notion_verification", f"Notion verification {key} must match the published artifact", "publish.verification"))
    readback_at = _parse_iso_datetime(verification.get("readback_at"))
    if readback_at is None:
        defects.append(Defect("delivery.notion_readback_time", "Notion verification requires a timezone-aware readback_at", "publish.verification"))
    elif published_at is not None and readback_at < published_at:
        defects.append(Defect("delivery.notion_readback_order", "Notion readback must occur after publish", "publish.verification"))
    return _result(
        "delivery_integrity",
        defects,
        report_sha256=report_hash,
        artifact_count=(
            sum(isinstance(value, dict) for value in records.values())
            + sum(isinstance(value, dict) for value in publish_records.values())
        ),
        page_id=_text(publish.get("page_id")),
    )
