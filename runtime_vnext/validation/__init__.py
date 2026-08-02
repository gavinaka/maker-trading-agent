"""Typed validation seams for the vNext back-half.

This package is an extraction boundary, not a second validation system.  Its
facades currently delegate to the existing production implementations and
therefore preserve the four public gates and every existing threshold.
"""

from .common import (
    DefectLike,
    GateResultLike,
    LegacyCoverage,
    LegacyDelegate,
    SemanticIssueLike,
)
from .report_semantics import (
    certify_maker_semantic_state,
    certify_order_lifecycle,
    order_lifecycle_display,
    project_scenario_audit,
    scenario_projection_policy,
    validate_scenario_projection,
)

__all__ = [
    "DefectLike",
    "GateResultLike",
    "LegacyCoverage",
    "LegacyDelegate",
    "SemanticIssueLike",
    "certify_maker_semantic_state",
    "certify_order_lifecycle",
    "order_lifecycle_display",
    "project_scenario_audit",
    "scenario_projection_policy",
    "validate_scenario_projection",
]
