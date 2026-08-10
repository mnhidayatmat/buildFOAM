"""Off-thread runtime detection (NFR-P1, FR-A2).

NFR-P1 gives cold start to an interactive Hub three seconds, and detection is not
free: it runs a real OpenFOAM binary, and on macOS the first one after a reboot
triggers a disk-image mount. Doing that before the window appears would spend the
whole budget on a question the user has not asked yet.

So the shell opens immediately in its honest not-detected-yet state and this
worker corrects it. That ordering is also what §7.9 rule 4 requires: the footer
is allowed to say "not detected", and is not allowed to say "ready" before
anything has been verified.

The work happens on a Qt thread and the result crosses back by signal, because
touching a widget from a worker thread is undefined behaviour in Qt — it usually
appears to work, which is what makes it a bad bug to have.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.runtime import RuntimeManager, RuntimeStatus

__all__ = ["RuntimeProbe"]

_log = get_logger("ui.probe")


class RuntimeProbe(QObject):
    """Runs runtime detection off the GUI thread and reports the result once."""

    finished = Signal(RuntimeStatus)

    def __init__(
        self, manager: RuntimeManager | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._manager = manager or RuntimeManager()
        self._thread: QThread | None = None

    def start(self) -> None:
        """Begin detection. Safe to call once; a second call is ignored."""
        if self._thread is not None:
            return

        thread = QThread()
        worker = _Worker(self._manager)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.done.connect(thread.quit)
        # The worker is owned by the thread's lifetime, not by Python's garbage
        # collector: dropping either while the thread runs is a crash, not an
        # exception.
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_done(self, status: RuntimeStatus) -> None:
        log_event(
            _log,
            Event.RUNTIME_VERIFY_RESULT,
            state=status.state.value,
            version=status.openfoam_version,
        )
        self.finished.emit(status)

    def stop(self) -> None:
        """Wait for the worker to finish, so shutdown never outruns it.

        A thread still running at interpreter teardown produces a crash on exit,
        which would look to a user exactly like the crash FR-A7 is meant to catch
        and report — but with nothing useful in the bundle.
        """
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)


class _Worker(QObject):
    done = Signal(RuntimeStatus)

    def __init__(self, manager: RuntimeManager) -> None:
        super().__init__()
        self._manager = manager

    def run(self) -> None:
        try:
            status = self._manager.detect()
        except Exception as exc:
            # Detection touches the filesystem and spawns a process; anything it
            # raises is a diagnosis, not a reason for the window to disappear.
            from foamwb.codes import ErrorCode
            from foamwb.services.runtime import RuntimeState

            log_event(_log, Event.ERROR_RAISED, where="runtime.detect", error=str(exc))
            status = RuntimeStatus(
                state=RuntimeState.BROKEN,
                reason=ErrorCode.RUNTIME_BROKEN,
                detail=str(exc),
            )
        self.done.emit(status)
