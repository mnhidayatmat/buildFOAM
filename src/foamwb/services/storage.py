"""Is this case somewhere a run can survive? (FR-C8, E-C06)

An OpenFOAM write interval creates one file per field per process. On a network
share, a synced folder, or a Windows drive seen from inside WSL, that workload is
roughly an order of magnitude slower than a local disk — and a long run can spend
more time writing than solving.

**Detected before the run, not diagnosed after it.** A user whose twelve-hour run
took eighteen has no way to attribute the difference, and nothing in the solver's
output mentions storage. The warning is worth little afterwards and a great deal
in advance.

**A warning, never a refusal.** Slow is not wrong: a shared drive may be the only
place a student is allowed to write, and an application that refused would simply
be unusable there. §7.9 rule 3 asks that a finding carry its remedy, so it names
where to move the case rather than only what is wrong with where it is.

Detection is by *evidence about the path*, not by timing it. A benchmark at open
would add a delay to every case to answer a question that the mount table
already answers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from foamwb.codes import Code, ErrorCode

__all__ = ["StorageKind", "StorageVerdict", "classify_path"]


class StorageKind(StrEnum):
    """Where a case lives, in terms that change the advice."""

    LOCAL = "local"
    NETWORK = "network"
    """A share on another machine: UNC, or an NFS/SMB mount."""

    SYNCED = "synced"
    """A folder a sync client watches. Fast, but every write is uploaded and
    the client can rewrite files underneath a running solver."""

    CROSS_OS = "cross_os"
    """A Windows drive seen from inside WSL, or the reverse — DEC-05's 9p path."""

    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StorageVerdict:
    kind: StorageKind
    reason: str = ""
    code: Code | None = None

    @property
    def is_slow(self) -> bool:
        return self.kind in {StorageKind.NETWORK, StorageKind.SYNCED, StorageKind.CROSS_OS}


#: Directory names sync clients use. Matched on a path component so that
#: ``~/Dropbox/cases`` is caught and ``~/my-dropbox-notes`` is not.
_SYNC_MARKERS = frozenset(
    {
        "Dropbox",
        "OneDrive",
        "Google Drive",
        "GoogleDrive",
        "iCloud Drive",
        "Creative Cloud Files",
        "Nextcloud",
        "ownCloud",
        "Sync",
    }
)

#: Filesystem types that are somebody else's disk.
_NETWORK_FS = frozenset({"nfs", "smbfs", "cifs", "afpfs", "webdav", "ftp", "fuse.sshfs"})


def classify_path(path: Path) -> StorageVerdict:
    """Judge where a case lives. Cheap: no I/O beyond a stat."""
    text = str(path)

    # A UNC path is a share by definition, on any platform that produced it.
    if text.startswith("\\\\") or text.startswith("//"):
        if "wsl.localhost" in text.lower() or "wsl$" in text.lower():
            # Inside the distro is exactly where DEC-05 wants cases to be.
            return StorageVerdict(kind=StorageKind.LOCAL)
        return StorageVerdict(
            kind=StorageKind.NETWORK,
            reason="This case is on a network share. An OpenFOAM run writes "
            "thousands of small files, which is the slowest thing a share does.",
            code=ErrorCode.SLOW_PATH,
        )

    parts = set(path.parts)
    if marker := (parts & _SYNC_MARKERS):
        return StorageVerdict(
            kind=StorageKind.SYNCED,
            reason=f"This case is inside {next(iter(marker))}. The sync client "
            "will upload every file a run writes, and may change files while the "
            "solver is using them.",
            code=ErrorCode.SLOW_PATH,
        )

    # /mnt/c inside WSL: DEC-05's 9p bridge, an order of magnitude slower for
    # many small files, and without POSIX permissions or working symlinks.
    if len(path.parts) > 2 and path.parts[1] == "mnt" and len(path.parts[2]) == 1:
        return StorageVerdict(
            kind=StorageKind.CROSS_OS,
            reason="This case is on a Windows drive seen from Linux. Small-file "
            "writes cross a translation layer and are far slower than the "
            "distribution's own filesystem.",
            code=ErrorCode.SLOW_PATH,
        )

    if _is_network_mount(path):
        return StorageVerdict(
            kind=StorageKind.NETWORK,
            reason="This case is on a network filesystem. An OpenFOAM run writes "
            "thousands of small files, which is the slowest thing it does.",
            code=ErrorCode.SLOW_PATH,
        )

    return StorageVerdict(kind=StorageKind.LOCAL)


def _is_network_mount(path: Path) -> bool:
    """Whether the path sits on a remotely-mounted filesystem.

    Best effort, and silent when it cannot tell. A wrong "your disk is slow"
    warning on a perfectly good local disk is worse than no warning: users who
    learn to dismiss one banner dismiss the next.
    """
    try:
        import subprocess

        if not hasattr(os, "statvfs"):
            return False
        result = subprocess.run(
            ["df", "-P", str(path)], capture_output=True, text=True, timeout=2, check=False
        )
        if result.returncode != 0:
            return False
        lines = result.stdout.strip().splitlines()
        if len(lines) < 2:
            return False
        device = lines[1].split()[0]
        return ":" in device or device.startswith("//")
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
