"""Meshing utilities with a live output panel (FR-P5, FR-P9).

Each utility runs as a one-stage plan through the same worker a solver uses, so
its output streams the same way and it can be stopped the same way. What differs
is what happens afterwards: ``checkMesh``'s output is read into figures rather
than left as eighty lines of prose (FR-P9), and a utility that changed the mesh
tells the view to rebuild the boundary matrix — a matrix built from the old mesh
would be quietly wrong about a case the user just re-meshed.

Only utilities the case can actually run are offered. ``snappyHexMesh`` on a case
with no ``snappyHexMeshDict`` is not something the user can fix from that button.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.mesh import (
    MeshQuality,
    Utility,
    Verdict,
    available_utilities,
    parse_check_mesh,
    utility_plan,
)
from foamwb.services.run import RunOutcome, RunResult, StopMode
from foamwb.services.runtime import RuntimeSession
from foamwb.ui.run_worker import RunWorker
from foamwb.ui.theme import Palette
from foamwb.ui.widgets.log_pane import LogPane

__all__ = ["MeshPanel"]


class MeshPanel(QWidget):
    """Run meshing utilities and report what they produced."""

    mesh_changed = Signal()
    """A utility rewrote the mesh, so anything derived from it is now stale."""

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
        self._case: Path | None = None
        self._worker: RunWorker | None = None
        self._running: Utility | None = None
        self._output: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._buttons_row = QWidget()
        self._buttons = QHBoxLayout(self._buttons_row)
        self._buttons.setContentsMargins(0, 0, 0, 0)
        self._buttons.setSpacing(6)
        layout.addWidget(self._buttons_row)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._quality = QLabel()
        self._quality.setWordWrap(True)
        self._quality.setVisible(False)
        layout.addWidget(self._quality)

        self._log = LogPane(palette, labels)
        layout.addWidget(self._log, stretch=1)

        self._set_idle()

    # -- configuration -----------------------------------------------------

    def set_context(self, session: RuntimeSession | None, case: Path, *, meshed: bool) -> None:
        """Offer the utilities this case can run."""
        self._session = session
        self._case = case
        self._rebuild_buttons(available_utilities(case, meshed=meshed))
        self._set_idle()

    def _rebuild_buttons(self, utilities: list[Utility]) -> None:
        while self._buttons.count():
            item = self._buttons.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        self._utility_buttons: dict[str, QPushButton] = {}
        for utility in utilities:
            button = QPushButton(utility.name)
            button.setToolTip(" ".join(utility.argv))
            button.clicked.connect(lambda _checked=False, u=utility: self.run_utility(u))
            self._buttons.addWidget(button)
            self._utility_buttons[utility.name] = button
        self._buttons.addStretch(1)

        self._stop_button = QPushButton(self._labels["stop_now"])
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(lambda: self.stop())
        self._buttons.addWidget(self._stop_button)

    # -- running -----------------------------------------------------------

    def run_utility(self, utility: Utility) -> bool:
        if self._session is None or self._case is None:
            self._status.setText(self._labels["mesh_needs_runtime"])
            return False
        if self._worker is not None and self._worker.is_running:
            return False

        self._running = utility
        self._output = []
        self._log.clear()
        self._quality.setVisible(False)

        self._worker = RunWorker(self._session, utility_plan(utility, self._case))
        self._worker.lines.connect(self._on_lines)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self._set_running(utility)
        self._worker.start()
        return True

    def stop(self) -> None:
        if self._worker is not None and self._worker.is_running:
            self._worker.stop(StopMode.TERMINATE)

    def shutdown(self) -> None:
        """Reap a running utility (FR-S10)."""
        if self._worker is not None and self._worker.is_running:
            self._worker.stop(StopMode.KILL)
            self._worker.wait(10_000)

    # -- signals -----------------------------------------------------------

    @Slot(str, list)
    def _on_lines(self, _stage: str, lines: list) -> None:
        self._output.extend(lines)
        self._log.append(lines)

    @Slot(RunResult)
    def _on_finished(self, result: RunResult) -> None:
        utility = self._running
        self._set_idle()

        if utility is not None and utility.name == "checkMesh":
            self._show_quality(parse_check_mesh("\n".join(self._output)))

        if result.outcome is RunOutcome.SUCCEEDED:
            self._status.setText(self._labels["utility_ok"].format(utility.name if utility else ""))
            self._status.setStyleSheet(f"color: {self._palette.ready};")
            if utility is not None and utility.makes_mesh:
                self.mesh_changed.emit()
        else:
            failed = result.failed_stage
            code = failed.reason.id if failed and failed.reason else ""
            self._status.setText(
                self._labels["utility_failed"].format(utility.name if utility else "", code)
            )
            self._status.setStyleSheet(f"color: {self._palette.broken};")
        self._running = None

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_idle()
        self._status.setText(self._labels["utility_error"].format(message))
        self._status.setStyleSheet(f"color: {self._palette.broken};")
        self._running = None

    def _show_quality(self, quality: MeshQuality) -> None:
        """FR-P9: the figures, not the prose."""
        colour = {
            Verdict.PASS: self._palette.ready,
            Verdict.WARN: self._palette.degraded,
            Verdict.FAIL: self._palette.broken,
        }[quality.verdict]

        parts = [
            self._labels["quality_metric"].format(
                metric.name, f"{metric.value:.4g}", metric.verdict.value
            )
            for metric in quality.metrics
        ]
        if quality.cells is not None:
            parts.insert(0, self._labels["quality_cells"].format(quality.cells))
        for failure in quality.failed_checks:
            parts.append(failure)

        self._quality.setText("   ·   ".join(parts) if parts else "")
        self._quality.setStyleSheet(f"color: {colour};")
        self._quality.setVisible(bool(parts))
        self._last_quality = quality

    # -- state -------------------------------------------------------------

    def _set_running(self, utility: Utility) -> None:
        for button in self._utility_buttons.values():
            button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._status.setText(self._labels["utility_running"].format(utility.name))
        self._status.setStyleSheet(f"color: {self._palette.text_muted};")

    def _set_idle(self) -> None:
        for button in getattr(self, "_utility_buttons", {}).values():
            button.setEnabled(self._session is not None)
        if hasattr(self, "_stop_button"):
            self._stop_button.setEnabled(False)
        if self._session is None:
            self._status.setText(self._labels["mesh_needs_runtime"])
            self._status.setStyleSheet(f"color: {self._palette.text_muted};")

    # -- for tests ---------------------------------------------------------

    @property
    def utilities(self) -> list[str]:
        return list(getattr(self, "_utility_buttons", {}))

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def quality_text(self) -> str:
        return self._quality.text() if self._quality.isVisibleTo(self) else ""

    @property
    def log(self) -> LogPane:
        return self._log

    def show_quality(self, quality: MeshQuality) -> None:
        self._show_quality(quality)
