"""The setup check (FR-C3, §7.3).

Runs before the solver does, and exists because the alternative is finding out
twenty minutes into a run — or worse, not finding out at all.

**A clean result is stated carefully.** It means the case does not contradict
itself: every field a solver reads is present, every patch named in a field
exists in the mesh, every value the schema knows about is in range. It does not
mean the case is *right*. §6.9's argument is that a plausible wrong answer is the
failure that matters, and a green tick implying correctness would be that failure
wearing this application's badge. The caveat sits beside the result, always, not
in a tooltip.

**Severity is a word, not a colour** (NFR-A2), and the word says the consequence:
"blocks the run" rather than "error". A user deciding whether to press Run needs
to know what happens, not how the finding was classified.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.codes import Severity
from foamwb.services.case import CaseError, CaseService
from foamwb.services.validation import Validation, validate_case
from foamwb.ui.theme import Palette

__all__ = ["VerifyView"]

_FILE_ROLE = Qt.ItemDataRole.UserRole

#: Severity to the label that names its consequence. Kept here rather than in the
#: enum because the enum is service-layer vocabulary and these are sentences.
_SEVERITY_KEYS: dict[Severity, str] = {
    Severity.FATAL: "sev_fatal",
    Severity.ERROR: "sev_error",
    Severity.WARNING: "sev_warning",
    Severity.INFO: "sev_info",
}


class VerifyView(QWidget):
    """Shows what is wrong with a case before it is run."""

    file_requested = Signal(Path)

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._case: Path | None = None
        self._cases = CaseService()
        self._validation: Validation | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        heading = QLabel(labels["verify_heading"])
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        intro = QLabel(labels["verify_intro"])
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        outer.addWidget(intro)

        row = QHBoxLayout()
        self._verdict = QLabel()
        self._verdict.setWordWrap(True)
        self._verdict.setProperty("role", "heading")
        row.addWidget(self._verdict, stretch=1)

        self._again = QPushButton(labels["verify_now"])
        self._again.clicked.connect(self.run_check)
        row.addWidget(self._again)
        outer.addLayout(row)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        outer.addWidget(self._summary)

        self._table = QTreeWidget()
        self._table.setColumnCount(4)
        self._table.setHeaderLabels(
            [
                labels["col_severity"],
                labels["col_where"],
                labels["col_problem"],
                labels["col_code"],
            ]
        )
        self._table.setRootIsDecorated(False)
        self._table.setAccessibleName(labels["verify_heading"])
        self._table.itemDoubleClicked.connect(self._on_open)
        outer.addWidget(self._table, stretch=1)

        # Always present, never a tooltip: what a clean check does not prove is
        # as important as what it does.
        self._caveat = QLabel(labels["verify_clean_caveat"])
        self._caveat.setWordWrap(True)
        self._caveat.setProperty("role", "muted")
        outer.addWidget(self._caveat)

        self.set_case(None)

    # -- content -----------------------------------------------------------

    def set_case(self, case: Path | None) -> None:
        self._case = case
        self.run_check()

    def run_check(self) -> None:
        """Re-read the case from disk and re-validate it.

        Re-read rather than cached: the point of a check is to describe the case
        as it is now, and a user who has just edited a file in another window is
        exactly who presses this.
        """
        self._table.clear()
        self._validation = None

        if self._case is None:
            self._verdict.setText("")
            self._summary.setText(self._labels["verify_no_case"])
            self._again.setEnabled(False)
            self._caveat.hide()
            return

        self._again.setEnabled(True)
        self._caveat.show()

        try:
            case = self._cases.open(self._case)
        except CaseError as exc:
            self._verdict.setText(self._labels["verify_not_ready"])
            self._summary.setText(str(exc))
            return

        self._validation = validate_case(case)
        self._populate(self._validation)

    def _populate(self, validation: Validation) -> None:
        for finding in validation.findings:
            where = str(finding.file)
            if finding.line:
                where = self._labels["at_line"].format(where, finding.line)
            item = QTreeWidgetItem(
                [
                    self._labels[_SEVERITY_KEYS[finding.severity]],
                    where,
                    finding.detail or finding.code.condition,
                    finding.code.id,
                ]
            )
            item.setData(0, _FILE_ROLE, str(finding.file))
            self._table.addTopLevelItem(item)

        for column in range(4):
            self._table.resizeColumnToContents(column)

        blocking = len(validation.blocking)
        warnings = len(validation.findings) - blocking

        self._verdict.setText(
            self._labels["verify_ready"]
            if validation.is_runnable
            else self._labels["verify_not_ready"]
        )

        parts: list[str] = []
        if blocking:
            parts.append(self._labels["verify_blocked"].format(blocking))
        if warnings:
            parts.append(self._labels["verify_warnings"].format(warnings))
        self._summary.setText(" ".join(parts) if parts else self._labels["verify_clean"])

    def _on_open(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, _FILE_ROLE)
        if path:
            self.file_requested.emit(Path(path))

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette

    # -- inspection --------------------------------------------------------

    @property
    def validation(self) -> Validation | None:
        return self._validation

    @property
    def verdict_text(self) -> str:
        return self._verdict.text()

    @property
    def summary_text(self) -> str:
        return self._summary.text()

    @property
    def finding_count(self) -> int:
        return self._table.topLevelItemCount()

    @property
    def is_runnable(self) -> bool:
        return self._validation is not None and self._validation.is_runnable

    @property
    def shows_caveat(self) -> bool:
        return self._caveat.isVisibleTo(self)

    def severity_of(self, row: int) -> str:
        item = self._table.topLevelItem(row)
        return item.text(0) if item is not None else ""
