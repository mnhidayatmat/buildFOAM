"""Duplicating a case (FR-C6).

"Save As", and the requirement's second clause is the whole difficulty:
**rewriting no absolute paths**. An OpenFOAM case that mentions its own location
is unusual but legal — a `#include` of a shared dictionary, a `functions` entry
writing somewhere specific, a `setFieldsDict` naming an STL by full path. Copying
such a case and silently rewriting those strings would change what it computes;
copying it and leaving them is what the user asked for.

So this copies bytes and rewrites nothing. Paths that pointed outside the case
still point there, which is correct: they refer to something that did not move.

**Results are not copied by default.** A duplicate is normally made to try a
variation, and carrying half a terabyte of time directories into it is rarely
wanted and never fast. The definition — `system`, `constant`, `0` — is what
travels, and the caller may ask for more.

**Our own metadata is never copied.** A duplicate is a new case: it has not been
run, and inheriting the original's run history and tree hash would make it claim
a past it does not have.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from foamwb.branding import CASE_METADATA_DIR
from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event

__all__ = ["DuplicateError", "DuplicatePlan", "duplicate_case", "plan_duplicate"]

_log = get_logger("services.duplicate")

#: The directories that *are* the case. Everything else is output or ours.
DEFINITION_DIRS: tuple[str, ...] = ("system", "constant", "0", "0.orig")


class DuplicateError(Exception):
    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class DuplicatePlan:
    """What would be copied, before anything is."""

    source: Path
    destination: Path
    files: list[Path] = field(default_factory=list)
    total_bytes: int = 0
    excluded_results: int = 0
    """Time directories left behind. Reported so the omission is visible."""

    absolute_references: list[str] = field(default_factory=list)
    """Absolute paths found inside the case, which will be copied unchanged.

    Surfaced rather than rewritten. The user is the only one who knows whether a
    path pointing outside the case should follow the copy or stay where it is,
    and guessing changes what the case computes."""

    @property
    def file_count(self) -> int:
        return len(self.files)


def plan_duplicate(
    source: Path, destination: Path, *, include_results: bool = False
) -> DuplicatePlan:
    """Work out what a duplicate would contain. Copies nothing."""
    if not (source / "system").is_dir():
        raise DuplicateError(ErrorCode.NOT_A_CASE, f"{source.name} is not a case.")
    if destination.exists():
        raise DuplicateError(ErrorCode.DESTINATION_EXISTS, f"{destination.name} already exists.")

    plan = DuplicatePlan(source=source, destination=destination)

    for entry in sorted(source.iterdir()):
        if entry.name == CASE_METADATA_DIR:
            continue
        if entry.is_dir() and entry.name not in DEFINITION_DIRS:
            if _is_time_dir(entry.name):
                plan.excluded_results += 1
                if not include_results:
                    continue
            elif entry.name in {"postProcessing", "VTK", "logs", "processor0"}:
                if not include_results:
                    continue

        for path in sorted(entry.rglob("*")) if entry.is_dir() else [entry]:
            if not path.is_file() or path.is_symlink():
                continue
            plan.files.append(path)
            try:
                plan.total_bytes += path.stat().st_size
            except OSError:
                continue

    plan.absolute_references = _absolute_references(plan.files, source)
    return plan


def _is_time_dir(name: str) -> bool:
    try:
        float(name)
    except ValueError:
        return False
    return True


def _absolute_references(files: list[Path], source: Path) -> list[str]:
    """Absolute paths mentioned inside the case's own dictionaries.

    Only reported. A path is flagged whether or not it points into the case,
    because both cases matter to the user and only they can tell which is which.
    """
    found: list[str] = []
    for path in files:
        if path.suffix in {".zip", ".gz", ".stl", ".obj"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            for token in ('"/', "'/", '"\\\\', str(source)):
                if token in line:
                    relative = path.relative_to(source).as_posix()
                    found.append(f"{relative}: {stripped[:90]}")
                    break
    return found


def duplicate_case(plan: DuplicatePlan) -> Path:
    """Carry out a plan. Copies bytes; rewrites nothing.

    Written to a scratch directory and moved into place, so an interrupted copy
    leaves no half-case that looks openable.
    """
    staging = plan.destination.with_name(f".{plan.destination.name}.partial")
    shutil.rmtree(staging, ignore_errors=True)

    try:
        for path in plan.files:
            relative = path.relative_to(plan.source)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            # copy2 preserves mode and timestamps: a duplicate that silently
            # changed a file's permissions would be a different case.
            shutil.copy2(path, target)
        staging.replace(plan.destination)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise DuplicateError(
            ErrorCode.NOT_A_CASE, f"{plan.destination.name} could not be created: {exc}"
        ) from exc

    log_event(
        _log,
        Event.CASE_WRITE,
        case=str(plan.destination),
        action="duplicate",
        files=plan.file_count,
    )
    return plan.destination
