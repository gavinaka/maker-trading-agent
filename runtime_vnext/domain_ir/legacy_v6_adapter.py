"""Compatibility adapter from generated registry projections to v6 JSON.

The committed JSON remains a transport artifact for existing tooling.  This
adapter makes its deterministic sections generated views instead of a second
authority owner.
"""

from __future__ import annotations

import copy
from typing import Any

from .projection import (
    deterministic_contract_sections,
    report_presentation_contract_registry_views,
    scoring_contract_registry_views,
)


def projected_v6_contract(
    contract: dict[str, Any],
    *,
    methodology_leaf_ownership: dict[str, Any],
) -> dict[str, Any]:
    projected = copy.deepcopy(contract)
    sections = deterministic_contract_sections(
        methodology_leaf_ownership=methodology_leaf_ownership
    )
    projected["schema_version"] = sections["schema_version"]
    projected["certified_schema_version"] = sections["certified_schema_version"]
    projected["additional_fields_allowed"] = sections["additional_fields_allowed"]
    projected["top_level"] = sections["top_level"]
    projected["claim_topology"] = sections["claim_topology"]
    projected["typed_narrative_ownership"] = sections[
        "typed_narrative_ownership"
    ]
    projected["server_projection"] = sections["server_projection"]
    projected["visual_citation_policy"] = sections["visual_citation_policy"]
    projected["observation_fields_by_source"] = sections[
        "observation_fields_by_source"
    ]
    projected["claim_fields_by_type"] = sections["claim_fields_by_type"]
    projected["scaffold_policy"] = sections["scaffold_policy"]
    projected["scenario_ownership"] = sections["scenario_ownership"]
    projected["scenario_fields"] = sections["scenario_fields"]
    scenario_enums = projected["methodology"]["arrays"]["scenario_tree"]["item"][
        "enum_fields"
    ]
    scenario_enums["account"]["values"] = sections["scenario_accounts"]
    scenario_enums["kind"]["values"] = sections["scenario_types"]
    scenario_enums["action"]["values"] = sections[
        "scenario_transition_codes"
    ]
    projected["pipeline_unit_fields"] = sections["pipeline_unit_fields"]
    projected["pipeline_unit_order"] = sections["pipeline_unit_order"]
    return projected


def deterministic_projection_drift(
    contract: dict[str, Any],
    *,
    methodology_leaf_ownership: dict[str, Any],
) -> bool:
    return contract != projected_v6_contract(
        contract,
        methodology_leaf_ownership=methodology_leaf_ownership,
    )


def projected_scoring_contract(contract: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(contract)
    for path, value in scoring_contract_registry_views().items():
        target = projected
        for key in path[:-1]:
            child = target.get(key)
            if not isinstance(child, dict):
                child = {}
                target[key] = child
            target = child
        target[path[-1]] = copy.deepcopy(value)
    return projected


def scoring_projection_drift(contract: dict[str, Any]) -> bool:
    return contract != projected_scoring_contract(contract)


def projected_report_presentation_contract(
    contract: dict[str, Any],
) -> dict[str, Any]:
    projected = copy.deepcopy(contract)
    for path, value in report_presentation_contract_registry_views().items():
        target = projected
        for key in path[:-1]:
            child = target.get(key)
            if not isinstance(child, dict):
                child = {}
                target[key] = child
            target = child
        target[path[-1]] = copy.deepcopy(value)
    return projected


def report_presentation_projection_drift(contract: dict[str, Any]) -> bool:
    return contract != projected_report_presentation_contract(contract)
