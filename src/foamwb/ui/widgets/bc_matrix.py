"""The boundary-condition matrix (FR-P4, §7.4).

Rows are patches from ``constant/polyMesh/boundary`` with their type; columns are
the fields in ``0/``; each cell shows the condition in force. **Empty cells are
errors**, and the grid is what makes that visible — §1.2 names patch/field
mismatches the most common beginner failure precisely because a per-file editor
hides them: nothing in ``0/p`` tells you a patch is missing from it.

Bulk actions exist "because that is what the work actually is" (§7.4). Setting
``noSlip`` on every wall is one intent, and making the user perform it once per
patch invites exactly the inconsistency the matrix is here to catch.

Cells that a regex supplied are marked. A value arriving through ``".*"`` is a
different fact from one written for the patch, and it is the first thing to look
at when a patch behaves unexpectedly.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.boundary import PatchType
from foamwb.services.boundary_matrix import BoundaryMatrix
from foamwb.ui.theme import Palette

__all__ = ["BoundaryMatrixView"]

#: Conditions offered by the bulk action, by patch type. Deliberately short: the
#: common, correct choices for that geometry, not a catalogue. Anything else is
#: reachable in the field's own editor, and a list of forty entries would make
#: the frequent choice harder to find.
_SUGGESTED: dict[str, tuple[str, ...]] = {
    PatchType.WALL: ("noSlip", "fixedValue", "zeroGradient", "kqRWallFunction"),
    PatchType.PATCH: (
        "fixedValue",
        "zeroGradient",
        "inletOutlet",
        "totalPressure",
        "pressureInletOutletVelocity",
    ),
}


class BoundaryMatrixView(QWidget):
    """Patch x field grid with per-type bulk actions."""

    apply_requested = Signal(str, str, str)
    """``(patch_type, field, condition)`` — a bulk action the caller performs.

    The widget requests rather than writes: dictionaries are the service layer's
    to change, and a widget that edited files directly could not be tested
    without one.
    """

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._matrix: BoundaryMatrix | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._notice = QLabel()
        self._notice.setProperty("role", "muted")
        self._notice.setWordWrap(True)
        layout.addWidget(self._notice)

        self._table = QTableWidget()
        self._table.setAccessibleName(labels["bc_matrix"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, stretch=1)
        layout.addWidget(self._build_bulk_row(labels))

        self.set_matrix(BoundaryMatrix())

    def _build_bulk_row(self, labels: dict[str, str]) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)

        line.addWidget(QLabel(labels["apply_to_all"]))
        self._type_box = QComboBox()
        self._type_box.currentTextChanged.connect(self._refresh_suggestions)
        line.addWidget(self._type_box)

        line.addWidget(QLabel(labels["for_field"]))
        self._field_box = QComboBox()
        line.addWidget(self._field_box)

        self._condition_box = QComboBox()
        self._condition_box.setEditable(True)
        # Editable so a condition outside the suggestions is still reachable —
        # the list is a shortcut, never a restriction on what OpenFOAM accepts.
        line.addWidget(self._condition_box, stretch=1)

        self._apply_button = QPushButton(labels["apply"])
        self._apply_button.clicked.connect(self._on_apply)
        line.addWidget(self._apply_button)

        self._bulk_row = row
        return row

    # -- content -----------------------------------------------------------

    def set_matrix(self, matrix: BoundaryMatrix) -> None:
        self._matrix = matrix

        if not matrix.is_meshed:
            # An unmeshed case is the ordinary state of a fresh import. Saying
            # what to do beats an empty grid or an error the user cannot act on.
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._notice.setText(self._labels["mesh_needed"])
            self._bulk_row.setVisible(False)
            return

        self._bulk_row.setVisible(True)
        self._table.setRowCount(len(matrix.patches))
        self._table.setColumnCount(len(matrix.fields))
        self._table.setHorizontalHeaderLabels(matrix.fields)
        self._table.setVerticalHeaderLabels(
            [self._labels["patch_header"].format(p.name, p.type) for p in matrix.patches]
        )

        missing = 0
        for row, patch in enumerate(matrix.patches):
            for column, field in enumerate(matrix.fields):
                cell = matrix.cell(patch.name, field)
                item = QTableWidgetItem()
                if cell is None or cell.is_missing:
                    missing += 1
                    item.setText(self._labels["cell_missing"])
                    item.setForeground(_colour(self._palette.broken))
                    item.setToolTip(self._labels["cell_missing_tip"].format(patch.name, field))
                else:
                    item.setText(cell.condition)
                    if cell.is_default:
                        item.setForeground(_colour(self._palette.text_muted))
                        item.setToolTip(self._labels["cell_default_tip"].format(cell.matched_by))
                # The accessible name carries the whole fact, so a screen reader
                # is not left to infer it from a grid position.
                item.setData(
                    Qt.ItemDataRole.AccessibleTextRole,
                    self._labels["cell_accessible"].format(patch.name, field, item.text()),
                )
                self._table.setItem(row, column, item)

        self._notice.setText(
            self._labels["matrix_summary"].format(len(matrix.patches), len(matrix.fields), missing)
        )
        self._notice.setStyleSheet(
            f"color: {self._palette.broken if missing else self._palette.text_muted};"
        )

        self._type_box.clear()
        self._type_box.addItems(sorted({p.type for p in matrix.patches}))
        self._field_box.clear()
        self._field_box.addItems(matrix.fields)
        self._refresh_suggestions()

    def _refresh_suggestions(self) -> None:
        self._condition_box.clear()
        self._condition_box.addItems(_SUGGESTED.get(self._type_box.currentText(), ()))

    def _on_apply(self) -> None:
        if self._matrix is None or not self._matrix.is_meshed:
            return
        condition = self._condition_box.currentText().strip()
        if not condition:
            return
        self.apply_requested.emit(
            self._type_box.currentText(), self._field_box.currentText(), condition
        )

    # -- for tests ---------------------------------------------------------

    @property
    def row_count(self) -> int:
        return self._table.rowCount()

    @property
    def column_count(self) -> int:
        return self._table.columnCount()

    def cell_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return item.text() if item is not None else ""

    @property
    def notice_text(self) -> str:
        return self._notice.text()

    @property
    def bulk_visible(self) -> bool:
        return self._bulk_row.isVisibleTo(self)

    def request_bulk(self, patch_type: str, field: str, condition: str) -> None:
        self._type_box.setCurrentText(patch_type)
        self._field_box.setCurrentText(field)
        self._condition_box.setCurrentText(condition)
        self._on_apply()


def _colour(value: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(value))
