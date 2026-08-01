"""Trading-System vNext: checkpointed daily-report production kernel.

The package is intentionally isolated from ``runtime`` while vNext is shadow
validated.  Legacy production remains untouched until the cutover contract is
met.
"""

from .artifacts import ArtifactStore
from .controller import RunController

__all__ = ["ArtifactStore", "RunController"]
