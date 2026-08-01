"""Cycle-safe types and lazy legacy delegation for validation facades."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Literal, Protocol, cast, runtime_checkable


LegacyCoverage = Literal["domain", "full_stage", "projection"]


@dataclass(frozen=True)
class LegacyDelegate:
    """Auditable description of the production implementation behind a facade."""

    stage: str
    domain: str
    module: str
    callable_name: str
    coverage: LegacyCoverage


@runtime_checkable
class DefectLike(Protocol):
    """Structural view of the existing immutable gate defect."""

    code: str
    message: str
    path: str
    severity: str


@runtime_checkable
class GateResultLike(Protocol):
    """Structural view of ``runtime_vnext.gates.GateResult``."""

    gate: str
    passed: bool
    defects: tuple[DefectLike, ...]
    facts: dict[str, Any]

    def to_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class SemanticIssueLike(Protocol):
    """Structural view of a semantic-validation issue."""

    code: str
    message: str
    path: str


def legacy_callable(delegate: LegacyDelegate) -> Callable[..., Any]:
    """Load one declared legacy implementation without eager import cycles."""

    module = import_module(delegate.module)
    candidate = getattr(module, delegate.callable_name)
    if not callable(candidate):
        raise TypeError(
            f"legacy delegate is not callable: "
            f"{delegate.module}.{delegate.callable_name}"
        )
    return cast(Callable[..., Any], candidate)


def invoke_legacy(
    delegate: LegacyDelegate,
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Invoke the declared production owner without altering its result."""

    return legacy_callable(delegate)(*args, **kwargs)


__all__ = [
    "DefectLike",
    "GateResultLike",
    "LegacyCoverage",
    "LegacyDelegate",
    "SemanticIssueLike",
    "invoke_legacy",
    "legacy_callable",
]
