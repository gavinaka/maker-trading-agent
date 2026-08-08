"""Single-owner typed domain contract for the vNext reasoning back-half.

The package owns deterministic identities, enums, topology and projection
rules.  It deliberately does not own market interpretation, evidence weight,
thesis selection, counterevidence selection, invalidation judgment, support
edge selection or Chinese narrative depth; those remain model-owned inputs
that the validators certify.
"""

from .registry import REGISTRY, DomainRegistry
from .projection import (
    project_blockbeats_cards_spec,
    project_canonical_report_model,
    project_report_bindings,
)
from .types import (
    CertifiedReportProjectionInput,
    ProjectedReport,
    ReportBindings,
    ReportField,
    ReportMetadata,
    ReportRecord,
    ReportScalar,
    ReportSectionBinding,
    ReportValue,
    canonical_json_bytes,
    canonical_sha256,
    to_plain,
)

__all__ = [
    "DomainRegistry",
    "CertifiedReportProjectionInput",
    "ProjectedReport",
    "REGISTRY",
    "ReportBindings",
    "ReportField",
    "ReportMetadata",
    "ReportRecord",
    "ReportScalar",
    "ReportSectionBinding",
    "ReportValue",
    "canonical_json_bytes",
    "canonical_sha256",
    "project_blockbeats_cards_spec",
    "project_canonical_report_model",
    "project_report_bindings",
    "to_plain",
]
