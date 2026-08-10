"""Native macOS runtime — the first :class:`RuntimeSession` implementation (§3.3).

DEC-11 builds this platform first: there is no bridge, no elevation and no
reboot, so M2 proves the *product* before M3 fights the *platform*.

**Two ways in, because installations differ.** The gerlero tap ships an
``OpenFOAM.app`` bundle containing OpenFOAM's own ``etc/openfoam`` launcher — "run
an OpenFOAM application after first sourcing the etc/bashrc file" — and handing
that an argv is the best route where it exists, since the environment is
constructed by the code that owns it and cannot drift from what a terminal user
gets.

The Debian packages that serve Linux and the WSL distribution ship ``etc/bashrc``
without that wrapper, so the session sources the bashrc itself and execs into the
command. That is exactly §3.2's command bridge —
``bash -lc "source <bashrc> && <cmd>"`` — which means this is not a detour for
CI: it is the mechanism ``WslSession`` needs at M3, proven a milestone early.

**The payload is a disk image.** The bundle mounts a volume on first use, which
has two consequences worth stating rather than discovering. The first command
after a reboot is slow because it triggers the mount, so a canary that times out
in two seconds would report a working install as broken. And ``WM_PROJECT_DIR``
points inside ``/Volumes``, so a path that resolves today may not exist after the
user ejects the volume — which is why :meth:`NativeSession.verify` re-runs the
canary rather than caching a result.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.runtime.session import Process, RuntimeKind, RuntimeSession

__all__ = ["NativeProcess", "NativeSession"]

_log = get_logger("runtime.native")

#: Generous, because the first command after a reboot triggers the disk-image
#: mount. A canary that gave up sooner would report a working install as broken,
#: which FR-R5 exists to prevent in the opposite direction.
DEFAULT_CANARY_TIMEOUT = 60.0


class NativeProcess(Process):
    """A command running under the OpenFOAM launcher.

    Owns a **process group**, not a process. An MPI job is a tree, and signalling
    only its root orphans the ranks — FR-S10 requires force-quitting the
    application to leave no ``simpleFoam`` or ``mpirun`` behind, and NFR-R6 makes
    that a reliability requirement rather than a nicety.
    """

    def __init__(self, popen: subprocess.Popen[str], argv: Sequence[str]) -> None:
        self._popen = popen
        self._argv = tuple(argv)

    @property
    def pid(self) -> int | None:
        return self._popen.pid

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode

    @property
    def argv(self) -> tuple[str, ...]:
        return self._argv

    def lines(self) -> Iterator[str]:
        """Yield merged stdout/stderr as they arrive, one line at a time.

        Merged because OpenFOAM writes diagnostics to both and the user's mental
        model is one log — the interleaving *is* information. Decoding is lenient
        so a stray byte from a third-party solver cannot take down the log pane.
        """
        stream = self._popen.stdout
        if stream is None:  # pragma: no cover - always piped by NativeSession.run
            return
        for line in stream:
            yield line.rstrip("\n")
        stream.close()

    def wait(self, timeout: float | None = None) -> int:
        try:
            return self._popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"{self._argv[0]!r} did not exit within {timeout}s") from exc

    def _signal_group(self, sig: int) -> None:
        """Signal the whole process group, tolerating a race with exit.

        The process may finish between the liveness check and the signal, and a
        stop that raises because the run already ended would be a dead end in the
        UI for a case that actually succeeded.
        """
        if self._popen.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self._popen.pid), sig)
        except (ProcessLookupError, PermissionError):
            self._popen.send_signal(sig)

    def terminate(self) -> None:
        """SIGTERM the group — FR-S5's *Stop Now*, never the default stop."""
        self._signal_group(signal.SIGTERM)

    def kill(self) -> None:
        """SIGKILL the group — FR-S5's *Force Kill*."""
        self._signal_group(signal.SIGKILL)


class NativeSession(RuntimeSession):
    """Runs OpenFOAM commands through a bundle's launcher script."""

    def __init__(self, launcher: Path | None = None, *, bashrc: Path | None = None) -> None:
        """Supply exactly one of ``launcher`` or ``bashrc``.

        Refusing both and refusing neither, rather than picking a default: a
        session that silently ran commands outside the OpenFOAM environment would
        fail with "command not found" for every solver, which looks like a broken
        installation rather than a misconfigured session.
        """
        if (launcher is None) == (bashrc is None):
            raise ValueError("Provide exactly one of launcher or bashrc")
        self._launcher = launcher
        self._bashrc = bashrc
        self._processes: list[NativeProcess] = []

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.NATIVE

    @property
    def launcher(self) -> Path | None:
        return self._launcher

    @property
    def bashrc(self) -> Path | None:
        return self._bashrc

    def _wrap(self, argv: Sequence[str]) -> list[str]:
        """Render the argv that actually reaches the operating system."""
        if self._launcher is not None:
            return [str(self._launcher), *argv]

        # The command is passed as positional parameters and expanded with "$@",
        # so nothing in it is ever re-parsed by the shell. Only the bashrc path is
        # interpolated, and it is quoted. A case directory containing a space, a
        # quote or a $ therefore stays one argument.
        assert self._bashrc is not None
        script = f'source {shlex.quote(str(self._bashrc))} >/dev/null 2>&1 && exec "$@"'
        return ["bash", "-c", script, "bash", *argv]

    # -- execution ---------------------------------------------------------

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: PurePosixPath | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Process:
        """Start ``argv`` with the OpenFOAM environment sourced.

        The command is passed as a token list, never a shell string, so a case
        directory containing a space, a quote or a ``$`` is an argument rather
        than a command injection (NFR-C4 requires those paths to work).
        """
        if not argv:
            raise ValueError("argv must not be empty")

        command = self._wrap(argv)
        environment = {**os.environ, **(env or {})}

        log_event(_log, Event.COMMAND_BEGIN, argv=list(argv), cwd=str(cwd) if cwd else None)

        popen = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Its own process group, so stop and force-kill reach the whole tree
            # rather than just the launcher (FR-S10).
            start_new_session=True,
        )

        process = NativeProcess(popen, argv)
        self._processes.append(process)
        return process

    def run_to_completion(
        self,
        argv: Sequence[str],
        *,
        cwd: PurePosixPath | None = None,
        timeout: float | None = None,
    ) -> tuple[int, str]:
        """Run and collect all output. For short probes, not for solvers.

        A solver's log is streamed so the UI stays responsive at 5 000 lines/s
        (NFR-P3); buffering one in memory would defeat that and could be
        gigabytes.

        ``timeout`` bounds the *whole* call. Reading a pipe blocks, so a deadline
        applied only to :meth:`Process.wait` would never fire — the read loop
        would sit there forever and the wizard would hang on a command that never
        answers. A watchdog kills the process group instead, which closes the pipe
        and ends the loop.
        """
        process = self.run(argv, cwd=cwd)
        timed_out = threading.Event()

        watchdog: threading.Timer | None = None
        if timeout is not None:

            def _expire() -> None:
                timed_out.set()
                process.kill()

            watchdog = threading.Timer(timeout, _expire)
            watchdog.daemon = True
            watchdog.start()

        try:
            output = list(process.lines())
            code = process.wait()
        finally:
            if watchdog is not None:
                watchdog.cancel()

        if timed_out.is_set():
            raise TimeoutError(f"{argv[0]!r} did not finish within {timeout}s")

        log_event(_log, Event.COMMAND_END, argv=list(argv), exit_code=code)
        return code, "\n".join(output)

    # -- path translation --------------------------------------------------

    def to_runtime_path(self, host_path: Path) -> PurePosixPath:
        """Identity: a native runtime shares the host filesystem.

        Implemented rather than omitted because callers must not have to know
        which kind of session they hold — that is the entire point of the
        abstraction, and it is what lets the WSL bridge land at M3 without
        touching anything above this layer.
        """
        return PurePosixPath(host_path)

    def to_host_path(self, runtime_path: PurePosixPath) -> Path:
        return Path(runtime_path)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Terminate anything still running. Idempotent (NFR-R6)."""
        for process in self._processes:
            if process.returncode is None:
                process.kill()
        self._processes.clear()
