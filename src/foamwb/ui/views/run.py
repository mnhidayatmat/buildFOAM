"""The Run view (§7.5).

Four regions, as specified: the plan as a stage strip across the top, the log on
the left, monitor plots on the right, and the stop control along the bottom.

**Destructive actions are never the default button** (§7.9 rule 5). *Stop & Write*
is the primary control; *Stop Now* and *Force Kill* live behind a menu. This is
DEC-14 made visible — SIGTERM mid-write leaves a partial time directory that
breaks reconstruction and ParaView, so the safe stop must be the easy one and the
damaging ones must take deliberate effort.

**The plan is shown before it runs** (FR-S1). Building a plan populates the strip
immediately; nothing starts until Run is pressed.

Monitoring polls rather than watches the filesystem. ``inotify`` does not work
across the WSL bridge at all (§3.2), so a watcher would be correct on macOS and
silently dead on Windows — one mechanism that works everywhere beats two that
disagree.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from foamwb.branding import CASE_METADATA_DIR
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.case import CaseService
from foamwb.services.monitor import MonitorService
from foamwb.services.run import RunPlan, RunResult, StageState, StopMode
from foamwb.services.runtime import RuntimeSession
from foamwb.ui.run_worker import RunWorker
from foamwb.ui.theme import Palette
from foamwb.ui.widgets.log_pane import LogPane
from foamwb.ui.widgets.residual_plot import ResidualPlot
from foamwb.ui.widgets.stage_strip import StageStrip

__all__ = ["MONITOR_POLL_MS", "RunView"]

_log = get_logger("ui.run_view")

#: How often ``postProcessing`` is re-read. NFR-P4 allows 500 ms from a ``.dat``
#: write to the plot updating; polling at half that leaves room for the read and
#: the redraw inside the budget.
MONITOR_POLL_MS = 250


class RunView(QWidget):
    """Composes the run experience over a session and a case."""

    run_started = Signal()
    run_finished = Signal(RunResult)

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels

        self._session: RuntimeSession | None = None
        self._cases = CaseService()
        self._case: Path | None = None
        self._plan: RunPlan | None = None
        self._worker: RunWorker | None = None
        self._monitor: MonitorService | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self._strip = StageStrip(palette, labels)
        layout.addWidget(self._strip)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._log = LogPane(palette, labels)
        splitter.addWidget(self._log)

        self._plots = QTabWidget()
        self._plots.setAccessibleName(labels["monitors"])
        self._residuals = ResidualPlot(palette, labels)
        self._residuals.export_requested.connect(self._export_csv)
        self._plots.addTab(self._residuals, labels["residuals"])
        splitter.addWidget(self._plots)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self._build_controls(labels))

        self._timer = QTimer(self)
        self._timer.setInterval(MONITOR_POLL_MS)
        self._timer.timeout.connect(self._poll_monitor)

        self._set_idle()

    def _build_controls(self, labels: dict[str, str]) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._status = QLabel()
        self._status.setProperty("role", "muted")
        row.addWidget(self._status, stretch=1)

        self._run_button = QPushButton(labels["run"])
        self._run_button.setDefault(True)
        self._run_button.clicked.connect(self.start)
        row.addWidget(self._run_button)

        # Stop & Write is the button; the destructive modes are in its menu, so
        # reaching them takes a deliberate second action (§7.9 rule 5, DEC-14).
        self._stop_button = QPushButton(labels["stop_write"])
        self._stop_button.setToolTip(labels["stop_write_tip"])
        self._stop_button.clicked.connect(lambda: self.stop(StopMode.WRITE))

        menu = QMenu(self._stop_button)
        for mode, key in (
            (StopMode.TERMINATE, "stop_now"),
            (StopMode.KILL, "stop_kill"),
        ):
            action = menu.addAction(labels[key])
            action.setToolTip(labels[f"{key}_tip"])
            action.triggered.connect(lambda _checked=False, m=mode: self._confirm_stop(m))
        self._stop_button.setMenu(menu)
        row.addWidget(self._stop_button)
        return bar

    # -- configuration -----------------------------------------------------

    def set_context(self, session: RuntimeSession, case: Path, plan: RunPlan) -> None:
        """Attach a session, a case and a plan, and show the plan (FR-S1)."""
        self._session = session
        self._case = case
        self._plan = plan
        self._monitor = MonitorService(case)
        self._strip.set_plan(plan)
        self._status.setText(self._labels["ready_to_run"].format(case.name))
        self._run_button.setEnabled(True)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._session is None or self._plan is None or self._case is None:
            return
        if self._worker is not None and self._worker.is_running:
            return

        self._log.clear()
        self._residuals.clear()
        self._strip.set_plan(self._plan)

        # FR-S3: monitoring is installed at launch, not at open. Opening someone
        # else's case must not modify it (§5.1); pressing Run is the consent.
        # A failure here costs the live plot and nothing else — DEC-13 keeps log
        # parsing as the fallback — so it must never stop the run.
        try:
            self._cases.enable_monitoring(self._cases.open(self._case))
        except (OSError, ValueError) as exc:
            log_event(_log, Event.ERROR_RAISED, where="enable_monitoring", error=str(exc))

        self._worker = RunWorker(
            self._session,
            self._plan,
            log_dir=self._case / CASE_METADATA_DIR / "logs" / "r-0001",
        )
        self._worker.lines.connect(self._on_lines)
        self._worker.stage_changed.connect(self._on_stage)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self._set_running()
        self._timer.start()
        self._worker.start()
        self.run_started.emit()

    def stop(self, mode: StopMode = StopMode.WRITE) -> None:
        if self._worker is not None and self._worker.is_running:
            self._worker.stop(mode)
            self._status.setText(self._labels[f"stopping_{mode.value}"])

    def _confirm_stop(self, mode: StopMode) -> None:
        """Confirm before a stop that can damage the case (§7.9 rule 5).

        Both non-default modes can leave a partial time directory, which breaks
        reconstruction and ParaView. Naming that consequence is the point of the
        dialog: a user who chooses it anyway has chosen it knowingly.
        """
        answer = QMessageBox.warning(
            self,
            self._labels["confirm_stop_title"],
            self._labels[f"confirm_{mode.value}"],
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.stop(mode)

    def shutdown(self) -> None:
        """Stop and reap the worker. Called when the window closes (FR-S10)."""
        self._timer.stop()
        if self._worker is not None and self._worker.is_running:
            self._worker.stop(StopMode.KILL)
            self._worker.wait(10_000)

    # -- signals -----------------------------------------------------------

    @Slot(str, list)
    def _on_lines(self, _stage: str, lines: list) -> None:
        self._log.append(lines)

    @Slot(str, StageState)
    def _on_stage(self, stage: str, state: StageState) -> None:
        self._strip.set_state(stage, state)
        if state is StageState.RUNNING:
            self._status.setText(self._labels["running_stage"].format(stage))

    @Slot(RunResult)
    def _on_finished(self, result: RunResult) -> None:
        # One last poll: the solver writes its final residual as it exits, and
        # stopping the timer first would leave the plot one sample short of the
        # number the user is about to be told about.
        self._poll_monitor()
        self._timer.stop()
        self._set_idle()

        failed = result.failed_stage
        if failed is not None and failed.reason is not None:
            # The §9 code travels with the message so support starts from a code
            # rather than a screenshot.
            self._status.setText(
                self._labels["run_failed_at"].format(failed.name, failed.reason.id)
            )
        else:
            self._status.setText(
                self._labels[f"run_{result.outcome.value}"].format(result.wall_seconds)
            )
        self.run_finished.emit(result)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._timer.stop()
        self._set_idle()
        self._status.setText(self._labels["run_error"].format(message))

    # -- monitoring --------------------------------------------------------

    def _poll_monitor(self) -> None:
        if self._monitor is None:
            return
        data = self._monitor.refresh()
        series = data.get("solverInfo") or next(iter(data.values()), None)
        if series is not None:
            self._residuals.set_series(series)

    def _export_csv(self) -> None:
        if self._case is None:
            return
        target = self._case / "monitors.csv"
        target.write_text(self._residuals.csv(), encoding="utf-8")
        self._status.setText(self._labels["exported_csv"].format(target.name))

    # -- state -------------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette and pass it to everything this view owns (NFR-A4)."""
        self._palette = palette
        self._strip.set_palette(palette)
        self._log.set_palette(palette)
        self._residuals.set_palette(palette)

    def _set_running(self) -> None:
        self._run_button.setEnabled(False)
        self._stop_button.setEnabled(True)

    def _set_idle(self) -> None:
        self._run_button.setEnabled(self._plan is not None)
        self._stop_button.setEnabled(False)
        if self._plan is None:
            self._status.setText(self._labels["no_case_for_run"])

    # -- for tests ---------------------------------------------------------

    @property
    def strip(self) -> StageStrip:
        return self._strip

    @property
    def log(self) -> LogPane:
        return self._log

    @property
    def residuals(self) -> ResidualPlot:
        return self._residuals

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def can_run(self) -> bool:
        return self._run_button.isEnabled()

    @property
    def can_stop(self) -> bool:
        return self._stop_button.isEnabled()

    @property
    def stop_button_text(self) -> str:
        return self._stop_button.text()
