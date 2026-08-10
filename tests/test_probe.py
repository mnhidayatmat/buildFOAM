"""Off-thread runtime detection (NFR-P1, FR-A2, §7.9 rule 4)."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer

from foamwb.codes import ErrorCode
from foamwb.services.runtime import RuntimeKind, RuntimeState, RuntimeStatus
from foamwb.ui.probe import RuntimeProbe
from foamwb.ui.shell import Shell
from foamwb.ui.theme import LIGHT

READY = RuntimeStatus(state=RuntimeState.READY, kind=RuntimeKind.NATIVE, openfoam_version="v0000")


class FakeManager:
    """Stands in for RuntimeManager so no subprocess runs during the suite."""

    def __init__(self, status=READY, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.calls = 0

    def detect(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.status


def _await(probe: RuntimeProbe, qtbot) -> RuntimeStatus:
    received: list[RuntimeStatus] = []
    loop = QEventLoop()
    probe.finished.connect(received.append)
    probe.finished.connect(lambda _s: loop.quit())
    QTimer.singleShot(10_000, loop.quit)
    probe.start()
    loop.exec()
    probe.stop()
    assert received, "probe never reported"
    return received[0]


class TestProbe:
    def test_reports_the_detected_status(self, qapp, qtbot) -> None:
        assert _await(RuntimeProbe(FakeManager()), qtbot).state is RuntimeState.READY

    def test_a_failure_becomes_a_status_not_a_crash(self, qapp, qtbot) -> None:
        # Detection touches the filesystem and spawns a process. Anything it
        # raises is a diagnosis; it is never a reason for the window to vanish.
        status = _await(RuntimeProbe(FakeManager(error=OSError("boom"))), qtbot)
        assert status.state is RuntimeState.BROKEN
        assert status.reason is ErrorCode.RUNTIME_BROKEN
        assert "boom" in status.detail

    def test_starting_twice_detects_once(self, qapp, qtbot) -> None:
        manager = FakeManager()
        probe = RuntimeProbe(manager)
        _await(probe, qtbot)
        probe.start()
        probe.stop()
        assert manager.calls == 1

    def test_stopping_without_starting_is_safe(self, qapp) -> None:
        RuntimeProbe(FakeManager()).stop()


class TestShellAdoption:
    def test_the_shell_opens_before_detection_answers(self, qtbot) -> None:
        # NFR-P1: the three-second budget buys an interactive Hub, not a probe.
        # The footer is allowed to say "not detected"; it is not allowed to say
        # "ready" before anything has been verified (§7.9 rule 4).
        shell = Shell(LIGHT)
        qtbot.addWidget(shell)
        assert "not installed" in shell.footer.runtime_text.lower()

    def test_applying_a_status_updates_state_and_version_together(self, qtbot) -> None:
        # One entry point, so the footer can never show a ready runtime beside a
        # stale version, or a version beside "not installed".
        shell = Shell(LIGHT)
        qtbot.addWidget(shell)
        shell.apply_runtime_status(READY)
        assert "ready" in shell.footer.runtime_text.lower()
        assert "v0000" in shell.footer.version_text
        assert not shell.hub.banner_visible

    def test_a_broken_result_shows_its_code_and_the_banner(self, qtbot) -> None:
        shell = Shell(LIGHT)
        qtbot.addWidget(shell)
        shell.apply_runtime_status(
            RuntimeStatus(state=RuntimeState.BROKEN, reason=ErrorCode.RUNTIME_BROKEN)
        )
        assert ErrorCode.RUNTIME_BROKEN.id in shell.footer.runtime_text
        assert shell.hub.banner_visible
        assert "No OpenFOAM" in shell.footer.version_text
