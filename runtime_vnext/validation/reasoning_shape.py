"""Reasoning-shape facade pending extraction from the full reasoning gate."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .common import GateResultLike, LegacyDelegate, invoke_legacy


LEGACY_DELEGATE = LegacyDelegate(
    stage="reasoning",
    domain="shape",
    module="runtime_vnext.gates",
    callable_name="evaluate_reasoning",
    coverage="full_stage",
)


def validate_reasoning_shape(
    payload: dict[str, Any],
    *,
    evidence: dict[str, Any],
    reasoning_authority_sha256: str,
    evidence_root: Path | None = None,
    methodology_root: Path | None = None,
    visual_review_not_after: datetime | None = None,
) -> GateResultLike:
    """Delegate to the unchanged full reasoning gate.

    The result intentionally includes semantic and graph defects until the
    production implementation is physically extracted.  Callers must not
    interpret it as shape-only coverage yet.
    """

    return cast(
        GateResultLike,
        invoke_legacy(
            LEGACY_DELEGATE,
            payload,
            evidence=evidence,
            reasoning_authority_sha256=reasoning_authority_sha256,
            evidence_root=evidence_root,
            methodology_root=methodology_root,
            visual_review_not_after=visual_review_not_after,
        ),
    )


__all__ = ["LEGACY_DELEGATE", "validate_reasoning_shape"]
