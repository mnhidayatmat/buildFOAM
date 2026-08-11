"""Executing a run without freezing the window (FR-S2, NFR-P3).

:meth:`RunController.execute` blocks: it iterates a solver's output until the
process exits, which for a real case is minutes to hours. Calling it on the GUI
thread would freeze the window for the entire run, so it happens on a Qt thread
and results cross back by signal.

**Lines are batched, and that is the whole performance design.** NFR-P3 requires
5 000 lines/s without UI stall. One signal per line at that rate is 5 000 queued
events per second, each waking the event loop to append a few characters — the
window would spend all its time on bookkeeping and none on staying responsive.
Lines are therefore accumulated and delivered in chunks, which turns 5 000 events
into about ten. FR-S2 allows 500 ms from emission to display, and the flush
interval is set well inside that.

The batching lives here rather than in the log widget because it is a *transport*
concern: every consumer of the stream wants whole chunks, and a widget that
re-implemented it would get a different answer.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.run import (
    RunController,
    RunPlan,
    RunResult,
    StageState,
    StopMode,
)
from foamwb.services.runtime import RuntimeSession

__all__ = ["FLUSH_INTERVAL_MS", "MAX_BATCH_LINES", "RunWorker"]

_log = get_logger("ui.run")

#: How long lines may wait before being delivered. Comfortably inside FR-S2's
#: 500 ms budget, and long enough that a fast solver produces tens of signals per
#: second rather than thousands.
FLUSH_INTERVAL_MS = 100

#: Deliver early once a batch reaches this size, so a burst is not held back by
#: the timer. Bounds how much text arrives in one event, which keeps any single
#: append cheap.
MAX_BATCH_LINES = 500


class RunWorker(QObject):
    """Runs a :class:`RunPlan` on its own thread and reports progress."""

    lines = Signal(str, list)
    """``(stage, [line, ...])`` — batched output, in order."""

    stage_changed = Signal(str, StageState)
    finished = Signal(RunResult)
    failed = Signal(str)
    """Emitted only for an exception that escaped the controller. A run that fails
    normally arrives through :attr:`finished` carrying its outcome — a failed
    solver is a result, not a defect in the application."""

    def __init__(
        self,
        session: RuntimeSession,
        plan: RunPlan,
        *,
        log_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._plan = plan
        self._log_dir = log_dir
        self._thread: QThread | None = None
        self._controller: RunController | None = None
        self._batch: list[str] = []
        self._batch_stage = ""
        self._last_flush = 0.0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return

        thread = QThread()
        self.moveToThread(thread)
        thread.started.connect(self._execute)
        # The thread owns its own teardown; dropping it while running is a crash
        # rather than an exception.
        self.finished.connect(thread.quit)
        self.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        thread.start()

    def stop(self, mode: StopMode = StopMode.WRITE) -> None:
        """Request a stop (FR-S5).

        Callable from the GUI thread while the worker runs, because that is the
        only moment it is useful. It only touches the controller's stop path,
        which is written to be safe from another thread: setting a flag, and —
        for the signal modes — signalling a process group.
        """
        if self._controller is not None:
            self._controller.stop(mode)

    def wait(self, timeout_ms: int = 30_000) -> bool:
        """Block until the thread ends. For shutdown, not for normal use."""
        if self._thread is None:
            return True
        return self._thread.wait(timeout_ms)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    # -- execution ---------------------------------------------------------

    def _execute(self) -> None:
        self._controller = RunController(
            self._session, on_line=self._on_line, on_state=self._on_state
        )
        self._last_flush = time.monotonic()
        try:
            result = self._controller.execute(self._plan, log_dir=self._log_dir)
        except Exception as exc:
            self._flush()
            log_event(_log, Event.ERROR_RAISED, where="run.execute", error=str(exc))
            self.failed.emit(str(exc))
            return
        self._flush()
        self.finished.emit(result)

    def _on_line(self, stage: str, line: str) -> None:
        # Called on the worker thread by the controller, once per line.
        if stage != self._batch_stage:
            self._flush()
            self._batch_stage = stage
        self._batch.append(line)

        now = time.monotonic()
        if (
            len(self._batch) >= MAX_BATCH_LINES
            or (now - self._last_flush) * 1000 >= FLUSH_INTERVAL_MS
        ):
            self._flush(now)

    def _flush(self, now: float | None = None) -> None:
        if self._batch:
            self.lines.emit(self._batch_stage, self._batch)
            self._batch = []
        self._last_flush = now if now is not None else time.monotonic()

    def _on_state(self, stage: str, state: StageState) -> None:
        # Flushed first so the log and the stage strip cannot disagree about what
        # had been printed when a stage ended.
        self._flush()
        self.stage_changed.emit(stage, state)
