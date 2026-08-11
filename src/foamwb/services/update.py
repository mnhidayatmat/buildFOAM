"""Updating, and undoing an update that failed (FR-A5, E-A01).

The requirement is one sentence — "a failed update restores the prior version
and reports the failure" — and almost all of the design is in what *failed*
means. An update can fail while downloading, while verifying, while swapping
files, or after the swap when the new version will not start. Only the last two
need a rollback, and only the last one is discoverable after the process that
performed the update has gone.

**The previous version is kept, not deleted.** Rollback is a rename, not a
re-download: a machine whose update failed is frequently a machine whose network
or disk is the reason, and a recovery path that needs either is no recovery.

**A new version proves itself before the old one is released.** The swap is
staged — download, verify, install beside, launch once, and only then retire the
predecessor. A version that installs and cannot start is the failure mode users
never forgive, because it takes the working application with it.

**Nothing is verified by version number.** The downloaded artefact is checked
against a signature and a digest, exactly as content is (FR-L4). An update
channel is a far more valuable thing to compromise than a case file.

This module plans and records; it does not download. The transport belongs to
whatever ships the release, and keeping it out means the state machine — which
is where the data loss lives — is testable without a network.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event

__all__ = [
    "UpdateOutcome",
    "UpdateRecord",
    "UpdateService",
    "UpdateStage",
]

_log = get_logger("services.update")


class UpdateStage(StrEnum):
    """Where an update got to. Only some of these need undoing."""

    IDLE = "idle"
    DOWNLOADED = "downloaded"
    """On disk, unverified. Nothing has been changed; failing here needs no
    rollback, only a cleared cache."""

    VERIFIED = "verified"
    """Signature and digest check out. Still nothing changed."""

    STAGED = "staged"
    """Installed beside the running version. Both exist; neither is retired."""

    ACTIVATED = "activated"
    """The new version is the one that launches. The old one is still on disk,
    which is what makes rollback a rename rather than a download."""

    COMMITTED = "committed"
    """The new version started successfully at least once. The predecessor may
    now be retired."""


class UpdateOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    """Rollback itself did not work. The worst outcome, and the one that must be
    reported loudest — the user needs to know to reinstall."""


@dataclass(slots=True)
class UpdateRecord:
    """The state an update leaves behind, so a later launch can finish or undo it.

    Persisted because the decisive failure — a new version that will not start —
    is only observable from a *different* process than the one that installed it.
    An in-memory state machine cannot see it at all.
    """

    from_version: str = ""
    to_version: str = ""
    stage: UpdateStage = UpdateStage.IDLE
    started: str = ""
    previous_path: str = ""
    """Where the outgoing version was kept. The rollback target."""

    launch_confirmed: bool = False
    """Set by the *new* version on its first successful start."""

    detail: str = ""

    @property
    def needs_rollback(self) -> bool:
        """An activated update that never confirmed a launch.

        This is the whole point of the record: the process that would have set
        `launch_confirmed` is precisely the one that failed to run.
        """
        return self.stage is UpdateStage.ACTIVATED and not self.launch_confirmed

    @property
    def is_finished(self) -> bool:
        return self.stage in {UpdateStage.IDLE, UpdateStage.COMMITTED}

    def to_json(self) -> dict[str, object]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "stage": self.stage.value,
            "started": self.started,
            "previous_path": self.previous_path,
            "launch_confirmed": self.launch_confirmed,
            "detail": self.detail,
        }

    @classmethod
    def from_json(cls, raw: dict) -> UpdateRecord:
        try:
            stage = UpdateStage(str(raw.get("stage", "idle")))
        except ValueError:
            # An unrecognised stage means a record from a version that knew
            # something this one does not. Treated as idle rather than guessed
            # at: acting on a state we cannot interpret is how an updater
            # deletes a working installation.
            stage = UpdateStage.IDLE
        return cls(
            from_version=str(raw.get("from_version", "")),
            to_version=str(raw.get("to_version", "")),
            stage=stage,
            started=str(raw.get("started", "")),
            previous_path=str(raw.get("previous_path", "")),
            launch_confirmed=bool(raw.get("launch_confirmed", False)),
            detail=str(raw.get("detail", "")),
        )


@dataclass
class UpdateService:
    """Records update progress and undoes an update that did not take."""

    state_path: Path | None = None
    _resolved: Path | None = field(default=None, init=False, repr=False)

    def location(self) -> Path | None:
        if self.state_path is not None:
            return self.state_path
        if self._resolved is None:
            try:
                from foamwb.paths import user_data_dir

                self._resolved = user_data_dir() / "update-state.json"
            except RuntimeError:
                return None
        return self._resolved

    # -- state -------------------------------------------------------------

    def read(self) -> UpdateRecord:
        """The recorded state, or an idle record.

        An unreadable record is idle, not an error. The alternative is an
        application that refuses to start because its updater is confused, which
        is a worse failure than the one it is guarding against.
        """
        target = self.location()
        if target is None or not target.is_file():
            return UpdateRecord()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return UpdateRecord()
        return UpdateRecord.from_json(raw) if isinstance(raw, dict) else UpdateRecord()

    def write(self, record: UpdateRecord) -> bool:
        target = self.location()
        if target is None:
            return False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(record.to_json(), indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
        except OSError as exc:
            log_event(_log, Event.ERROR_RAISED, where="update.write", error=str(exc))
            return False
        return True

    def clear(self) -> None:
        target = self.location()
        if target is not None:
            target.unlink(missing_ok=True)

    # -- the sequence ------------------------------------------------------

    def begin(self, *, from_version: str, to_version: str) -> UpdateRecord:
        record = UpdateRecord(
            from_version=from_version,
            to_version=to_version,
            stage=UpdateStage.DOWNLOADED,
            started=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self.write(record)
        return record

    def advance(self, record: UpdateRecord, stage: UpdateStage, **fields) -> UpdateRecord:
        record.stage = stage
        for name, value in fields.items():
            setattr(record, name, value)
        self.write(record)
        log_event(_log, Event.APP_START, update_stage=stage.value)
        return record

    def confirm_launch(self) -> UpdateRecord:
        """Called by the *new* version once it has started successfully.

        The commit point. Until this happens the predecessor stays on disk, and
        a launch that never gets here is what :meth:`roll_back` undoes.
        """
        record = self.read()
        if record.stage is UpdateStage.ACTIVATED:
            record.launch_confirmed = True
            record.stage = UpdateStage.COMMITTED
            self.write(record)
        return record

    def roll_back(self, record: UpdateRecord, *, install_root: Path) -> UpdateOutcome:
        """Put the previous version back (E-A01).

        A rename, never a download: the machine whose update failed is often the
        machine whose network or disk caused it.
        """
        if not record.needs_rollback:
            return UpdateOutcome.SUCCEEDED

        previous = Path(record.previous_path) if record.previous_path else None
        if previous is None or not previous.exists():
            # The one outcome the user must be told about loudly: there is
            # nothing to restore and the application will not start.
            log_event(_log, Event.ERROR_RAISED, where="update.rollback", error="no-previous")
            record.detail = "The previous version could not be found."
            self.write(record)
            return UpdateOutcome.FAILED

        try:
            if install_root.exists():
                shutil.rmtree(install_root)
            shutil.move(str(previous), str(install_root))
        except OSError as exc:
            log_event(_log, Event.ERROR_RAISED, where="update.rollback", error=str(exc))
            record.detail = str(exc)
            self.write(record)
            return UpdateOutcome.FAILED

        self.clear()
        return UpdateOutcome.ROLLED_BACK

    # -- reporting ---------------------------------------------------------

    @staticmethod
    def code_for(outcome: UpdateOutcome) -> Code | None:
        """The §9 code to report, or ``None`` when nothing went wrong.

        A rollback that worked is still a failure the user should hear about —
        their update did not happen, and silence would leave them believing it
        did.
        """
        if outcome is UpdateOutcome.SUCCEEDED:
            return None
        return ErrorCode.UPDATE_FAILED
