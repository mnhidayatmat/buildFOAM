"""The solver log, streamed live (FR-S2, NFR-P3).

Three requirements, each shaping something visible.

**Throughput.** NFR-P3 allows no UI stall at 5 000 lines/s. Lines arrive already
batched from :class:`~foamwb.ui.run_worker.RunWorker`, and are appended with a
single call per batch rather than one per line — appending text to a rich-text
document is the expensive part, and doing it 5 000 times a second is what makes
naive log panes stutter.

**Bounded memory.** A long transient run produces hundreds of megabytes of
output. ``maximumBlockCount`` keeps the widget at a fixed ceiling and discards
the oldest lines, which is safe because the *full* log is written to disk by the
controller (FR-S7). The pane is a window onto the log, not the log.

**Jump to error.** FR-S2 asks for search and a jump-to-error control. A user
watching a run that failed wants the first line that explains it, and scrolling
back through 40 000 lines of iteration output to find it is the thing the control
exists to prevent.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.ui.theme import Palette

__all__ = ["MAX_VISIBLE_LINES", "LogPane"]

#: Lines kept in the widget. The controller writes the complete log to disk, so
#: this bounds memory without losing anything (FR-S7).
MAX_VISIBLE_LINES = 20_000

#: What "jump to error" looks for. Deliberately the same markers the controller
#: classifies severity by, so the control and the run's verdict agree about what
#: an error is.
_ERROR_PATTERN = re.compile(
    r"FOAM FATAL ERROR|FOAM FATAL IO ERROR|\*\*\*|--> FOAM Warning|error:", re.IGNORECASE
)


class LogPane(QWidget):
    """Streams solver output with search, filtering and error navigation."""

    error_selected = Signal(int)
    """Line number jumped to, so a caller can correlate it with a stage."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._error_lines: list[int] = []
        self._error_cursor = -1
        self._total_lines = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._build_toolbar(labels))

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.setMaximumBlockCount(MAX_VISIBLE_LINES)
        self._view.setObjectName("logView")
        self._view.setAccessibleName(labels["log"])
        # Monospace, because solver output is columnar and proportional type
        # makes a residual table unreadable.
        self._view.setStyleSheet("font-family: ui-monospace, Menlo, Consolas, monospace;")
        layout.addWidget(self._view, stretch=1)

        self._status = QLabel()
        self._status.setProperty("role", "muted")
        layout.addWidget(self._status)
        self._update_status()

    def _build_toolbar(self, labels: dict[str, str]) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText(labels["search_log"])
        self._search.setClearButtonEnabled(True)
        self._search.returnPressed.connect(self.find_next)
        row.addWidget(self._search, stretch=1)

        self._find_button = QPushButton(labels["find_next"])
        self._find_button.clicked.connect(self.find_next)
        row.addWidget(self._find_button)

        self._error_button = QPushButton(labels["jump_to_error"])
        self._error_button.clicked.connect(self.jump_to_next_error)
        self._error_button.setEnabled(False)
        row.addWidget(self._error_button)

        self._follow = QCheckBox(labels["follow_output"])
        self._follow.setChecked(True)
        # On by default, because a user watching a live run wants the newest
        # line. Unticking it holds position, which is what someone reading back
        # through a failure needs — scrolling that fights the user is worse than
        # no scrolling at all.
        row.addWidget(self._follow)
        return bar

    # -- content -----------------------------------------------------------

    def append(self, lines: list[str]) -> None:
        """Append a batch. One call per batch, never one per line."""
        if not lines:
            return

        for offset, line in enumerate(lines):
            if _ERROR_PATTERN.search(line):
                self._error_lines.append(self._total_lines + offset)
        self._total_lines += len(lines)

        at_bottom = self._follow.isChecked()
        self._view.appendPlainText("\n".join(lines))
        if at_bottom:
            self._view.moveCursor(QTextCursor.MoveOperation.End)

        self._error_button.setEnabled(bool(self._error_lines))
        self._update_status()

    def clear(self) -> None:
        self._view.clear()
        self._error_lines.clear()
        self._error_cursor = -1
        self._total_lines = 0
        self._error_button.setEnabled(False)
        self._update_status()

    def _update_status(self) -> None:
        self._status.setText(
            self._labels["log_status"].format(self._total_lines, len(self._error_lines))
        )

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette (NFR-A4).

        Nothing to repaint: every colour in this pane comes from the application
        style sheet, which the shell has already replaced. The method exists so
        the shell can hand a palette to every widget it owns without keeping a
        list of which ones happen to need it — a list that would go stale the
        first time one of them started using a token.
        """
        self._palette = palette

    # -- navigation --------------------------------------------------------

    def find_next(self) -> bool:
        """Search forward from the cursor, wrapping once at the end."""
        needle = self._search.text().strip()
        if not needle:
            return False
        if self._view.find(needle):
            return True
        # Wrapping rather than reporting "not found" at the end of the document:
        # the user asked to find the text, not to be told where the cursor is.
        self._view.moveCursor(QTextCursor.MoveOperation.Start)
        return bool(self._view.find(needle))

    def jump_to_next_error(self) -> int | None:
        """Move to the next line that looks like an error (FR-S2).

        Cycles rather than stopping at the last one, so repeated presses walk the
        whole set without the user having to scroll back to the top.
        """
        if not self._error_lines:
            return None
        self._error_cursor = (self._error_cursor + 1) % len(self._error_lines)
        line = self._error_lines[self._error_cursor]

        # Following would immediately drag the view back to the newest line and
        # undo the jump, so a jump turns it off — the user has just said they
        # want to look at something else.
        self._follow.setChecked(False)

        block = max(0, line - (self._total_lines - self._view.blockCount()))
        cursor = QTextCursor(self._view.document().findBlockByNumber(block))
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        self._view.setTextCursor(cursor)
        self._view.centerCursor()
        self.error_selected.emit(line)
        return line

    # -- for tests ---------------------------------------------------------

    @property
    def line_count(self) -> int:
        return self._total_lines

    @property
    def error_count(self) -> int:
        return len(self._error_lines)

    @property
    def text(self) -> str:
        return self._view.toPlainText()

    @property
    def following(self) -> bool:
        return self._follow.isChecked()

    def set_search(self, needle: str) -> None:
        self._search.setText(needle)
