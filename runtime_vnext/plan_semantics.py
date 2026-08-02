"""Deterministic Maker candidate semantics.

This module deliberately owns only closed geometry and failure ordering.  It
does not decide whether a trade should be taken and it never mutates runtime
state.  The decision gate supplies already-certified typed inputs and seals the
result as part of the decision attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from .domain_ir.registry import (
    CANNOT_DO_ABSOLUTE_DIRECTION_CONFLICTS,
    CANNOT_DO_BOTH_PURSUIT,
    CANNOT_DO_PURSUIT_DIRECTION,
    DIRECTIONAL_DIRECTIONS,
    ENTRY_TYPES,
    EVIDENCE_DIRECTIONS,
    EVIDENCE_SUBJECT_DIRECTIONS,
    MAKER_DIRECTIONS,
    MAKER_FAILURE_ORDER,
    MAKER_PLAN_STATES,
    MAKER_SEMANTIC_STATES,
    ORDER_LIFECYCLE_APPLICABILITY,
    ORDER_LIFECYCLE_PATH_FLAGS,
    REGISTRY,
)
from .domain_ir.types import (
    Direction,
    EntryType,
    EvidenceEffect,
    MakerPlanState,
    MakerSemanticState,
    OrderLifecycleState,
    ReachDirection,
)

FAILURE_ORDER = MAKER_FAILURE_ORDER
QUALIFIED_CANDIDATE = MakerSemanticState.QUALIFIED_CANDIDATE.value
REJECTED_SUBMITTED_CANDIDATE = (
    MakerSemanticState.REJECTED_SUBMITTED_CANDIDATE.value
)
DIRECTIONAL_THESIS_ONLY = MakerSemanticState.DIRECTIONAL_THESIS_ONLY.value
NON_DIRECTIONAL_OBSERVATION = MakerSemanticState.NON_DIRECTIONAL_OBSERVATION.value


@dataclass(frozen=True)
class MakerCandidateAssessment:
    """Closed constructibility result ordered from structure to execution."""

    failure_codes: tuple[str, ...]

    @property
    def constructible(self) -> bool:
        return not self.failure_codes

    @property
    def status(self) -> str:
        return "constructible" if self.constructible else "not_constructible"

    @property
    def primary_reason_code(self) -> str:
        return "constructible" if self.constructible else self.failure_codes[0]


@dataclass(frozen=True)
class MakerOrderLifecycle:
    """Closed pre-fill order lifecycle derived from price geometry only."""

    state: str
    legal_fill_path_exists: bool
    legal_cancel_path_exists: bool
    fill_probability: None = None

    @property
    def fill_probability_applicability(self) -> str:
        return ORDER_LIFECYCLE_APPLICABILITY[self.state]

    @property
    def reason_code(self) -> str:
        return self.state

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": REGISTRY.maker_order_lifecycle_schema_version,
            "state": self.state,
            "legal_fill_path_exists": self.legal_fill_path_exists,
            "legal_cancel_path_exists": self.legal_cancel_path_exists,
            "fill_probability": self.fill_probability,
            "fill_probability_applicability": self.fill_probability_applicability,
            "reason_code": self.reason_code,
        }


def _order_lifecycle_for_state(
    state: OrderLifecycleState,
) -> MakerOrderLifecycle:
    """Build one lifecycle result from the registry-owned path flags."""

    flags = ORDER_LIFECYCLE_PATH_FLAGS[state.value]
    if (
        set(flags) != {
            "legal_fill_path_exists",
            "legal_cancel_path_exists",
        }
        or type(flags["legal_fill_path_exists"]) is not bool
        or type(flags["legal_cancel_path_exists"]) is not bool
    ):
        raise RuntimeError("order lifecycle registry path flags are invalid")
    return MakerOrderLifecycle(
        state=state.value,
        legal_fill_path_exists=flags["legal_fill_path_exists"],
        legal_cancel_path_exists=flags["legal_cancel_path_exists"],
    )


@dataclass(frozen=True)
class EvidencePolarity:
    """Gate-owned effect of one typed evidence direction on one thesis."""

    subject_direction: str
    evidence_direction: str
    effect: str
    effect_basis_code: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schema_version": REGISTRY.evidence_polarity_schema_version,
            "subject_direction": self.subject_direction,
            "evidence_direction": self.evidence_direction,
            "effect": self.effect,
            "effect_basis_code": self.effect_basis_code,
        }


def classify_maker_semantic_state(
    *,
    plan_state: Any,
    direction: Any,
    plan_constructible: Any,
    threshold_eligible: Any,
    risk_plan: Any,
    defense_plan: Any,
    position_notional_usdt: Any,
    entry_type: Any,
    order_lifecycle_state: Any,
    entry_reach_probability_applicability: Any,
    constructibility_reason: Any,
) -> str:
    """Classify the four closed Maker states from already-typed decision facts.

    A directional thesis is not a candidate submission.  Candidate existence is
    owned by a non-empty ``risk_plan``; a zone reference or a long/short thesis
    alone cannot promote an observation into a plan.  Empty-risk states also
    fail closed if any execution-only field survives.
    """

    if plan_state not in MAKER_PLAN_STATES:
        raise ValueError("Maker plan_state must be qualified or observe")
    if direction not in MAKER_DIRECTIONS:
        raise ValueError("Maker direction must be long, short or observe")
    if type(plan_constructible) is not bool:
        raise ValueError("Maker plan_constructible must be a boolean")
    if type(threshold_eligible) is not bool:
        raise ValueError("Maker threshold_eligible must be a boolean")
    if not isinstance(risk_plan, dict):
        raise ValueError("Maker risk_plan must be an object")
    if not isinstance(defense_plan, dict):
        raise ValueError("Maker defense_plan must be an object")

    candidate_submitted = bool(risk_plan)
    if plan_state == MakerPlanState.QUALIFIED.value:
        if (
            direction not in DIRECTIONAL_DIRECTIONS
            or not candidate_submitted
            or plan_constructible is not True
            or threshold_eligible is not True
            or not defense_plan
            or position_notional_usdt is None
            or entry_type not in ENTRY_TYPES
            or order_lifecycle_state != OrderLifecycleState.FILLABLE.value
            or entry_reach_probability_applicability != "applicable"
        ):
            raise ValueError(
                "qualified Maker state conflicts with its typed candidate fields"
            )
        return QUALIFIED_CANDIDATE

    if candidate_submitted:
        if direction not in DIRECTIONAL_DIRECTIONS:
            raise ValueError("a submitted Maker candidate requires long or short")
        if plan_constructible is True and threshold_eligible is True:
            raise ValueError(
                "a fully eligible constructible Maker candidate cannot remain observe"
            )
        return REJECTED_SUBMITTED_CANDIDATE

    ghost_fields = (
        position_notional_usdt is not None
        or bool(defense_plan)
        or entry_type != EntryType.NOT_APPLICABLE.value
        or order_lifecycle_state
        != OrderLifecycleState.NOT_APPLICABLE_NO_CANDIDATE_GEOMETRY.value
        or entry_reach_probability_applicability
        != "not_applicable_no_certified_entry_geometry"
    )
    if ghost_fields:
        raise ValueError(
            "a Maker state without submitted risk input contains candidate-only fields"
        )
    if plan_constructible is not False:
        raise ValueError("a Maker state without submitted risk input is not constructible")
    if direction == Direction.OBSERVE.value:
        if constructibility_reason != "non_directional_thesis":
            raise ValueError(
                "a non-directional Maker observation requires non_directional_thesis"
            )
        return NON_DIRECTIONAL_OBSERVATION
    if constructibility_reason == "non_directional_thesis":
        raise ValueError(
            "a directional Maker thesis cannot use non_directional_thesis"
        )
    return DIRECTIONAL_THESIS_ONLY


def assess_candidate(*, failed_checks: Iterable[str]) -> MakerCandidateAssessment:
    """Return every known failure in authority order without short-circuiting."""

    supplied = {str(value) for value in failed_checks}
    unknown = supplied - set(FAILURE_ORDER)
    if unknown:
        raise ValueError(f"unknown Maker semantic failure code(s): {sorted(unknown)}")
    return MakerCandidateAssessment(
        tuple(code for code in FAILURE_ORDER if code in supplied)
    )


def expected_reach_direction(
    reference_price: Decimal | None,
    reference_entry: Decimal | None,
) -> str | None:
    if reference_price is None or reference_entry is None:
        return None
    if reference_entry > reference_price:
        return ReachDirection.UP_TO_ENTRY.value
    if reference_entry < reference_price:
        return ReachDirection.DOWN_TO_ENTRY.value
    return ReachDirection.AT_ENTRY.value


def classify_evidence_polarity(
    *,
    subject_direction: str,
    evidence_direction: str,
) -> EvidencePolarity:
    """Compare closed directional evidence with a directional or observe thesis.

    For a non-directional thesis, a directional owner is counterevidence to
    remaining neutral/observe, while neutral evidence supports that state.
    The reasoning Gate separately requires all clauses of one non-directional
    strongest counter to point toward one coherent alternative direction.
    """

    if subject_direction not in EVIDENCE_SUBJECT_DIRECTIONS:
        raise ValueError("subject_direction must be long, short, neutral or observe")
    if evidence_direction not in EVIDENCE_DIRECTIONS:
        raise ValueError("evidence_direction must be long, short or neutral")
    if subject_direction in {Direction.NEUTRAL.value, Direction.OBSERVE.value}:
        if evidence_direction == Direction.NEUTRAL.value:
            effect = EvidenceEffect.SUPPORT.value
            basis = "typed_neutral_evidence_matches_non_directional_subject"
        else:
            effect = EvidenceEffect.COUNTER.value
            basis = "typed_directional_evidence_opposes_non_directional_subject"
    elif evidence_direction == Direction.NEUTRAL.value:
        effect = EvidenceEffect.NEUTRAL.value
        basis = "typed_evidence_has_no_absolute_account_direction"
    elif evidence_direction == subject_direction:
        effect = EvidenceEffect.SUPPORT.value
        basis = "typed_evidence_direction_matches_subject"
    else:
        effect = EvidenceEffect.COUNTER.value
        basis = "typed_evidence_direction_opposes_subject"
    return EvidencePolarity(
        subject_direction=subject_direction,
        evidence_direction=evidence_direction,
        effect=effect,
        effect_basis_code=basis,
    )


def structural_noise_stop_is_outside(
    *,
    direction: str,
    anchor_price: Decimal | None,
    noise_outer_boundary: Decimal | None,
    price_distance: Decimal | None,
) -> bool:
    """Prove a direction-aware stop lies strictly beyond visible noise."""

    if (
        direction not in DIRECTIONAL_DIRECTIONS
        or anchor_price is None
        or noise_outer_boundary is None
        or price_distance is None
        or anchor_price <= 0
        or noise_outer_boundary <= 0
        or price_distance <= 0
    ):
        return False
    if direction == Direction.SHORT.value:
        return anchor_price + price_distance > noise_outer_boundary >= anchor_price
    return anchor_price - price_distance < noise_outer_boundary <= anchor_price


def resting_maker_order_valid(
    *,
    direction: str,
    reference_price: Decimal | None,
    entries: Iterable[Decimal | None],
) -> bool:
    """A Maker candidate must rest away from current price, never cross it."""

    values = tuple(entries)
    if reference_price is None or not values or any(value is None for value in values):
        return False
    clean = tuple(value for value in values if value is not None)
    if direction == Direction.SHORT.value:
        return all(value > reference_price for value in clean)
    if direction == Direction.LONG.value:
        return all(value < reference_price for value in clean)
    return False


def assess_order_lifecycle(
    *,
    reference_price: Decimal | None,
    cancel_price: Decimal | None,
    entries: Iterable[Decimal | None],
) -> MakerOrderLifecycle:
    """Classify whether a resting ladder has a legal fill and pre-fill cancel.

    A valid pre-fill cancel must live on the branch opposite the current-to-
    entry path.  A same-branch cancel either prevents every fill or occurs only
    after at least one fill; neither is a valid pre-fill lifecycle.
    """

    values = tuple(entries)
    if (
        reference_price is None
        or cancel_price is None
        or not values
    ):
        return _order_lifecycle_for_state(
            OrderLifecycleState.NOT_APPLICABLE_NO_CANDIDATE_GEOMETRY
        )
    if (
        reference_price <= 0
        or cancel_price <= 0
        or any(value is not None and value <= 0 for value in values)
    ):
        return _order_lifecycle_for_state(OrderLifecycleState.INVALID_GEOMETRY)
    if (
        cancel_price == reference_price
        or any(value is None or value == reference_price for value in values)
    ):
        return _order_lifecycle_for_state(OrderLifecycleState.INVALID_GEOMETRY)
    clean = tuple(value for value in values if value is not None)
    if cancel_price in clean:
        return _order_lifecycle_for_state(OrderLifecycleState.INVALID_GEOMETRY)
    entry_sides = {
        "above" if value > reference_price else "below" for value in clean
    }
    if len(entry_sides) != 1:
        return _order_lifecycle_for_state(OrderLifecycleState.INVALID_GEOMETRY)
    entry_side = next(iter(entry_sides))
    cancel_side = "above" if cancel_price > reference_price else "below"
    if cancel_side != entry_side:
        return _order_lifecycle_for_state(OrderLifecycleState.FILLABLE)
    cancel_distance = abs(cancel_price - reference_price)
    nearest_entry_distance = min(abs(value - reference_price) for value in clean)
    if cancel_distance < nearest_entry_distance:
        return _order_lifecycle_for_state(
            OrderLifecycleState.CANCEL_BLOCKS_ALL_ENTRIES
        )
    return _order_lifecycle_for_state(OrderLifecycleState.ENTRY_BEFORE_CANCEL)


def cancel_precedes_any_fill(
    *,
    reference_price: Decimal | None,
    cancel_price: Decimal | None,
    entries: Iterable[Decimal | None],
) -> bool:
    """Compatibility helper: only an opposite-branch cancel is valid."""

    return assess_order_lifecycle(
        reference_price=reference_price,
        cancel_price=cancel_price,
        entries=entries,
    ).state == OrderLifecycleState.FILLABLE.value


def structure_zone_role_valid(
    *,
    direction: str,
    zone_kind: str,
    zone_role: str | None,
    allowed_roles: dict[str, Iterable[str]],
) -> bool:
    """Manual profile zones stay direction-neutral; structure zones do not."""

    if zone_kind == "manual_profile":
        return True
    if zone_kind != "structure_zone":
        return False
    return bool(zone_role and zone_role in set(allowed_roles.get(direction, ())))


def cannot_do_conflicts(
    *,
    cannot_do_code: str,
    direction: str,
    entry_type: str,
    resting_order_valid: bool | None,
) -> bool:
    if (cannot_do_code, direction) in CANNOT_DO_ABSOLUTE_DIRECTION_CONFLICTS:
        return True
    right_side_or_marketable = (
        entry_type == EntryType.RIGHT.value or resting_order_valid is False
    )
    if (
        CANNOT_DO_PURSUIT_DIRECTION.get(cannot_do_code) == direction
        and right_side_or_marketable
    ):
        return True
    return (
        cannot_do_code == CANNOT_DO_BOTH_PURSUIT
        and direction in DIRECTIONAL_DIRECTIONS
        and right_side_or_marketable
    )
