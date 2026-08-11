"""Getting cases out of a runtime before it is removed (FR-R12, FR-R9).

The uninstaller refuses to remove a WSL distribution while it still holds the
user's cases. This is what lifts that refusal.

The hazard is specific and severe. DEC-05 keeps cases off ``/mnt/c`` for
performance, DEC-12 gives them a distribution of their own, and together those
put the user's work on an ext4 filesystem inside a VHDX that ``wsl --unregister``
deletes outright. There is no recycle bin, no undo, and no partial recovery.

**Copied out, then verified by digest, then reported — and only then may the
runtime go.** FR-R9 asks for "no user case lost, verified by checksum comparison
before and after", which is a stronger claim than "the copy did not raise". A
copy that silently truncated one field file would satisfy the weaker claim and
lose the run.

**The export is a plan first, like everything destructive here.** The user sees
how many cases, how large, and where they will land before anything moves —
and, importantly, whether the destination has room.

The transport goes through :class:`RuntimeSession` so the same code serves a WSL
distro and a local directory. Nothing here shells out to ``wsl.exe`` directly.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event

__all__ = [
    "CaseExport",
    "ExportPlan",
    "ExportResult",
    "export_cases",
    "plan_export",
    "verify_export",
]

_log = get_logger("services.export")


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            sha.update(block)
    return sha.hexdigest()


def _tree_digests(root: Path) -> dict[str, str]:
    """Every file under a root, by relative path.

    Symlinks are recorded by their target rather than followed: a case that
    links ``0`` to ``0.orig`` — which the tutorial suite does — would otherwise
    be counted twice and compared against itself.
    """
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            found[relative] = f"link:{path.readlink()}"
        elif path.is_file():
            try:
                found[relative] = _digest(path)
            except OSError:
                found[relative] = "unreadable"
    return found


@dataclass(frozen=True, slots=True)
class CaseExport:
    """One case to be copied out."""

    source: Path
    name: str
    size_bytes: int = 0
    file_count: int = 0


@dataclass(slots=True)
class ExportPlan:
    """What would be copied out, before anything is."""

    destination: Path
    cases: list[CaseExport] = field(default_factory=list)
    free_bytes: int = 0
    blocked: str = ""
    code: Code | None = None

    @property
    def total_bytes(self) -> int:
        return sum(case.size_bytes for case in self.cases)

    @property
    def fits(self) -> bool:
        """Whether the destination has room, with a margin.

        Ten per cent, because a destination that fills during the export leaves
        exactly the half-copied state this whole module exists to avoid.
        """
        return self.free_bytes == 0 or self.free_bytes > self.total_bytes * 1.1

    @property
    def can_proceed(self) -> bool:
        return not self.blocked and bool(self.cases) and self.fits


@dataclass(slots=True)
class ExportResult:
    exported: list[Path] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    verified: bool = False
    """Every exported case matched its source digest-for-digest."""

    @property
    def succeeded(self) -> bool:
        return bool(self.exported) and not self.failed and self.verified


def plan_export(case_root: Path, destination: Path) -> ExportPlan:
    """Work out what exporting would move. Copies nothing."""
    plan = ExportPlan(destination=destination)

    if not case_root.is_dir():
        plan.blocked = f"{case_root} does not exist, so there is nothing to export."
        plan.code = ErrorCode.NOT_A_CASE
        return plan

    for entry in sorted(case_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if not (entry / "system").is_dir():
            continue
        files = [p for p in entry.rglob("*") if p.is_file() and not p.is_symlink()]
        plan.cases.append(
            CaseExport(
                source=entry,
                name=entry.name,
                size_bytes=sum(p.stat().st_size for p in files),
                file_count=len(files),
            )
        )

    if not plan.cases:
        plan.blocked = "No cases were found to export."
        return plan

    try:
        usage = shutil.disk_usage(destination if destination.exists() else destination.parent)
        plan.free_bytes = usage.free
    except OSError:
        plan.free_bytes = 0

    if not plan.fits:
        plan.blocked = (
            f"{destination} has {plan.free_bytes / 1024**3:.1f} GB free, and the "
            f"cases need {plan.total_bytes / 1024**3:.1f} GB."
        )
        plan.code = ErrorCode.INSUFFICIENT_DISK

    return plan


def export_cases(plan: ExportPlan) -> ExportResult:
    """Copy the cases out and verify every one by digest (FR-R12).

    A case that does not verify is reported as failed *and left in place at the
    destination*, so a user can inspect it. Deleting a partial copy would remove
    the only remaining evidence of what went wrong, on the one occasion when the
    original is about to be destroyed.
    """
    result = ExportResult()
    if not plan.can_proceed:
        return result

    plan.destination.mkdir(parents=True, exist_ok=True)

    for case in plan.cases:
        target = plan.destination / case.name
        if target.exists():
            result.failed.append((case.name, "a folder of that name is already there"))
            continue
        try:
            shutil.copytree(case.source, target, symlinks=True)
        except OSError as exc:
            result.failed.append((case.name, str(exc)))
            continue

        if _tree_digests(case.source) != _tree_digests(target):
            # FR-R9 asks for verification by checksum, not for the copy not
            # raising. A truncated field file raises nothing at all.
            result.failed.append((case.name, "the copy does not match the original"))
            continue

        result.exported.append(target)

    result.verified = bool(result.exported) and not result.failed
    log_event(
        _log,
        Event.CASE_WRITE,
        action="export",
        exported=len(result.exported),
        failed=len(result.failed),
    )
    return result


def verify_export(source: Path, exported: Path) -> bool:
    """Compare two case trees digest-for-digest.

    Separate from the copy so it can be run again later — before an unregister,
    a user who wants to check for themselves should be able to.
    """
    return _tree_digests(source) == _tree_digests(exported)
