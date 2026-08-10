"""Recently opened cases (FR-A1, §7.2).

Qt-free, because the Hub is not the only thing that will want this: a returning
user's first action is almost always "continue what I was doing", and the same
list drives the Hub, the window title and (later) a Reopen action.

Persistence is deliberately absent at M1. Recent cases belong in ``config.json``
(§5.3), and that file is owned by the configuration layer that lands with
CaseService at M4. Half-building it here would mean two writers for one file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = ["RecentCase"]


@dataclass(frozen=True, slots=True)
class RecentCase:
    """One row in the Hub's recent-cases list."""

    path: Path
    solver: str | None = None
    """Application from ``system/controlDict``, or ``None`` if not yet read."""

    last_run: datetime | None = None
    last_exit: int | None = None
    """Exit status of the most recent run; ``None`` if never run."""

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def has_run(self) -> bool:
        return self.last_run is not None
