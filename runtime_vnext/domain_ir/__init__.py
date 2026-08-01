"""Single-owner typed domain contract for the vNext reasoning back-half.

The package owns deterministic identities, enums, topology and projection
rules.  It deliberately does not own market interpretation, evidence weight,
thesis selection, counterevidence selection, invalidation judgment, support
edge selection or Chinese narrative depth; those remain model-owned inputs
that the validators certify.
"""

from .canonical import canonical_json_bytes, canonical_sha256
from .registry import REGISTRY, DomainRegistry

__all__ = [
    "DomainRegistry",
    "REGISTRY",
    "canonical_json_bytes",
    "canonical_sha256",
]
