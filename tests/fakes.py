"""Test doubles for the runtime seam.

A fake :class:`RuntimeSession` rather than a mocked one. The interface is small
and its contract is behavioural — process groups, streamed lines, exit codes — so
a hand-written double states the contract in one readable place, and any real
implementation that diverges from it is a genuine defect rather than a test that
needs updating.

The suite runs against these; the real runtime is exercised separately by the
tests marked ``requires_runtime``, which need OpenFOAM installed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath

from foamwb.services.runtime.session import Process, RuntimeKind, RuntimeSession

__all__ = ["FakeProcess", "FakeSession", "ScriptedCommand"]


class ScriptedCommand:
    """What a fake session should do when it sees a given command."""

    def __init__(
        self,
        lines: Sequence[str] = (),
        exit_code: int = 0,
        raises: OSError | None = None,
    ) -> None:
        self.lines = list(lines)
        self.exit_code = exit_code
        self.raises = raises


class FakeProcess(Process):
    def __init__(self, argv: Sequence[str], script: ScriptedCommand) -> None:
        self._argv = tuple(argv)
        self._script = script
        self._returncode: int | None = None
        self.terminated = False
        self.killed = False

    @property
    def pid(self) -> int | None:
        return 4242

    @property
    def returncode(self) -> int | None:
        return self._returncode

    def lines(self) -> Iterator[str]:
        yield from self._script.lines

    def wait(self, timeout: float | None = None) -> int:
        self._returncode = self._script.exit_code
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = -15

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9


class FakeSession(RuntimeSession):
    """Records what it was asked to run and replays a scripted response."""

    def __init__(self, scripts: Mapping[str, ScriptedCommand] | None = None) -> None:
        self._scripts = dict(scripts or {})
        self.calls: list[tuple[tuple[str, ...], PurePosixPath | None]] = []
        self.processes: list[FakeProcess] = []
        self.closed = False

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.NATIVE

    def script(self, command: str, script: ScriptedCommand) -> FakeSession:
        self._scripts[command] = script
        return self

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: PurePosixPath | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Process:
        self.calls.append((tuple(argv), cwd))
        # Keyed on the executable, so a scripted response survives the mpirun
        # wrapper a parallel plan adds around it.
        key = next((token for token in argv if token in self._scripts), argv[0])
        process = FakeProcess(argv, self._scripts.get(key, ScriptedCommand()))
        if process._script.raises is not None:
            raise process._script.raises
        self.processes.append(process)
        return process

    def to_runtime_path(self, host_path: Path) -> PurePosixPath:
        return PurePosixPath(host_path)

    def to_host_path(self, runtime_path: PurePosixPath) -> Path:
        return Path(runtime_path)

    def close(self) -> None:
        self.closed = True

    # -- assertions --------------------------------------------------------

    @property
    def commands(self) -> list[tuple[str, ...]]:
        return [argv for argv, _cwd in self.calls]

    def ran(self, executable: str) -> bool:
        return any(executable in argv for argv in self.commands)
