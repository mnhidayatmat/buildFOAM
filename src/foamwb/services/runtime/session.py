"""The runtime abstraction: "run a command in an OpenFOAM environment" (§4.2).

Three implementations land later — ``NativeSession`` (macOS, M2), ``WslSession``
(Windows, M3) and ``DockerSession`` (macOS fallback, FR-R10). Everything above
this seam is written once, against this interface.

The interface carries three responsibilities that are easy to get wrong if they
are left implicit:

**Environment ownership.** Every OpenFOAM command must run in a shell that has
sourced the correct ``etc/bashrc``. That is the session's job and nobody else's;
no caller ever constructs a ``source ... &&`` string. This is barrier 2 of §1.2,
solved once.

**Path translation.** ``to_runtime_path`` and ``to_host_path`` are a pair, and
NFR-C4 requires both to survive Unicode and spaces — including across the WSL
bridge, where the host path is a ``\\\\wsl.localhost\\`` UNC path and the runtime
path is ext4. Callers must never hand-build either form.

**Process-group ownership.** :meth:`RuntimeSession.run` returns a
:class:`Process` whose ``terminate`` and ``kill`` act on the whole process group,
because an MPI job is a tree and signalling only its root orphans the ranks
(FR-S10, NFR-R6).
"""

from __future__ import annotations

import abc
from collections.abc import Iterator, Mapping, Sequence
from enum import StrEnum
from pathlib import Path, PurePosixPath

__all__ = ["Process", "RuntimeKind", "RuntimeSession"]


class RuntimeKind(StrEnum):
    """Which flavour of runtime a session drives."""

    NATIVE = "native"
    """Native install on the host — macOS via the Homebrew tap (§3.3)."""

    WSL = "wsl"
    """A dedicated WSL2 distribution on Windows (DEC-12)."""

    DOCKER = "docker"
    """A container, used as the macOS fallback (FR-R10)."""


class Process(abc.ABC):
    """A running command inside a runtime.

    Deliberately narrower than :class:`subprocess.Popen`: no ``stdin``, no
    ``communicate``, no direct pipe access. OpenFOAM solvers do not take
    interactive input, and exposing the pipes would let callers deadlock on a
    full buffer during a 5 000 line/s log burst (NFR-P3).
    """

    @property
    @abc.abstractmethod
    def pid(self) -> int | None:
        """Host-visible process id, or ``None`` where the runtime hides it.

        A WSL or Docker session runs the real solver inside the guest, so this is
        the id of the *bridge* process. Signalling still works, because the
        implementation is responsible for propagating it inward, but the number
        is not the solver's own pid and must not be shown as one.
        """

    @property
    @abc.abstractmethod
    def returncode(self) -> int | None:
        """Exit status, or ``None`` while still running."""

    @abc.abstractmethod
    def lines(self) -> Iterator[str]:
        """Yield merged stdout/stderr, one decoded line at a time, as they arrive.

        Merged rather than separated because OpenFOAM writes diagnostics to both
        and the user's mental model is one log; interleaving order is the
        information. Decoding is lenient — a solver that emits a stray byte must
        not take down the log pane.

        The iterator ends when the process closes its output. Consuming it is how
        FR-S2 gets lines onto the screen within 500 ms of emission.
        """

    @abc.abstractmethod
    def wait(self, timeout: float | None = None) -> int:
        """Block until exit and return the status.

        Raises :class:`TimeoutError` if ``timeout`` elapses first.
        """

    @abc.abstractmethod
    def terminate(self) -> None:
        """SIGTERM the process *group*.

        This is FR-S5's *Stop Now*, never the default stop. The default is
        *Stop & Write*, which is a graceful OpenFOAM-level stop and does not go
        through this method at all — SIGTERM mid-write leaves a partial time
        directory that breaks reconstruction and ParaView (DEC-14).
        """

    @abc.abstractmethod
    def kill(self) -> None:
        """SIGKILL the process group. FR-S5's *Force Kill*."""


class RuntimeSession(abc.ABC):
    """Abstracts "run a command in an OpenFOAM environment"."""

    @property
    @abc.abstractmethod
    def kind(self) -> RuntimeKind:
        """Which flavour this session drives."""

    @abc.abstractmethod
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: PurePosixPath | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Process:
        """Start ``argv`` with the OpenFOAM environment sourced.

        ``argv`` is a token sequence, never a shell string, so that a case name
        containing a space or a quote cannot become a command injection or a
        mangled argument. ``cwd`` is a *runtime* path — translate first with
        :meth:`to_runtime_path` if you hold a host path. ``env`` overlays the
        sourced environment; it does not replace it.
        """

    @abc.abstractmethod
    def to_runtime_path(self, host_path: Path) -> PurePosixPath:
        """Translate a host path into the runtime's filesystem namespace."""

    @abc.abstractmethod
    def to_host_path(self, runtime_path: PurePosixPath) -> Path:
        """Translate a runtime path back into a host path.

        The inverse of :meth:`to_runtime_path` for any path reachable from both
        sides. FR-A3 and FR-V3 depend on it: opening the case folder in Explorer
        and handing a case to the Windows-side ParaView both need the UNC form.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Release whatever the session holds open.

        Implementations must make this idempotent and safe to call with processes
        still running; NFR-R6 requires shutdown to reap them rather than orphan
        them.
        """

    def __enter__(self) -> RuntimeSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
