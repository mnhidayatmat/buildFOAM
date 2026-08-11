"""The Preprocessor view (§7.4).

Three regions, as specified: the real case file tree on the left, tabbed editors
in the centre — a Form tab and a Text tab, **always both** (DEC-07) — and the
live validation panel on the right.

"Always both" is the whole reason forms are safe here. Forms serve P1 and P2; the
text tab keeps the P4 constraint that a power user is never trapped. Round-trip
fidelity (FR-P7) is what lets the two coexist without the form quietly reformatting
what the text tab shows.

The tree lists **real filenames**. A user told their case contains
``system/controlDict`` must find that file on disk under that name, or the
application has taught them something false about their own case.

Every save goes through the service layer and re-validates. A panel that could
drift from the files beside it would be worse than no panel: it would be believed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.case import Case, CaseService, Finding
from foamwb.services.foamdict import Document, ParseError
from foamwb.services.schema import load_schema
from foamwb.services.validation import validate_case
from foamwb.ui.theme import Palette
from foamwb.ui.widgets.bc_matrix import BoundaryMatrixView
from foamwb.ui.widgets.form_editor import FormEditor
from foamwb.ui.widgets.mesh_panel import MeshPanel
from foamwb.ui.widgets.text_editor import TextEditor

__all__ = ["PreprocessorView"]

#: The narrowest the file tree, the editors and the validation panel may become,
#: in pixels. Sized to what each has to show rather than shared out evenly: the
#: tree needs to spell out a path, the editors hold the form, and the validation
#: column only ever carries wrapping text.
_PANE_MINIMUMS = (180, 400, 190)


class PreprocessorView(QWidget):
    """Edit a case's dictionaries, with validation beside them."""

    case_changed = Signal()
    """A dictionary was written, so anything downstream should re-read."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._cases = CaseService()
        self._case: Case | None = None
        self._session = None
        self._current: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_tree(labels))
        splitter.addWidget(self._build_editors(labels))
        splitter.addWidget(self._build_validation(labels))
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)
        # Without a floor the file tree is handed whatever is left over and
        # elides its own contents — ``polyMesh/boundary``, the one entry whose
        # name says which directory it came from, renders as ``polyMesh/…`` and
        # stops distinguishing itself from the file above it.
        for index, minimum in enumerate(_PANE_MINIMUMS):
            splitter.widget(index).setMinimumWidth(minimum)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, stretch=1)

        self._show_no_case()

    # -- construction ------------------------------------------------------

    def _build_tree(self, labels: dict[str, str]) -> QWidget:
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel(labels["case_files"])
        self._tree.setAccessibleName(labels["case_files"])
        self._tree.currentItemChanged.connect(self._on_file_selected)
        return self._tree

    def _build_editors(self, labels: dict[str, str]) -> QWidget:
        self._tabs = QTabWidget()

        self._form = FormEditor(self._palette, labels)
        self._form.saved.connect(self._on_saved)
        self._tabs.addTab(self._form, labels["form_tab"])

        self._text = TextEditor(self._palette, labels)
        self._text.saved.connect(self._on_saved)
        self._tabs.addTab(self._text, labels["text_tab"])

        self._matrix = BoundaryMatrixView(self._palette, labels)
        self._matrix.apply_requested.connect(self._apply_bulk)
        self._tabs.addTab(self._matrix, labels["bc_tab"])

        self._mesh = MeshPanel(self._palette, labels)
        # A utility that rewrote the mesh invalidates everything derived from it:
        # the patch list, the matrix and the findings are all about the old one.
        self._mesh.mesh_changed.connect(self._on_mesh_changed)
        self._tabs.addTab(self._mesh, labels["mesh_tab"])
        return self._tabs

    def _build_validation(self, labels: dict[str, str]) -> QWidget:
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        heading = QLabel(labels["validation"])
        heading.setProperty("role", "subheading")
        column.addWidget(heading)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        column.addWidget(self._summary)

        self._findings = QListWidget()
        self._findings.setAccessibleName(labels["validation"])
        self._findings.setWordWrap(True)
        self._findings.itemActivated.connect(self._on_finding_activated)
        column.addWidget(self._findings, stretch=1)
        return panel

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

        self.refresh_validation()
        self._refresh_mesh_context()
        self._select_first_editable()

    def _refresh_mesh_context(self) -> None:
        if self._case is None:
            return
        from foamwb.services.boundary import read_boundary

        self._mesh.set_context(
            self._session, self._case.path, meshed=bool(read_boundary(self._case.path))
        )

    @Slot()
    def _on_mesh_changed(self) -> None:
        """A utility rewrote the mesh, so everything derived from it is stale."""
        self.refresh_validation()
        self._refresh_mesh_context()
        self.case_changed.emit()

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
        self._text.set_journal_target(*self._journal_target_for(path))
        self._text.set_content(data)

        schema = load_schema(path.name)
        document: Document | None = None
        if schema is not None:
            try:
                document = Document.parse_bytes(data)
            except ParseError:
                document = None

        if schema is not None and document is not None:
            self._form.set_document(schema, document)
            self._tabs.setTabEnabled(0, True)
            self._tabs.setTabText(0, self._labels["form_tab"])
        else:
            self._tabs.setTabEnabled(0, False)
            self._tabs.setCurrentWidget(self._text)
            self._tabs.setTabText(0, self._labels["form_tab_unavailable"])

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

    def refresh_validation(self) -> None:
        """Re-run validation and repopulate the panel (FR-C3)."""
        self._findings.clear()
        # An empty findings list is an empty bordered box a third of the panel
        # tall, which reads as something that failed to load rather than as a
        # case with nothing wrong with it. The summary line already carries the
        # verdict, so the list only appears when it has something to list.
        self._findings.setVisible(False)
        if self._case is None:
            return

        validation = validate_case(self._case)
        self._matrix.set_matrix(validation.matrix)

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
                _brush(self._palette.broken if finding.blocks_run else self._palette.degraded)
            )
            self._findings.addItem(item)

    def _describe(self, finding: Finding) -> str:
        where = finding.file.name
        if finding.line is not None:
            where = self._labels["finding_at_line"].format(where, finding.line)
        return self._labels["finding"].format(finding.code.id, where, finding.detail)

    @Slot(QListWidgetItem)
    def _on_finding_activated(self, item: QListWidgetItem) -> None:
        """Open the offending file and, where known, the offending line (§7.4)."""
        finding = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(finding, Finding) or not finding.file.is_file():
            return
        self.open_file(finding.file)
        self._tabs.setCurrentWidget(self._text)
        if finding.line is not None:
            self._text._go_to(finding.line, finding.column or 1)

    def _show_no_case(self) -> None:
        self._summary.setText(self._labels["no_case_open_hint"])
        self._summary.setStyleSheet(f"color: {self._palette.text_muted};")

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette across the tabs and the validation panel (NFR-A4).

        The panel is re-derived from the case rather than recoloured item by
        item, because its colours *mean* something — red is a finding that blocks
        the run — and re-running validation is the only way to be certain the
        colours and the findings still agree. It costs a re-parse of the case,
        which is a price worth paying at the rate a person changes theme.
        """
        self._palette = palette
        self._form.set_palette(palette)
        self._text.set_palette(palette)
        self._matrix.set_palette(palette)
        self._mesh.set_palette(palette)

        if self._case is None:
            self._show_no_case()
        else:
            self.refresh_validation()

    # -- for tests ---------------------------------------------------------

    @property
    def form(self) -> FormEditor:
        return self._form

    @property
    def text(self) -> TextEditor:
        return self._text

    @property
    def matrix(self) -> BoundaryMatrixView:
        return self._matrix

    @property
    def mesh(self) -> MeshPanel:
        return self._mesh

    def shutdown(self) -> None:
        self._mesh.shutdown()

    @property
    def current_file(self) -> Path | None:
        return self._current

    @property
    def finding_count(self) -> int:
        return self._findings.count()

    @property
    def summary_text(self) -> str:
        return self._summary.text()

    @property
    def form_available(self) -> bool:
        return self._tabs.isTabEnabled(0)

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

    def activate_finding(self, index: int) -> None:
        self._on_finding_activated(self._findings.item(index))


def _brush(colour: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(colour))
