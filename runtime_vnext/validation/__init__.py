"""Typed validation seams for the vNext back-half.

This package is an extraction boundary, not a second validation system.  Its
facades currently delegate to the existing production implementations and
therefore preserve the four public gates and every existing threshold.
"""

from .common import (
    DefectLike,
    GateResultLike,
    LegacyCoverage,
    LegacyDelegate,
    SemanticIssueLike,
)

__all__ = [
    "DefectLike",
    "GateResultLike",
    "LegacyCoverage",
    "LegacyDelegate",
    "SemanticIssueLike",
]
