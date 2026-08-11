"""Unsaved edits survive a crash (NFR-R3).

An editor buffer that exists only in memory is lost when the process stops, and
processes stop: a solver exhausts memory, a laptop lid closes on a dying battery,
Qt segfaults in a driver. Losing twenty minutes of boundary-condition work to any
of those contradicts the one thing this application promises above all others,
which is that it will not damage your case.

**The journal lives in the application's own data directory, not in the case.**
This is the load-bearing decision. Until the user saves, their case is untouched
— §5.1's promise is that opening someone else's case does not modify it, and a
crash must not leave debris in a directory they own and may be sharing, syncing
or submitting. Our uncertainty about their file is our state to keep.

**A baseline hash travels with every entry.** Recovery is not "write this back":
the file may have changed underneath while the process was gone — another editor,
a solver run, a colleague's commit. An entry whose baseline no longer matches the
file on disk is offered as a *conflict*, not applied. Silently overwriting a
newer file with a recovered older buffer would be data loss dressed as recovery.

**Recovery is offered and never automatic.** The user chooses. An application
that reinstated buffers on launch would eventually reinstate one somebody had
deliberately abandoned.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from foamwb.logs import Event, get_logger, log_event

__all__ = [
    "JournalEntry",
    "JournalService",
    "Recovery",
    "journal_dir",
]

_log = get_logger("services.journal")


def journal_dir() -> Path:
    """Where unsaved buffers are kept — beside the settings, never in the case."""
    from foamwb.paths import user_data_dir

    return user_data_dir() / "journal"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key(case: Path, relative: str) -> str:
    """A filename-safe identity for one edited file.

    Hashed rather than encoded from the path: a case path can be long, contain
    separators and non-ASCII, and be on a filesystem that disagrees with ours
    about case sensitivity. The full path is stored inside the entry, so nothing
    is lost by the hash — it is an identity, not a record.
    """
    return _digest(f"{case}\x00{relative}".encode())[:32]


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One unsaved buffer."""

    case: Path
    relative: str
    """The edited file, relative to the case root."""

    content: str
    baseline: str
    """Digest of the file on disk when editing began.

    What makes recovery safe rather than merely possible."""

    modified: str = ""

    @property
    def path(self) -> Path:
        return self.case / self.relative

    def to_json(self) -> dict[str, object]:
        return {
            "case": str(self.case),
            "relative": self.relative,
            "content": self.content,
            "baseline": self.baseline,
            "modified": self.modified,
        }

    @classmethod
    def from_json(cls, raw: dict) -> JournalEntry:
        return cls(
            case=Path(str(raw.get("case", ""))),
            relative=str(raw.get("relative", "")),
            content=str(raw.get("content", "")),
            baseline=str(raw.get("baseline", "")),
            modified=str(raw.get("modified", "")),
        )


@dataclass(frozen=True, slots=True)
class Recovery:
    """A journal entry judged against the file as it is now."""

    entry: JournalEntry
    conflicted: bool
    """The file changed while this application was not running."""

    missing: bool = False
    """The file is gone entirely — deleted, moved, or the case relocated."""

    @property
    def safe(self) -> bool:
        return not self.conflicted and not self.missing

    @property
    def relative(self) -> str:
        return self.entry.relative


class JournalService:
    """Records unsaved buffers and offers them back after a restart."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory

    def location(self) -> Path | None:
        if self._directory is not None:
            return self._directory
        try:
            return journal_dir()
        except RuntimeError:
            return None

    # -- recording ---------------------------------------------------------

    def record(self, case: Path, relative: str, content: str) -> bool:
        """Journal an unsaved buffer. Returns whether it was written.

        Callers should debounce: this is called from a keystroke handler, and a
        write per character would put the disk in the typing path. A second or
        two of coalescing loses at most a second or two of work.
        """
        directory = self.location()
        if directory is None:
            return False

        source = case / relative
        try:
            baseline = _digest(source.read_bytes()) if source.is_file() else ""
        except OSError:
            baseline = ""

        entry = JournalEntry(
            case=case,
            relative=relative,
            content=content,
            baseline=baseline,
            modified=datetime.now(UTC).isoformat(timespec="seconds"),
        )

        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{_key(case, relative)}.json"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(entry.to_json(), indent=2) + "\n", encoding="utf-8")
            # Atomic. A half-written journal is worse than none: it would be
            # offered as recovery and would restore a truncated file.
            temporary.replace(target)
        except OSError as exc:
            # Journalling must never be able to stop the user editing. A disk
            # that cannot take the journal is a degraded state, not a failure.
            log_event(_log, Event.ERROR_RAISED, where="journal.record", error=str(exc))
            return False
        return True

    def forget(self, case: Path, relative: str) -> None:
        """Drop an entry once its file has been saved."""
        directory = self.location()
        if directory is not None:
            (directory / f"{_key(case, relative)}.json").unlink(missing_ok=True)

    def forget_case(self, case: Path) -> int:
        """Drop every entry for a case. Returns how many went."""
        return sum(1 for entry in self.entries(case) if self._drop(entry))

    def _drop(self, entry: JournalEntry) -> bool:
        self.forget(entry.case, entry.relative)
        return True

    # -- reading -----------------------------------------------------------

    def entries(self, case: Path | None = None) -> list[JournalEntry]:
        """Every journalled buffer, optionally for one case.

        A file that will not parse is deleted rather than reported. It cannot be
        recovered from, and leaving it would offer the user a choice with no
        good outcome on every launch.
        """
        directory = self.location()
        if directory is None or not directory.is_dir():
            return []

        found: list[JournalEntry] = []
        for source in sorted(directory.glob("*.json")):
            try:
                raw = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                source.unlink(missing_ok=True)
                continue
            if not isinstance(raw, dict):
                source.unlink(missing_ok=True)
                continue
            entry = JournalEntry.from_json(raw)
            if not entry.relative:
                source.unlink(missing_ok=True)
                continue
            if case is None or entry.case == case:
                found.append(entry)
        return found

    def recoveries(self, case: Path) -> list[Recovery]:
        """What could be restored, and which of it is safe to restore.

        Entries whose content matches the file on disk are dropped silently:
        the buffer was saved before the crash and there is nothing to recover.
        Offering those would train the user to dismiss the dialog.
        """
        found: list[Recovery] = []
        for entry in self.entries(case):
            source = entry.path
            if not source.is_file():
                found.append(Recovery(entry=entry, conflicted=False, missing=True))
                continue

            try:
                current = source.read_bytes()
            except OSError:
                found.append(Recovery(entry=entry, conflicted=True))
                continue

            if entry.content.encode("utf-8") == current:
                self.forget(entry.case, entry.relative)
                continue

            found.append(Recovery(entry=entry, conflicted=_digest(current) != entry.baseline))
        return found

    def has_recoveries(self, case: Path) -> bool:
        return bool(self.recoveries(case))
