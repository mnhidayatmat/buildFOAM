"""Translating paths across the WSL boundary (FR-V3, FR-A3, NFR-C4, DEC-05).

Pure string and path logic, deliberately separated from :mod:`wsl` so that the
part which is *decidable* can be tested anywhere, including on a machine with no
Windows and no WSL. Everything here is verified on this repository's CI-less
preflight regardless of platform; only the part that actually invokes ``wsl.exe``
depends on being on Windows.

**Two families of path, and they are not interchangeable** (DEC-05):

* Cases live on the distro's own ext4 filesystem — ``/home/u/cases/pitzDaily``.
  Windows reaches those through the UNC share
  ``\\\\wsl.localhost\\<distro>\\home\\u\\cases\\pitzDaily``.
* Windows drives are visible from inside the distro under ``/mnt/c``, and DEC-05
  keeps cases *off* that path: it crosses a 9p translation layer that is roughly
  an order of magnitude slower for many-small-file work, which is exactly what an
  OpenFOAM write interval produces. It also has no POSIX permissions or symlinks,
  which breaks the ``0.orig`` symlink pattern used across the tutorial suite, and
  NTFS case-insensitivity collides ``U`` with ``u``.

Both directions round-trip, and that is asserted rather than assumed: a path that
came from Windows must come back as the same Windows path, or the Explorer
integration (FR-A3) opens the wrong folder.

``\\\\wsl$\\`` is accepted on input and never produced on output. It is the older
spelling of the same share, still present in older documentation and in paths
users have bookmarked, so refusing it would reject something Windows itself still
resolves — but the modern form is what gets written down.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

__all__ = [
    "MOUNT_ROOT",
    "UNC_PREFIX",
    "PathOutsideRuntimeError",
    "to_host",
    "to_runtime",
]

#: Where WSL mounts Windows drives inside the distro.
MOUNT_ROOT = PurePosixPath("/mnt")

#: The modern UNC prefix for a distro's filesystem. ``\\wsl$\`` is the older
#: spelling of the same thing and is accepted on input.
UNC_PREFIX = "wsl.localhost"
_LEGACY_UNC_PREFIX = "wsl$"

_DRIVE = re.compile(r"^([A-Za-z]):[\\/]?$")


class PathOutsideRuntimeError(ValueError):
    """A path that has no meaning inside the distro.

    Raised rather than guessed at. A mapped network drive or a UNC share on
    another machine is reachable from Windows but is not mounted in the distro,
    so inventing a plausible ``/mnt/...`` for it would produce a path the solver
    cannot open — and the failure would surface much later, as a missing case.
    """


def to_runtime(host_path: PureWindowsPath | str, *, distro: str) -> PurePosixPath:
    """Windows path → the path the distro sees.

    ``C:\\Users\\Ali Baba\\kes`` → ``/mnt/c/Users/Ali Baba/kes``
    ``\\\\wsl.localhost\\<distro>\\home\\u\\kes`` → ``/home/u/kes``

    Spaces and non-ASCII characters pass through untouched (NFR-C4). Nothing is
    quoted or escaped here: the result is one argument in a token list, and
    escaping it would embed backslashes in a filename.
    """
    windows = PureWindowsPath(host_path)
    parts = windows.parts
    if not parts:
        raise PathOutsideRuntimeError("An empty path has no location in the distro.")

    anchor = parts[0]

    # A UNC share: \\wsl.localhost\<distro>\... or the legacy \\wsl$\<distro>\...
    if anchor.startswith("\\\\"):
        server, _, share = anchor.strip("\\").partition("\\")
        if server.lower() not in {UNC_PREFIX, _LEGACY_UNC_PREFIX}:
            raise PathOutsideRuntimeError(
                f"\\\\{server} is a network location, which is not mounted inside "
                f"the {distro} distribution."
            )
        if share.lower() != distro.lower():
            raise PathOutsideRuntimeError(
                f"That path is inside the {share} distribution, not {distro}."
            )
        return PurePosixPath("/", *parts[1:])

    # A drive letter: C:\... -> /mnt/c/...
    if (match := _DRIVE.match(anchor)) is not None:
        return PurePosixPath(MOUNT_ROOT, match.group(1).lower(), *parts[1:])

    raise PathOutsideRuntimeError(
        f"{host_path} is not an absolute Windows path, so it cannot be located "
        "inside the distribution."
    )


def to_host(runtime_path: PurePosixPath | str, *, distro: str) -> PureWindowsPath:
    """The path the distro sees → the Windows path.

    ``/mnt/c/Users/Ali Baba/kes`` → ``C:\\Users\\Ali Baba\\kes``
    ``/home/u/kes`` → ``\\\\wsl.localhost\\<distro>\\home\\u\\kes``

    A ``/mnt/<letter>`` path becomes a drive letter rather than a UNC path into
    the distro. Both spellings would open, but only the drive letter is the file
    Windows actually owns — handing back a UNC route to a file on ``C:`` would
    send every subsequent access through the 9p layer for no reason.
    """
    posix = PurePosixPath(runtime_path)
    if not posix.is_absolute():
        raise PathOutsideRuntimeError(
            f"{runtime_path} is not an absolute path inside the distribution."
        )

    parts = posix.parts[1:]  # drop the leading "/"

    # A bare /mnt/c falls out of this too: parts[2:] is empty and the result is
    # the drive root.
    if len(parts) >= 2 and parts[0] == MOUNT_ROOT.name and _is_drive_letter(parts[1]):
        return PureWindowsPath(f"{parts[1].upper()}:\\", *parts[2:])

    return PureWindowsPath(f"\\\\{UNC_PREFIX}\\{distro}", *parts)


def _is_drive_letter(part: str) -> bool:
    return len(part) == 1 and part.isascii() and part.isalpha()
