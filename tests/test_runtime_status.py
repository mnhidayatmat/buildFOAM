"""RuntimeStatus (FR-R2) and the RuntimeSession contract (§4.2).

The status tests encode one rule: a non-ready runtime always carries a §9 code.
The session tests assert only that the abstraction is *complete* — that a
concrete implementation is forced to supply every operation the layers above
depend on. The real implementations arrive at M2 (native), M3 (WSL) and with
FR-R10 (Docker), each with its own integration suite against a live runtime.
"""

from __future__ import annotations

import abc
import inspect

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.runtime import RuntimeKind, RuntimeSession, RuntimeState, RuntimeStatus
from foamwb.services.runtime.session import Process


class TestRuntimeStatus:
    def test_ready_needs_no_reason(self) -> None:
        status = RuntimeStatus(state=RuntimeState.READY, kind=RuntimeKind.NATIVE)
        assert status.is_usable
        assert status.reason is None

    @pytest.mark.parametrize(
        "state",
        [RuntimeState.MISSING, RuntimeState.BROKEN, RuntimeState.DEGRADED],
    )
    def test_non_ready_states_require_a_machine_readable_reason(self, state: RuntimeState) -> None:
        with pytest.raises(ValueError, match="FR-R2"):
            RuntimeStatus(state=state)

    def test_ready_must_not_carry_an_error_code(self) -> None:
        with pytest.raises(ValueError, match="must not carry"):
            RuntimeStatus(state=RuntimeState.READY, reason=ErrorCode.RUNTIME_BROKEN)

    def test_broken_is_not_usable(self) -> None:
        # FR-R5: "installed" and "works" are different claims, and a corrupted
        # install must land in BROKEN rather than READY.
        status = RuntimeStatus(
            state=RuntimeState.BROKEN,
            reason=ErrorCode.RUNTIME_BROKEN,
            detail="foamVersion: command not found",
        )
        assert not status.is_usable

    def test_degraded_is_still_usable(self) -> None:
        # The Docker fallback runs simulations perfectly well; refusing to launch
        # would be a dead end (§7.9 rule 1).
        status = RuntimeStatus(
            state=RuntimeState.DEGRADED,
            reason=ErrorCode.MACOS_INTEL_UNSUPPORTED,
            kind=RuntimeKind.DOCKER,
        )
        assert status.is_usable

    def test_status_is_immutable(self) -> None:
        status = RuntimeStatus(state=RuntimeState.READY)
        with pytest.raises(AttributeError):
            status.state = RuntimeState.BROKEN  # type: ignore[misc]


class TestSessionContract:
    """The seam every runtime flavour has to satisfy."""

    def test_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(TypeError):
            RuntimeSession()  # type: ignore[abstract]

    @pytest.mark.parametrize(
        "name",
        ["run", "to_runtime_path", "to_host_path", "close", "kind"],
    )
    def test_session_requires(self, name: str) -> None:
        assert name in RuntimeSession.__abstractmethods__

    @pytest.mark.parametrize(
        "name",
        ["pid", "returncode", "lines", "wait", "terminate", "kill"],
    )
    def test_process_requires(self, name: str) -> None:
        # terminate and kill are the FR-S5 escalation; a Process that cannot be
        # signalled would make FR-S10's no-orphans guarantee unimplementable.
        assert name in Process.__abstractmethods__

    def test_run_takes_a_token_sequence_not_a_shell_string(self) -> None:
        # A case name containing a space or a quote must not become a command
        # injection or a mangled argument.
        params = inspect.signature(RuntimeSession.run).parameters
        assert "argv" in params
        assert params["cwd"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["env"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_session_is_a_context_manager(self) -> None:
        # NFR-R6: shutdown reaps child processes rather than orphaning them.
        assert hasattr(RuntimeSession, "__enter__")
        assert hasattr(RuntimeSession, "__exit__")

    def test_abstractions_use_abc(self) -> None:
        assert isinstance(RuntimeSession, abc.ABCMeta)
        assert isinstance(Process, abc.ABCMeta)
