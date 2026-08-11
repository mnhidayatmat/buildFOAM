"""The property panel — scFLOW's Parameter / Value / Unit table (§7.4).

The shape is borrowed deliberately. A three-column table of parameter, value and
unit is how every CFD pre-processor presents a settings page, and it happens to
be an almost exact match for what an OpenFOAM dictionary *is*: a ``controlDict``
is a list of keywords with values, some of which carry dimensions.

Three things it does that a plain form does not.

**Units are their own column.** In OpenFOAM a dimension is part of the value's
meaning and users get it wrong constantly — ``nu`` is kinematic, not dynamic, and
a wrong assumption there is a run that converges to the wrong answer. A column
that is always present makes the omission of a unit visible rather than implied.

**It names the file each group came from.** §5.1's principle is that the user's
case stays theirs and legible; a panel that showed "End time" without ever saying
``system/controlDict`` would teach the interface instead of teaching OpenFOAM,
and D4 is explicit that the tool should leave the user more able, not less.

**Nesting is shown by indentation, and it is real.** A row's depth is its depth in
the dictionary, so ``ddtSchemes/default`` sits under ``ddtSchemes``. The path is
what the editor writes back, so what the user sees and what is saved cannot
diverge.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.properties import PropertyGroup, PropertyRow
from foamwb.ui.theme import Palette

#: Re-exported so a caller needs one import, while the definitions stay in
#: the service layer where they can be built and tested without Qt.
__all__ = ["PropertyGroup", "PropertyPanel", "PropertyRow"]

_PATH_ROLE = Qt.ItemDataRole.UserRole


class PropertyPanel(QWidget):
    """A read-oriented view of a dictionary's settings, with units."""

    value_edited = Signal(str, str)
    """``(path, new value)``. The panel never writes; the owner does."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._groups: tuple[PropertyGroup, ...] = ()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        heading = QLabel(labels["properties"])
        heading.setProperty("role", "panelTitle")
        heading.setContentsMargins(10, 6, 10, 6)
        outer.addWidget(heading)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(
            [
                labels["column_parameter"],
                labels["column_value"],
                labels["column_unit"],
            ]
        )
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(14)
        self._tree.setAlternatingRowColors(True)
        self._tree.setAccessibleName(labels["properties"])
        self._tree.currentItemChanged.connect(self._on_current)
        self._tree.itemChanged.connect(self._on_edited)
        outer.addWidget(self._tree, stretch=1)

        # scFLOW puts a description box under its table; the same idea, because
        # a parameter name alone is not an explanation and hover text is not
        # reachable from a keyboard.
        self._description = QLabel()
        self._description.setWordWrap(True)
        self._description.setProperty("role", "muted")
        self._description.setContentsMargins(10, 6, 10, 8)
        self._description.setMinimumHeight(48)
        self._description.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(self._description)

        self.clear()
        self.set_palette(palette)

    # -- content -----------------------------------------------------------

    def set_groups(self, groups: tuple[PropertyGroup, ...]) -> None:
        """Replace the contents. Editing is suppressed while rebuilding."""
        self._groups = groups
        self._tree.blockSignals(True)
        self._tree.clear()

        for group in groups:
            header = QTreeWidgetItem([group.title, "", ""])
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            header.setFirstColumnSpanned(True)
            if group.source:
                header.setToolTip(0, self._labels["property_source"].format(group.source))
                header.setText(0, self._labels["group_row"].format(group.title, group.source))
            self._tree.addTopLevelItem(header)

            for row in group.rows:
                item = QTreeWidgetItem(["    " * row.depth + row.label, row.value, row.unit])
                item.setData(0, _PATH_ROLE, row.path)
                item.setToolTip(0, row.description)
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                if row.editable:
                    flags |= Qt.ItemFlag.ItemIsEditable
                item.setFlags(flags)
                if row.unknown:
                    item.setForeground(0, self._tree.palette().brush(self._tree.foregroundRole()))
                self._tree.addTopLevelItem(item)

        self._tree.blockSignals(False)
        for column in range(3):
            self._tree.resizeColumnToContents(column)

        self._description.setText("" if groups else self._labels["no_properties"])

    def clear(self) -> None:
        self.set_groups(())

    # -- interaction -------------------------------------------------------

    def _on_current(self, item: QTreeWidgetItem | None, _previous) -> None:
        if item is None:
            self._description.setText("")
            return
        path = item.data(0, _PATH_ROLE)
        row = self._row_for(path)
        self._description.setText(row.description if row is not None else "")

    def _on_edited(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 1:
            return
        path = item.data(0, _PATH_ROLE)
        if path:
            self.value_edited.emit(path, item.text(1))

    def _row_for(self, path: str) -> PropertyRow | None:
        for group in self._groups:
            for row in group.rows:
                if row.path == path:
                    return row
        return None

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.setStyleSheet(
            f"QTreeWidget {{ background: {palette.bg}; color: {palette.text};"
            f" border: 1px solid {palette.border}; }}"
            f"QHeaderView::section {{ background: {palette.surface};"
            f" color: {palette.text}; padding: 4px; border: none;"
            f" border-bottom: 1px solid {palette.border}; }}"
        )

    # -- inspection --------------------------------------------------------

    @property
    def groups(self) -> tuple[PropertyGroup, ...]:
        return self._groups

    @property
    def row_count(self) -> int:
        return sum(len(group.rows) for group in self._groups)

    @property
    def column_titles(self) -> list[str]:
        header = self._tree.headerItem()
        return [header.text(i) for i in range(self._tree.columnCount())]

    @property
    def description_text(self) -> str:
        return self._description.text()

    def value_of(self, path: str) -> str:
        row = self._row_for(path)
        return row.value if row is not None else ""

    def select(self, path: str) -> None:
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item.data(0, _PATH_ROLE) == path:
                self._tree.setCurrentItem(item)
                return
