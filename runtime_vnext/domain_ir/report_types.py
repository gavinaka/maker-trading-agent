"""Immutable, I/O-free types at the certified report projection boundary.

The boundary accepts only already-certified report values.  It intentionally
has no raw evidence, reasoning or decision payload field and performs no
market interpretation, risk arithmetic, artifact loading or rendering side
effects.  Consumers may turn these immutable values into fresh plain
primitives with :func:`to_plain` immediately before serialization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import TypeAlias

from .registry import REGISTRY


ReportScalar: TypeAlias = None | bool | int | float | str | Decimal


def _require_text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise TypeError(f"{label} must be a non-empty string")


def _require_string_tuple(value: object, label: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{label} must be a tuple")
    for index, item in enumerate(value):
        _require_text(item, f"{label}[{index}]")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")


def _validate_scalar(value: object, label: str) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{label} must be finite")
        return
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError(f"{label} must be finite")
        return
    raise TypeError(f"{label} must contain only immutable report values")


@dataclass(frozen=True, slots=True)
class ReportField:
    """One ordered field in a certified immutable report record."""

    name: str
    value: ReportValue

    def __post_init__(self) -> None:
        _require_text(self.name, "report field name")
        _validate_report_value(self.value, f"report field {self.name!r}")


@dataclass(frozen=True, slots=True)
class ReportRecord:
    """An insertion-ordered immutable replacement for an untyped mapping."""

    fields: tuple[ReportField, ...] = ()

    def __post_init__(self) -> None:
        if type(self.fields) is not tuple:
            raise TypeError("report record fields must be a tuple")
        names: list[str] = []
        for index, item in enumerate(self.fields):
            if type(item) is not ReportField:
                raise TypeError(
                    f"report record fields[{index}] must be a ReportField"
                )
            names.append(item.name)
        if len(set(names)) != len(names):
            raise ValueError("report record field names must be unique")

    def get(self, name: str) -> ReportValue | None:
        """Return an immutable field value without exposing a mapping."""

        for item in self.fields:
            if item.name == name:
                return item.value
        return None


ReportValue: TypeAlias = ReportScalar | ReportRecord | tuple["ReportValue", ...]


def _validate_report_value(value: object, label: str) -> None:
    if type(value) is ReportRecord:
        return
    if type(value) is tuple:
        for index, item in enumerate(value):
            _validate_report_value(item, f"{label}[{index}]")
        return
    _validate_scalar(value, label)


@dataclass(frozen=True, slots=True)
class ReportMetadata:
    """Certified identities required to bind one report to one immutable run."""

    schema_version: str
    presentation_contract_version: str
    presentation_contract_sha256: str
    run_id: str
    run_sha256: str
    run_mode: str
    execution_authorization: ReportRecord
    trading_date: str
    slot: str
    methodology_sha256: str
    report_contract_sha256: str
    evidence_snapshot_sha256: str
    reasoning_sha256: str
    decision_sha256: str

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "execution_authorization":
                if type(value) is not ReportRecord:
                    raise TypeError(
                        "execution_authorization must be a ReportRecord"
                    )
                continue
            _require_text(value, f"report metadata {item.name}")


@dataclass(frozen=True, slots=True)
class ReportSectionBinding:
    """Traceability binding for one already-certified report section."""

    section_id: str
    model_path: tuple[str, ...]
    claim_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.section_id, "report section binding id")
        _require_string_tuple(self.model_path, "report section model_path")
        if not self.model_path:
            raise ValueError("report section model_path must not be empty")
        _require_string_tuple(self.claim_ids, "report section claim_ids")
        _require_string_tuple(
            self.observation_ids,
            "report section observation_ids",
        )
        _require_string_tuple(self.evidence_refs, "report section evidence_refs")


@dataclass(frozen=True, slots=True)
class ReportBindings:
    """Ordered traceability bindings; never a second semantic owner."""

    schema_version: str
    sections: tuple[ReportSectionBinding, ...]

    def __post_init__(self) -> None:
        _require_text(self.schema_version, "report bindings schema_version")
        if type(self.sections) is not tuple:
            raise TypeError("report bindings sections must be a tuple")
        section_ids: list[str] = []
        model_paths: list[tuple[str, ...]] = []
        for index, item in enumerate(self.sections):
            if type(item) is not ReportSectionBinding:
                raise TypeError(
                    "report bindings sections"
                    f"[{index}] must be a ReportSectionBinding"
                )
            section_ids.append(item.section_id)
            model_paths.append(item.model_path)
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("report binding section ids must be unique")
        if len(set(model_paths)) != len(model_paths):
            raise ValueError("report binding model paths must be unique")
        actual = tuple(
            (item.section_id, item.model_path)
            for item in self.sections
        )
        if actual != REGISTRY.report_binding_section_model_paths:
            raise ValueError(
                "report bindings must exactly cover the required section/model paths"
            )


@dataclass(frozen=True, slots=True)
class CertifiedReportProjectionInput:
    """The complete typed input accepted by a future pure report projector.

    Every value below is a certified projection.  The class deliberately
    exposes the exact report surfaces instead of accepting generic upstream
    payloads.
    """

    metadata: ReportMetadata
    bindings: ReportBindings
    blockbeats_cards: tuple[ReportRecord, ...]
    frontstage: ReportRecord
    maker_summary: ReportRecord
    main_summary: ReportRecord
    audit: ReportRecord

    def __post_init__(self) -> None:
        if type(self.metadata) is not ReportMetadata:
            raise TypeError("metadata must be ReportMetadata")
        if type(self.bindings) is not ReportBindings:
            raise TypeError("bindings must be ReportBindings")
        if type(self.blockbeats_cards) is not tuple:
            raise TypeError("blockbeats_cards must be a tuple")
        for index, card in enumerate(self.blockbeats_cards):
            if type(card) is not ReportRecord:
                raise TypeError(
                    f"blockbeats_cards[{index}] must be a ReportRecord"
                )
        for name in ("frontstage", "maker_summary", "main_summary", "audit"):
            if type(getattr(self, name)) is not ReportRecord:
                raise TypeError(f"{name} must be a ReportRecord")


@dataclass(frozen=True, slots=True)
class ProjectedReport:
    """Pure in-memory report outputs, before artifact persistence or delivery."""

    model: ReportRecord
    markdown: str
    cards_spec: ReportRecord

    def __post_init__(self) -> None:
        if type(self.model) is not ReportRecord:
            raise TypeError("projected report model must be a ReportRecord")
        if type(self.markdown) is not str:
            raise TypeError("projected report markdown must be a string")
        if type(self.cards_spec) is not ReportRecord:
            raise TypeError("projected report cards_spec must be a ReportRecord")


_BOUNDARY_DATACLASSES = (
    ReportField,
    ReportMetadata,
    ReportSectionBinding,
    ReportBindings,
    CertifiedReportProjectionInput,
    ProjectedReport,
)


def to_plain(value: object) -> object:
    """Deep-copy a boundary value into deterministic plain primitives.

    Dataclass declaration order, record field order and tuple order are kept.
    ``Decimal`` values become exact base-10 strings; no value is inferred,
    sorted or recalculated.
    """

    if type(value) is ReportRecord:
        return {
            item.name: to_plain(item.value)
            for item in value.fields
        }
    if type(value) in _BOUNDARY_DATACLASSES:
        return {
            item.name: to_plain(getattr(value, item.name))
            for item in fields(value)
        }
    if type(value) is tuple:
        return [to_plain(item) for item in value]
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("report Decimal must be finite")
        return format(value, "f")
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("report float must be finite")
        return value
    if value is None or type(value) in {bool, int, str}:
        return value
    raise TypeError(
        f"unsupported report projection value: {type(value).__name__}"
    )


__all__ = [
    "CertifiedReportProjectionInput",
    "ProjectedReport",
    "ReportBindings",
    "ReportField",
    "ReportMetadata",
    "ReportRecord",
    "ReportScalar",
    "ReportSectionBinding",
    "ReportValue",
    "to_plain",
]
