"""The task page (§7.2, DEC-21): the form for whatever the outline selected.

Fluent's *Task Page* sits beside the Outline View and changes with the node
that is selected there: *General* shows the solver and time settings, *Run
Calculation* shows the iteration count and the Calculate button. It is the one
place a form ever appears, which is what keeps the graphics window the centre
of the screen rather than one panel among several.

The page is a stack the shell drives. There is deliberately no tab bar over it:
the outline already states the order of the work, and a second ordering beside
it is how a user ends up unable to say where they are.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

__all__ = ["TaskPage"]


class TaskPage(QWidget):
    """A titled stack of pages, one shown at a time."""

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskPage")
        self._labels = labels
        self._keys: dict[str, int] = {}

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        header = QWidget()
        header.setObjectName("taskPageHeader")
        rows = QVBoxLayout(header)
        rows.setContentsMargins(12, 8, 12, 8)
        rows.setSpacing(2)

        self._title = QLabel(labels["task_page"])
        self._title.setProperty("role", "panelTitle")
        rows.addWidget(self._title)

        # One sentence under the title: what this page is for. Read here it is a
        # caption to the form it explains, rather than a tooltip on a tree row.
        self._caption = QLabel()
        self._caption.setProperty("role", "muted")
        self._caption.setWordWrap(True)
        self._caption.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        rows.addWidget(self._caption)
        column.addWidget(header)

        self._header = header
        self._stack = QStackedWidget()
        self._stack.setObjectName("taskPageStack")
        column.addWidget(self._stack, stretch=1)

        self._empty = QLabel(labels["task_page_none"])
        self._empty.setProperty("role", "muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._empty.setContentsMargins(12, 8, 12, 8)
        self._empty.setWordWrap(True)
        self.add_page("", self._empty)

    def _fit_caption(self) -> None:
        """Give the caption the height its own wrapping asks for.

        A word-wrapped ``QLabel`` reports a *single-line* size hint, and a
        vertical layout that has no spare room to give it — which is the case
        here, because the page below takes the stretch — grants exactly that.
        Every caption longer than the column was therefore clipped mid-word, and
        the sentence explaining the selected node lost its second half. Setting
        the height from ``heightForWidth`` is the one way to say what a wrapped
        label actually needs; nothing in the layout system will work it out.
        """
        width = max(self._caption.width(), 1)
        self._caption.setFixedHeight(
            self._caption.heightForWidth(width) if self._caption.text() else 0
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_caption()

    #: Margin every page is given, unless it already sets its own.
    #:
    #: Set here rather than in each of the twelve pages. They were written at
    #: different times with different contents margins — several with none — so
    #: some headings and tables ran into the column's left edge and others did
    #: not, and the column had no left alignment at all. A style sheet ``padding``
    #: does not do this: on a plain ``QWidget`` it insets the frame Qt paints,
    #: not the layout inside it.
    MARGIN = (12, 10, 12, 10)

    def add_page(self, key: str, widget: QWidget) -> None:
        """Register a page under a name a node can refer to.

        A page that has already set its own margins keeps them — the run page's
        stage strip is inset by its own frame, and adding to that would indent
        it past everything beside it.
        """
        layout = widget.layout()
        if layout is not None and layout.contentsMargins().left() == 0:
            layout.setContentsMargins(*self.MARGIN)
        self._keys[key] = self._stack.addWidget(widget)

    def show_page(self, key: str, *, title: str = "", caption: str = "") -> bool:
        """Bring one page to the front. Unknown names change nothing.

        Deliberately not called ``show``: that is ``QWidget``'s, and an override
        with a different signature turns every ordinary ``widget.show()`` in Qt
        or in a test into a ``TypeError`` at a place that has nothing to do with
        this class.
        """
        index = self._keys.get(key)
        if index is None:
            return False
        self._stack.setCurrentIndex(index)
        self._title.setText(title or self._labels["task_page"])
        self._caption.setText(caption)
        self._caption.setVisible(bool(caption))
        self._fit_caption()
        return True

    @property
    def current(self) -> str:
        current = self._stack.currentIndex()
        return next((key for key, index in self._keys.items() if index == current), "")

    @property
    def title_text(self) -> str:
        return self._title.text()

    @property
    def caption_text(self) -> str:
        return self._caption.text()

    @property
    def pages(self) -> list[str]:
        return [key for key in self._keys if key]
