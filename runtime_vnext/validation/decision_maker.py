"""Maker decision facade pending extraction from the decision gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .common import GateResultLike, LegacyDelegate, invoke_legacy


LEGACY_DELEGATE = LegacyDelegate(
    stage="decision",
    domain="maker",
    module="runtime_vnext.gates",
    callable_name="evaluate_decision",
    coverage="full_stage",
)


def validate_maker_decision(
    payload: dict[str, Any],
    *,
    reasoning: dict[str, Any],
    run: dict[str, Any],
    pretrade_gate: dict[str, Any] | None,
    root: Path,
) -> GateResultLike:
    """Delegate to the unchanged full decision gate without defect filtering."""

    return cast(
        GateResultLike,
        invoke_legacy(
            LEGACY_DELEGATE,
            payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=pretrade_gate,
            root=root,
        ),
    )


__all__ = ["LEGACY_DELEGATE", "validate_maker_decision"]
