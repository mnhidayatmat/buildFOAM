"""What uninstalling removes, and what it must never touch (FR-A6).

The whole design is one distinction: **the application's own state versus the
user's work.** Settings, logs, caches and the downloaded runtime manifest belong
to the application and go. Cases, meshes and results are the user's, and an
uninstaller that deletes a term's simulations because they happened to live in
the default folder has done something no reinstall can undo.

So the case directory is *reported and never removed*. Not offered as a checkbox
either: a destructive default that a tired user can accept by pressing Return is
the same failure with an extra step. If they want it gone they can delete a
folder, which they already know how to do and which their operating system will
put in a bin they can retrieve it from.

**The runtime is separate and is asked about.** A WSL distribution or a Homebrew
cask is not part of this application, may have been there first, and may be
shared with other work — but it is also gigabytes that a user uninstalling would
reasonably expect to reclaim. So it is listed with its size and left to them.

Everything here is a *plan* first. Nothing is deleted until a caller acts on a
plan it has been shown, which is the same rule the provisioner follows (§7.3
step 4) and for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from foamwb.logs import Event, get_logger, log_event

__all__ = [
    "RemovalKind",
    "UninstallItem",
    "UninstallPlan",
    "perform",
    "plan_uninstall",
]

_log = get_logger("services.uninstall")


class RemovalKind(StrEnum):
    """What an item is, which decides what happens to it."""

    APPLICATION_STATE = "application_state"
    """Ours. Removed without asking — settings, logs, caches."""

    USER_WORK = "user_work"
    """Theirs. Reported, never removed, not even as an opt-in."""

    RUNTIME = "runtime"
    """OpenFOAM itself. Large, possibly shared, possibly pre-existing: listed
    with its size and left to the user to decide."""


@dataclass(frozen=True, slots=True)
class UninstallItem:
    """One thing an uninstall found."""

    path: Path
    kind: RemovalKind
    label: str
    """A key from the string catalogue, not prose — this is a service."""

    size_bytes: int = 0
    exists: bool = True

    @property
    def is_removed(self) -> bool:
        return self.kind is RemovalKind.APPLICATION_STATE


@dataclass(slots=True)
class UninstallPlan:
    """Everything found, sorted into what goes and what stays."""

    items: list[UninstallItem] = field(default_factory=list)

    @property
    def removed(self) -> list[UninstallItem]:
        return [i for i in self.items if i.is_removed and i.exists]

    @property
    def kept(self) -> list[UninstallItem]:
        """Reported so the user knows it is still there, and where."""
        return [i for i in self.items if i.kind is RemovalKind.USER_WORK and i.exists]

    @property
    def offered(self) -> list[UninstallItem]:
        return [i for i in self.items if i.kind is RemovalKind.RUNTIME and i.exists]

    @property
    def freed_bytes(self) -> int:
        return sum(i.size_bytes for i in self.removed)

    @property
    def retained_bytes(self) -> int:
        return sum(i.size_bytes for i in self.kept)


def _size_of(path: Path) -> int:
    """Bytes under a path. Symlinks are counted as links, never followed.

    Following them would count a case directory twice when a user has symlinked
    one into another, and — worse — could wander outside the tree entirely.
    """
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_symlink() or not child.is_file():
            continue
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


def plan_uninstall(*, include_sizes: bool = True) -> UninstallPlan:
    """Work out what an uninstall would do. Removes nothing.

    Sizes are measured rather than estimated, because the figure's whole purpose
    is to let the user decide whether reclaiming the runtime is worth it — and an
    estimate that is wrong by a factor of three makes that decision for them.
    """
    from foamwb import paths

    plan = UninstallPlan()

    def add(getter, kind: RemovalKind, label: str) -> None:
        try:
            path = getter()
        except (RuntimeError, OSError):
            # An unsupported platform cannot say where its data lives. Reporting
            # nothing is right; guessing a path and deleting it is not.
            return
        exists = path.exists()
        plan.items.append(
            UninstallItem(
                path=path,
                kind=kind,
                label=label,
                size_bytes=_size_of(path) if (exists and include_sizes) else 0,
                exists=exists,
            )
        )

    add(paths.user_data_dir, RemovalKind.APPLICATION_STATE, "uninstall_settings")
    add(paths.log_dir, RemovalKind.APPLICATION_STATE, "uninstall_logs")
    add(paths.cache_dir, RemovalKind.APPLICATION_STATE, "uninstall_cache")
    add(paths.macos_cases_dir, RemovalKind.USER_WORK, "uninstall_cases")
    add(paths.macos_content_dir, RemovalKind.USER_WORK, "uninstall_content")
    return plan


def perform(plan: UninstallPlan, *, dry_run: bool = False) -> list[Path]:
    """Carry out a plan, returning what was removed.

    Only ever removes items the plan classified as application state. The check
    is repeated here rather than trusted from the caller: this function deletes
    directory trees, and a caller that hands it the wrong list should get nothing
    rather than an apology.
    """
    import shutil

    removed: list[Path] = []
    for item in plan.items:
        if not item.is_removed or not item.exists:
            continue
        if dry_run:
            removed.append(item.path)
            continue
        try:
            if item.path.is_dir():
                shutil.rmtree(item.path)
            else:
                item.path.unlink(missing_ok=True)
        except OSError as exc:
            log_event(_log, Event.ERROR_RAISED, where="uninstall", error=str(exc))
            continue
        removed.append(item.path)

    log_event(_log, Event.APP_STOP, uninstalled=len(removed), dry_run=dry_run)
    return removed
