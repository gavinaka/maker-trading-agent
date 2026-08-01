"""Closed string types for the deterministic vNext domain vocabulary."""

from __future__ import annotations

from enum import Enum


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
