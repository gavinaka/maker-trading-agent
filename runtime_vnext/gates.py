"""Stable public entrypoint for the four vNext production gates.

Implementations live in stage-owned validation modules. This compatibility
surface preserves result types, helper imports and defect ordering without
owning business validation logic.
"""

from __future__ import annotations

from .domain_ir.registry import (
    ACCOUNT_CURRENT_BASIS_POLICY_FIELDS,
    CLAIM_TYPES as REQUIRED_CLAIM_TYPES,
    EVIDENCE_SOURCE_ORDER as REQUIRED_SOURCES,
    NON_TRACEABLE_REPORT_SECTIONS,
    REPORT_SECTIONS as REQUIRED_REPORT_SECTIONS,
    SCENARIO_TYPES as REQUIRED_SCENARIO_TYPES,
    SOURCE_ROLES,
    TRADINGVIEW_TIMEFRAMES,
)
from .validation.common import Defect, GateResult, maker_fill_scenarios
from .validation.decision import decision_model_sha256, evaluate_decision
from .validation.delivery import evaluate_delivery, evaluate_shadow_delivery
from .validation.evidence import evaluate_evidence, evidence_snapshot_sha256
from .validation.reasoning import (
    _current_basis_policy, _execution_parameter_leak,
    _future_trigger_clause_polarities, _trigger_logic_policy,
    _typed_direction_prose_issue, evaluate_reasoning, reasoning_model_sha256,
)

TRACEABLE_REPORT_SECTIONS = REQUIRED_REPORT_SECTIONS - NON_TRACEABLE_REPORT_SECTIONS

__all__ = [
    "ACCOUNT_CURRENT_BASIS_POLICY_FIELDS", "Defect", "GateResult",
    "REQUIRED_CLAIM_TYPES", "REQUIRED_REPORT_SECTIONS",
    "REQUIRED_SCENARIO_TYPES", "REQUIRED_SOURCES", "SOURCE_ROLES",
    "TRACEABLE_REPORT_SECTIONS", "TRADINGVIEW_TIMEFRAMES",
    "decision_model_sha256", "evaluate_decision", "evaluate_delivery",
    "evaluate_evidence", "evaluate_reasoning", "evaluate_shadow_delivery",
    "evidence_snapshot_sha256", "maker_fill_scenarios", "reasoning_model_sha256",
]
