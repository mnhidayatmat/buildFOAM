"""The console dock (§7.5, DEC-21): the transcript, under the graphics window.

Fluent's console is a bottom dock that is always there: every utility, every
solver iteration and every warning lands in it, and it can be folded down to a
title bar when the graphics need the height. The same here, with one deliberate
difference — **no command line**. §1.1 promises a workflow that never opens a
terminal, and a console that accepted commands would be one. The transcript is
read-only; what a power user needs is the file system, which D4 keeps theirs.

One log pane serves the run, the meshing utilities and the post utilities,
because a user reads one stream of what the application did on their behalf.
Beside it, a **Messages** tab holds validation's findings, which would be lost
in a transcript that scrolls at five thousand lines a second.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabWidget, QToolButton, QVBoxLayout, QWidget

__all__ = ["ConsoleDock"]


class ConsoleDock(QWidget):
    """A collapsible dock with a Console and a Messages tab."""

    collapsed_changed = Signal(bool)

    def __init__(
        self,
        labels: dict[str, str],
        console: QWidget,
        messages: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("consoleDock")
        self._labels = labels
        self._collapsed = False

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        header = QWidget()
        header.setObjectName("consoleHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 2, 6, 2)
        row.setSpacing(6)

        title = QLabel(labels["console"])
        title.setProperty("role", "panelTitle")
        row.addWidget(title)
        row.addStretch(1)

        self._toggle = QToolButton()
        self._toggle.setObjectName("consoleToggle")
        self._toggle.setAutoRaise(True)
        self._toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._toggle.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        row.addWidget(self._toggle)
        column.addWidget(header)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("consoleTabs")
        self._tabs.setDocumentMode(True)
        self._tabs.setAccessibleName(labels["console"])
        self._tabs.addTab(console, labels["console"])
        self._tabs.addTab(messages, labels["messages"])
        column.addWidget(self._tabs, stretch=1)

        self._describe_toggle()

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold to the title bar, or unfold. The header always stays."""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._tabs.setVisible(not collapsed)
        self._describe_toggle()
        self.collapsed_changed.emit(collapsed)

    def _describe_toggle(self) -> None:
        # Glyph *and* accessible text, so the state is never appearance alone.
        label = self._labels["console_expand" if self._collapsed else "console_collapse"]
        self._toggle.setText("▴" if self._collapsed else "▾")
        self._toggle.setToolTip(label)
        self._toggle.setAccessibleName(label)

    def show_console(self) -> None:
        self._tabs.setCurrentIndex(0)
        self.set_collapsed(False)

    def show_messages(self) -> None:
        self._tabs.setCurrentIndex(1)
        self.set_collapsed(False)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @property
    def current_tab(self) -> str:
        return "console" if self._tabs.currentIndex() == 0 else "messages"
