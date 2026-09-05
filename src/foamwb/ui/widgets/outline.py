"""The Outline View (§7.2, DEC-21).

Fluent's Outline View, adapted. The important property is that it is **the
structure of the case in the order it is set up**, not a set of destinations:
the user reads down it and knows both what a CFD case consists of and where they
have got to. That is the single largest thing a nav rail cannot do.

Four rules it keeps.

**Every state is carried in words as well as appearance** (NFR-A2). A greyed-out
row is invisible to a screen reader and ambiguous to everyone else — "locked"
and "not yet" mean different things and need different remedies, so each row
says which it is, and the state glyph sits in its own column where it can be
scanned.

**A blocked node explains itself and stays visible** (§7.9 rule 3). Hiding nodes
that are not yet reachable would leave a user unable to see what the procedure
even is, which is the whole reason for showing it in this shape.

**A locked phase is reversible.** Fluent greys the meshing workflow out once the
case has switched to solution mode and offers *Switch to Meshing*; the same
affordance appears here as soon as the mesh exists, because a user whose mesh is
wrong must be able to get back to it.

**The tree is filterable.** Fluent's outline has a filter box, and twenty-five
nodes is past the point where scanning beats typing.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.workflow import STEPS, Step, StepKind, StepState, WorkflowModel
from foamwb.ui.theme import Palette

__all__ = ["STATE_GLYPHS", "Outline"]

#: A distinct *shape* per state, not merely a colour (NFR-A2). Chosen so the
#: four are told apart at a glance and by anyone with a colour vision deficiency.
#: Fluent's outline marks a task the same way — a tick for done, a hollow mark
#: for outstanding — which is what makes progress readable without a legend.
STATE_GLYPHS: dict[StepState, str] = {
    StepState.DONE: "✓",
    # Workbench draws its *Update Required* as a lightning bolt. A recycle arrow
    # says the same thing and survives a font that has no ⚡ — and the shape is
    # what has to differ, not the pictogram (NFR-A2).
    StepState.STALE: "↻",
    StepState.AVAILABLE: "○",
    StepState.BLOCKED: "·",
    StepState.LOCKED: "▪",
}

_STEP_ROLE = Qt.ItemDataRole.UserRole

#: The glyph column's width in characters. Two, so a tick and the space after it
#: line every label up at the same left edge whatever the row's state.
_GLYPH_COLUMN = 34


class Outline(QWidget):
    """An ordered, stateful tree of what the case consists of."""

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
        self.setObjectName("outline")
        self._palette = palette
        self._labels = labels
        self._model = WorkflowModel()
        self._items: dict[str, QTreeWidgetItem] = {}
        self._filter = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("outlineHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(10, 6, 10, 6)
        header_row.setSpacing(8)

        heading = QLabel(labels["workflow"])
        heading.setProperty("role", "panelTitle")
        header_row.addWidget(heading)
        header_row.addStretch(1)

        # "2 of 4 done" beside the title. A tree of names can say what the work
        # is but not how much of it is left, and that is the question a
        # first-time user asks second.
        self._progress = QLabel()
        self._progress.setProperty("role", "muted")
        header_row.addWidget(self._progress)
        outer.addWidget(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText(labels["outline_filter"])
        self._search.setAccessibleName(labels["outline_filter"])
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_filter)
        outer.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setObjectName("outlineTree")
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setIndentation(14)
        self._tree.setRootIsDecorated(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setAccessibleName(labels["workflow"])
        self._tree.itemClicked.connect(self._on_clicked)
        self._tree.currentItemChanged.connect(self._on_current)
        outer.addWidget(self._tree, stretch=1)

        # Kept and not shown: the node's purpose is the caption above the task
        # page now, and the way forward is a ribbon button. The widget stays
        # because the text is still what the tooltips are built from.
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setProperty("role", "muted")
        self._hint.setVisible(False)

        self._next = QLabel()
        self._next.setWordWrap(True)
        self._next.setVisible(False)

        # Fluent's *Switch to Meshing*, appearing only once there is a mode to
        # switch back from.
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
        self._tree.setColumnWidth(0, _GLYPH_COLUMN)
        self.refresh()

    # -- state -------------------------------------------------------------

    def set_model(self, model: WorkflowModel) -> None:
        self._model = model
        self.refresh()

    @property
    def model(self) -> WorkflowModel:
        return self._model

    def refresh(self) -> None:
        """Re-render every row from the model. Cheap: the tree is 25 rows."""
        for step in STEPS:
            item = self._items[step.id]
            # Hidden rather than removed, so the item survives to be shown again
            # the moment the model says the node has something behind it.
            item.setHidden(not self._model.is_offered(step) or not self._matches(step))
            self._render(step, item)

        done, total = self._model.progress
        self._progress.setText(
            self._labels["workflow_progress_none"]
            if self._model.case is None
            else self._labels["workflow_progress"].format(done, total)
        )

        following = self._model.next_step
        if self._model.case is None:
            # Every node needs a case, so nothing is outstanding in the sense
            # the spine means — and saying "every required step is done" over an
            # empty window would be the plainest possible lie.
            self._next.setText(self._labels["workflow_progress_none"])
        else:
            self._next.setText(
                self._labels["next_step"].format(self._labels[f"step.{following.id}"])
                if following is not None
                else self._labels["nothing_outstanding"]
            )
        self._return.setVisible(self._model.has_mesh)

    def _matches(self, step: Step) -> bool:
        """Whether the filter keeps this row.

        A group survives if any of its children does, so filtering never leaves
        a node floating without the heading that says what part of the case it
        belongs to.
        """
        if not self._filter:
            return True
        if self._filter in self._labels[f"step.{step.id}"].lower():
            return True
        if step.is_group:
            return any(
                self._filter in self._labels[f"step.{child.id}"].lower()
                for child in self._model.children_of(step.id)
            )
        parent = self._labels.get(f"step.{step.parent}", "").lower()
        return self._filter in parent

    def _on_filter(self, text: str) -> None:
        self._filter = text.strip().lower()
        self.refresh()

    def _render(self, step: Step, item: QTreeWidgetItem) -> None:
        state = self._model.state_of(step)
        label = self._labels[f"step.{step.id}"]

        if step.is_group:
            # Headers carry no marker, and are set in bold. That difference is
            # what tells a header from a node at a glance.
            item.setText(0, "")
            item.setText(1, label)
            font = item.font(1)
            font.setBold(True)
            item.setFont(1, font)
        else:
            item.setText(0, STATE_GLYPHS[state])
            item.setText(1, self._row_text(step, state, label))

        # Never `setDisabled`. Qt refuses to make a disabled item current, so a
        # blocked row could not be focused — and its explanation, which is the
        # one thing the user needs, would be reachable only by hovering a mouse
        # over it. NFR-A1 requires the whole shell to work without one. The row
        # is muted instead, and the *action* is what refuses.
        colour = QBrush(QColor(self._row_colour(state)))
        for column in (0, 1):
            item.setForeground(column, colour)
            item.setToolTip(column, self._explain(step, state))

        # The accessible name carries the state in words, so it is never
        # conveyed by the glyph or the greying alone.
        item.setData(
            1,
            Qt.ItemDataRole.AccessibleTextRole,
            self._labels["step_accessible"].format(label, self._labels[f"state.{state.value}"]),
        )

    def _row_colour(self, state: StepState) -> str:
        """What colour a row is drawn in.

        Green for done, so progress is visible while scanning the column rather
        than only by reading each marker. This is safe against NFR-A2 — colour
        is never the sole carrier — because the row already shows a tick and the
        accessible name already says "done"; the colour is a third statement of
        a fact two other channels have made, not the only one.

        Blocked and locked stay muted: they are the rows the user cannot act on,
        and receding is what says so.
        """
        if state is StepState.DONE:
            return self._palette.ready
        # Amber, the same token the footer uses for a degraded runtime: this is
        # the state that most needs to be noticed and is least like a failure.
        if state is StepState.STALE:
            return self._palette.degraded
        if state in {StepState.BLOCKED, StepState.LOCKED}:
            return self._palette.text_muted
        return self._palette.text

    def _row_text(self, step: Step, state: StepState, label: str) -> str:
        """A node's label, and the state in words where it is unclear.

        ``available`` is the ordinary case and saying so on every row would be
        noise; ``done`` already shows a tick. The three that remain are the ones
        a user cannot otherwise account for — "why can I not click this?" and
        "why is this one amber?" — and putting the answer on the row rather
        than in a tooltip is what stops the tree needing to be learned (NFR-A2:
        never appearance alone). ``stale`` most of all: a mark that says only
        "something is different about this row" is a mark that gets ignored.
        """
        if state in {StepState.BLOCKED, StepState.LOCKED, StepState.STALE}:
            return (
                self._labels["step_row_state"]
                .format("", label, self._labels[f"state.{state.value}"])
                .strip()
            )
        return label

    def _explain(self, step: Step, state: StepState) -> str:
        """Why a row is in the state it is in. Shown rather than left to guess."""
        if state is StepState.STALE:
            # The file, not merely the fact. A user who has edited four things
            # needs to know which one of them did this.
            return self._labels["stale_because"].format(self._model.stale_because(step))
        if state is StepState.LOCKED:
            return self._labels["locked_explains"]
        if state is StepState.BLOCKED:
            if self._model.awaiting_mesh(step):
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
            # done with is the cheapest way to shorten the tree.
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

    # -- inspection --------------------------------------------------------

    @property
    def rows(self) -> list[str]:
        return [step.id for step in STEPS]

    @property
    def visible_rows(self) -> list[str]:
        """The rows actually drawn — what the user sees, not what exists."""
        return [step_id for step_id, item in self._items.items() if not item.isHidden()]

    def text_of(self, step_id: str) -> str:
        item = self._items.get(step_id)
        return f"{item.text(0)} {item.text(1)}".strip() if item is not None else ""

    @property
    def current_step(self) -> str:
        item = self._tree.currentItem()
        return item.data(0, _STEP_ROLE) if item is not None else ""

    def colour_of(self, step_id: str) -> str:
        item = self._items.get(step_id)
        return item.foreground(1).color().name() if item is not None else ""

    def state_text_of(self, step_id: str) -> str:
        item = self._items.get(step_id)
        return item.data(1, Qt.ItemDataRole.AccessibleTextRole) if item is not None else ""

    def is_actionable(self, step_id: str) -> bool:
        """Whether activating this row does anything.

        Distinct from whether it can be focused: a blocked row is focusable so
        its explanation can be read, but activating it is a no-op.
        """
        step = next((s for s in STEPS if s.id == step_id), None)
        if step is None or step.is_group:
            return False
        return self._model.state_of(step) not in {StepState.BLOCKED, StepState.LOCKED}

    def filter_by(self, text: str) -> None:
        self._search.setText(text)

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
