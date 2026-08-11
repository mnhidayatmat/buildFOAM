"""Running OpenFOAM inside WSL (§3.2, FR-R7, DEC-05).

The bridge itself is not new. :class:`NativeSession`'s bashrc mode is §3.2's
command bridge verbatim — ``bash -c 'source <bashrc> && exec "$@"' bash <argv>``
— and has been exercised against a real OpenFOAM since M2. This class wraps that
same script in ``wsl.exe`` and translates paths around it. Building the bridge
once and reaching it two ways is why M2's suite can apply here unchanged, which
is M3's exit criterion.

**Honest scope.** Everything in :mod:`wslpath` is decidable anywhere and is
tested on every platform. Everything that invokes ``wsl.exe`` can only be
exercised on Windows, so this module is written so the *decidable* part is as
large as possible: argv construction is a pure function returning a token list,
and it is asserted directly. What remains unverified off-Windows is whether
``wsl.exe`` behaves as documented — not whether this code builds the right
command.

``--cd`` is used rather than ``cd &&`` inside the script. It takes the directory
as its own argument, so a case path containing a space, a quote or a ``$`` never
reaches a shell parser. It needs a WSL new enough to have the flag, which
Windows 11 22H2 — §3.1's floor — ships.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

from foamwb.branding import WSL_DISTRO_NAME
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.runtime.native import NativeProcess
from foamwb.services.runtime.session import Process, RuntimeKind, RuntimeSession
from foamwb.services.runtime.wslpath import PathOutsideRuntimeError, to_host, to_runtime

__all__ = ["WSL_EXECUTABLE", "WslSession", "wsl_argv"]

_log = get_logger("runtime.wsl")

#: Resolved by name rather than by absolute path. On 32-bit-emulating callers
#: the System32 copy is not the one that answers, and letting Windows resolve it
#: is what gets the right one.
WSL_EXECUTABLE = "wsl.exe"


def wsl_argv(
    argv: Sequence[str],
    *,
    distro: str,
    bashrc: PurePosixPath,
    cwd: PurePosixPath | None = None,
) -> list[str]:
    """Build the full ``wsl.exe`` command line. A pure function, so it is testable.

    The user's command is passed as *positional parameters* and expanded with
    ``"$@"``. Only the bashrc path is interpolated into the script text, and it
    is quoted. Nothing the user supplies is ever re-parsed by a shell.
    """
    if not argv:
        raise ValueError("argv must not be empty")

    command = [WSL_EXECUTABLE, "-d", distro]
    if cwd is not None:
        command += ["--cd", str(cwd)]

    script = f'source {shlex.quote(str(bashrc))} >/dev/null 2>&1 && exec "$@"'
    command += ["--", "bash", "-c", script, "bash", *argv]
    return command


class WslSession(RuntimeSession):
    """A session that runs commands inside the dedicated WSL distribution."""

    def __init__(
        self,
        bashrc: PurePosixPath | str,
        *,
        distro: str = WSL_DISTRO_NAME,
    ) -> None:
        """``bashrc`` is required, and deliberately has no default.

        The path is version-suffixed — ``/usr/lib/openfoam/openfoam2512/etc/``
        — and the manifest owns it (NFR-M3, DEC-15). A default here would be a
        version literal in code by another name, and a wrong one would produce a
        session that sources nothing and then fails inside OpenFOAM with a
        message about a missing solver rather than a missing environment.

        :meth:`for_version` is the ordinary way in.
        """
        self._distro = distro
        self._bashrc = PurePosixPath(bashrc)
        self._processes: list[NativeProcess] = []

    @classmethod
    def for_version(cls, version: str, *, distro: str = WSL_DISTRO_NAME) -> WslSession:
        """Build a session for a release named in the manifest.

        A version the manifest does not describe raises ``ManifestError``, which
        names the releases it does know. Guessing a path from the version string
        would work for one lineage and silently fail for the other, which is the
        failure DEC-15's indirection exists to prevent.
        """
        from foamwb.services.runtime.manifest import ManifestError, load_manifest

        spec = load_manifest().release(version).platform("linux")
        if spec is None or not spec.bashrc:
            raise ManifestError(f"The manifest describes no Linux layout for {version}.")
        return cls(PurePosixPath(spec.bashrc), distro=distro)

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.WSL

    @property
    def distro(self) -> str:
        return self._distro

    @property
    def bashrc(self) -> PurePosixPath:
        return self._bashrc

    # -- execution ---------------------------------------------------------

    def command_for(self, argv: Sequence[str], *, cwd: PurePosixPath | None = None) -> list[str]:
        """The argv that would reach the operating system. Exposed for testing."""
        return wsl_argv(argv, distro=self._distro, bashrc=self._bashrc, cwd=cwd)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: PurePosixPath | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Process:
        """Start ``argv`` inside the distro with the OpenFOAM environment sourced."""
        command = self.command_for(argv, cwd=cwd)

        # WSLENV is how a Windows-side variable is made visible inside the
        # distro; setting the variable alone does nothing, which is a common and
        # silent way for an environment override to be ignored.
        environment = dict(os.environ)
        if env:
            environment.update(env)
            existing = environment.get("WSLENV", "")
            names = [n for n in env if n not in existing.split(":")]
            environment["WSLENV"] = ":".join(filter(None, [existing, *names]))

        log_event(_log, Event.COMMAND_BEGIN, argv=list(argv), cwd=str(cwd) if cwd else None)

        popen = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Its own process group, so a stop reaches the whole tree. Note this
            # governs the Windows-side wsl.exe; signalling the Linux-side tree is
            # what the abort function object (FR-S5) is for, and is one more
            # reason Stop & Write is the default rather than SIGTERM.
            start_new_session=True,
        )

        process = NativeProcess(popen, argv)
        self._processes.append(process)
        return process

    # -- paths -------------------------------------------------------------

    def to_runtime_path(self, host_path: Path) -> PurePosixPath:
        """Windows path → distro path (FR-V3, NFR-C4)."""
        return to_runtime(PureWindowsPath(host_path), distro=self._distro)

    def to_host_path(self, runtime_path: PurePosixPath) -> Path:
        """Distro path → Windows path, for Explorer and ParaView (FR-A3, FR-V3)."""
        return Path(str(to_host(runtime_path, distro=self._distro)))

    def is_reachable(self, host_path: Path) -> bool:
        """Whether a Windows path can be seen from inside the distro.

        Used before offering to open a case: a path on a mapped network drive is
        perfectly openable in Explorer and completely invisible to the solver,
        and finding that out at run time turns a clear message into a confusing
        "cannot find file" from OpenFOAM.
        """
        try:
            self.to_runtime_path(host_path)
        except PathOutsideRuntimeError:
            return False
        return True

    def close(self) -> None:
        for process in self._processes:
            if process.returncode is None:
                process.kill()
        self._processes.clear()
