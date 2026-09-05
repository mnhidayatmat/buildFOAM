"""The Messages pane (§7.4, FR-C3): validation findings, each a link to a line.

Fluent has one console. This application has two kinds of message a console
would interleave badly: the solver's transcript, which is thousands of lines a
minute, and validation's findings, which are a dozen sentences that must stay
readable while the transcript scrolls. So the console dock has two tabs, and
this is the second.

Colour states severity and so does the text: a finding that would stop the run
says so in words, because red alone is invisible to a colourblind user and to a
greyscale screenshot attached to a support ticket (NFR-A2).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from foamwb.services.case import Finding
from foamwb.services.validation import Validation
from foamwb.ui.theme import Palette

__all__ = ["MessagesPane"]


class MessagesPane(QWidget):
    """A summary line and the findings under it."""

    finding_activated = Signal(object)
    """A :class:`~foamwb.services.case.Finding` the user asked to see."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._validation: Validation | None = None
        self._has_case = False

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 6, 8, 6)
        column.setSpacing(6)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        column.addWidget(self._summary)

        self._findings = QListWidget()
        self._findings.setAccessibleName(labels["messages"])
        self._findings.setWordWrap(True)
        # Word wrap only takes effect once the list stops offering to scroll
        # sideways instead. Without this a finding wrapped to two lines and was
        # still cut off mid-sentence at the right edge — and the half that goes
        # missing is the end, which is where these messages say what will happen.
        self._findings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._findings.itemActivated.connect(self._on_activated)
        column.addWidget(self._findings, stretch=1)

        self.set_findings(None, has_case=False)

    # -- content -----------------------------------------------------------

    def set_findings(self, validation: Validation | None, *, has_case: bool = True) -> None:
        """Show a validation's findings, or the no-case hint."""
        self._validation = validation
        self._has_case = has_case
        self._findings.clear()
        # An empty findings list is an empty bordered box, which reads as
        # something that failed to load rather than as a case with nothing wrong
        # with it. The summary line already carries the verdict, so the list
        # only appears when it has something to list.
        self._findings.setVisible(False)

        if not has_case or validation is None:
            self._summary.setText(self._labels["no_case_open_hint"])
            self._summary.setStyleSheet(f"color: {self._palette.text_muted};")
            return

        if not validation.findings:
            self._summary.setText(self._labels["no_findings"])
            self._summary.setStyleSheet(f"color: {self._palette.ready};")
            return

        self._findings.setVisible(True)
        blocking = len(validation.blocking)
        self._summary.setText(
            self._labels["findings_summary"].format(len(validation.findings), blocking)
        )
        self._summary.setStyleSheet(
            f"color: {self._palette.broken if blocking else self._palette.degraded};"
        )
        for finding in validation.findings:
            item = QListWidgetItem(self._describe(finding))
            item.setData(Qt.ItemDataRole.UserRole, finding)
            item.setForeground(
                QBrush(
                    QColor(self._palette.broken if finding.blocks_run else self._palette.degraded)
                )
            )
            self._findings.addItem(item)

    def _describe(self, finding: Finding) -> str:
        where = finding.file.name
        if finding.line is not None:
            where = self._labels["finding_at_line"].format(where, finding.line)
        return self._labels["finding"].format(finding.code.id, where, finding.detail)

    @Slot(QListWidgetItem)
    def _on_activated(self, item: QListWidgetItem) -> None:
        finding = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(finding, Finding):
            self.finding_activated.emit(finding)

    def set_palette(self, palette: Palette) -> None:
        """Re-derive the colours, because they mean something (NFR-A4)."""
        self._palette = palette
        self.set_findings(self._validation, has_case=self._has_case)

    # -- inspection --------------------------------------------------------

    @property
    def count(self) -> int:
        return self._findings.count()

    @property
    def summary_text(self) -> str:
        return self._summary.text()

    def activate(self, index: int) -> None:
        self._on_activated(self._findings.item(index))
