"""Closed domain vocabulary and canonical identity primitives.

This module is the dependency-light owner for values that every downstream
layer must share.  Keeping canonical serialization beside the closed string
types prevents registry, projections and compatibility adapters from growing
parallel identity implementations.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields
from decimal import Decimal
from enum import Enum
from typing import Any, TypeAlias


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=str)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return the sole canonical JSON representation for domain identity."""

    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Hash a typed value without allowing formatting or enum drift."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class DomainString(str, Enum):
    """JSON-compatible closed vocabulary value."""

    def __str__(self) -> str:
        return self.value


class Account(DomainString):
    SHARED = "shared"
    MAIN = "main"
    MAKER = "maker"


class EvidenceSource(DomainString):
    BLOCKBEATS = "BlockBeats"
    COINGLASS = "Coinglass"
    EXOCHARTS = "Exocharts"
    FEDWATCH = "FedWatch"
    FARSIDE = "Farside"
    TRADINGVIEW = "TradingView"


class ContractSource(DomainString):
    BLOCKBEATS = "BlockBeats"
    COINGLASS = "Coinglass"
    EXOCHARTS = "Exocharts"
    FEDWATCH = "FedWatch"
    FEDWATCH_PLAN_C = "FedWatchPlanC"
    FARSIDE = "Farside"
    TRADINGVIEW = "TradingView"


class ObservationKind(DomainString):
    STRUCTURED = "structured_observation"
    VISUAL = "visual_judgment"


class ClaimType(DomainString):
    CANNOT_DO = "cannot_do"
    CHART_INTERPRETATION = "chart_interpretation"
    ETF_CONFIRMATION = "etf_confirmation"
    FUNDAMENTAL_CONTEXT = "fundamental_context"
    FUNDAMENTAL_EVENT_REALIZATION = "fundamental_event_realization"
    FUNDAMENTAL_PRICE_REALIZATION = "fundamental_price_realization"
    INVALIDATION_PATH = "invalidation_path"
    LIQUIDATION_CONFIRMATION = "liquidation_confirmation"
    LIQUIDITY_HUNT = "liquidity_hunt"
    MAIN_ACCOUNT_THESIS = "main_account_thesis"
    MAKER_THESIS = "maker_thesis"
    MARKET_REGIME = "market_regime"
    ORDERFLOW_INTERPRETATION = "orderflow_interpretation"
    STRONGEST_COUNTEREVIDENCE = "strongest_counterevidence"


class ScenarioType(DomainString):
    BASE = "base"
    COUNTER = "counter"
    INVALIDATION = "invalidation"


class TriggerOperator(DomainString):
    BECOMES = "becomes"
    EQUALS = "equals"
    EQUALS_AT_TRIGGER = "equals_at_trigger"
    ONE_OF_AT_TRIGGER = "one_of_at_trigger"


class Direction(DomainString):
    LONG = "long"
    SHORT = "short"
    OBSERVE = "observe"
    NEUTRAL = "neutral"


class MakerPlanState(DomainString):
    QUALIFIED = "qualified"
    OBSERVE = "observe"


class EntryType(DomainString):
    LEFT = "left"
    RIGHT = "right"
    NOT_APPLICABLE = "not_applicable"


class OrderLifecycleState(DomainString):
    FILLABLE = "fillable"
    CANCEL_BLOCKS_ALL_ENTRIES = "cancel_blocks_all_entries"
    ENTRY_BEFORE_CANCEL = "entry_before_cancel"
    INVALID_GEOMETRY = "invalid_geometry"
    NOT_APPLICABLE_NO_CANDIDATE_GEOMETRY = (
        "not_applicable_no_candidate_geometry"
    )


class ReachDirection(DomainString):
    UP_TO_ENTRY = "up_to_entry"
    DOWN_TO_ENTRY = "down_to_entry"
    AT_ENTRY = "at_entry"


class EvidenceEffect(DomainString):
    SUPPORT = "support"
    COUNTER = "counter"
    NEUTRAL = "neutral"


class MakerSemanticState(DomainString):
    QUALIFIED_CANDIDATE = "qualified_candidate"
    REJECTED_SUBMITTED_CANDIDATE = "rejected_submitted_candidate"
    DIRECTIONAL_THESIS_ONLY = "directional_thesis_only"
    NON_DIRECTIONAL_OBSERVATION = "non_directional_observation"


class ContinuityAction(DomainString):
    NEW = "new"
    KEEP = "keep"
    CANCEL_REPLACE = "cancel_replace"
    CANCEL = "cancel"
    OBSERVE = "observe"
    RECONCILE_FILLED = "reconcile_filled"


class ContinuityPriorStatus(DomainString):
    NONE = "none"
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    STOPPED = "stopped"
    EXPIRED = "expired"


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
        _require_string_tuple(self.observation_ids, "report section observation_ids")
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
                    f"report bindings sections[{index}] must be a ReportSectionBinding"
                )
            section_ids.append(item.section_id)
            model_paths.append(item.model_path)
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("report binding section ids must be unique")
        if len(set(model_paths)) != len(model_paths):
            raise ValueError("report binding model paths must be unique")
        actual = tuple((item.section_id, item.model_path) for item in self.sections)
        from .registry import REGISTRY

        if actual != REGISTRY.report_binding_section_model_paths:
            raise ValueError(
                "report bindings must exactly cover the required section/model paths"
            )


@dataclass(frozen=True, slots=True)
class CertifiedReportProjectionInput:
    """Complete certified input accepted by the pure report projector."""

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
                raise TypeError(f"blockbeats_cards[{index}] must be a ReportRecord")
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
    """Deep-copy a boundary value into deterministic plain primitives."""

    if type(value) is ReportRecord:
        return {item.name: to_plain(item.value) for item in value.fields}
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
    raise TypeError(f"unsupported report projection value: {type(value).__name__}")
