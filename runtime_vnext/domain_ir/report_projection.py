"""Pure projection from certified report sections to canonical artifacts.

This module accepts no repository root, raw stage payload, policy loader or
artifact path.  It performs no market interpretation, validation, risk math,
file I/O or subprocess work.
"""

from __future__ import annotations

from typing import Any

from .canonical import canonical_sha256
from .registry import REGISTRY
from .report_types import CertifiedReportProjectionInput, to_plain


def project_report_bindings(
    source: CertifiedReportProjectionInput,
) -> dict[str, Any]:
    """Project the exact typed traceability contract as its own artifact."""

    bindings = source.bindings
    if bindings.schema_version != REGISTRY.report_bindings_schema_version:
        raise ValueError("report bindings schema differs from the domain registry")
    projected = to_plain(bindings)
    if not isinstance(projected, dict):
        raise RuntimeError("typed report bindings did not project to an object")
    return projected


def project_canonical_report_model(
    source: CertifiedReportProjectionInput,
) -> dict[str, Any]:
    metadata = source.metadata
    values: dict[str, Any] = {
        "schema_version": metadata.schema_version,
        "presentation_contract_version": metadata.presentation_contract_version,
        "presentation_contract_sha256": metadata.presentation_contract_sha256,
        "run_id": metadata.run_id,
        "run_sha256": metadata.run_sha256,
        "run_mode": metadata.run_mode,
        "execution_authorization": to_plain(metadata.execution_authorization),
        "trading_date": metadata.trading_date,
        "slot": metadata.slot,
        "methodology_sha256": metadata.methodology_sha256,
        "report_contract_sha256": metadata.report_contract_sha256,
        "evidence_snapshot_sha256": metadata.evidence_snapshot_sha256,
        "reasoning_sha256": metadata.reasoning_sha256,
        "decision_sha256": metadata.decision_sha256,
        "blockbeats_cards": to_plain(source.blockbeats_cards),
        "frontstage": to_plain(source.frontstage),
        "maker_summary": to_plain(source.maker_summary),
        "main_summary": to_plain(source.main_summary),
        "audit": to_plain(source.audit),
    }
    expected_fields = tuple(
        field
        for field in REGISTRY.report_model_field_order
        if field != "model_sha256"
    )
    if set(values) != set(expected_fields):
        raise RuntimeError("report registry field order differs from projector values")
    model = {field: values[field] for field in expected_fields}
    model["model_sha256"] = canonical_sha256(model)
    return model


def project_blockbeats_cards_spec(
    source: CertifiedReportProjectionInput,
) -> dict[str, Any]:
    return {
        "schema_version": REGISTRY.blockbeats_cards_schema_version,
        "trading_date": source.metadata.trading_date,
        "slot": source.metadata.slot,
        "evidence_snapshot_sha256": source.metadata.evidence_snapshot_sha256,
        "cards": to_plain(source.blockbeats_cards),
    }


__all__ = [
    "project_blockbeats_cards_spec",
    "project_canonical_report_model",
    "project_report_bindings",
]
