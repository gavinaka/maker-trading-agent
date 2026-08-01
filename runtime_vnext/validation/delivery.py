"""Shadow and production delivery-stage validation facades."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .common import GateResultLike, LegacyDelegate, invoke_legacy


LEGACY_SHADOW_DELEGATE = LegacyDelegate(
    stage="delivery",
    domain="shadow_delivery",
    module="runtime_vnext.gates",
    callable_name="evaluate_shadow_delivery",
    coverage="full_stage",
)
LEGACY_PRODUCTION_DELEGATE = LegacyDelegate(
    stage="delivery",
    domain="production_delivery",
    module="runtime_vnext.gates",
    callable_name="evaluate_delivery",
    coverage="full_stage",
)


def validate_shadow_delivery(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None = None,
    expected_cards: dict[str, dict[str, Any]] | None = None,
) -> GateResultLike:
    """Run the unchanged pre-cutover shadow-delivery gate."""

    return cast(
        GateResultLike,
        invoke_legacy(
            LEGACY_SHADOW_DELEGATE,
            payload,
            root=root,
            run=run,
            expected_report=expected_report,
            expected_cards=expected_cards,
        ),
    )


def validate_delivery(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None = None,
    expected_cards: dict[str, dict[str, Any]] | None = None,
) -> GateResultLike:
    """Run the unchanged production-delivery gate."""

    return cast(
        GateResultLike,
        invoke_legacy(
            LEGACY_PRODUCTION_DELEGATE,
            payload,
            root=root,
            run=run,
            expected_report=expected_report,
            expected_cards=expected_cards,
        ),
    )


__all__ = [
    "LEGACY_PRODUCTION_DELEGATE",
    "LEGACY_SHADOW_DELEGATE",
    "validate_delivery",
    "validate_shadow_delivery",
]
