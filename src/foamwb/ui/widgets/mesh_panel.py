"""Meshing utilities with a live output panel (FR-P5, FR-P9).

Utilities run through the same worker a solver uses, so their output streams the
same way and they can be stopped the same way. What differs is what happens
afterwards: ``checkMesh``'s output is read into figures rather than left as
eighty lines of prose (FR-P9), and a utility that changed the mesh tells the view
to rebuild the boundary matrix — a matrix built from the old mesh would be
quietly wrong about a case the user just re-meshed.

**Generating a mesh is one press.** The individual buttons are still here, and
still each run one utility, because §6.3 asks for them and because a user
re-running ``snappyHexMesh`` after editing its dictionary should not have to
re-run ``blockMesh`` too. But the ordinary path — geometry in, mesh out — was
four presses in a fixed order, each waited on, which asked the user to know a
sequence the application already knows. *Generate mesh* runs that sequence as one
multi-stage plan, reported chip by chip in the strip.

Only utilities the case can actually run are offered. ``snappyHexMesh`` on a case
with no ``snappyHexMeshDict`` is not something the user can fix from that button.
The same rule reaches past dictionaries to arguments: ``transformPoints`` exits
fatally when run bare, so the button asks what to do first and a cancelled answer
runs nothing at all. Cancelling is not a failure and does not colour the status
line — the user changed their mind, which is a thing they are allowed to do.
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

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.mesh import (
    UTILITIES,
    MeshQuality,
    Transform,
    Utility,
    Verdict,
    available_utilities,
    can_mesh,
    mesh_plan,
    parse_check_mesh,
    utility_plan,
)
from foamwb.services.run import RunOutcome, RunPlan, RunResult, StageState, StopMode
from foamwb.services.runtime import RuntimeSession
from foamwb.ui.run_worker import RunWorker
from foamwb.ui.theme import Palette
from foamwb.ui.widgets.log_pane import LogPane
from foamwb.ui.widgets.stage_strip import StageStrip
from foamwb.ui.widgets.transform_dialog import ask_for_transform

__all__ = ["MeshPanel"]

_log = get_logger("ui.mesh")


class MeshPanel(QWidget):
    """Run meshing utilities and report what they produced."""

    mesh_changed = Signal()
    """A utility rewrote the mesh, so anything derived from it is now stale."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        log: LogPane | None = None,
    ) -> None:
        """``log`` is the window's console when the window has one.

        A meshing utility's output is the same kind of thing as a solver's, and
        a user reads one stream of what the application did on their behalf —
        so in the shell both go to the console dock.
        """
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._owns_log = log is None
        self._session: RuntimeSession | None = None
        self._case: Path | None = None
        self._worker: RunWorker | None = None
        self._running: str = ""
        """Name of what is running — a utility, or the generation chain."""

        # Keyed by stage, not one flat list. The chain runs four utilities into
        # the same log, and `parse_check_mesh` reading the concatenation would be
        # handed blockMesh's output as well as checkMesh's.
        self._output: dict[str, list[str]] = {}
        # The status line's colour is a palette *token*, not a resolved colour,
        # so a theme change can re-derive it. Storing the colour would leave the
        # panel showing the previous theme's red after a switch.
        self._status_token = "text_muted"
        self._last_quality: MeshQuality | None = None
        self._ask_transform = self._default_ask_transform

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._buttons_row = QWidget()
        self._buttons = QHBoxLayout(self._buttons_row)
        self._buttons.setContentsMargins(0, 0, 0, 0)
        self._buttons.setSpacing(6)
        layout.addWidget(self._buttons_row)

        # Hidden until something is running: a strip of four grey chips above an
        # idle panel states a plan nobody asked for yet, and the buttons below
        # already say what this case can run.
        self._strip = StageStrip(palette, labels)
        self._strip.setVisible(False)
        layout.addWidget(self._strip)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._quality = QLabel()
        self._quality.setWordWrap(True)
        self._quality.setVisible(False)
        layout.addWidget(self._quality)

        self._log = log or LogPane(palette, labels)
        if self._owns_log:
            layout.addWidget(self._log, stretch=1)
        else:
            layout.addStretch(1)

        self._set_idle()

    # -- configuration -----------------------------------------------------

    def set_context(self, session: RuntimeSession | None, case: Path, *, meshed: bool) -> None:
        """Offer the utilities this case can run."""
        self._session = session
        self._case = case
        self._rebuild_buttons(available_utilities(case, meshed=meshed), offer_chain=can_mesh(case))
        self._set_idle()

    def _rebuild_buttons(self, utilities: list[Utility], *, offer_chain: bool) -> None:
        while self._buttons.count():
            item = self._buttons.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        # First and default, because it is what most users want most of the time.
        # The individual utilities follow it, which reads as "the whole thing, or
        # a piece of it" rather than as a fifth peer among four.
        self._chain_button = QPushButton(self._labels["generate_mesh"])
        self._chain_button.setDefault(True)
        self._chain_button.setToolTip(self._labels["generate_mesh_tip"])
        self._chain_button.clicked.connect(lambda: self.generate_mesh())
        self._chain_button.setVisible(offer_chain)
        self._buttons.addWidget(self._chain_button)

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

    # -- operations --------------------------------------------------------

    def set_dialogs(self, *, ask_transform=None) -> None:
        """Replace the modal dialogs, for tests and scripted runs."""
        if ask_transform is not None:
            self._ask_transform = ask_transform

    def _default_ask_transform(self) -> Transform | None:
        return ask_for_transform(self._palette, self._labels, self)

    # -- running -----------------------------------------------------------

    def run_utility(self, utility: Utility) -> bool:
        if self._session is None or self._case is None:
            self._set_status(self._labels["mesh_needs_runtime"], "text_muted")
            return False
        if self._worker is not None and self._worker.is_running:
            return False

        operation: Transform | None = None
        if utility.needs_operation:
            operation = self._ask_transform()
            # Both of these end with no run, and each says so. Staying silent
            # was the original mistake: a button that sometimes does nothing and
            # never says why is indistinguishable from one that is broken, and
            # leaves nothing in the log for anyone asked to explain it later.
            if operation is None:
                self._set_status(self._labels["transform_cancelled"], "text_muted")
                log_event(_log, Event.UI_MESH_TRANSFORM, action="cancelled")
                return False
            if operation.is_identity:
                self._set_status(self._labels["transform_identity"], "text_muted")
                log_event(
                    _log,
                    Event.UI_MESH_TRANSFORM,
                    action="declined",
                    kind=operation.kind.value,
                )
                return False
            log_event(
                _log,
                Event.UI_MESH_TRANSFORM,
                action="applied",
                kind=operation.kind.value,
                argv=list(operation.argv()),
            )

        return self._launch(utility_plan(utility, self._case, operation=operation), utility.name)

    def generate_mesh(self) -> bool:
        """Run the whole generation sequence as one plan (FR-P5).

        The chain is composed from the case rather than assumed, so a case with
        no surface skips ``surfaceFeatureExtract`` and one with no
        ``snappyHexMeshDict`` is ``blockMesh`` then ``checkMesh`` — the sequence
        that case actually has, not a template it has to fit.
        """
        if self._session is None or self._case is None:
            self._set_status(self._labels["mesh_needs_runtime"], "text_muted")
            return False
        if self._worker is not None and self._worker.is_running:
            return False

        try:
            plan = mesh_plan(self._case)
        except ValueError:
            # Only reachable if the case lost its dictionaries since the buttons
            # were built. Said rather than swallowed: a primary button that does
            # nothing is the thing §7.9 rule 1 forbids most strongly.
            self._set_status(self._labels["nothing_to_mesh"], "degraded")
            return False

        log_event(_log, Event.UI_MESH_TRANSFORM, action="chain", argv=[s.name for s in plan.stages])
        return self._launch(plan, self._labels["generate_mesh"])

    def _launch(self, plan: RunPlan, running: str) -> bool:
        """Start a plan, however many stages it has.

        One path for both buttons, so the log, the strip, the stop button and the
        quality figures cannot behave differently depending on which was pressed.
        """
        if self._session is None:
            self._set_status(self._labels["mesh_needs_runtime"], "text_muted")
            return False

        self._running = running
        self._output = {}
        self._log.clear()
        self._quality.setVisible(False)

        # Only worth a strip when there is a sequence to follow. One chip beside
        # a status line that already names the utility is a second copy of the
        # same fact.
        self._strip.set_plan(plan)
        self._strip.setVisible(len(plan.stages) > 1)

        self._worker = RunWorker(self._session, plan)
        self._worker.lines.connect(self._on_lines)
        self._worker.stage_changed.connect(self._on_stage)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self._set_running(running)
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
    def _on_lines(self, stage: str, lines: list) -> None:
        self._output.setdefault(stage, []).extend(lines)
        self._log.append(lines)

    @Slot(str, object)
    def _on_stage(self, stage: str, state: StageState) -> None:
        """Move the chip, and say which utility of the sequence is running now."""
        self._strip.set_state(stage, state)
        if state is StageState.RUNNING:
            self._set_status(self._labels["utility_running"].format(stage), "text_muted")

    @Slot(RunResult)
    def _on_finished(self, result: RunResult) -> None:
        running = self._running
        self._set_idle()

        # Read from checkMesh's own output whether it ran alone or as the last
        # stage of the chain — the figures belong to that stage, not to the log.
        if "checkMesh" in self._output:
            self._show_quality(parse_check_mesh("\n".join(self._output["checkMesh"])))

        if result.outcome is RunOutcome.SUCCEEDED:
            self._set_status(self._labels["utility_ok"].format(running), "ready")
            # A chain that reached the end has made a mesh by definition; a lone
            # utility only has if that is what it does.
            if self._made_mesh(result):
                self.mesh_changed.emit()
        else:
            failed = result.failed_stage
            code = failed.reason.id if failed and failed.reason else ""
            # Name the stage that failed, not the button that was pressed:
            # "Generate mesh failed" leaves the user to find which of four
            # utilities it was, which is in the log they now have to read.
            self._set_status(
                self._labels["utility_failed"].format(failed.name if failed else running, code),
                "broken",
            )
            # A chain that got as far as snappyHexMesh and then failed checkMesh
            # has still replaced the mesh, and everything derived from the old
            # one is stale whether or not the run as a whole succeeded.
            if self._made_mesh(result):
                self.mesh_changed.emit()
        self._running = ""

    def _made_mesh(self, result: RunResult) -> bool:
        """Whether any stage that succeeded was one that writes a mesh."""
        makers = {utility.name for utility in UTILITIES if utility.makes_mesh}
        return any(
            stage.name in makers and stage.state is StageState.SUCCEEDED for stage in result.stages
        )

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_idle()
        self._set_status(self._labels["utility_error"].format(message), "broken")
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

    def _set_status(self, text: str, token: str) -> None:
        """Say something, in the palette colour named by ``token``.

        Every status message goes through here so the *token* is remembered
        rather than the colour it resolved to, which is what makes a theme change
        able to repaint a message written under the previous one.
        """
        self._status_token = token
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {getattr(self._palette, token)};")

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette and repaint the status and quality lines (NFR-A4)."""
        self._palette = palette
        # Only when it is this panel's own: a shared console belongs to the
        # shell, which repaints it once for every view that writes to it.
        if self._owns_log:
            self._log.set_palette(palette)
        self._set_status(self._status.text(), self._status_token)
        # Only if it is on screen: a utility that has started since hides the
        # panel, and repainting it would put a stale mesh's figures back in front
        # of someone watching the mesh being replaced.
        if self._last_quality is not None and self._quality.isVisibleTo(self):
            self._show_quality(self._last_quality)

    def _set_running(self, running: str) -> None:
        for button in self._all_buttons():
            button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._set_status(self._labels["utility_running"].format(running), "text_muted")

    def _set_idle(self) -> None:
        for button in self._all_buttons():
            button.setEnabled(self._session is not None)
        if hasattr(self, "_stop_button"):
            self._stop_button.setEnabled(False)
        if self._session is None:
            self._set_status(self._labels["mesh_needs_runtime"], "text_muted")

    def _all_buttons(self) -> list[QPushButton]:
        """Every button a run must disable, the chain's included.

        Gathered in one place because forgetting the chain button here would let
        a second sequence be launched over a running one, which the worker would
        refuse silently — a button that does nothing and says nothing.
        """
        buttons = list(getattr(self, "_utility_buttons", {}).values())
        chain = getattr(self, "_chain_button", None)
        return [*buttons, chain] if chain is not None else buttons

    # -- for tests ---------------------------------------------------------

    @property
    def utilities(self) -> list[str]:
        return list(getattr(self, "_utility_buttons", {}))

    @property
    def offers_generate(self) -> bool:
        chain = getattr(self, "_chain_button", None)
        return chain is not None and chain.isVisibleTo(self)

    @property
    def strip(self) -> StageStrip:
        return self._strip

    @property
    def strip_shown(self) -> bool:
        return self._strip.isVisibleTo(self)

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
