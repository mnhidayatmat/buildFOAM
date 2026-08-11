"""The raw-text tab, for every dictionary (FR-P6, DEC-07).

DEC-07 keeps both a form and a text tab because they serve different people: the
forms serve P1 and P2, and the text tab is what keeps the P4 constraint — a power
user must never be trapped, and must be able to reach anything the form does not
model.

Two behaviours are requirements rather than niceties.

**Validate on save, with a line-accurate error.** FR-P6: "invalid syntax blocks
the save with a line-accurate error". Writing a file the parser cannot read would
leave the case broken *and* unopenable in the application that broke it, which is
the one failure D4 exists to prevent. The check is the same parser the rest of
the product uses, so the tab cannot accept something the case view will later
reject.

**Highlighting is lexical, not a second grammar.** Colours come from the same
token stream the parser consumes, so the editor and the parser can never disagree
about what a string or a comment is. A separate regex highlighter would eventually
paint something the parser reads differently, and the user would trust the
colours.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.foamdict import Document, ParseError, TokenKind, tokenize
from foamwb.services.journal import JournalService
from foamwb.ui.theme import Palette

__all__ = ["DictionaryHighlighter", "TextEditor"]

#: Token kinds worth colouring. Everything else is body text — colouring more
#: would compete with the content rather than clarify it.
_COLOURED = {
    TokenKind.COMMENT: "text_muted",
    TokenKind.STRING: "ready",
    TokenKind.DIRECTIVE: "accent",
    TokenKind.VARIABLE: "accent",
    TokenKind.VERBATIM: "text_muted",
}


class DictionaryHighlighter(QSyntaxHighlighter):
    """Colours a dictionary using the product's own lexer.

    Qt highlights one block at a time, but OpenFOAM has constructs that span
    lines — block comments and ``#{ ... #}`` verbatim regions. Those are tracked
    with Qt's block state, which is what keeps a multi-line comment coloured all
    the way down instead of only on its first line.
    """

    #: Block states. NONE means the previous line ended cleanly.
    NONE = 0
    IN_COMMENT = 1
    IN_VERBATIM = 2

    def __init__(self, document: QTextDocument, palette: Palette) -> None:
        super().__init__(document)
        self._formats = {
            kind: _format(getattr(palette, token)) for kind, token in _COLOURED.items()
        }
        self._continuation = {
            self.IN_COMMENT: _format(palette.text_muted),
            self.IN_VERBATIM: _format(palette.text_muted),
        }

    def highlightBlock(self, text: str) -> None:
        previous = max(self.previousBlockState(), self.NONE)

        if previous in self._continuation:
            closer = "*/" if previous == self.IN_COMMENT else "#}"
            end = text.find(closer)
            if end == -1:
                self.setFormat(0, len(text), self._continuation[previous])
                self.setCurrentBlockState(previous)
                return
            self.setFormat(0, end + len(closer), self._continuation[previous])
            text = " " * (end + len(closer)) + text[end + len(closer) :]

        state = self.NONE
        try:
            tokens = tokenize(text)
        except ValueError:
            # An unterminated construct on this line: the region continues onto
            # the next one. Colour the rest of the line and record which kind, so
            # the continuation picks up where this left off.
            state = self.IN_VERBATIM if "#{" in text else self.IN_COMMENT
            opener = text.rfind("#{" if state == self.IN_VERBATIM else "/*")
            if opener >= 0:
                self.setFormat(opener, len(text) - opener, self._continuation[state])
            self.setCurrentBlockState(state)
            return

        for token in tokens:
            fmt = self._formats.get(token.kind)
            if fmt is not None:
                self.setFormat(token.start, len(token.text), fmt)
        self.setCurrentBlockState(state)


def _format(colour: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(colour))
    return fmt


#: How long typing must pause before the buffer is journalled. Long enough
#: that a disk write never lands between keystrokes, short enough that the
#: most a crash can cost is a sentence.
JOURNAL_DELAY_MS = 1500


class TextEditor(QWidget):
    """Edit any dictionary as text, with validate-on-save (FR-P6)."""

    saved = Signal(bytes)
    """The bytes to write. Emitted only after they have been shown to parse."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._original = b""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._view = QPlainTextEdit()
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.setAccessibleName(labels["raw_text"])
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(12)
        self._view.setFont(font)
        # Tabs would be written into the file as tabs, changing bytes the user did
        # not intend to change (FR-P7).
        self._view.setTabStopDistance(4 * self._view.fontMetrics().horizontalAdvance(" "))
        self._view.textChanged.connect(self._on_changed)
        layout.addWidget(self._view, stretch=1)

        self._highlighter = DictionaryHighlighter(self._view.document(), palette)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._status = QLabel()
        self._status.setWordWrap(True)
        row.addWidget(self._status, stretch=1)

        self._revert_button = QPushButton(labels["revert"])
        self._revert_button.clicked.connect(self.revert)
        row.addWidget(self._revert_button)

        self._save_button = QPushButton(labels["save"])
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self.save)
        row.addWidget(self._save_button)
        layout.addLayout(row)

        # NFR-R3. Coalesced rather than written per keystroke: a disk write in
        # the typing path would be felt, and a second of lost work is not the
        # failure this exists to prevent.
        self._journal = JournalService()
        self._journal_target: tuple[Path, str] | None = None
        self._journal_timer = QTimer(self)
        self._journal_timer.setSingleShot(True)
        self._journal_timer.setInterval(JOURNAL_DELAY_MS)
        self._journal_timer.timeout.connect(self._write_journal)

        self.set_content(b"")

    # -- content -----------------------------------------------------------

    def set_journal_target(self, case: Path | None, relative: str = "") -> None:
        """Say which file this buffer belongs to, so it can be journalled.

        Without a target nothing is recorded — an editor showing a scratch
        buffer has no file to recover *into*, and journalling it would offer
        the user a recovery for something that was never theirs.
        """
        self._journal_target = (case, relative) if case is not None and relative else None

    def set_content(self, data: bytes) -> None:
        """Load a dictionary. Decoding is lenient so any file can be opened."""
        self._original = data
        self._view.setPlainText(data.decode("utf-8", errors="replace"))
        self._view.document().clearUndoRedoStacks()
        self._update_state()

    @property
    def content(self) -> bytes:
        return self._view.toPlainText().encode("utf-8")

    @property
    def is_modified(self) -> bool:
        return self.content != self._original

    def revert(self) -> None:
        self.set_content(self._original)
        self._clear_journal()

    # -- journalling (NFR-R3) ----------------------------------------------

    def _write_journal(self) -> None:
        if self._journal_target is None:
            return
        case, relative = self._journal_target
        if self.is_modified:
            self._journal.record(case, relative, self._view.toPlainText())
        else:
            self._journal.forget(case, relative)

    def _clear_journal(self) -> None:
        """Drop the entry. Called on save and on revert — in both cases the
        buffer no longer differs from something the user wants kept."""
        self._journal_timer.stop()
        if self._journal_target is not None:
            self._journal.forget(*self._journal_target)

    def flush_journal(self) -> None:
        """Write any pending entry immediately, for shutdown."""
        self._journal_timer.stop()
        self._write_journal()

    # -- saving ------------------------------------------------------------

    def validate(self) -> ParseError | None:
        """Parse the buffer, returning the error rather than raising it."""
        try:
            Document.parse_bytes(self.content)
        except ParseError as exc:
            return exc
        return None

    def save(self) -> bool:
        """Validate, then emit the bytes. Returns whether the save happened.

        Refusing the save is the point (FR-P6). A file written past the parser
        would leave the case broken *and* unopenable in the application that
        broke it.
        """
        problem = self.validate()
        if problem is not None:
            self._show_error(problem)
            self._go_to(problem.line, problem.column)
            return False

        self._original = self.content
        # The buffer is on disk now, so the journal entry has done its job.
        # Kept until *after* the save succeeds: dropping it first would lose the
        # recovery in the window where writing the file is what fails.
        self.saved.emit(self._original)
        self._clear_journal()
        self._update_state()
        return True

    def _show_error(self, problem: ParseError) -> None:
        self._status.setText(self._labels["save_blocked"].format(problem.line, problem.message))
        self._status.setStyleSheet(f"color: {self._palette.broken};")

    def _go_to(self, line: int, column: int) -> None:
        """Put the cursor on the offending place (E-C02, §7.4).

        The whole value of a line-accurate error is arriving at the line; making
        the user scroll to it themselves wastes the accuracy.
        """
        block = self._view.document().findBlockByNumber(max(0, line - 1))
        cursor = QTextCursor(block)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.MoveAnchor,
            max(0, column - 1),
        )
        self._view.setTextCursor(cursor)
        self._view.centerCursor()
        self._view.setFocus()

    # -- state -------------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette and re-highlight the buffer (NFR-A4).

        The highlighter bakes its formats at construction — that is what keeps
        ``highlightBlock`` cheap on a file with thousands of lines — so a theme
        change has to build a new one rather than update the old one in place.
        The document is detached from the outgoing highlighter first, because two
        highlighters on one document both run, and the loser paints last.

        The buffer's contents and undo history are untouched: this is a colour
        change, and a user who loses unsaved edits to it would rightly never
        touch the control again.
        """
        self._palette = palette
        self._highlighter.setDocument(None)
        self._highlighter = DictionaryHighlighter(self._view.document(), palette)
        self._highlighter.rehighlight()
        self._update_state()

    def _on_changed(self) -> None:
        self._update_state()
        if self._journal_target is not None:
            self._journal_timer.start()

    def _update_state(self) -> None:
        modified = self.is_modified
        self._save_button.setEnabled(modified)
        self._revert_button.setEnabled(modified)
        if not modified:
            self._status.setText(self._labels["no_changes"])
            self._status.setStyleSheet(f"color: {self._palette.text_muted};")
            return
        self._status.setText(self._labels["unsaved_changes"])
        self._status.setStyleSheet(f"color: {self._palette.degraded};")

    # -- for tests ---------------------------------------------------------

    @property
    def text(self) -> str:
        return self._view.toPlainText()

    def set_text(self, text: str) -> None:
        self._view.setPlainText(text)

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def can_save(self) -> bool:
        return self._save_button.isEnabled()

    @property
    def cursor_line(self) -> int:
        return self._view.textCursor().blockNumber() + 1

    def find(self, needle: str) -> bool:  # pragma: no cover - parity with LogPane
        return self._view.find(QRegularExpression.escape(needle))
