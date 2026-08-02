"""Deterministic scenario, lifecycle and Maker-state report certification.

The report compiler may format these certified values, but it does not own
their closed vocabularies, state matrices or projection topology.  Those
owners live in :mod:`runtime_vnext.domain_ir.registry` and their generated
contract views live in :mod:`runtime_vnext.domain_ir.projection`.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ..domain_ir.projection import (
    scenario_ownership_projection,
    scenario_projection_contract_projection,
)
from ..domain_ir.registry import (
    MAKER_ORDER_LIFECYCLE_FIELD_ORDER,
    MAKER_SEMANTIC_STATES,
    ORDER_LIFECYCLE_APPLICABILITY,
    ORDER_LIFECYCLE_DISPLAY_BY_STATE,
    ORDER_LIFECYCLE_PATH_FLAGS,
    REGISTRY,
    SCENARIO_CANONICAL_AUDIT_FIELD_ORDER,
    SCENARIO_FIELD_ORDER,
    SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT,
)
from ..plan_semantics import classify_maker_semantic_state


def _canonical_closed_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def certify_maker_semantic_state(maker: Mapping[str, Any]) -> str:
    """Certify the four-state Maker classification from sealed decision facts."""

    sealed_state = maker.get("semantic_state")
    if sealed_state is not None:
        if sealed_state not in MAKER_SEMANTIC_STATES:
            raise ValueError("Maker semantic_state is outside the closed vocabulary")
        return str(sealed_state)
    constructibility = (
        maker.get("plan_constructibility")
        if isinstance(maker.get("plan_constructibility"), Mapping)
        else {}
    )
    lifecycle = (
        maker.get("order_lifecycle")
        if isinstance(maker.get("order_lifecycle"), Mapping)
        else {}
    )
    reach_basis = (
        maker.get("entry_reach_probability_basis")
        if isinstance(maker.get("entry_reach_probability_basis"), Mapping)
        else {}
    )
    return classify_maker_semantic_state(
        plan_state=maker.get("plan_state"),
        direction=maker.get("direction"),
        plan_constructible=maker.get("plan_constructible"),
        threshold_eligible=maker.get("threshold_eligible"),
        risk_plan=maker.get("risk_plan"),
        defense_plan=maker.get("defense_plan"),
        position_notional_usdt=maker.get("position_notional_usdt"),
        entry_type=maker.get("entry_type"),
        order_lifecycle_state=lifecycle.get("state"),
        entry_reach_probability_applicability=reach_basis.get("applicability"),
        constructibility_reason=constructibility.get("primary_reason_code"),
    )


def certify_order_lifecycle(maker: Mapping[str, Any]) -> dict[str, Any]:
    """Certify an exact gate-derived lifecycle without inferring or rewriting it."""

    raw = maker.get("order_lifecycle")
    lifecycle = dict(raw) if isinstance(raw, Mapping) else {}
    if set(lifecycle) != set(MAKER_ORDER_LIFECYCLE_FIELD_ORDER):
        raise ValueError("order lifecycle differs from the closed typed schema")
    if lifecycle.get("schema_version") != REGISTRY.maker_order_lifecycle_schema_version:
        raise ValueError("order lifecycle schema version is unsupported")
    if lifecycle.get("fill_probability") is not None:
        raise ValueError("order lifecycle may not fabricate an actual fill probability")

    state = str(lifecycle.get("state") or "")
    path_flags = ORDER_LIFECYCLE_PATH_FLAGS.get(state)
    probability_applicability = ORDER_LIFECYCLE_APPLICABILITY.get(state)
    if path_flags is None or probability_applicability is None:
        raise ValueError("order lifecycle state is outside the closed vocabulary")
    if (
        lifecycle.get("legal_fill_path_exists")
        is not path_flags["legal_fill_path_exists"]
        or lifecycle.get("legal_cancel_path_exists")
        is not path_flags["legal_cancel_path_exists"]
        or lifecycle.get("fill_probability_applicability")
        != probability_applicability
        or lifecycle.get("reason_code") != state
    ):
        raise ValueError("order lifecycle projection is internally inconsistent")
    return copy.deepcopy(lifecycle)


def order_lifecycle_display(lifecycle: Mapping[str, Any]) -> str:
    """Project the registry-owned Chinese lifecycle explanation."""

    certified = certify_order_lifecycle({"order_lifecycle": lifecycle})
    state = str(certified["state"])
    try:
        return ORDER_LIFECYCLE_DISPLAY_BY_STATE[state]
    except KeyError as exc:  # Registry coherence tests should make this unreachable.
        raise ValueError("order lifecycle state is outside the closed vocabulary") from exc


def scenario_projection_policy(
    presentation_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact generated scenario-presentation contract."""

    projection = presentation_contract.get("scenario_projection_contract")
    expected = scenario_projection_contract_projection()
    if not isinstance(projection, Mapping) or dict(projection) != expected:
        raise ValueError("scenario presentation contract is invalid")
    return copy.deepcopy(dict(projection))


def project_scenario_audit(
    reasoning: Mapping[str, Any],
    *,
    account_controls: Mapping[str, Mapping[str, Any]],
    scenario_ownership: Mapping[str, Any],
    presentation_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project all visible scenario language from certified typed owners."""

    projection = scenario_projection_policy(presentation_contract)
    expected_ownership = scenario_ownership_projection()
    if dict(scenario_ownership) != expected_ownership:
        raise ValueError("scenario ownership policy is invalid")
    expected_items = {
        (str(item["account"]), str(item["scenario_type"])): item
        for item in expected_ownership["items"]
    }
    claims = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, Mapping) and str(item.get("id") or "")
    }
    methodology = reasoning.get("methodology")
    methodology_scenarios = (
        methodology.get("scenario_tree")
        if isinstance(methodology, Mapping)
        and isinstance(methodology.get("scenario_tree"), list)
        else []
    )
    methodology_by_key = {
        (str(item.get("account")), str(item.get("kind"))): item
        for item in methodology_scenarios
        if isinstance(item, Mapping)
    }
    projected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in reasoning.get("scenario_tree", []):
        if not isinstance(raw, Mapping) or set(raw) != set(SCENARIO_FIELD_ORDER):
            raise ValueError("scenario does not use the exact typed ownership fields")
        if not all(_canonical_closed_string(value) for value in raw.values()):
            raise ValueError("scenario ownership identifiers are not canonical")
        account = str(raw["account"])
        scenario_type = str(raw["scenario_type"])
        owner_claim_id = str(raw["owner_claim_id"])
        key = (account, scenario_type)
        expected = expected_items.get(key)
        owner_claim = claims.get(owner_claim_id)
        if (
            expected is None
            or key in seen
            or raw["id"] != expected.get("id")
            or not isinstance(owner_claim, Mapping)
            or owner_claim.get("account") != account
            or owner_claim.get("claim_type") != expected.get("owner_claim_type")
        ):
            raise ValueError("scenario typed owner does not match its exact matrix row")
        seen.add(key)
        transition_code = str(
            projection["transition_code_by_type"].get(scenario_type) or ""
        )
        methodology_item = methodology_by_key.get(key)
        if (
            not isinstance(methodology_item, Mapping)
            or methodology_item.get("claim_id") != owner_claim_id
            or methodology_item.get("action") != transition_code
        ):
            raise ValueError(
                "methodology scenario owner or transition code drifted from the "
                "top-level scenario"
            )
        if scenario_type == "base":
            direction = str(owner_claim.get("direction") or "")
            condition = str(
                (
                    projection["base_condition_by_account_direction"].get(account)
                    or {}
                ).get(direction)
                or ""
            )
        else:
            control = (account_controls.get(account) or {}).get(scenario_type)
            if (
                not isinstance(control, Mapping)
                or control.get("claim_id") != owner_claim_id
            ):
                raise ValueError("scenario lacks its same-account typed control")
            condition = str(control.get("condition") or "")
        visible = (
            projection["projection_by_account_and_transition_code"].get(account)
            or {}
        ).get(transition_code)
        if (
            not condition
            or not isinstance(visible, Mapping)
            or set(visible) != {"expected_path", "action"}
        ):
            raise ValueError("scenario deterministic presentation mapping is incomplete")
        values = {
            "id": raw["id"],
            "account": account,
            "scenario_type": scenario_type,
            "owner_claim_id": owner_claim_id,
            "transition_code": transition_code,
            "condition": condition,
            "expected_path": str(visible["expected_path"]),
            "action": str(visible["action"]),
        }
        projected.append(
            {
                field: values[field]
                for field in SCENARIO_CANONICAL_AUDIT_FIELD_ORDER
            }
        )
    if seen != set(expected_items):
        raise ValueError("scenario typed ownership matrix is incomplete")
    validate_scenario_projection(
        projected,
        claims=list(claims.values()),
        account_controls=account_controls,
        presentation_contract=presentation_contract,
    )
    return projected


def validate_scenario_projection(
    scenarios: list[dict[str, Any]],
    *,
    claims: list[dict[str, Any]],
    account_controls: Mapping[str, Mapping[str, Any]],
    presentation_contract: Mapping[str, Any],
) -> None:
    """Validate canonical scenario output by exact structural reconstruction."""

    projection = scenario_projection_policy(presentation_contract)
    fields = set(SCENARIO_CANONICAL_AUDIT_FIELD_ORDER)
    claim_index = {
        str(item.get("id")): item
        for item in claims
        if isinstance(item, Mapping) and str(item.get("id") or "")
    }
    owner_type_by_key = {
        (account, scenario_type): owner_claim_type
        for account, rows in SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT.items()
        for scenario_type, owner_claim_type in rows.items()
    }
    seen: set[tuple[str, str]] = set()
    for item in scenarios:
        if not isinstance(item, Mapping) or set(item) != fields:
            raise ValueError("canonical scenario field set is invalid")
        account = str(item.get("account") or "")
        scenario_type = str(item.get("scenario_type") or "")
        key = (account, scenario_type)
        owner = claim_index.get(str(item.get("owner_claim_id") or ""))
        transition_code = projection["transition_code_by_type"].get(scenario_type)
        if (
            key not in owner_type_by_key
            or key in seen
            or item.get("id") != f"scenario_{account}_{scenario_type}"
            or not isinstance(owner, Mapping)
            or owner.get("account") != account
            or owner.get("claim_type") != owner_type_by_key[key]
            or item.get("transition_code") != transition_code
        ):
            raise ValueError("canonical scenario typed provenance is invalid")
        seen.add(key)
        if scenario_type == "base":
            expected_condition = (
                projection["base_condition_by_account_direction"]
                .get(account, {})
                .get(str(owner.get("direction") or ""))
            )
        else:
            control = (account_controls.get(account) or {}).get(scenario_type)
            if (
                not isinstance(control, Mapping)
                or control.get("claim_id") != item.get("owner_claim_id")
            ):
                raise ValueError("canonical scenario control owner is invalid")
            expected_condition = control.get("condition")
        visible = (
            projection["projection_by_account_and_transition_code"]
            .get(account, {})
            .get(transition_code)
        )
        if (
            not isinstance(visible, Mapping)
            or item.get("condition") != expected_condition
            or item.get("expected_path") != visible.get("expected_path")
            or item.get("action") != visible.get("action")
        ):
            raise ValueError("canonical scenario projection drifted from typed owners")
    if seen != set(owner_type_by_key):
        raise ValueError("canonical scenario matrix is incomplete")


__all__ = [
    "certify_maker_semantic_state",
    "certify_order_lifecycle",
    "order_lifecycle_display",
    "project_scenario_audit",
    "scenario_projection_policy",
    "validate_scenario_projection",
]
