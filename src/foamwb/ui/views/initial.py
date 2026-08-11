"""The initial-conditions editor (FR-P3, §7.4).

A three-column table of field, starting value and units — the property panel's
shape, because that is what this is: one row per file in ``0``.

**Units are read from each file, not looked up by name.** ``p`` is m²/s² in an
incompressible case and a genuine pressure in a compressible one, so a table
keyed on field names would print a confident wrong unit for half the tutorial
suite. The exponent vector in the file is the only thing that knows.

**Non-uniform fields are shown and not offered for editing.** A
``nonuniform List<vector>`` holds one entry per cell; a text box for a million
numbers would be a worse lie than no text box. The row says where to edit it
instead.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.initial import InitialField, read_initial_fields, set_internal_field
from foamwb.ui.theme import Palette

__all__ = ["InitialConditionsView"]

_FIELD_ROLE = Qt.ItemDataRole.UserRole


class InitialConditionsView(QWidget):
    """Edits the ``internalField`` of every file in the initial-condition directory."""

    field_changed = Signal(str)

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
        self._fields: list[InitialField] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        heading = QLabel(labels["initial_heading"])
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        intro = QLabel(labels["initial_intro"])
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        outer.addWidget(intro)

        self._table = QTreeWidget()
        self._table.setColumnCount(3)
        self._table.setHeaderLabels(
            [
                labels["col_field"],
                labels["col_internal"],
                labels["col_dimensions"],
            ]
        )
        self._table.setRootIsDecorated(False)
        self._table.setAlternatingRowColors(True)
        self._table.setAccessibleName(labels["initial_heading"])
        self._table.itemChanged.connect(self._on_edited)
        self._table.currentItemChanged.connect(self._on_selected)
        outer.addWidget(self._table, stretch=1)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setProperty("role", "muted")
        outer.addWidget(self._hint)

        self._status = QLabel()
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        self.set_case(None)

    # -- content -----------------------------------------------------------

    def set_case(self, case: Path | None) -> None:
        self._case = case
        self.refresh()

    def refresh(self) -> None:
        self._table.blockSignals(True)
        self._table.clear()
        self._status.setText("")
        self._hint.setText("")

        self._fields = read_initial_fields(self._case) if self._case is not None else []
        if not self._fields:
            self._table.blockSignals(False)
            self._status.setText(self._labels["no_fields"])
            return

        for entry in self._fields:
            item = QTreeWidgetItem([entry.name, entry.value, entry.unit])
            item.setData(0, _FIELD_ROLE, entry.name)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

            if not entry.internal_field:
                item.setText(1, "")
                item.setToolTip(1, self._labels["unreadable_field"])
            elif entry.is_uniform:
                flags |= Qt.ItemFlag.ItemIsEditable
            else:
                item.setToolTip(1, self._labels["nonuniform_note"])

            item.setFlags(flags)
            item.setToolTip(0, self._labels["source_note"].format(entry.path.parent.name))
            self._table.addTopLevelItem(item)

        for column in range(3):
            self._table.resizeColumnToContents(column)
        self._table.blockSignals(False)
        self._table.setCurrentItem(self._table.topLevelItem(0))

    # -- interaction -------------------------------------------------------

    def _entry_for(self, name: str) -> InitialField | None:
        return next((f for f in self._fields if f.name == name), None)

    def _on_selected(self, item: QTreeWidgetItem | None, _previous) -> None:
        if item is None:
            self._hint.setText("")
            return
        entry = self._entry_for(item.data(0, _FIELD_ROLE))
        if entry is None:
            self._hint.setText("")
        elif not entry.internal_field:
            self._hint.setText(self._labels["unreadable_field"])
        elif not entry.is_uniform:
            self._hint.setText(self._labels["nonuniform_note"])
        else:
            self._hint.setText(
                self._labels["vector_hint"] if entry.is_vector else self._labels["scalar_hint"]
            )

    def _on_edited(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 1:
            return
        entry = self._entry_for(item.data(0, _FIELD_ROLE))
        if entry is None:
            return

        typed = item.text(1)
        changed = set_internal_field(entry, typed)

        # Re-read either way: a row that disagrees with what is on disk is the
        # one thing an editor must never display, and a rejected edit leaves the
        # table holding a value the file does not contain.
        #
        # The message is set *after* the refresh, because refresh clears it.
        # Setting it first left the confirmation invisible — the edit worked and
        # the interface said nothing, which reads as a control that does nothing.
        self.refresh()
        if changed:
            self._status.setText(self._labels["field_updated"].format(entry.name, typed))
            self.field_changed.emit(entry.name)
        else:
            self._status.setText(self._labels["field_unchanged"].format(entry.name))

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette

    # -- inspection --------------------------------------------------------

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self._fields]

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def hint_text(self) -> str:
        return self._hint.text()

    def unit_of(self, name: str) -> str:
        entry = self._entry_for(name)
        return entry.unit if entry is not None else ""

    def value_of(self, name: str) -> str:
        entry = self._entry_for(name)
        return entry.value if entry is not None else ""

    def is_editable(self, name: str) -> bool:
        for index in range(self._table.topLevelItemCount()):
            item = self._table.topLevelItem(index)
            if item.data(0, _FIELD_ROLE) == name:
                return bool(item.flags() & Qt.ItemFlag.ItemIsEditable)
        return False

    def set_value(self, name: str, value: str) -> None:
        """For tests and scripted use: edit a row as a user would."""
        for index in range(self._table.topLevelItemCount()):
            item = self._table.topLevelItem(index)
            if item.data(0, _FIELD_ROLE) == name:
                item.setText(1, value)
                return
