"""Evidence-stage validation facade over the existing production owners."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .common import GateResultLike, LegacyDelegate, SemanticIssueLike, invoke_legacy


LEGACY_GATE_DELEGATE = LegacyDelegate(
    stage="evidence",
    domain="evidence",
    module="runtime_vnext.gates",
    callable_name="evaluate_evidence",
    coverage="full_stage",
)
LEGACY_VISUAL_DELEGATE = LegacyDelegate(
    stage="evidence",
    domain="visual_artifacts",
    module="runtime_vnext.semantic_validation",
    callable_name="validate_visual_artifacts",
    coverage="domain",
)
LEGACY_PROFILE_DELEGATE = LegacyDelegate(
    stage="evidence",
    domain="tradingview_profile_capture_binding",
    module="runtime_vnext.semantic_validation",
    callable_name="validate_tradingview_profile_capture_binding",
    coverage="domain",
)


def validate_evidence(
    payload: dict[str, Any],
    *,
    root: Path | None = None,
    expected_contract_sha256: str | None = None,
) -> GateResultLike:
    """Run the unchanged full evidence gate through its extraction seam."""

    return cast(
        GateResultLike,
        invoke_legacy(
            LEGACY_GATE_DELEGATE,
            payload,
            root=root,
            expected_contract_sha256=expected_contract_sha256,
        ),
    )


def validate_visual_artifacts(
    evidence: dict[str, Any],
    *,
    root: Path,
) -> list[SemanticIssueLike]:
    """Run the unchanged visual-artifact evidence validator."""

    return cast(
        list[SemanticIssueLike],
        invoke_legacy(LEGACY_VISUAL_DELEGATE, evidence, root=root),
    )


def validate_tradingview_profile_capture_binding(
    evidence: dict[str, Any],
) -> list[SemanticIssueLike]:
    """Run the unchanged TradingView profile-lineage validator."""

    return cast(
        list[SemanticIssueLike],
        invoke_legacy(LEGACY_PROFILE_DELEGATE, evidence),
    )


__all__ = [
    "LEGACY_GATE_DELEGATE",
    "LEGACY_PROFILE_DELEGATE",
    "LEGACY_VISUAL_DELEGATE",
    "validate_evidence",
    "validate_tradingview_profile_capture_binding",
    "validate_visual_artifacts",
]
