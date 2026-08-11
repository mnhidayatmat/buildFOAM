"""The Post view (§7.6, FR-V1, FR-V2, FR-V5, FR-P8).

ParaView's absence is a **state, not an error**. It is the ordinary condition of
a machine that has only just installed this application, and a view that greeted
that with a red failure banner would be telling the user something is broken when
nothing is. The banner offers what to do instead, which is §7.9 rule 3.

**Two ways into ParaView, because they answer different questions.** "Open in
ParaView" shows results; "Inspect mesh" shows the mesh alone, at the initial
state, and works on a case that has never run (FR-P8). Collapsing them into one
button would mean a user checking their mesh before a long run has to open the
results of a run that has not happened.

Utilities stream their output into the same log pane the run uses. ``foamToVTK``
on a large transient case takes minutes, and a view that showed nothing until it
finished would be indistinguishable from one that had hung.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.paraview import ParaViewService
from foamwb.services.post import FUNCTIONS, PostFunction, PostService
from foamwb.services.runtime.session import RuntimeSession
from foamwb.ui.theme import Palette
from foamwb.ui.widgets.log_pane import LogPane

__all__ = ["PostView"]

_log = get_logger("ui.post")


class PostView(QWidget):
    """Open results in ParaView and run the standard utilities."""

    setup_requested = Signal()

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        paraview: ParaViewService | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._case: Path | None = None
        self._session: RuntimeSession | None = None
        self._paraview = paraview or ParaViewService()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        heading = QLabel(labels["post_heading"])
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        self._missing = self._build_missing_banner(labels)
        outer.addWidget(self._missing)

        outer.addWidget(self._build_actions(labels))

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setProperty("role", "muted")
        outer.addWidget(self._status)

        self._log = LogPane(palette, labels)
        outer.addWidget(self._log, stretch=1)

        self.refresh()

    def _build_missing_banner(self, labels: dict[str, str]) -> QFrame:
        banner = QFrame()
        banner.setObjectName("paraviewMissing")
        layout = QVBoxLayout(banner)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        title = QLabel(labels["paraview_missing"])
        title.setProperty("role", "heading")
        layout.addWidget(title)

        detail = QLabel(labels["paraview_missing_detail"])
        detail.setWordWrap(True)
        layout.addWidget(detail)

        row = QHBoxLayout()
        row.addStretch(1)
        button = QPushButton(labels["action_settings"])
        button.clicked.connect(self.setup_requested)
        row.addWidget(button)
        layout.addLayout(row)

        banner.setStyleSheet(
            f"#paraviewMissing {{ background: {self._palette.surface_alt};"
            f" border: 1px solid {self._palette.degraded}; border-radius: 6px; }}"
        )
        banner.hide()
        return banner

    def _build_actions(self, labels: dict[str, str]) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._open_button = QPushButton(labels["open_in_paraview"])
        self._open_button.clicked.connect(lambda: self._open(mesh_only=False))
        row.addWidget(self._open_button)

        self._mesh_button = QPushButton(labels["inspect_mesh"])
        self._mesh_button.setToolTip(labels["inspect_mesh_tip"])
        self._mesh_button.clicked.connect(lambda: self._open(mesh_only=True))
        row.addWidget(self._mesh_button)

        row.addSpacing(16)

        self._functions = QComboBox()
        self._functions.setAccessibleName(labels["utilities"])
        for function in FUNCTIONS:
            self._functions.addItem(function.label, function.key)
        self._functions.currentIndexChanged.connect(self._on_function_changed)
        row.addWidget(self._functions, stretch=1)

        self._argument = QLineEdit()
        self._argument.setPlaceholderText(labels["utility_argument"])
        self._argument.hide()
        row.addWidget(self._argument)

        self._run_button = QPushButton(labels["run_utility"])
        self._run_button.clicked.connect(self._run_utility)
        row.addWidget(self._run_button)
        return bar

    # -- context -----------------------------------------------------------

    def set_context(self, session: RuntimeSession | None, case: Path | None) -> None:
        self._session = session
        self._case = case
        self.refresh()

    def refresh(self) -> None:
        """Re-read what is available and re-enable accordingly."""
        available = self._paraview.is_available
        # `isVisibleTo` semantics apply to the banner too, so it is shown and
        # hidden rather than merely styled: a user with ParaView installed should
        # never see a message about it being missing.
        self._missing.setVisible(not available)

        has_case = self._case is not None
        self._open_button.setEnabled(available and has_case)
        self._mesh_button.setEnabled(available and has_case)
        self._run_button.setEnabled(has_case and self._session is not None)
        self._functions.setEnabled(has_case and self._session is not None)

        if not has_case:
            self._status.setText(self._labels["no_case_for_post"])
        elif available and (install := self._paraview.locate()) is not None:
            self._status.setText(self._labels["paraview_found"].format(install.version or ""))
        else:
            self._status.setText("")

        self._on_function_changed()

    def _on_function_changed(self) -> None:
        function = self._selected()
        self._argument.setVisible(function is not None and function.needs_argument)

    def _selected(self) -> PostFunction | None:
        key = self._functions.currentData()
        return next((f for f in FUNCTIONS if f.key == key), None)

    # -- actions -----------------------------------------------------------

    def _open(self, *, mesh_only: bool) -> None:
        if self._case is None:
            return
        if self._paraview.open_case(self._case, mesh_only=mesh_only):
            self._status.setText(self._labels["paraview_opened"].format(self._case.name))
        else:
            # E-V01 is a state; the banner already explains it.
            self.refresh()

    @Slot()
    def _run_utility(self) -> None:
        function = self._selected()
        if function is None or self._case is None or self._session is None:
            return

        self._log.clear()
        self._status.setText(self._labels["running_utility"].format(function.label))
        self._run_button.setEnabled(False)
        try:
            result = PostService(self._session).run(
                self._case,
                function,
                argument=self._argument.text().strip(),
                on_line=lambda line: self._log.append([line]),
            )
        except ValueError as exc:
            # A templated function with no argument. Reported rather than run,
            # because running it would fail inside OpenFOAM with a far worse
            # message than the one we can give here.
            self._status.setText(str(exc))
            return
        finally:
            self._run_button.setEnabled(True)

        if not result.succeeded:
            self._status.setText(self._labels["utility_failed"].format(function.label))
        elif result.produced_nothing:
            # Not a failure. `yPlus` on a case with no wall patches does exactly
            # this, and calling it an error would be wrong.
            self._status.setText(self._labels["utility_wrote_nothing"].format(function.label))
        else:
            self._status.setText(
                self._labels["utility_wrote"].format(function.label, len(result.written))
            )
        log_event(
            _log,
            Event.COMMAND_END,
            component="post.view",
            function=function.key,
            exit_code=result.exit_code,
        )

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._log.set_palette(palette)
        self._missing.setStyleSheet(
            f"#paraviewMissing {{ background: {palette.surface_alt};"
            f" border: 1px solid {palette.degraded}; border-radius: 6px; }}"
        )

    # -- inspection --------------------------------------------------------

    @property
    def log(self) -> LogPane:
        return self._log

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def shows_missing_banner(self) -> bool:
        return self._missing.isVisibleTo(self)

    @property
    def can_open(self) -> bool:
        return self._open_button.isEnabled()

    @property
    def can_inspect_mesh(self) -> bool:
        return self._mesh_button.isEnabled()

    @property
    def argument_visible(self) -> bool:
        return self._argument.isVisibleTo(self)
