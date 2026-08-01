"""Single machine truth for vNext model and reasoning-effort requests."""

from __future__ import annotations


REQUESTED_MODEL = "gpt-5.6-sol"
REQUESTED_EFFORT = "xhigh"

# Codex host observations may exceed the exact run request.  New vNext runs
# still request exactly ``xhigh``; this order exists only for the mechanical
# at-least capability proof.
EFFORT_ORDER = {
    "high": 0,
    "xhigh": 1,
    "max": 2,
    "ultra": 3,
}


def satisfies_requested_effort(actual: object, requested: object) -> bool:
    """Return whether an observed host effort satisfies the sealed request."""

    return (
        isinstance(actual, str)
        and isinstance(requested, str)
        and actual in EFFORT_ORDER
        and requested in EFFORT_ORDER
        and EFFORT_ORDER[actual] >= EFFORT_ORDER[requested]
    )
