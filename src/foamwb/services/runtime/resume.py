"""Surviving the reboot (FR-R3, E-R03, §7.3 step 5).

Windows will not let a newly enabled optional feature be used until the machine
restarts, so a first-run provision is necessarily interrupted. FR-R3's acceptance
test is that the wizard "completes across one reboot with no terminal use and no
second elevation" — which means the state has to outlive the process.

**Written before the reboot is offered, not after it is accepted.** A user who
restarts from the Start menu, or whose machine restarts for its own reasons, must
come back to the same place as one who pressed the button. State written only on
the happy path is state that is missing exactly when it is needed.

**A stale resume is discarded, not honoured.** The record carries the version and
distro it belongs to and a timestamp; if the user has since changed what they are
installing, or the record is from another era, resuming would carry out half of a
plan nobody asked for. Discarding costs a re-plan, which is cheap and visible.

Written atomically. A half-written resume file is worse than none: it would parse
as "nothing completed" and repeat the elevated step, which is the one prompt
FR-R3 promises not to repeat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from foamwb.logs import Event, get_logger, log_event
from foamwb.paths import user_data_dir

__all__ = ["MAX_AGE", "ResumeState", "ResumeStore", "resume_file"]

_log = get_logger("runtime.resume")

#: How long a pending provision stays meaningful. Long enough for a user who
#: restarts, goes home and comes back tomorrow; short enough that a record from
#: a previous release is never acted on.
MAX_AGE = timedelta(days=7)


def resume_file() -> Path:
    """Where the record lives. Beside the settings, not inside a case."""
    return user_data_dir() / "provision-resume.json"


@dataclass(frozen=True, slots=True)
class ResumeState:
    """A provision that was interrupted and can be picked up."""

    version: str
    distro: str
    completed: tuple[str, ...] = ()
    """Step actions already carried out. The resumed plan drops these."""

    awaiting_reboot: bool = False
    created: str = ""
    strategy: str = "wsl"

    def with_completed(self, action: str) -> ResumeState:
        if action in self.completed:
            return self
        return ResumeState(
            version=self.version,
            distro=self.distro,
            completed=(*self.completed, action),
            awaiting_reboot=self.awaiting_reboot,
            created=self.created,
            strategy=self.strategy,
        )

    def matches(self, *, version: str, distro: str) -> bool:
        """Whether this record describes the provision now being attempted."""
        return self.version == version and self.distro == distro

    @property
    def age(self) -> timedelta | None:
        """How old the record is, or ``None`` if it never said."""
        if not self.created:
            return None
        try:
            when = datetime.fromisoformat(self.created)
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return datetime.now(UTC) - when

    @property
    def is_stale(self) -> bool:
        """A record with no timestamp is stale.

        The alternative — treating it as fresh — means a corrupted or
        hand-edited file is trusted indefinitely, and the failure it produces is
        a skipped step rather than an error.
        """
        age = self.age
        return age is None or age > MAX_AGE

    def to_json(self) -> dict[str, object]:
        return {
            "version": self.version,
            "distro": self.distro,
            "completed": list(self.completed),
            "awaiting_reboot": self.awaiting_reboot,
            "created": self.created,
            "strategy": self.strategy,
        }

    @classmethod
    def from_json(cls, raw: dict) -> ResumeState:
        return cls(
            version=str(raw.get("version", "")),
            distro=str(raw.get("distro", "")),
            completed=tuple(str(c) for c in raw.get("completed", ())),
            awaiting_reboot=bool(raw.get("awaiting_reboot", False)),
            created=str(raw.get("created", "")),
            strategy=str(raw.get("strategy", "wsl")),
        )


@dataclass
class ResumeStore:
    """Reads and writes the interrupted-provision record."""

    path: Path | None = None
    _resolved: Path | None = field(default=None, init=False, repr=False)

    def location(self) -> Path | None:
        """Where the record is kept, or ``None`` if the platform cannot say."""
        if self.path is not None:
            return self.path
        if self._resolved is None:
            try:
                self._resolved = resume_file()
            except RuntimeError:
                return None
        return self._resolved

    def save(self, state: ResumeState) -> bool:
        """Persist a record, stamping it if it has no timestamp of its own."""
        target = self.location()
        if target is None:
            return False

        stamped = state
        if not state.created:
            stamped = ResumeState(
                version=state.version,
                distro=state.distro,
                completed=state.completed,
                awaiting_reboot=state.awaiting_reboot,
                created=datetime.now(UTC).isoformat(timespec="seconds"),
                strategy=state.strategy,
            )

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(stamped.to_json(), indent=2) + "\n", encoding="utf-8")
            # Atomic: a half-written record would parse as "nothing completed"
            # and repeat the one elevated step FR-R3 promises not to repeat.
            temporary.replace(target)
        except OSError as exc:
            log_event(_log, Event.ERROR_RAISED, where="resume.save", error=str(exc))
            return False

        log_event(
            _log, Event.RUNTIME_PROVISION_STAGE, resume=True, completed=len(stamped.completed)
        )
        return True

    def load(self, *, version: str = "", distro: str = "") -> ResumeState | None:
        """Read a usable record, or ``None``.

        ``None`` covers every unusable case — absent, unreadable, malformed,
        stale, or for a different install — because the caller's response to all
        of them is identical: plan afresh. Distinguishing them would offer a
        choice the user cannot act on.
        """
        target = self.location()
        if target is None or not target.is_file():
            return None

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log_event(_log, Event.ERROR_RAISED, where="resume.load", error=str(exc))
            self.clear()
            return None

        if not isinstance(raw, dict):
            self.clear()
            return None

        state = ResumeState.from_json(raw)
        if state.is_stale:
            self.clear()
            return None
        if version and distro and not state.matches(version=version, distro=distro):
            # Not cleared: the user may switch back, and deleting a record for a
            # provision that is merely not the current one would lose work.
            return None
        return state

    def clear(self) -> None:
        """Forget any pending provision. Safe to call when there is none."""
        target = self.location()
        if target is not None:
            target.unlink(missing_ok=True)

    @property
    def has_pending(self) -> bool:
        return self.load() is not None
