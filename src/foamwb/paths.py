"""Host-side application paths (§5.3).

Every path is derived from :mod:`foamwb.branding`; no product name appears here.

Windows case storage is deliberately absent from this module. Default cases live
inside the dedicated WSL distribution on ext4 (DEC-05), so their host-visible
location is a ``\\\\wsl.localhost\\`` UNC path that depends on the distribution's
Linux user — a fact only :class:`~foamwb.services.runtime.session.RuntimeSession`
knows. Path translation is that abstraction's job, not this module's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath

from foamwb.branding import CONTENT_NAMESPACE, USER_DATA_DIR_NAME

__all__ = [
    "Platform",
    "cache_dir",
    "config_file",
    "current_platform",
    "log_dir",
    "macos_cases_dir",
    "macos_content_dir",
    "manifest_dir",
    "runtime_content_subpath",
    "user_data_dir",
]


class Platform:
    """Supported host platforms (§3.1).

    Linux is absent by design: NG4 rules out a native Linux desktop build, since
    Linux users already have a working CLI and package manager. Linux is still a
    first-class *CI* target for the golden-case regression (§12.3), which
    exercises the service layer headlessly rather than the application.
    """

    WINDOWS = "windows"
    MACOS = "macos"


def current_platform() -> str:
    """Return the host platform, or raise on an unsupported one."""
    if sys.platform == "win32":
        return Platform.WINDOWS
    if sys.platform == "darwin":
        return Platform.MACOS
    raise RuntimeError(
        f"Unsupported host platform {sys.platform!r}. "
        "Supported desktop platforms are Windows and macOS (§3.1, NG4)."
    )


def _windows_dir(env_var: str, fallback: Path) -> Path:
    raw = os.environ.get(env_var)
    base = Path(raw) if raw else fallback
    return base / USER_DATA_DIR_NAME


def user_data_dir() -> Path:
    """Roaming configuration directory.

    Windows: ``%APPDATA%\\<name>``. macOS: ``~/Library/Application Support/<name>``.
    """
    if current_platform() == Platform.WINDOWS:
        return _windows_dir("APPDATA", Path.home() / "AppData" / "Roaming")
    return Path.home() / "Library" / "Application Support" / USER_DATA_DIR_NAME


def _local_data_dir() -> Path:
    """Machine-local (non-roaming) data directory.

    On Windows this is ``%LOCALAPPDATA%``, kept distinct from ``%APPDATA%``
    because a roaming profile must not carry a multi-gigabyte download cache
    across the network (§14.1).
    """
    if current_platform() == Platform.WINDOWS:
        return _windows_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    return Path.home() / "Library" / "Application Support" / USER_DATA_DIR_NAME


def config_file() -> Path:
    """Path to ``config.json``."""
    return user_data_dir() / "config.json"


def manifest_dir() -> Path:
    """Cache for the independently-versioned runtime manifest (§3.4, §15.1)."""
    return _local_data_dir() / "manifest"


def log_dir() -> Path:
    """Application log directory (JSON lines, see :mod:`foamwb.logs`)."""
    if current_platform() == Platform.WINDOWS:
        return _local_data_dir() / "logs"
    return Path.home() / "Library" / "Logs" / USER_DATA_DIR_NAME


def cache_dir() -> Path:
    """Resumable download cache (NFR-R1)."""
    if current_platform() == Platform.WINDOWS:
        return _local_data_dir() / "cache"
    return Path.home() / "Library" / "Caches" / USER_DATA_DIR_NAME


def macos_cases_dir() -> Path:
    """Default case root on macOS — native APFS, no bridge required (§3.3)."""
    return Path.home() / USER_DATA_DIR_NAME / "cases"


def macos_content_dir() -> Path:
    """Installed content root on macOS (§5.3)."""
    return Path.home() / USER_DATA_DIR_NAME / "content"


def runtime_content_subpath() -> PurePosixPath:
    """Content location *inside* the runtime, relative to ``$WM_PROJECT_USER_DIR``.

    Always POSIX: this is a path in the Linux runtime, not on the host.
    """
    return PurePosixPath(CONTENT_NAMESPACE) / "content"
