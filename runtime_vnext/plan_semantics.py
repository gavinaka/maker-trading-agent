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


FAILURE_ORDER: tuple[str, ...] = (
    "non_directional_thesis",
    "no_certified_entry_zone",
    "entry_zone_binding_invalid",
    "entry_zone_role_invalid",
    "maker_order_marketable",
    "entry_semantics_invalid",
    "cannot_do_conflict",
    "order_lifecycle_invalid",
    "structural_stop_invalid",
    "risk_math_invalid",
    "defense_trigger_invalid",
)

ORDER_LIFECYCLE_SCHEMA_VERSION = "maker-order-lifecycle-v1"
EVIDENCE_POLARITY_SCHEMA_VERSION = "evidence-polarity-v1"
QUALIFIED_CANDIDATE = "qualified_candidate"
REJECTED_SUBMITTED_CANDIDATE = "rejected_submitted_candidate"
DIRECTIONAL_THESIS_ONLY = "directional_thesis_only"
NON_DIRECTIONAL_OBSERVATION = "non_directional_observation"
MAKER_SEMANTIC_STATES = frozenset(
    {
        QUALIFIED_CANDIDATE,
        REJECTED_SUBMITTED_CANDIDATE,
        DIRECTIONAL_THESIS_ONLY,
        NON_DIRECTIONAL_OBSERVATION,
    }
)


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
        return {
            "fillable": "not_estimated_lifecycle_only",
            "cancel_blocks_all_entries": "not_applicable_no_legal_fill_path",
            "entry_before_cancel": "not_applicable_invalid_prefill_cancel",
            "invalid_geometry": "not_applicable_invalid_geometry",
            "not_applicable_no_candidate_geometry": "not_applicable_no_candidate_geometry",
        }[self.state]

    @property
    def reason_code(self) -> str:
        return self.state

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": ORDER_LIFECYCLE_SCHEMA_VERSION,
            "state": self.state,
            "legal_fill_path_exists": self.legal_fill_path_exists,
            "legal_cancel_path_exists": self.legal_cancel_path_exists,
            "fill_probability": self.fill_probability,
            "fill_probability_applicability": self.fill_probability_applicability,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class EvidencePolarity:
    """Gate-owned effect of one typed evidence direction on one thesis."""

    subject_direction: str
    evidence_direction: str
    effect: str
    effect_basis_code: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schema_version": EVIDENCE_POLARITY_SCHEMA_VERSION,
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

    if plan_state not in {"qualified", "observe"}:
        raise ValueError("Maker plan_state must be qualified or observe")
    if direction not in {"long", "short", "observe"}:
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
    if plan_state == "qualified":
        if (
            direction not in {"long", "short"}
            or not candidate_submitted
            or plan_constructible is not True
            or threshold_eligible is not True
            or not defense_plan
            or position_notional_usdt is None
            or entry_type not in {"left", "right"}
            or order_lifecycle_state != "fillable"
            or entry_reach_probability_applicability != "applicable"
        ):
            raise ValueError(
                "qualified Maker state conflicts with its typed candidate fields"
            )
        return QUALIFIED_CANDIDATE

    if candidate_submitted:
        if direction not in {"long", "short"}:
            raise ValueError("a submitted Maker candidate requires long or short")
        if plan_constructible is True and threshold_eligible is True:
            raise ValueError(
                "a fully eligible constructible Maker candidate cannot remain observe"
            )
        return REJECTED_SUBMITTED_CANDIDATE

    ghost_fields = (
        position_notional_usdt is not None
        or bool(defense_plan)
        or entry_type != "not_applicable"
        or order_lifecycle_state != "not_applicable_no_candidate_geometry"
        or entry_reach_probability_applicability
        != "not_applicable_no_certified_entry_geometry"
    )
    if ghost_fields:
        raise ValueError(
            "a Maker state without submitted risk input contains candidate-only fields"
        )
    if plan_constructible is not False:
        raise ValueError("a Maker state without submitted risk input is not constructible")
    if direction == "observe":
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
        return "up_to_entry"
    if reference_entry < reference_price:
        return "down_to_entry"
    return "at_entry"


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

    if subject_direction not in {"long", "short", "neutral", "observe"}:
        raise ValueError("subject_direction must be long, short, neutral or observe")
    if evidence_direction not in {"long", "short", "neutral"}:
        raise ValueError("evidence_direction must be long, short or neutral")
    if subject_direction in {"neutral", "observe"}:
        if evidence_direction == "neutral":
            effect = "support"
            basis = "typed_neutral_evidence_matches_non_directional_subject"
        else:
            effect = "counter"
            basis = "typed_directional_evidence_opposes_non_directional_subject"
    elif evidence_direction == "neutral":
        effect = "neutral"
        basis = "typed_evidence_has_no_absolute_account_direction"
    elif evidence_direction == subject_direction:
        effect = "support"
        basis = "typed_evidence_direction_matches_subject"
    else:
        effect = "counter"
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
        direction not in {"long", "short"}
        or anchor_price is None
        or noise_outer_boundary is None
        or price_distance is None
        or anchor_price <= 0
        or noise_outer_boundary <= 0
        or price_distance <= 0
    ):
        return False
    if direction == "short":
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
    if direction == "short":
        return all(value > reference_price for value in clean)
    if direction == "long":
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
        return MakerOrderLifecycle(
            "not_applicable_no_candidate_geometry", False, False
        )
    if (
        reference_price <= 0
        or cancel_price <= 0
        or any(value is not None and value <= 0 for value in values)
    ):
        return MakerOrderLifecycle("invalid_geometry", False, False)
    if (
        cancel_price == reference_price
        or any(value is None or value == reference_price for value in values)
    ):
        return MakerOrderLifecycle("invalid_geometry", False, False)
    clean = tuple(value for value in values if value is not None)
    if cancel_price in clean:
        return MakerOrderLifecycle("invalid_geometry", False, False)
    entry_sides = {
        "above" if value > reference_price else "below" for value in clean
    }
    if len(entry_sides) != 1:
        return MakerOrderLifecycle("invalid_geometry", False, False)
    entry_side = next(iter(entry_sides))
    cancel_side = "above" if cancel_price > reference_price else "below"
    if cancel_side != entry_side:
        return MakerOrderLifecycle("fillable", True, True)
    cancel_distance = abs(cancel_price - reference_price)
    nearest_entry_distance = min(abs(value - reference_price) for value in clean)
    if cancel_distance < nearest_entry_distance:
        return MakerOrderLifecycle("cancel_blocks_all_entries", False, True)
    return MakerOrderLifecycle("entry_before_cancel", True, False)


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
    ).state == "fillable"


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
    if (cannot_do_code, direction) in {("做多", "long"), ("做空", "short")}:
        return True
    right_side_or_marketable = entry_type == "right" or resting_order_valid is False
    if cannot_do_code == "追多" and direction == "long" and right_side_or_marketable:
        return True
    if cannot_do_code == "追空" and direction == "short" and right_side_or_marketable:
        return True
    return (
        cannot_do_code == "追多空"
        and direction in {"long", "short"}
        and right_side_or_marketable
    )
