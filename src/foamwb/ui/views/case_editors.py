"""The case's editors, built and wired but not laid out (§7.4, DEC-21).

Everything a user can change about a case lives here: the settings table, the
file tree and its two editors, the geometry panel, the meshing utilities, the
boundary matrix and the initial conditions. What is new is that this class does
**not arrange them**. It builds them, keeps them agreeing with the case on
disk, and hands them out; the shell decides which are task pages beside the
outline and which are documents in the graphics window.

That split is the whole point of the Fluent-shaped shell. A narrow form and a
wide table want opposite amounts of room, and the previous three-region view
gave them the same room because they were tabs of one widget. Here the boundary
matrix gets the graphics window and the geometry controls get the task page,
without either of them knowing where it ended up.

Two promises the arrangement must not lose:

**The Form and Text tabs are always both there** (DEC-07). Forms serve P1 and
P2; the text tab keeps the P4 constraint that a power user is never trapped.
Round-trip fidelity (FR-P7) is what lets the two coexist without the form
quietly reformatting what the text tab shows.

**The tree lists real filenames.** A user told their case contains
``system/controlDict`` must find that file on disk under that name, or the
application has taught them something false about their own case.

Every save goes through the service layer and re-validates, and the result is
emitted rather than displayed — the Messages tab of the console dock is the one
place findings appear, so they cannot be shown twice and disagree.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from foamwb.services.case import Case, CaseService
from foamwb.services.foamdict import Document, ParseError
from foamwb.services.schema import load_schema
from foamwb.services.validation import Validation, validate_case
from foamwb.ui.theme import Palette
from foamwb.ui.views.initial import InitialConditionsView
from foamwb.ui.widgets.bc_matrix import BoundaryMatrixView
from foamwb.ui.widgets.form_editor import FormEditor
from foamwb.ui.widgets.geometry_panel import GeometryPanel
from foamwb.ui.widgets.log_pane import LogPane
from foamwb.ui.widgets.mesh_panel import MeshPanel
from foamwb.ui.widgets.property_panel import PropertyPanel
from foamwb.ui.widgets.surface_preview import SurfacePreview
from foamwb.ui.widgets.text_editor import TextEditor

__all__ = ["CaseEditors"]

#: The Form tab's index within the Form/Text pair (DEC-07). A constant because
#: the pair has exactly two members and always will: they are two views of one
#: dictionary, not a list anything else is added to.
_FORM_TAB = 0

#: The narrowest the file tree may become before it starts eliding its own
#: contents — ``polyMesh/boundary``, the one entry whose name says which
#: directory it came from, renders as ``polyMesh/…`` and stops distinguishing
#: itself from the file above it.
_TREE_MINIMUM = 180


class CaseEditors(QWidget):
    """Owns the editors for one case and keeps them true to disk.

    A ``QWidget`` rather than a plain object because it owns child widgets and
    emits signals, but it is never shown: the shell takes its children and
    places them. Parenting them here is what keeps them alive and what makes
    one ``shutdown()`` reach all of them.
    """

    case_changed = Signal()
    """A dictionary was written, so anything downstream should re-read."""

    validated = Signal(object)
    """A :class:`~foamwb.services.validation.Validation`, or ``None`` for no case."""

    file_opened = Signal(Path)

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        log: LogPane | None = None,
    ) -> None:
        """``log`` is the window's console, when the window has one.

        A meshing utility's output is the same kind of thing as a solver's, and
        the user reads one stream of what the application did on their behalf —
        so in the shell it goes to the console dock rather than into a second
        log pane inside a 380-pixel column. Defaults to a private one so the
        editors still construct whole in a test.
        """
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._cases = CaseService()
        self._case: Case | None = None
        self._session = None
        self._current: Path | None = None

        # The picture belongs to the graphics window, so it is built here and
        # handed over rather than built inside the geometry panel: the panel's
        # naming controls point at the same object the user is clicking on.
        self.preview = SurfacePreview(palette, labels)

        self.properties = PropertyPanel(palette, labels)

        self.geometry = GeometryPanel(palette, labels, preview=self.preview, embed_sizing=False)
        self.geometry.geometry_changed.connect(self._on_geometry_changed)
        self.sizing = self.geometry.sizing_section
        self.sizing.setParent(self)

        self.mesh = MeshPanel(palette, labels, log=log)
        # A utility that rewrote the mesh invalidates everything derived from it:
        # the patch list, the matrix and the findings are all about the old one.
        self.mesh.mesh_changed.connect(self._on_mesh_changed)

        # The two halves of "what values does this case start from and hold at
        # its edges": initial conditions are the interior, boundary conditions
        # the edge. It is the disagreement between them that is usually wrong.
        self.matrix = BoundaryMatrixView(palette, labels)
        self.matrix.apply_requested.connect(self._apply_bulk)

        self.initial = InitialConditionsView(palette, labels)

        self.files = self._build_file_document(labels)
        self.files.setParent(self)

    # -- construction ------------------------------------------------------

    def _build_file_document(self, labels: dict[str, str]) -> QWidget:
        """The case's files, with the selected one open in both editors.

        Wide by nature — a dictionary is 80 columns of text beside a tree of
        paths — so this is a graphics-window document rather than a task page.
        """
        page = QSplitter(Qt.Orientation.Horizontal)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabel(labels["case_files"])
        self._tree.setAccessibleName(labels["case_files"])
        self._tree.currentItemChanged.connect(self._on_file_selected)
        page.addWidget(self._tree)

        self._editors = QTabWidget()
        self.form = FormEditor(self._palette, labels)
        self.form.saved.connect(self._on_saved)
        self._editors.addTab(self.form, labels["form_tab"])

        self.text = TextEditor(self._palette, labels)
        self.text.saved.connect(self._on_saved)
        self._editors.addTab(self.text, labels["text_tab"])

        page.addWidget(self._editors)
        page.setStretchFactor(0, 2)
        page.setStretchFactor(1, 5)
        page.widget(0).setMinimumWidth(_TREE_MINIMUM)
        page.setChildrenCollapsible(False)
        return page

    # -- content -----------------------------------------------------------

    def set_session(self, session) -> None:
        """Supply the runtime the meshing utilities run in.

        Separate from :meth:`set_case` because the two arrive at different times:
        a case can be opened before detection finishes, and the mesh panel says
        so rather than offering buttons that cannot work.
        """
        self._session = session
        if self._case is not None:
            self._refresh_mesh_context()

    def set_case(self, case: Case) -> None:
        """Load a case: populate the tree, select something, validate."""
        self._case = case
        self._populate_tree(case)
        self.geometry.set_case(case.path)
        self.initial.set_case(case.path)
        self.refresh_validation()
        self._refresh_mesh_context()
        self._select_first_editable()

    def clear_case(self) -> None:
        self._case = None
        self._current = None
        self._tree.clear()
        self.geometry.set_case(None)
        self.initial.set_case(None)
        self.validated.emit(None)

    def set_property_groups(self, groups) -> None:
        """Fill the settings page with what the selected node owns."""
        self.properties.set_groups(groups)

    def _populate_tree(self, case: Case) -> None:
        """Fill the file tree from what is on disk right now."""
        self._tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for path in self._cases.dictionary_files(case):
            relative = path.relative_to(case.path)
            group = relative.parts[0]
            if group not in groups:
                node = QTreeWidgetItem([group])
                self._tree.addTopLevelItem(node)
                node.setExpanded(True)
                groups[group] = node
            leaf = QTreeWidgetItem([str(Path(*relative.parts[1:]))])
            leaf.setData(0, Qt.ItemDataRole.UserRole, path)
            groups[group].addChild(leaf)

    def _refresh_mesh_context(self) -> None:
        if self._case is None:
            return
        from foamwb.services.boundary import read_boundary

        self.mesh.set_context(
            self._session, self._case.path, meshed=bool(read_boundary(self._case.path))
        )

    @Slot()
    def _on_mesh_changed(self) -> None:
        """A utility rewrote the mesh, so everything derived from it is stale."""
        self.refresh_validation()
        self._refresh_mesh_context()
        self.case_changed.emit()

    @Slot()
    def _on_geometry_changed(self) -> None:
        """Geometry was imported, removed, or turned into meshing dictionaries.

        The file tree is rebuilt as well as the utilities, because generating
        writes two dictionaries into ``system`` — and a tree that still listed
        three files after the panel said it had written two more would be telling
        the user something false about their own case, which is the one thing
        the tree exists not to do.
        """
        self._rebuild_tree()
        self._refresh_mesh_context()
        self.refresh_validation()
        self.case_changed.emit()

    def _rebuild_tree(self) -> None:
        """Re-read the case's dictionaries, keeping what is open selected.

        Selection is restored rather than reset: the tree is rebuilt underneath a
        user who was editing a file, and moving them somewhere else because a
        different file appeared would lose their place for no reason.
        """
        if self._case is None:
            return
        current = self._current
        self._populate_tree(self._case)
        if current is not None:
            self._select_path(current)
        if self._tree.currentItem() is None:
            self._select_first_editable()

    def _select_path(self, wanted: Path) -> None:
        for index in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.data(0, Qt.ItemDataRole.UserRole) == wanted:
                    self._tree.setCurrentItem(child)
                    return

    def _select_first_editable(self) -> None:
        """Open a dictionary the form can edit, rather than whatever sorts first.

        A case opens on ``constant/polyMesh/boundary`` otherwise, which is
        generated data and the least useful thing to land on.
        """
        for index in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                path = child.data(0, Qt.ItemDataRole.UserRole)
                if path is not None and load_schema(Path(path).name) is not None:
                    self._tree.setCurrentItem(child)
                    return
        if self._tree.topLevelItemCount() and self._tree.topLevelItem(0).childCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0).child(0))

    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_file_selected(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            return
        path = current.data(0, Qt.ItemDataRole.UserRole)
        if path is None:
            return  # a group header
        self.open_file(Path(path))

    def _journal_target_for(self, path: Path) -> tuple[Path | None, str]:
        """Which case and relative path a buffer belongs to (NFR-R3).

        Both sides are resolved before comparing: on macOS ``/tmp`` is a symlink
        to ``/private/tmp``, so a caller passing an unresolved path made
        ``relative_to`` raise — and journalling must never be able to stop a file
        being opened. A path outside the case simply is not journalled.
        """
        if self._case is None:
            return None, ""
        try:
            root = self._case.path.resolve()
            return root, path.resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            return None, ""

    def open_file(self, path: Path) -> None:
        """Show a dictionary in both tabs.

        The text tab is populated for *every* file (FR-P6). The form tab is
        enabled only where a schema exists, and says so when it does not, rather
        than presenting an empty form that looks like a file with no settings.
        """
        self._current = path
        data = path.read_bytes()
        # NFR-R3: tell the editor which file this buffer belongs to, so an
        # unsaved edit survives a crash. Set before the content, so the first
        # change is already attributable.
        self.text.set_journal_target(*self._journal_target_for(path))
        self.text.set_content(data)

        schema = load_schema(path.name)
        document: Document | None = None
        if schema is not None:
            try:
                document = Document.parse_bytes(data)
            except ParseError:
                document = None

        if schema is not None and document is not None:
            self.form.set_document(schema, document)
            self._editors.setTabEnabled(_FORM_TAB, True)
            self._editors.setTabText(_FORM_TAB, self._labels["form_tab"])
        else:
            self._editors.setTabEnabled(_FORM_TAB, False)
            self._editors.setCurrentWidget(self.text)
            self._editors.setTabText(_FORM_TAB, self._labels["form_tab_unavailable"])
        self.file_opened.emit(path)

    def show_line(self, path: Path, line: int | None, column: int | None) -> None:
        """Open a file at a line — what activating a finding does."""
        self.open_file(path)
        self._editors.setCurrentWidget(self.text)
        if line is not None:
            self.text._go_to(line, column or 1)

    # -- saving ------------------------------------------------------------

    @Slot(bytes)
    def _on_saved(self, data: bytes) -> None:
        if self._case is None or self._current is None:
            return
        self._cases.write_dictionary(self._case, self._current, data)
        # Reload both tabs from disk rather than trusting the buffer: the file is
        # now the truth, and a tab still showing pre-save state would let the two
        # editors disagree about the same file.
        self.open_file(self._current)
        self.refresh_validation()
        self.case_changed.emit()

    @Slot(str, str, str)
    def _apply_bulk(self, patch_type: str, field_name: str, condition: str) -> None:
        """Set one condition on every patch of a type, for one field (§7.4).

        Only patches that already have an entry are updated. Creating entries is
        deliberately out of scope here: inserting a boundary condition needs the
        other keys that go with it — a ``fixedValue`` without a ``value`` is not a
        working case — and silently writing an incomplete entry would trade a
        visible error for a subtle one.
        """
        if self._case is None:
            return
        source = self._case.path / ("0" if (self._case.path / "0").is_dir() else "0.orig")
        target = source / field_name
        if not target.is_file():
            return

        patches = [p.name for p in validate_case(self._case).matrix.patches if p.type == patch_type]
        try:
            document = Document.parse_bytes(target.read_bytes())
        except ParseError:
            return

        changed = False
        for patch in patches:
            path = f"boundaryField/{patch}/type"
            if document.has(path) and document.get(path) != condition:
                document.set(path, condition)
                changed = True

        if changed:
            self._current = target
            self._on_saved(document.render_bytes())

    # -- validation --------------------------------------------------------

    def refresh_validation(self) -> Validation | None:
        """Re-run validation, update the matrix, and publish the findings (FR-C3)."""
        if self._case is None:
            self.validated.emit(None)
            return None

        validation = validate_case(self._case)
        self.matrix.set_matrix(validation.matrix)
        self.validated.emit(validation)
        return validation

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette across every editor (NFR-A4).

        Validation is re-run rather than the findings recoloured, because their
        colours *mean* something — red is a finding that blocks the run — and
        re-running is the only way to be certain the colours and the findings
        still agree. It costs a re-parse of the case, which is a price worth
        paying at the rate a person changes theme.
        """
        self._palette = palette
        for widget in (
            self.form,
            self.text,
            self.matrix,
            self.mesh,
            self.geometry,
            self.initial,
            self.properties,
            self.preview,
        ):
            widget.set_palette(palette)
        self.refresh_validation()

    # -- lifecycle ---------------------------------------------------------

    def shutdown(self) -> None:
        self.mesh.shutdown()

    # -- for tests ---------------------------------------------------------

    @property
    def case(self) -> Case | None:
        return self._case

    @property
    def current_file(self) -> Path | None:
        return self._current

    @property
    def form_available(self) -> bool:
        return self._editors.isTabEnabled(_FORM_TAB)

    @property
    def editors(self) -> QTabWidget:
        return self._editors

    @property
    def tree_files(self) -> list[Path]:
        found: list[Path] = []
        for index in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(index)
            for child_index in range(group.childCount()):
                path = group.child(child_index).data(0, Qt.ItemDataRole.UserRole)
                if path is not None:
                    found.append(Path(path))
        return found
