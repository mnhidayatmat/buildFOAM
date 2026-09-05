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
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
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
from foamwb.services.snappy import (
    FlowRegion,
    MeshPlan,
    MeshSettings,
    SnappyError,
    plan_mesh,
    write_dictionaries,
)
from foamwb.services.surface_regions import (
    FaceAssignment,
    clean_region_name,
    write_named_surface,
)
from foamwb.ui.theme import Palette
from foamwb.ui.widgets.surface_preview import SurfacePreview

__all__ = ["GeometryPanel"]

_log = get_logger("ui.geometry")

#: How tall the surface list may grow, in pixels. Three rows of three lines —
#: name, size and regions — which is more surfaces than a case usually has.
_LIST_HEIGHT = 170

#: How tall the named-region list may grow. Four rows: enough for the inlet,
#: outlet, walls and one more that most cases come down to, without the list
#: pushing the meshing controls off the page.
_REGION_LIST_HEIGHT = 110

#: Decimal places used when reporting a bounding box.
#:
#: Three, because the question the number answers is "are these millimetres or
#: metres?", and that is visible in the magnitude rather than the precision.
_PLACES = 3

#: How wide a value control in the mesh section may get, in pixels. Matches the
#: form editor, so the two read as the same application.
_CONTROL_WIDTH = 260


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
        preview: SurfacePreview | None = None,
        embed_sizing: bool = True,
    ) -> None:
        """``preview`` and ``embed_sizing`` place the two halves this panel is
        made of.

        In the Fluent-shaped shell the picture belongs in the graphics window
        and the sizing form belongs to its own outline node, so the shell passes
        a preview it owns and takes :attr:`sizing_section` away to a page of its
        own. Both default to the self-contained arrangement, because the panel
        is also constructed on its own in tests and there it has to be whole.
        """
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._case: Path | None = None
        self._converter = converter or CadConverter()
        self._surfaces: list[Surface] = []
        #: Face names per surface, keyed by path. Kept while the panel lives
        #: so switching between two imports and back does not lose the work,
        #: and cleared whenever the surface list is re-read, because a face id
        #: only means anything for the file it was computed from.
        self._assignments: dict[Path, FaceAssignment] = {}

        # Injectable for the same reason the shell's dialogs are: a modal file
        # dialog blocks its thread until a human answers, so a test that reached
        # one would hang rather than fail.
        self._choose_file = self._ask_for_file
        self._confirm = self._ask_to_confirm
        self._plan: MeshPlan | None = None
        #: Whether this panel draws the preview itself. When the shell owns it,
        #: the panel must not hide it — the graphics window is showing it to
        #: someone, and a tab that empties because a list is empty reads as a
        #: view that failed to load.
        self._owns_preview = preview is None

        # Scrolled, because this page is a form read top to bottom and the
        # preview gave it more height than a short window has. Without this Qt
        # shares the shortfall out among the children, and the meshing controls
        # at the foot collapse into each other rather than moving below the fold.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)

        column = QVBoxLayout(body)
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
        # Sized to its contents rather than stretched: inside a scrolling column
        # nothing should claim spare height, and a case has two or three
        # surfaces, not twenty. Left stretching, the list opened as a mostly
        # empty box with the preview pushed under the fold beneath it.
        self._list.setMaximumHeight(_LIST_HEIGHT)
        column.addWidget(self._list)

        # Under the list rather than beside it, so the page still reads top to
        # bottom: what is in the case, then what it looks like, then what to do
        # about it. When the shell supplies one, it is in the graphics window
        # instead and this column carries only the controls.
        self._preview = preview or SurfacePreview(self._palette, labels)
        self._preview.selection_changed.connect(self._on_faces_selected)
        if self._owns_preview:
            column.addWidget(self._preview)

        column.addWidget(self._build_naming(labels))

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

        sizing = self._build_mesh_section(labels)
        if embed_sizing:
            column.addWidget(sizing)
        else:
            # Reparented by the shell onto its own page. Kept off this layout
            # rather than merely hidden, so it cannot be shown in two places.
            sizing.setParent(None)
        # Takes the spare height so the form stays at the top of a tall window
        # rather than being spread down it.
        column.addStretch(1)

        self._describe_converter()
        self.set_case(None)

    def _build_naming(self, labels: dict[str, str]) -> QWidget:
        """Name the faces picked in the view above (FR-P3).

        Directly under the picture, because the selection *is* the subject of
        this control and a name field anywhere else would be a form about
        something off screen. The list of regions below it is the record: colour
        says which face on the model, the list says what they are called, and
        neither is the only statement of it (NFR-A2).
        """
        section = QWidget()
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 4, 0, 0)
        column.setSpacing(6)

        self._naming_hint = QLabel()
        self._naming_hint.setProperty("role", "muted")
        self._naming_hint.setWordWrap(True)
        column.addWidget(self._naming_hint)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._region_name = QLineEdit()
        self._region_name.setPlaceholderText(labels["region_name_placeholder"])
        self._region_name.setAccessibleName(labels["region_name_label"])
        self._region_name.returnPressed.connect(self.name_selection)
        self._region_name.textChanged.connect(self._update_naming)
        row.addWidget(self._region_name, stretch=1)

        self._name_button = QPushButton(labels["region_name_apply"])
        self._name_button.clicked.connect(self.name_selection)
        row.addWidget(self._name_button)
        column.addLayout(row)

        self._regions_list = QListWidget()
        self._regions_list.setAccessibleName(labels["region_list"])
        self._regions_list.setMaximumHeight(_REGION_LIST_HEIGHT)
        self._regions_list.currentItemChanged.connect(self._on_region_row)
        column.addWidget(self._regions_list)

        self._naming_section = section
        return section

    def _build_mesh_section(self, labels: dict[str, str]) -> QWidget:
        """The mesh built *from* the geometry, beside the geometry itself.

        Here rather than in the Mesh tab because that tab runs utilities, and
        until these dictionaries exist it has none to offer — which is the dead
        end this closes. The decisions are also all about the surface just
        imported, so they belong next to it.
        """
        section = QWidget()
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(6)

        heading = QLabel(labels["mesh_from_geometry"])
        heading.setProperty("role", "subheading")
        column.addWidget(heading)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._region = QComboBox()
        # The value carried, not the label, so the answer survives translation.
        self._region.addItem(labels["flow_external"], FlowRegion.EXTERNAL)
        self._region.addItem(labels["flow_internal"], FlowRegion.INTERNAL)
        self._region.setAccessibleName(labels["flow_region"])
        self._region.currentIndexChanged.connect(self._replan)
        self._region.setMaximumWidth(_CONTROL_WIDTH)
        form.addRow(labels["flow_region"], self._region)

        region_help = QLabel(labels["flow_region_help"])
        region_help.setProperty("role", "muted")
        region_help.setWordWrap(True)
        column.addLayout(form)
        column.addWidget(region_help)

        levels = QFormLayout()
        levels.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        levels.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        refinement = QHBoxLayout()
        self._refine_min = _spin(0, 6, 2, labels["refinement_levels"])
        self._refine_max = _spin(0, 8, 3, labels["refinement_levels"])
        for box in (self._refine_min, self._refine_max):
            box.valueChanged.connect(self._replan)
            refinement.addWidget(box)
        refinement.addStretch(1)
        levels.addRow(labels["refinement_levels"], refinement)

        self._cells = _spin(4, 400, 40, labels["background_cells"])
        self._cells.valueChanged.connect(self._replan)
        levels.addRow(labels["background_cells"], self._cells)
        column.addLayout(levels)

        self._domain = QLabel()
        self._domain.setProperty("role", "muted")
        self._domain.setWordWrap(True)
        column.addWidget(self._domain)

        self._generate_button = QPushButton(labels["generate_mesh_dicts"])
        self._generate_button.clicked.connect(self.generate_dictionaries)
        column.addWidget(self._generate_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self._mesh_section = section
        return section

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
        if self._owns_preview:
            self._preview.setVisible(not empty)
        # Select something, so the preview has a subject: a list where nothing
        # is current shows a blank frame beside a case that plainly has geometry
        # in it.
        if not empty and self._list.currentItem() is None:
            self._list.setCurrentRow(0)
        if empty and self._case is not None:
            self._status.setText(self._labels["geometry_none"])
        self._import_button.setEnabled(self._case is not None)
        self._update_buttons()
        self._update_naming()
        # The domain follows the geometry, so it is re-derived whenever the
        # surfaces change rather than only when a control is touched.
        self._replan()

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
        item = self._list.currentItem()
        self._remove_button.setEnabled(item is not None)

        # The preview follows the selection, so a case with several surfaces
        # shows the one the user is pointing at rather than an arbitrary one.
        surface = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if surface is None:
            self._preview.clear()
        elif self._preview.showing != surface.path.name:
            self._preview.set_surface(surface.path, surface.path.name)
        self._update_naming()

    def _set_status(self, text: str, token: str) -> None:
        """Say something, in the palette colour named by ``token``.

        The status line was previously only ever written to plainly, so a
        failure and a success looked the same. Naming carries both outcomes
        often enough — an invalid name, a surface too large to group — that
        the difference has to be visible without reading the sentence.
        """
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {getattr(self._palette, token)};")

    # -- naming faces ------------------------------------------------------

    def _assignment_for(self, surface: Surface | None) -> FaceAssignment | None:
        """The names given to this surface's faces, kept for as long as it is.

        Held per surface path rather than one at a time, so switching between two
        imports and back does not lose the work — and dropped when the surface
        list is re-read, because face ids only mean anything for the file they
        were computed from.
        """
        if surface is None:
            return None
        return self._assignments.setdefault(surface.path, FaceAssignment(surface=surface.path))

    def _on_faces_selected(self) -> None:
        self._update_naming()

    def _on_region_row(self, *_args) -> None:
        """Selecting a region in the list lights its faces on the model.

        The list and the picture are two views of one thing, so pointing at a
        name has to answer "which face is that?" — otherwise a user who named
        six faces an hour ago has no way to check they named the right ones.
        """
        item = self._regions_list.currentItem()
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        assignment = self._assignment_for(self._current_surface())
        if assignment is None or not name:
            return
        faces = [face for face, given in assignment.names.items() if given == name]
        if faces and tuple(sorted(faces)) != self._preview.selected:
            self._preview.select(faces)

    def name_selection(self) -> bool:
        """Give the picked faces the typed name, and write the named surface."""
        surface = self._current_surface()
        assignment = self._assignment_for(surface)
        selected = self._preview.selected
        if assignment is None or not selected:
            return False

        typed = self._region_name.text().strip()
        name = clean_region_name(typed)
        if not name:
            self._set_status(self._labels["region_name_invalid"], "degraded")
            return False

        assignment.assign(selected, name)
        try:
            written = write_named_surface(assignment.surface, assignment)
        except GeometryError as exc:
            self._set_status(str(exc), "broken")
            return False

        self._region_name.clear()
        self._preview.clear_selection()
        self._update_naming()
        # The named file is what snappyHexMesh must read, so the plan is redone
        # against it rather than left pointing at the unnamed original.
        self._replan()
        self._set_status(
            self._labels["region_named"].format(name, len(selected), written.name), "ready"
        )
        if name != typed:
            # Said, not hidden: a user who typed "front face" and got front_face
            # would otherwise go looking for a patch under the name they chose.
            self._set_status(self._labels["region_name_cleaned"].format(typed, name), "degraded")
        self.geometry_changed.emit()
        return True

    def _update_naming(self, *_args) -> None:
        """Re-read the naming controls from the selection and the assignment."""
        surface = self._current_surface()
        assignment = self._assignment_for(surface)
        selected = self._preview.selected

        known = self._preview.faces_known
        self._naming_section.setVisible(surface is not None and self._preview.isVisibleTo(self))
        self._name_button.setEnabled(
            bool(selected) and bool(clean_region_name(self._region_name.text()))
        )
        self._region_name.setEnabled(known)

        if not known:
            self._naming_hint.setText(self._labels["region_too_large"])
        elif selected:
            self._naming_hint.setText(
                self._labels["region_selected"].format(len(selected), self._preview.face_count)
            )
        else:
            self._naming_hint.setText(self._labels["region_pick"].format(self._preview.face_count))

        self._regions_list.clear()
        if assignment is not None:
            for name in assignment.regions:
                count = sum(1 for given in assignment.names.values() if given == name)
                item = QListWidgetItem(self._labels["region_row"].format(name, count))
                item.setData(Qt.ItemDataRole.UserRole, name)
                self._regions_list.addItem(item)
        self._regions_list.setVisible(self._regions_list.count() > 0)

        self._preview.set_region_names(
            dict(assignment.names) if assignment else {},
            self._region_colours(assignment),
        )

    def _region_colours(self, assignment: FaceAssignment | None) -> dict[str, str]:
        """A colour per region, taken from the palette.

        The same series the residual plot uses, for the same reason it takes them
        from the palette rather than from a list of its own: a second set of
        colours is a second thing to keep in contrast with two themes. Regions
        past the end of the series repeat a colour, and the named list beside the
        model is what tells those apart — colour was never carrying it alone
        (NFR-A2).
        """
        if assignment is None:
            return {}
        series = (
            self._palette.accent,
            self._palette.ready,
            self._palette.degraded,
            self._palette.broken,
            self._palette.missing,
        )
        return {name: series[index % len(series)] for index, name in enumerate(assignment.regions)}

    def _current_surface(self) -> Surface | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    # -- meshing -----------------------------------------------------------

    def settings(self) -> MeshSettings:
        """What the controls currently say."""
        return MeshSettings(
            region=self._region.currentData(),
            refinement_min=self._refine_min.value(),
            refinement_max=self._refine_max.value(),
            background_cells=self._cells.value(),
        )

    def _replan(self, *_args) -> None:
        """Re-derive the domain and say what it would cost.

        Run on every change rather than only when Generate is pressed, so the
        cell count — the number that decides whether meshing takes a minute or an
        hour — moves while the user is choosing, not after.
        """
        self._plan = None
        if self._case is None:
            self._domain.clear()
            self._generate_button.setEnabled(False)
            return

        try:
            self._plan = plan_mesh(self._case, self.settings())
        except SnappyError:
            # No geometry yet is the ordinary state of a new case, and the
            # surfaces list above already says so.
            self._domain.clear()
            self._generate_button.setEnabled(False)
            return

        size = (self._plan.high[axis] - self._plan.low[axis] for axis in range(3))
        self._domain.setText(
            self._labels["domain_summary"].format(
                *(_number(value) for value in size),
                self._plan.background_cell_count,
            )
        )
        self._generate_button.setEnabled(True)
        # The button states the consequence: replacing is not the same act as
        # generating, and the label is where that difference is visible.
        replacing = bool(self._plan.existing)
        self._generate_button.setText(
            self._labels["replace_mesh_dicts"] if replacing else self._labels["generate_mesh_dicts"]
        )

    def generate_dictionaries(self) -> bool:
        """Write the background mesh and meshing dictionary (FR-P3)."""
        if self._case is None or self._plan is None:
            return False

        if self._plan.existing:
            names = ", ".join(path.name for path in self._plan.existing)
            if not self._confirm(
                self._labels["confirm_replace_title"],
                self._labels["confirm_replace_body"].format(names),
            ):
                return False

        try:
            write_dictionaries(self._case, self._plan, replace_existing=True)
        except SnappyError as exc:
            self._status.setStyleSheet(f"color: {self._palette.broken};")
            self._status.setText(self._labels["mesh_dicts_failed"].format(exc.message, exc.code.id))
            log_event(_log, Event.ERROR_RAISED, where="geometry.generate", error=exc.code.id)
            return False

        self._status.setStyleSheet(f"color: {self._palette.ready};")
        self._status.setText(self._labels["mesh_dicts_written"])
        self._replan()
        # The Mesh tab has utilities to offer now, where a moment ago it had none.
        self.geometry_changed.emit()
        return True

    # -- importing ---------------------------------------------------------

    def set_dialogs(self, *, choose_file=None, confirm=None) -> None:
        """Replace the modal dialogs, for tests and scripted runs."""
        if choose_file is not None:
            self._choose_file = choose_file
        if confirm is not None:
            self._confirm = confirm

    def _ask_to_confirm(self, title: str, body: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            title,
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            # Cancel is the default, because the destructive answer should not be
            # the one a return key reaches first.
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

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
        self._preview.set_palette(palette)
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

    @property
    def can_generate(self) -> bool:
        return self._generate_button.isEnabled()

    @property
    def generate_text(self) -> str:
        return self._generate_button.text()

    @property
    def domain_text(self) -> str:
        return self._domain.text()

    @property
    def plan(self):
        return self._plan

    @property
    def sizing_section(self) -> QWidget:
        """The mesh-from-geometry form, for a shell that pages it separately."""
        return self._mesh_section

    @property
    def preview(self) -> SurfacePreview:
        return self._preview

    @property
    def region_name_field(self):
        return self._region_name

    @property
    def naming_hint(self) -> str:
        return self._naming_hint.text()

    @property
    def region_rows(self) -> list[str]:
        return [self._regions_list.item(row).text() for row in range(self._regions_list.count())]

    def select(self, index: int) -> None:
        self._list.setCurrentRow(index)


def _number(value: float) -> str:
    """A dimension, without trailing zeros that suggest false precision."""
    return f"{value:.{_PLACES}f}".rstrip("0").rstrip(".") or "0"


def _spin(low: int, high: int, value: int, name: str) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    box.setAccessibleName(name)
    box.setMaximumWidth(_CONTROL_WIDTH)
    return box
