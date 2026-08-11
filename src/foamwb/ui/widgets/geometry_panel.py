"""Importing and listing a case's surfaces (FR-P3, §7.4).

The panel is deliberately plain: a list of what is in ``constant/triSurface``,
a button that puts something there, and the facts about each surface that decide
whether the mesh will work.

**Every surface states its size.** No geometry format records its units, so a
model exported in millimetres is indistinguishable from one in metres until the
mesh comes out a thousand times too big. Nothing can detect that — but a user who
sees ``4200 x 1800 x 1400`` next to a car knows immediately, and one who sees
``4.2 x 1.8 x 1.4`` knows it is right. Reporting the bounding box is the whole
mitigation, and it costs a line.

**Region names are shown because refinement is per region.** A single STL holding
``body``, ``inlet`` and ``outlet`` can be refined three different ways, and a
user who cannot see the names cannot ask for it.

**Conversion happens on the GUI thread, and that is a compromise.** A large STEP
file takes minutes, and the window is unresponsive for that time — which is why
the status line says so before it starts. Moving it to a worker is the right
answer and is what :mod:`foamwb.ui.run_worker` exists for; it is not done here
because the converter is a single blocking call with no output to stream, so the
worker would buy responsiveness and nothing else. That trade is recorded rather
than hidden.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.cad import CadConverter
from foamwb.services.geometry import (
    GeometryError,
    Surface,
    existing_surfaces,
    import_geometry,
)
from foamwb.ui.theme import Palette

__all__ = ["GeometryPanel"]

_log = get_logger("ui.geometry")

#: Decimal places used when reporting a bounding box.
#:
#: Three, because the question the number answers is "are these millimetres or
#: metres?", and that is visible in the magnitude rather than the precision.
_PLACES = 3


class GeometryPanel(QWidget):
    """Lists the case's surfaces and imports new ones."""

    geometry_changed = Signal()
    """A surface was added or removed, so the mesh settings are now stale."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        converter: CadConverter | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._case: Path | None = None
        self._converter = converter or CadConverter()
        self._surfaces: list[Surface] = []

        # Injectable for the same reason the shell's dialogs are: a modal file
        # dialog blocks its thread until a human answers, so a test that reached
        # one would hang rather than fail.
        self._choose_file = self._ask_for_file

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        heading = QLabel(labels["geometry_heading"])
        heading.setProperty("role", "subheading")
        column.addWidget(heading)

        intro = QLabel(labels["geometry_intro"])
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        column.addWidget(intro)

        self._list = QListWidget()
        self._list.setAccessibleName(labels["geometry_heading"])
        self._list.setWordWrap(True)
        # Word wrap only takes effect once the list stops offering to scroll
        # sideways instead; without this a surface's size line is cut off.
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentItemChanged.connect(self._update_buttons)
        column.addWidget(self._list, stretch=1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        column.addWidget(self._status)

        buttons = QHBoxLayout()
        self._import_button = QPushButton(labels["geometry_import"])
        self._import_button.clicked.connect(self.import_dialog)
        buttons.addWidget(self._import_button)

        self._remove_button = QPushButton(labels["geometry_remove"])
        self._remove_button.clicked.connect(self.remove_selected)
        buttons.addWidget(self._remove_button)
        buttons.addStretch(1)
        column.addLayout(buttons)

        self._converter_note = QLabel()
        self._converter_note.setProperty("role", "muted")
        self._converter_note.setWordWrap(True)
        column.addWidget(self._converter_note)

        self._describe_converter()
        self.set_case(None)

    # -- content -----------------------------------------------------------

    def set_case(self, case: Path | None) -> None:
        """Point the panel at a case, or at none."""
        self._case = case
        self.refresh()

    def refresh(self) -> None:
        """Re-read ``constant/triSurface``."""
        self._list.clear()
        self._surfaces = [] if self._case is None else existing_surfaces(self._case)

        for surface in self._surfaces:
            item = QListWidgetItem(self._describe(surface))
            item.setData(Qt.ItemDataRole.UserRole, surface)
            item.setToolTip(str(surface.path))
            self._list.addItem(item)

        # An empty list widget is a bordered void; the hint says what to do with
        # it instead.
        empty = not self._surfaces
        self._list.setVisible(not empty)
        if empty and self._case is not None:
            self._status.setText(self._labels["geometry_none"])
        self._import_button.setEnabled(self._case is not None)
        self._update_buttons()

    def _describe(self, surface: Surface) -> str:
        """One surface, as the facts that decide whether it will mesh."""
        if surface.triangles == 0:
            return self._labels["geometry_unreadable_row"].format(surface.name)

        if surface.triangles == 1:
            lines = [self._labels["geometry_summary_one"].format(surface.name)]
        else:
            lines = [self._labels["geometry_summary"].format(surface.name, surface.triangles)]
        if (size := surface.size) is not None:
            lines.append(
                self._labels["geometry_bounds"].format(*(_number(value) for value in size))
            )
        if surface.solids:
            lines.append(self._labels["geometry_regions"].format(", ".join(surface.solids)))
        return "\n".join(lines)

    def _describe_converter(self) -> None:
        """Say whether STEP and IGES can be handled, before the user tries one."""
        tool = self._converter.locate()
        self._converter_note.setText(
            self._labels["geometry_converter"].format(tool.label)
            if tool is not None
            else self._labels["geometry_converter_none"]
        )

    def _update_buttons(self, *_args) -> None:
        self._remove_button.setEnabled(self._list.currentItem() is not None)

    # -- importing ---------------------------------------------------------

    def set_dialogs(self, *, choose_file=None) -> None:
        """Replace the file dialog, for tests and scripted runs."""
        if choose_file is not None:
            self._choose_file = choose_file

    def _ask_for_file(self, title: str, filters: str) -> Path | None:
        from PySide6.QtWidgets import QFileDialog

        chosen, _selected = QFileDialog.getOpenFileName(self, title, "", filters)
        return Path(chosen) if chosen else None

    def import_dialog(self) -> None:
        """Ask for a file and import it. Cancelling changes nothing."""
        if self._case is None:
            return
        chosen = self._choose_file(self._labels["geometry_choose"], self._labels["geometry_filter"])
        if chosen is not None:
            self.import_file(chosen)

    def import_file(self, source: Path) -> bool:
        """Import one file, reporting the outcome either way."""
        if self._case is None:
            return False

        from foamwb.services.cad import needs_conversion

        if needs_conversion(source):
            # Said before the window stops responding, not after.
            self._status.setText(self._labels["geometry_converting"].format(source.name))
            self._status.repaint()

        try:
            surface = import_geometry(self._case, source, converter=self._converter)
        except GeometryError as exc:
            # The code travels with the message: E-C10, E-C11 and E-C12 call for
            # three different responses, and "import failed" tells the user none
            # of them.
            self._status.setText(self._labels["geometry_failed"].format(exc.message, exc.code.id))
            self._status.setStyleSheet(f"color: {self._palette.broken};")
            log_event(_log, Event.ERROR_RAISED, where="geometry.import", error=exc.code.id)
            return False

        self._status.setStyleSheet(f"color: {self._palette.ready};")
        self._status.setText(self._labels["geometry_imported"].format(surface.name))
        self.refresh()
        self.geometry_changed.emit()
        return True

    def remove_selected(self) -> bool:
        """Delete the selected surface from the case."""
        item = self._list.currentItem()
        if item is None:
            return False
        surface: Surface = item.data(Qt.ItemDataRole.UserRole)
        try:
            surface.path.unlink()
        except OSError:
            return False

        log_event(_log, Event.CASE_WRITE, case=str(self._case), action="remove_geometry")
        self._status.setStyleSheet(f"color: {self._palette.text_muted};")
        self._status.setText(self._labels["geometry_removed"].format(surface.name))
        self.refresh()
        self.geometry_changed.emit()
        return True

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette (NFR-A4).

        The status line is the only thing here carrying an inline colour, and it
        is cleared rather than recoloured: it reports the *last* import, and by
        the time the theme changes that message is stale anyway.
        """
        self._palette = palette
        self._status.setStyleSheet("")

    # -- for tests ---------------------------------------------------------

    @property
    def surfaces(self) -> list[Surface]:
        return list(self._surfaces)

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def converter_text(self) -> str:
        return self._converter_note.text()

    @property
    def can_import(self) -> bool:
        return self._import_button.isEnabled()

    def select(self, index: int) -> None:
        self._list.setCurrentRow(index)


def _number(value: float) -> str:
    """A dimension, without trailing zeros that suggest false precision."""
    return f"{value:.{_PLACES}f}".rstrip("0").rstrip(".") or "0"
