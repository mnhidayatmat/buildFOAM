"""Runtime status with a machine-readable reason (FR-R2).

The status footer is always visible and always truthful (§7.9 rule 4, FR-A2).
That is only achievable if "not working" is a value with structure, rather than a
string assembled at the point of failure — so every non-ready state carries a §9
code that the footer can render, the guide can link, and a diagnostics bundle can
be filtered on.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from foamwb.codes import Code
from foamwb.services.runtime.session import RuntimeKind

__all__ = ["RuntimeState", "RuntimeStatus"]


class RuntimeState(StrEnum):
    """The four states the footer's coloured dot renders (§7.1).

    Colour is never the sole carrier of meaning (NFR-A2), so each state also
    supplies a shape and a label in the presentation layer.
    """

    READY = "ready"
    """Provisioned and the canary command passed (FR-R5)."""

    DEGRADED = "degraded"
    """Usable, but something the user should know about — for example the Docker
    fallback on Intel hardware, or a version outside the support window."""

    MISSING = "missing"
    """Nothing provisioned yet. The expected first-launch state."""

    BROKEN = "broken"
    """Present but not working. A corrupted install must land here and never in
    :data:`READY` — FR-R5 exists because "installed" and "works" are different
    claims, and only the second one matters to the user."""


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    """A point-in-time answer to "can this machine run OpenFOAM right now?"."""

    state: RuntimeState

    reason: Code | None = None
    """The §9 code explaining a non-ready state.

    Required for every state except :data:`RuntimeState.READY`; enforced in
    :meth:`__post_init__` so that an un-diagnosable failure cannot reach the UI.
    """

    detail: str = ""
    """Free-text detail for logs and the diagnostics bundle — the last 20 lines of
    apt output, a canary command's stderr. Not a user-facing message: the code
    selects that, so it stays translatable (NFR-A5)."""

    kind: RuntimeKind | None = None
    """Which runtime flavour this describes, once one has been identified."""

    openfoam_version: str | None = None
    """Version reported by the canary, e.g. as parsed from ``foamVersion``.

    A string from the manifest, never a literal in code (NFR-M3).
    """

    def __post_init__(self) -> None:
        if self.state is not RuntimeState.READY and self.reason is None:
            raise ValueError(
                f"RuntimeStatus({self.state}) requires a reason code — "
                "FR-R2 requires a machine-readable reason at all times."
            )
        if self.state is RuntimeState.READY and self.reason is not None:
            raise ValueError("A ready runtime must not carry an error code.")

    @property
    def is_usable(self) -> bool:
        """Whether a run may be attempted.

        Degraded counts: a Docker fallback runs simulations perfectly well, and
        refusing to launch would be a dead end (§7.9 rule 1).
        """
        return self.state in (RuntimeState.READY, RuntimeState.DEGRADED)
