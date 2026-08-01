"""Typed failure taxonomy for the vNext workflow.

Business-integrity failures stop the affected business stage.  Operational
failures are retryable at their own stage and never invalidate earlier
evidence or reasoning by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    EVIDENCE_INTEGRITY = "evidence_integrity"
    REASONING_CONSISTENCY = "reasoning_consistency"
    RISK_EXECUTION = "risk_execution"
    DELIVERY_INTEGRITY = "delivery_integrity"
    INFRASTRUCTURE_TRANSIENT = "infrastructure_transient"
    COMPILATION = "compilation"
    MANUAL_REVIEW = "manual_review"


class RetryScope(str, Enum):
    CAPTURE = "evidence"
    REASONING = "reasoning"
    DECISION = "decision"
    REPORT = "report"
    DELIVERY = "delivery"
    NONE = "none"


@dataclass(frozen=True)
class FailurePolicy:
    retryable: bool
    retry_scope: RetryScope
    invalidates: tuple[str, ...] = ()
    needs_manual_review: bool = False


FAILURE_POLICIES: dict[FailureClass, FailurePolicy] = {
    FailureClass.EVIDENCE_INTEGRITY: FailurePolicy(
        retryable=True,
        retry_scope=RetryScope.CAPTURE,
        invalidates=("reasoning", "decision", "report", "delivery"),
    ),
    FailureClass.REASONING_CONSISTENCY: FailurePolicy(
        retryable=True,
        retry_scope=RetryScope.REASONING,
        invalidates=("decision", "report", "delivery"),
    ),
    FailureClass.RISK_EXECUTION: FailurePolicy(
        retryable=True,
        retry_scope=RetryScope.DECISION,
        invalidates=("report", "delivery"),
    ),
    FailureClass.DELIVERY_INTEGRITY: FailurePolicy(
        retryable=True,
        retry_scope=RetryScope.DELIVERY,
    ),
    FailureClass.INFRASTRUCTURE_TRANSIENT: FailurePolicy(
        retryable=True,
        retry_scope=RetryScope.DELIVERY,
    ),
    FailureClass.COMPILATION: FailurePolicy(
        retryable=True,
        retry_scope=RetryScope.REPORT,
        invalidates=("delivery",),
    ),
    FailureClass.MANUAL_REVIEW: FailurePolicy(
        retryable=False,
        retry_scope=RetryScope.NONE,
        needs_manual_review=True,
    ),
}


class WorkflowFailure(RuntimeError):
    def __init__(
        self,
        failure_class: FailureClass,
        message: str,
        *,
        defects: list[dict] | None = None,
        retry_scope: RetryScope | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.defects = defects or []
        base = FAILURE_POLICIES[failure_class]
        self.policy = (
            FailurePolicy(
                retryable=base.retryable,
                retry_scope=retry_scope,
                invalidates=base.invalidates,
                needs_manual_review=base.needs_manual_review,
            )
            if retry_scope is not None
            else base
        )
