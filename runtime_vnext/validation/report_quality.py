"""Report-quality and compatibility-lint facades."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .common import LegacyDelegate, invoke_legacy


LEGACY_REASONING_DEPTH_DELEGATE = LegacyDelegate(
    stage="report",
    domain="human_reasoning_depth",
    module="runtime_vnext.report_compiler",
    callable_name="evaluate_human_reasoning_depth",
    coverage="domain",
)
LEGACY_TEMPLATE_FIDELITY_DELEGATE = LegacyDelegate(
    stage="report",
    domain="gold_template_fidelity",
    module="runtime_vnext.report_compiler",
    callable_name="evaluate_gold_template_fidelity",
    coverage="domain",
)
LEGACY_COMPATIBILITY_LINT_DELEGATE = LegacyDelegate(
    stage="report",
    domain="compatibility_lint",
    module="runtime_vnext.report_compiler",
    callable_name="run_compatibility_lint",
    coverage="domain",
)


def evaluate_human_reasoning_depth(
    model: dict[str, Any],
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Run the unchanged report reasoning-depth evaluator."""

    return cast(
        dict[str, Any],
        invoke_legacy(
            LEGACY_REASONING_DEPTH_DELEGATE,
            model,
            contract=contract,
        ),
    )


def evaluate_gold_template_fidelity(
    markdown: str,
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Run the unchanged gold-template fidelity evaluator."""

    return cast(
        dict[str, Any],
        invoke_legacy(
            LEGACY_TEMPLATE_FIDELITY_DELEGATE,
            markdown,
            contract=contract,
        ),
    )


def run_compatibility_lint(
    report_path: Path,
    *,
    root: Path,
) -> dict[str, Any]:
    """Run the existing non-bypassable compatibility lint."""

    return cast(
        dict[str, Any],
        invoke_legacy(
            LEGACY_COMPATIBILITY_LINT_DELEGATE,
            report_path,
            root=root,
        ),
    )


__all__ = [
    "LEGACY_COMPATIBILITY_LINT_DELEGATE",
    "LEGACY_REASONING_DEPTH_DELEGATE",
    "LEGACY_TEMPLATE_FIDELITY_DELEGATE",
    "evaluate_gold_template_fidelity",
    "evaluate_human_reasoning_depth",
    "run_compatibility_lint",
]
