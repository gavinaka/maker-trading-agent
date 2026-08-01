"""Certify legacy v6/v7 artifacts into the pure report projection boundary."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ..domain_ir.canonical import canonical_sha256
from ..domain_ir.registry import REGISTRY
from ..domain_ir.report_types import (
    CertifiedReportProjectionInput,
    ReportBindings,
    ReportField,
    ReportMetadata,
    ReportRecord,
    ReportSectionBinding,
    ReportValue,
)
from .common import LegacyDelegate, invoke_legacy


LEGACY_CERTIFIER_DELEGATE = LegacyDelegate(
    stage="report",
    domain="legacy_v6_v7_projection_certification",
    module="runtime_vnext.report_compiler",
    callable_name="build_canonical_report_model",
    coverage="full_stage",
)

CANONICAL_REPORT_FIELDS = REGISTRY.report_model_field_order


def _freeze_value(value: Any, *, path: str) -> ReportValue:
    if isinstance(value, Mapping):
        return _freeze_record(value, path=path)
    if type(value) in {list, tuple}:
        return tuple(
            _freeze_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if value is None or type(value) in {bool, int, float, str, Decimal}:
        return value
    raise TypeError(f"unsupported certified report value at {path}: {type(value).__name__}")


def _freeze_record(value: Mapping[str, Any], *, path: str) -> ReportRecord:
    fields: list[ReportField] = []
    for key, item in value.items():
        if type(key) is not str or not key:
            raise TypeError(f"certified report record key is invalid at {path}")
        fields.append(
            ReportField(
                key,
                _freeze_value(item, path=f"{path}.{key}"),
            )
        )
    return ReportRecord(tuple(fields))


def certify_canonical_report_model(
    model: Mapping[str, Any],
    *,
    bindings: ReportBindings,
) -> CertifiedReportProjectionInput:
    """Bind an already-validated current model to explicit immutable sections.

    A persisted legacy model without its own bindings is intentionally not
    promoted through this active projection boundary.
    """

    if set(model) != set(CANONICAL_REPORT_FIELDS):
        raise ValueError("canonical report fields differ from the projection boundary")
    if model.get("schema_version") != REGISTRY.report_model_schema_version:
        raise ValueError("canonical report schema differs from the domain registry")
    clean = dict(model)
    recorded_hash = clean.pop("model_sha256", None)
    if recorded_hash != canonical_sha256(clean):
        raise ValueError("canonical report model hash is invalid")
    authorization = model.get("execution_authorization")
    if not isinstance(authorization, Mapping):
        raise TypeError("canonical execution_authorization must be a mapping")
    cards = model.get("blockbeats_cards")
    if not isinstance(cards, list):
        raise TypeError("canonical blockbeats_cards must be an array")
    if any(not isinstance(item, Mapping) for item in cards):
        raise TypeError("canonical blockbeats_cards must contain only mappings")
    for key in (
        "schema_version",
        "presentation_contract_version",
        "presentation_contract_sha256",
        "run_id",
        "run_sha256",
        "run_mode",
        "trading_date",
        "slot",
        "methodology_sha256",
        "report_contract_sha256",
        "evidence_snapshot_sha256",
        "reasoning_sha256",
        "decision_sha256",
    ):
        value = model.get(key)
        if type(value) is not str or not value.strip():
            raise TypeError(f"canonical report field must be non-empty text: {key}")
    for key in ("frontstage", "maker_summary", "main_summary", "audit"):
        if not isinstance(model.get(key), Mapping):
            raise TypeError(f"canonical report section must be a mapping: {key}")
    if type(bindings) is not ReportBindings:
        raise TypeError("canonical report bindings must be a ReportBindings")
    if bindings.schema_version != REGISTRY.report_bindings_schema_version:
        raise ValueError("canonical report bindings schema differs from the domain registry")
    metadata = ReportMetadata(
        schema_version=model["schema_version"],
        presentation_contract_version=model["presentation_contract_version"],
        presentation_contract_sha256=model["presentation_contract_sha256"],
        run_id=model["run_id"],
        run_sha256=model["run_sha256"],
        run_mode=model["run_mode"],
        execution_authorization=_freeze_record(
            authorization,
            path="execution_authorization",
        ),
        trading_date=model["trading_date"],
        slot=model["slot"],
        methodology_sha256=model["methodology_sha256"],
        report_contract_sha256=model["report_contract_sha256"],
        evidence_snapshot_sha256=model["evidence_snapshot_sha256"],
        reasoning_sha256=model["reasoning_sha256"],
        decision_sha256=model["decision_sha256"],
    )
    return CertifiedReportProjectionInput(
        metadata=metadata,
        bindings=bindings,
        blockbeats_cards=tuple(
            _freeze_record(item, path=f"blockbeats_cards[{index}]")
            for index, item in enumerate(cards)
        ),
        frontstage=_freeze_record(model["frontstage"], path="frontstage"),
        maker_summary=_freeze_record(
            model["maker_summary"], path="maker_summary"
        ),
        main_summary=_freeze_record(model["main_summary"], path="main_summary"),
        audit=_freeze_record(model["audit"], path="audit"),
    )


def build_report_bindings(
    reasoning: Mapping[str, Any],
) -> ReportBindings:
    """Derive report traceability from the certified reasoning support DAG."""

    observations = reasoning.get("observations")
    claims = reasoning.get("claims")
    if not isinstance(observations, list) or not isinstance(claims, list):
        raise TypeError("certified reasoning graph is missing observations or claims")
    observation_rows: list[Mapping[str, Any]] = []
    observation_by_id: dict[str, Mapping[str, Any]] = {}
    for row in observations:
        if not isinstance(row, Mapping):
            raise TypeError("certified reasoning observation must be a mapping")
        observation_id = row.get("id")
        if type(observation_id) is not str or not observation_id:
            raise TypeError("certified reasoning observation id is invalid")
        if observation_id in observation_by_id:
            raise ValueError("certified reasoning observation ids are not unique")
        observation_rows.append(row)
        observation_by_id[observation_id] = row

    claim_rows: list[Mapping[str, Any]] = []
    claim_by_id: dict[str, Mapping[str, Any]] = {}
    for row in claims:
        if not isinstance(row, Mapping):
            raise TypeError("certified reasoning claim must be a mapping")
        claim_id = row.get("id")
        if type(claim_id) is not str or not claim_id:
            raise TypeError("certified reasoning claim id is invalid")
        if claim_id in claim_by_id or claim_id in observation_by_id:
            raise ValueError("certified reasoning graph ids are not unique")
        claim_rows.append(row)
        claim_by_id[claim_id] = row

    def graph_closure(root_claim_ids: list[str]) -> tuple[set[str], set[str]]:
        reachable_claims: set[str] = set()
        reachable_observations: set[str] = set()
        pending = list(root_claim_ids)
        while pending:
            node_id = pending.pop()
            if node_id in observation_by_id:
                reachable_observations.add(node_id)
                continue
            row = claim_by_id.get(node_id)
            if row is None:
                raise ValueError(f"report binding references unknown graph id: {node_id}")
            if node_id in reachable_claims:
                continue
            reachable_claims.add(node_id)
            for field in ("support_ids", "counter_ids"):
                values = row.get(field)
                if not isinstance(values, list) or any(
                    type(value) is not str or not value for value in values
                ):
                    raise TypeError(
                        f"certified reasoning claim {field} is invalid: {node_id}"
                    )
                pending.extend(reversed(values))
        return reachable_claims, reachable_observations

    def section_binding(
        section_id: str,
        model_path: tuple[str, ...],
        root_claim_ids: list[str],
        *,
        forced_observation_ids: set[str] | None = None,
    ) -> ReportSectionBinding:
        reachable_claims, reachable_observations = graph_closure(root_claim_ids)
        reachable_observations.update(forced_observation_ids or set())
        ordered_claim_ids = tuple(
            str(row["id"])
            for row in claim_rows
            if row["id"] in reachable_claims
        )
        ordered_observation_ids = tuple(
            str(row["id"])
            for row in observation_rows
            if row["id"] in reachable_observations
        )
        evidence_refs: list[str] = []
        for observation_id in ordered_observation_ids:
            refs = observation_by_id[observation_id].get("evidence_refs")
            if not isinstance(refs, list) or any(
                type(value) is not str or not value for value in refs
            ):
                raise TypeError(
                    f"certified reasoning evidence_refs are invalid: {observation_id}"
                )
            for value in refs:
                if value not in evidence_refs:
                    evidence_refs.append(value)
        return ReportSectionBinding(
            section_id=section_id,
            model_path=model_path,
            claim_ids=ordered_claim_ids,
            observation_ids=ordered_observation_ids,
            evidence_refs=tuple(evidence_refs),
        )

    main_roots = [
        str(row["id"]) for row in claim_rows if row.get("account") == "main"
    ]
    maker_roots = [
        str(row["id"]) for row in claim_rows if row.get("account") == "maker"
    ]
    all_roots = [str(row["id"]) for row in claim_rows]
    blockbeats_observations = {
        str(row["id"]) for row in observation_rows if row.get("source") == "BlockBeats"
    }
    blockbeats_roots: list[str] = []
    for row in claim_rows:
        _, reachable_observations = graph_closure([str(row["id"])])
        if reachable_observations & blockbeats_observations:
            blockbeats_roots.append(str(row["id"]))

    section_inputs: dict[str, tuple[list[str], set[str] | None]] = {
        "blockbeats_cards": (blockbeats_roots, blockbeats_observations),
        "frontstage": (main_roots + maker_roots, None),
        "maker_summary": (maker_roots, None),
        "main_summary": (main_roots, None),
        "audit": (all_roots, None),
    }
    return ReportBindings(
        schema_version=REGISTRY.report_bindings_schema_version,
        sections=tuple(
            section_binding(
                section_id,
                model_path,
                section_inputs[section_id][0],
                forced_observation_ids=section_inputs[section_id][1],
            )
            for section_id, model_path in (
                REGISTRY.report_binding_section_model_paths
            )
        ),
    )


def certify_report_projection_input(
    *,
    evidence: dict[str, Any],
    reasoning: dict[str, Any],
    decision: dict[str, Any],
    methodology_sha256: str,
    report_contract_sha256: str,
    root: Path,
) -> CertifiedReportProjectionInput:
    """Run the bounded legacy certifier, then close the immutable projection seam."""

    model = invoke_legacy(
        LEGACY_CERTIFIER_DELEGATE,
        evidence=evidence,
        reasoning=reasoning,
        decision=decision,
        methodology_sha256=methodology_sha256,
        report_contract_sha256=report_contract_sha256,
        root=root,
    )
    if not isinstance(model, Mapping):
        raise TypeError("legacy report certifier did not return a mapping")
    return certify_canonical_report_model(
        model,
        bindings=build_report_bindings(reasoning),
    )


__all__ = [
    "CANONICAL_REPORT_FIELDS",
    "LEGACY_CERTIFIER_DELEGATE",
    "certify_canonical_report_model",
    "certify_report_projection_input",
    "build_report_bindings",
]
