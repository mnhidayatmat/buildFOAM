"""The workflow navigation panel (§7.2, D1).

scFLOW's Navigation panel, adapted. The important property is that it is an
**ordered procedure rather than a set of destinations**: the user reads down it
and knows both what a CFD case consists of and where they have got to. That is
the single largest thing the previous nav rail did not do.

Three rules it keeps.

**Every state is carried in words as well as appearance** (NFR-A2). A greyed-out
row is invisible to a screen reader and ambiguous to everyone else — "locked"
and "not yet" mean different things and need different remedies, so each row says
which it is.

**A blocked step explains itself and stays visible** (§7.9 rule 3). Hiding steps
that are not yet reachable would leave a user unable to see what the procedure
even is, which is the whole reason for showing it in this shape.

**A locked phase is reversible.** scFLOW replaces *Build Analysis Model* with
*Return to Prepare Parts*; the same affordance appears here as soon as the mesh
exists, because a user whose mesh is wrong must be able to get back to it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.workflow import STEPS, Step, StepKind, StepState, WorkflowModel
from foamwb.ui.theme import Palette

__all__ = ["STATE_GLYPHS", "WorkflowNav"]

#: A distinct *shape* per state, not merely a colour (NFR-A2). Chosen so the
#: four are told apart at a glance and by anyone with a colour vision deficiency.
STATE_GLYPHS: dict[StepState, str] = {
    StepState.DONE: "●",
    StepState.AVAILABLE: "○",
    StepState.BLOCKED: "·",
    StepState.LOCKED: "▪",
}

_STEP_ROLE = Qt.ItemDataRole.UserRole


class WorkflowNav(QWidget):
    """An ordered, stateful list of the steps in setting up a case."""

    step_selected = Signal(str)
    action_requested = Signal(str)
    return_to_mesh = Signal()

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._model = WorkflowModel()
        self._items: dict[str, QTreeWidgetItem] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(10, 6, 10, 6)
        header_row.setSpacing(8)

        heading = QLabel(labels["workflow"])
        heading.setProperty("role", "panelTitle")
        header_row.addWidget(heading)
        header_row.addStretch(1)

        # "2 of 4 done" beside the title. The panel could previously answer "what
        # next?" but not "how far along am I?", and a procedure that will not say
        # how long it is asks for more faith than a first-time user has.
        self._progress = QLabel()
        self._progress.setProperty("role", "muted")
        header_row.addWidget(self._progress)
        outer.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setRootIsDecorated(False)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setAccessibleName(labels["workflow"])
        self._tree.itemClicked.connect(self._on_clicked)
        self._tree.currentItemChanged.connect(self._on_current)
        outer.addWidget(self._tree, stretch=1)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setProperty("role", "muted")
        self._hint.setContentsMargins(10, 4, 10, 4)
        outer.addWidget(self._hint)

        self._next = QLabel()
        self._next.setWordWrap(True)
        self._next.setContentsMargins(10, 0, 10, 6)
        outer.addWidget(self._next)

        # scFLOW's "Return to Prepare Parts", appearing only once there is a
        # phase to return from.
        self._return = QPushButton(labels["return_to_mesh"])
        self._return.clicked.connect(self.return_to_mesh)
        self._return.hide()
        outer.addWidget(self._return)

        self._build()
        self.set_palette(palette)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        self._tree.clear()
        self._items.clear()

        for step in STEPS:
            item = QTreeWidgetItem()
            item.setData(0, _STEP_ROLE, step.id)
            if step.parent and step.parent in self._items:
                self._items[step.parent].addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            self._items[step.id] = item

        self._tree.expandAll()
        self.refresh()

    # -- state -------------------------------------------------------------

    def set_model(self, model: WorkflowModel) -> None:
        self._model = model
        self.refresh()

    @property
    def model(self) -> WorkflowModel:
        return self._model

    def refresh(self) -> None:
        """Re-render every row from the model. Cheap: the list is twenty rows."""
        for step in STEPS:
            self._render(step, self._items[step.id])

        done, total = self._model.progress
        self._progress.setText(
            self._labels["workflow_progress_none"]
            if self._model.case is None
            else self._labels["workflow_progress"].format(done, total)
        )

        following = self._model.next_step
        self._next.setText(
            self._labels["next_step"].format(self._labels[f"step.{following.id}"])
            if following is not None
            else self._labels["nothing_outstanding"]
        )
        self._return.setVisible(self._model.has_mesh)

    def _render(self, step: Step, item: QTreeWidgetItem) -> None:
        state = self._model.state_of(step)
        label = self._labels[f"step.{step.id}"]

        if step.is_group:
            # Headers carry no marker, and are set in bold against the muted
            # colour. That difference is what tells a header from a step at a
            # glance — the previous version distinguished them only by the
            # presence of a four-pixel glyph, which is not a difference anyone
            # reads.
            item.setText(0, label)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
        else:
            item.setText(0, self._row_text(step, state, label))

        # Never `setDisabled`. Qt refuses to make a disabled item current, so a
        # blocked row could not be focused — and its explanation, which is the
        # one thing the user needs, would be reachable only by hovering a mouse
        # over it. NFR-A1 requires the whole shell to work without one. The row
        # is muted instead, and the *action* is what refuses.
        muted = state in {StepState.BLOCKED, StepState.LOCKED}
        item.setForeground(
            0,
            QBrush(QColor(self._palette.text_muted if muted else self._palette.text)),
        )

        item.setData(0, Qt.ItemDataRole.AccessibleTextRole, "")
        item.setToolTip(0, self._explain(step, state))
        item.setData(
            0,
            Qt.ItemDataRole.UserRole + 1,
            state.value,
        )
        # The accessible name carries the state in words, so it is never conveyed
        # by the glyph or the greying alone.
        item.setData(
            0,
            Qt.ItemDataRole.AccessibleTextRole,
            self._labels["step_accessible"].format(label, self._labels[f"state.{state.value}"]),
        )

    def _marker(self, step: Step, state: StepState) -> str:
        """The mark at the head of a row.

        A required step shows its **number** in the procedure, or a tick once the
        evidence says it is done. That single choice does three jobs the old
        four-glyph vocabulary could not: it states the order, it distinguishes
        the four steps that must happen from the seventeen that need not, and it
        makes completion legible without a legend.

        Optional steps keep a state glyph, because they have no position to show.
        """
        if (number := self._model.number_of(step)) is not None:
            # The number stays when the step is done. Replacing it with a bare
            # tick loses the sequence exactly where the user most wants it — a
            # column reading "✓ ✓ 3 ✓" says nothing about what order those were
            # in, or which one the 3 follows.
            if state is StepState.DONE:
                return self._labels["step_done_number"].format(number)
            return str(number)
        return STATE_GLYPHS[state]

    def _row_text(self, step: Step, state: StepState, label: str) -> str:
        """A step row: marker, label, and the state in words where it is unclear.

        Only ``blocked`` and ``locked`` get the trailing word. ``available`` is
        the ordinary case and saying so on every row would be noise; ``done``
        already shows a tick. The two that remain are exactly the two a user
        cannot otherwise account for — "why can I not click this?" — and putting
        the answer on the row rather than in a tooltip is what stops the panel
        needing to be learned (NFR-A2: never appearance alone).
        """
        marker = self._marker(step, state)
        if state in {StepState.BLOCKED, StepState.LOCKED}:
            return self._labels["step_row_state"].format(
                marker, label, self._labels[f"state.{state.value}"]
            )
        return self._labels["step_row"].format(marker, label)

    def _explain(self, step: Step, state: StepState) -> str:
        """Why a row is in the state it is in. Shown rather than left to guess."""
        if state is StepState.LOCKED:
            return self._labels["locked_explains"]
        if state is StepState.BLOCKED:
            if step.needs_mesh and not self._model.has_mesh:
                return self._labels["blocked_no_mesh"]
            return self._labels["blocked_no_case"]
        return self._labels.get(f"hint.{step.id}", "")

    # -- interaction -------------------------------------------------------

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        step_id = item.data(0, _STEP_ROLE)
        step = next((s for s in STEPS if s.id == step_id), None)
        if step is None:
            return
        if step.is_group:
            # Collapse or expand, rather than nothing at all. A header that
            # swallows a click reads as broken, and folding a group the user is
            # done with is the cheapest way to shorten a twenty-row list.
            item.setExpanded(not item.isExpanded())
            return
        if self._model.state_of(step) in {StepState.BLOCKED, StepState.LOCKED}:
            return
        if step.kind is StepKind.ACTION:
            self.action_requested.emit(step.id)
        else:
            self.step_selected.emit(step.id)

    def _on_current(self, item: QTreeWidgetItem | None, _previous) -> None:
        if item is None:
            self._hint.setText("")
            return
        step_id = item.data(0, _STEP_ROLE)
        step = next((s for s in STEPS if s.id == step_id), None)
        if step is None:
            self._hint.setText("")
            return
        self._hint.setText(self._explain(step, self._model.state_of(step)))

    def select(self, step_id: str) -> None:
        item = self._items.get(step_id)
        if item is not None:
            self._tree.setCurrentItem(item)

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        if self._items:
            self.refresh()
        self.setStyleSheet(
            f"QTreeWidget {{ background: {palette.surface}; border: none;"
            f" color: {palette.text}; }}"
            f"QTreeWidget::item {{ padding: 3px 2px; }}"
            f"QTreeWidget::item:selected {{ background: {palette.surface_alt};"
            f" color: {palette.text}; }}"
            f"QTreeWidget::item:disabled {{ color: {palette.text_muted}; }}"
        )

    # -- inspection --------------------------------------------------------

    @property
    def rows(self) -> list[str]:
        return [step.id for step in STEPS]

    def text_of(self, step_id: str) -> str:
        item = self._items.get(step_id)
        return item.text(0) if item is not None else ""

    def state_text_of(self, step_id: str) -> str:
        item = self._items.get(step_id)
        return item.data(0, Qt.ItemDataRole.AccessibleTextRole) if item is not None else ""

    def is_actionable(self, step_id: str) -> bool:
        """Whether activating this row does anything.

        Distinct from whether it can be focused: a blocked row is focusable so
        its explanation can be read, but activating it is a no-op.
        """
        step = next((s for s in STEPS if s.id == step_id), None)
        if step is None or step.is_group:
            return False
        return self._model.state_of(step) not in {StepState.BLOCKED, StepState.LOCKED}

    @property
    def progress_text(self) -> str:
        return self._progress.text()

    @property
    def next_text(self) -> str:
        return self._next.text()

    @property
    def hint_text(self) -> str:
        return self._hint.text()

    @property
    def offers_return_to_mesh(self) -> bool:
        return self._return.isVisibleTo(self)
