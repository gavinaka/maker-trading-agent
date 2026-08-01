"""Reasoning semantic-certification facade."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .common import LegacyDelegate, SemanticIssueLike, invoke_legacy


LEGACY_DELEGATE = LegacyDelegate(
    stage="reasoning",
    domain="semantics",
    module="runtime_vnext.semantic_validation",
    callable_name="validate_reasoning_semantics",
    coverage="domain",
)


def validate_reasoning_semantics(
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    *,
    evidence: dict[str, Any],
    root: Path,
    full_policy: dict[str, Any],
    methodology: Any,
    submission_contract: dict[str, Any],
    visual_review_not_after: datetime | None = None,
) -> list[SemanticIssueLike]:
    """Run the unchanged domain semantic validator."""

    return cast(
        list[SemanticIssueLike],
        invoke_legacy(
            LEGACY_DELEGATE,
            observations,
            claims,
            evidence=evidence,
            root=root,
            full_policy=full_policy,
            methodology=methodology,
            submission_contract=submission_contract,
            visual_review_not_after=visual_review_not_after,
        ),
    )


__all__ = ["LEGACY_DELEGATE", "validate_reasoning_semantics"]
