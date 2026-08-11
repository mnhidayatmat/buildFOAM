"""Installing content, and refusing to (FR-L2, FR-L3, FR-L4).

This is the module that writes attacker-influenced bytes into a user's home
directory, so it is written as a series of refusals with an install at the end
rather than an install with checks bolted on.

**Nothing is written outside a temporary directory until every check has
passed.** The archive is inspected whole, extracted to a scratch directory,
and only then moved into place. A check-as-you-extract design leaves a partial
case behind when the fourth file is the bad one — and §9 says a rejected package
installs *nothing*, not *nearly nothing*.

Four refusals, and why each exists:

* **Checksum (E-L02).** The sha256 comes from the signed catalog, so this is
  where the catalog's signature actually starts protecting the user.
* **Executable bits (FR-L3).** Content is data in v1.0. This is not theoretical:
  the OpenFOAM tutorial suite contains 1,283 executable files, so any packaging
  of real tutorials meets this rule immediately.
* **Build recipes (FR-L3).** A ``Make/`` directory is a compiled extension,
  which is FR-L8 and v2.0. Seven tutorials contain one, so this rule also fires
  on real content rather than only on malicious content.
* **Path traversal.** An entry named ``../../.ssh/authorized_keys`` would escape
  the destination entirely. The PRD does not name this one — it is the oldest
  archive bug there is, and an installer that omitted it would be unsafe while
  passing every requirement written down.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.library.catalog import ContentItem

__all__ = [
    "InstallError",
    "InstallPlan",
    "Rejection",
    "inspect_archive",
    "install_item",
    "sha256_of",
]

_log = get_logger("library.install")

#: Directory names that mean "this package builds something".
_BUILD_DIRS = frozenset({"Make", "build", "cmake"})

#: Filenames that are build recipes wherever they appear.
_BUILD_FILES = frozenset({"Makefile", "makefile", "CMakeLists.txt", "wmake", "Allwmake"})

#: The executable bits, as stored in a zip entry's external attributes.
_EXECUTABLE_MASK = 0o111

#: Bounds an archive so a malicious one cannot exhaust the disk while being
#: checked. Generous for a case: the largest tutorial meshes are far smaller.
MAX_UNCOMPRESSED_BYTES = 2 * 1024**3
MAX_ENTRIES = 20_000


class InstallError(Exception):
    """A package that was refused. Carries its §9 code and what to do next."""

    def __init__(self, code: Code, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Rejection:
    """One reason an archive cannot be installed, naming the entry at fault."""

    entry: str
    reason: str


@dataclass(slots=True)
class InstallPlan:
    """What an archive would install, and everything wrong with it."""

    files: list[str] = field(default_factory=list)
    total_bytes: int = 0
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def acceptable(self) -> bool:
        return not self.rejections

    @property
    def top_level(self) -> list[str]:
        """The directories a user will see appear. FR-L5's dialog lists these."""
        roots = {PurePosixPath(name).parts[0] for name in self.files if name}
        return sorted(roots)


def sha256_of(path: Path, *, chunk: int = 1 << 20) -> str:
    """Hash a file without reading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def inspect_archive(archive: Path) -> InstallPlan:
    """Read an archive's index and judge every entry. Extracts nothing.

    Separate from installing so the trust dialog (FR-L5) can show a user exactly
    what a package contains *before* they agree to it, and so a refusal costs no
    disk at all.
    """
    plan = InstallPlan()

    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > MAX_ENTRIES:
                plan.rejections.append(
                    Rejection("", f"contains {len(entries)} entries, more than {MAX_ENTRIES}")
                )
                return plan

            for info in entries:
                plan.total_bytes += info.file_size
                if plan.total_bytes > MAX_UNCOMPRESSED_BYTES:
                    plan.rejections.append(Rejection(info.filename, "archive is implausibly large"))
                    return plan
                _judge(info, plan)
    except (zipfile.BadZipFile, OSError) as exc:
        plan.rejections.append(Rejection("", f"the file is not a readable archive: {exc}"))

    if not plan.files and not plan.rejections:
        plan.rejections.append(Rejection("", "the archive contains no files"))
    return plan


def _judge(info: zipfile.ZipInfo, plan: InstallPlan) -> None:
    name = info.filename
    mode = (info.external_attr >> 16) & 0xFFFF

    # Symlinks first: a link is neither a file nor a directory to the checks
    # below, and a link pointing outside the case would defeat all of them.
    if mode & 0xF000 == 0xA000:
        plan.rejections.append(Rejection(name, "contains a symbolic link"))
        return

    if info.is_dir():
        _judge_path(name, plan, directory=True)
        return

    _judge_path(name, plan, directory=False)
    if mode & _EXECUTABLE_MASK:
        # FR-L3: content is data in v1.0.
        plan.rejections.append(Rejection(name, "is marked executable"))
        return

    if PurePosixPath(name).name in _BUILD_FILES:
        plan.rejections.append(Rejection(name, "is a build recipe"))
        return

    plan.files.append(name)


def _judge_path(name: str, plan: InstallPlan, *, directory: bool) -> None:
    """Reject anything that would land outside the destination."""
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        plan.rejections.append(Rejection(name, "is an absolute path"))
        return

    parts = PurePosixPath(name).parts
    if ".." in parts:
        plan.rejections.append(Rejection(name, "escapes the destination directory"))
        return
    if not directory and any(part in _BUILD_DIRS for part in parts[:-1]):
        plan.rejections.append(Rejection(name, "is inside a build directory"))
    elif directory and any(part in _BUILD_DIRS for part in parts):
        plan.rejections.append(Rejection(name, "is a build directory"))


def install_item(
    item: ContentItem,
    archive: Path,
    destination: Path,
    *,
    name: str | None = None,
) -> Path:
    """Verify and install one catalog item, or raise and leave nothing behind.

    ``destination`` is the user's case area; the case lands in a directory named
    after the item. An existing directory is never overwritten — content install
    is not a place to silently destroy someone's work.
    """
    if (digest := sha256_of(archive)) != item.sha256:
        # E-L02. The expected hash came from the signed catalog, so this check is
        # what the signature was protecting.
        raise InstallError(
            ErrorCode.CHECKSUM_MISMATCH,
            f"{item.name} did not match the checksum the catalog gives for it.",
            detail=f"expected {item.sha256}, got {digest}",
        )

    plan = inspect_archive(archive)
    if not plan.acceptable:
        raise InstallError(
            ErrorCode.PACKAGE_NOT_DATA,
            f"{item.name} was not installed because it contains something that is not data.",
            detail="; ".join(f"{r.entry or 'archive'}: {r.reason}" for r in plan.rejections[:5]),
        )

    target = destination / (name or item.id)
    if target.exists():
        raise InstallError(
            ErrorCode.DESTINATION_EXISTS,
            f"{target.name} already exists. Rename or remove it first.",
            detail=str(target),
        )

    destination.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".install-", dir=destination))
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in plan.files:
                bundle.extract(member, staged)
        root = _single_root(staged, plan)
        root.replace(target)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError(
            ErrorCode.CHECKSUM_MISMATCH,
            f"{item.name} could not be unpacked.",
            detail=str(exc),
        ) from exc
    finally:
        shutil.rmtree(staged, ignore_errors=True)

    log_event(_log, Event.LIBRARY_INSTALL, item=item.id, target=str(target))
    return target


def _single_root(staged: Path, plan: InstallPlan) -> Path:
    """Unwrap a package that wraps its case in one directory.

    Most archives contain ``cavity/system/...`` rather than ``system/...``, and
    installing the wrapper would give the user ``cases/cavity/cavity``. When
    there is exactly one top-level directory it is treated as the wrapper;
    anything else is installed as-is, because guessing further would rearrange
    a package the author laid out deliberately.
    """
    roots = plan.top_level
    if len(roots) == 1:
        candidate = staged / roots[0]
        if candidate.is_dir():
            return candidate
    return staged
