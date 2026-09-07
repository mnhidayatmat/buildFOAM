"""The application shell: ribbon, outline, task page, graphics window, console
and status footer (§7.1, DEC-21).

Five regions, arranged as the single-window Fluent arranges them, because that
arrangement answers three questions at once and the previous one answered two.
Across the top, a **ribbon** of tabs — Domain, Physics, Solution, Results,
View — is *what can I do?*. Down the left, the **Outline View** over its **Task
Page** is *what does a case consist of, and where am I in it?*. The centre is
the **graphics window**, a stack of document tabs that is never covered by a
form, and under it the **console** carries everything the application did on the
user's behalf. The **status footer** is unchanged, and still never lies.

The shell owns the wiring and nothing else — it holds no case, runs no command
and parses no dictionary. Everything it displays arrives through a setter, which
is what lets the whole window be driven from a test without a runtime, a case,
or a display.

The one piece of *state* it does own is the appearance setting (NFR-A4), and for
the same reason it owns the runtime status: the theme is global, it belongs to no
view, and one setter driving both the stored preference and every widget's
palette is what keeps the window from disagreeing with its own footer about which
theme is in force.

**Outline nodes, ribbon actions and documents are three views of one list.** A
node names the task page it opens and the document it raises
(:data:`~foamwb.services.workflow.STEPS`); a ribbon action names the node it
selects (:data:`_ACTION_STEPS`). A node with no page, or an action naming a node
that does not exist, is caught by the tests rather than discovered by a user
pressing a button that does nothing.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from foamwb.branding import APP_DISPLAY_NAME
from foamwb.codes import ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.paths import desktop_dir
from foamwb.services.case import Case, CaseError, CaseService
from foamwb.services.freshness import Freshness, assess
from foamwb.services.geometry import existing_surfaces
from foamwb.services.newcase import NewCaseError, create_case
from foamwb.services.polymesh import MeshSurface, Unavailable, read_mesh_surface
from foamwb.services.properties import groups_for_step
from foamwb.services.recents import RecentCase
from foamwb.services.run import StopMode, build_plan, build_update_plan, plan_generates_mesh
from foamwb.services.runtime import (
    RuntimeManager,
    RuntimeState,
    RuntimeStatus,
    load_manifest,
)
from foamwb.services.settings import DEFAULT_THEME, SettingsService, ThemeChoice
from foamwb.services.validation import validate_case
from foamwb.services.workflow import STEPS, StepKind, StepState, WorkflowModel, step_by_id
from foamwb.ui import strings
from foamwb.ui.appearance import resolve_palette
from foamwb.ui.footer import StatusFooter
from foamwb.ui.ribbon import Ribbon
from foamwb.ui.theme import Palette, stylesheet
from foamwb.ui.views.case_editors import CaseEditors
from foamwb.ui.views.guide import GuideView
from foamwb.ui.views.hub import HubView
from foamwb.ui.views.library import LibraryView
from foamwb.ui.views.placeholder import PlaceholderView
from foamwb.ui.views.post import PostView
from foamwb.ui.views.regions import RegionsView
from foamwb.ui.views.run import RunView
from foamwb.ui.views.vandv import VandVView
from foamwb.ui.views.verify import VerifyView
from foamwb.ui.widgets.console_dock import ConsoleDock
from foamwb.ui.widgets.graphics_window import GraphicsWindow
from foamwb.ui.widgets.log_pane import LogPane
from foamwb.ui.widgets.messages_pane import MessagesPane
from foamwb.ui.widgets.outline import Outline
from foamwb.ui.widgets.property_panel import PropertyPanel
from foamwb.ui.widgets.residual_plot import ResidualPlot
from foamwb.ui.widgets.surface_preview import SurfacePreview
from foamwb.ui.widgets.task_page import TaskPage

__all__ = ["Shell"]

#: Which outline node each ribbon action selects. The ribbon is a second route
#: to the same work, never a second implementation of it: pressing *Physics →
#: Materials* does exactly what clicking *Materials* in the outline does, so the
#: outline highlight and the task page cannot end up describing different nodes.
#:
#: Actions absent from this table do something that is not a node — open a
#: dialog, switch a theme, fold a panel — and are handled in
#: :meth:`_on_ribbon_action`.
_ACTION_STEPS: dict[str, str] = {
    "import_geometry": "workflow.import",
    "describe_geometry": "workflow.describe",
    "local_sizing": "workflow.sizing",
    "update_boundaries": "workflow.boundaries",
    "volume_mesh": "workflow.volume",
    "general": "setup.general",
    "models": "setup.models",
    "materials": "setup.materials",
    "boundary_conditions": "setup.boundary",
    "reference_values": "setup.reference",
    "methods": "solution.methods",
    "controls": "solution.controls",
    "monitors": "solution.monitors",
    "initialization": "solution.initialization",
    "activities": "solution.activities",
    "check_case": "solution.check",
    "calculate": "solution.run",
    "graphics": "results.graphics",
    "residuals": "results.plots",
    "reports": "results.reports",
    "case_files": "files.case",
}

#: Ribbon actions that need a case open, and the outline node whose blocked
#: state explains why when they are not available.
_NEEDS_CASE: frozenset[str] = frozenset(_ACTION_STEPS) | {
    "update",
    "check_mesh",
    "display_mesh",
    "paraview",
    "export_csv",
    "stop_write",
    "case_folder",
}


def _is_time(name: str) -> bool:
    """Whether a directory name is a written time. Results, not case structure."""
    try:
        float(name)
    except ValueError:
        return False
    return True


_log = get_logger("ui.shell")


class Shell(QMainWindow):
    """Main window."""

    def __init__(
        self,
        palette: Palette,
        parent: QWidget | None = None,
        *,
        settings: SettingsService | None = None,
        theme: ThemeChoice = DEFAULT_THEME,
    ) -> None:
        """``palette`` must already be the one ``theme`` resolves to.

        Both are passed rather than derived here because the entry point has to
        style the application *before* the window exists (NFR-P1), and computing
        the palette twice invites the two answers to differ — which would show up
        as a window that does not match its own footer.
        """
        super().__init__(parent)
        self._strings = strings.shell_strings()
        self._palette = palette
        self._settings = settings or SettingsService()
        self._theme = ThemeChoice(theme)

        self.setWindowTitle(APP_DISPLAY_NAME)
        # Wider than tall, and wide enough for the outline, a task page and a
        # graphics window side by side. Below this the three columns start
        # taking room from each other rather than from the window.
        self.setMinimumSize(1120, 700)

        # One catalogue for the whole window. The regions share vocabulary —
        # the console's "Messages" tab and the outline's findings are the same
        # word, the residual plot's axis labels belong to the Run page that
        # feeds it — and merging once here is what stops the same sentence
        # reaching a translator twice under two keys.
        self._labels = {
            **self._strings,
            **strings.workflow_strings(),
            **strings.ribbon_strings(),
            **strings.preprocessor_strings(),
            **strings.run_strings(),
            **strings.console_strings(),
            **strings.graphics_strings(),
        }

        self._cases = CaseService()
        self._runtime: RuntimeStatus | None = None
        self._session = None
        self._case_path: Path | None = None
        self._freshness = Freshness()
        """What the case has, and what of it is out of date (DEC-22). Re-read on
        every refresh, because the user edits files between one and the next."""

        self._mesh_shown: tuple[str, float] | None = None
        """Which mesh the Mesh document is drawing, as case and write time.

        The document is re-read only when this moves. Re-reading on every
        refresh would be correct and would throw away the angle the user turned
        the model to — on every save."""
        """The open case. Held here because the outline and the task page are
        both drawn from evidence on disk, and the shell is the only thing that
        knows which case that is."""

        self._current_step: str | None = None

        # How the user is asked for a folder, and how they are told something
        # went wrong. Injectable because a modal dialog blocks its thread until a
        # human answers: with these hard-coded, no test could press "Open Case"
        # without hanging forever, and the one path a user takes most would be
        # the one path never exercised.
        self._choose_directory = self._ask_for_directory
        self._report = self._show_message
        self._ask_text = self._ask_for_text
        self._reveal = self._open_in_file_manager

        self._build()
        self._connect()
        self._install_shortcuts()

        # Start honest: nothing has been detected yet, so the footer says exactly
        # that rather than implying a working runtime (§7.9 rule 4).
        self.set_runtime_status(
            RuntimeStatus(state=RuntimeState.MISSING, reason=ErrorCode.NOT_PROVISIONED)
        )
        self.set_openfoam_version(None)
        self._footer.set_theme_choice(self._theme)
        self._graphics.show_document("start")
        self._task_page.show_page("start", title=self._labels["doc.start"])
        self._refresh_ribbon()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        palette, labels = self._palette, self._labels

        self._ribbon = Ribbon(palette, labels)
        self._outline = Outline(palette, labels)
        self._task_page = TaskPage(labels)
        self._graphics = GraphicsWindow(labels)
        self._footer = StatusFooter(palette)

        # One console and one residual plot in the window, written to by the
        # run, the meshing utilities and the post utilities alike — because the
        # user reads one stream of what the application did on their behalf.
        self._console = LogPane(palette, labels)
        self._messages = MessagesPane(palette, labels)
        self._dock = ConsoleDock(labels, self._console, self._messages)
        self._residuals = ResidualPlot(palette, labels)

        self._build_documents()
        self._build_task_pages()

        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self._outline)
        left.addWidget(self._task_page)
        # The tree is twenty-five rows and the task page is usually one short
        # form, so the split favours the tree. At parity the outline showed nine
        # rows of twenty-five and the user had to scroll to see the shape of the
        # work, which is the one thing it exists to show.
        left.setStretchFactor(0, 7)
        left.setStretchFactor(1, 5)
        left.setChildrenCollapsible(False)
        # Wide enough for the longest row the outline can produce and for the
        # settings table's three columns. Below this the tree elides, and
        # "Calculation Activ…" beside "Initializat…" is a list of nodes whose
        # names the user cannot read. Ctrl+B hides the column outright when the
        # space is genuinely needed.
        left.setMinimumWidth(340)
        self._left = left

        centre = QSplitter(Qt.Orientation.Vertical)
        centre.addWidget(self._graphics)
        centre.addWidget(self._dock)
        centre.setStretchFactor(0, 5)
        centre.setStretchFactor(1, 2)
        centre.setChildrenCollapsible(False)
        self._centre = centre

        row = QSplitter(Qt.Orientation.Horizontal)
        row.addWidget(left)
        row.addWidget(centre)
        row.setStretchFactor(0, 0)
        row.setStretchFactor(1, 1)
        row.setSizes([380, 1020])
        row.setChildrenCollapsible(False)

        central = QWidget()
        body = QVBoxLayout(central)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._ribbon)
        body.addWidget(row, stretch=1)
        body.addWidget(self._footer)
        self.setCentralWidget(central)

    def _build_documents(self) -> None:
        """The graphics window's tabs — everything too wide for a task page."""
        palette, labels = self._palette, self._labels

        self._hub = HubView(labels)
        self._graphics.add_document("start", self._hub)

        self._editors = CaseEditors(palette, labels, log=self._console)
        self._graphics.add_document("geometry", self._editors.preview)

        # The generated mesh, which is a different thing from the surface it was
        # built around and so a different document (DEC-23). Its own widget
        # rather than a second source for one: the geometry panel's naming
        # controls act on whatever its preview is showing, and a mesh under them
        # would mean naming faces of the wrong model.
        self._mesh_preview = SurfacePreview(palette, labels)
        self._mesh_preview.selection_changed.connect(self._on_mesh_face_picked)
        self._graphics.add_document("mesh", self._mesh_preview)
        self._graphics.add_document("residuals", self._residuals)
        self._graphics.add_document("boundary", self._editors.matrix)
        self._graphics.add_document("files", self._editors.files)

        self._verify = VerifyView(palette, {**labels, **strings.verify_strings()})
        self._graphics.add_document("verify", self._verify)

        self._vandv = VandVView(palette, {**labels, **strings.vandv_strings()})
        self._graphics.add_document("vv", self._vandv)

        self._library = LibraryView(palette, {**labels, **strings.library_strings()})
        self._graphics.add_document("library", self._library)

        self._guide = GuideView(palette, {**labels, **strings.guide_strings()})
        self._graphics.add_document("guide", self._guide)

        title, detail = strings.view_placeholders()["setup"]
        self._graphics.add_document("setup", PlaceholderView(title, detail))

    def _build_task_pages(self) -> None:
        """The column beside the outline — one form per node that has one."""
        palette, labels = self._palette, self._labels

        self._task_page.add_page("start", self._build_start_page())
        self._task_page.add_page("settings", self._editors.properties)
        self._task_page.add_page("geometry", self._editors.geometry)
        self._task_page.add_page("describe", self._editors.sizing)
        self._task_page.add_page("mesh", self._editors.mesh)
        self._task_page.add_page("initial", self._editors.initial)
        self._task_page.add_page("files", self._build_files_page())

        self._regions = RegionsView(palette, {**labels, **strings.regions_strings()})
        self._task_page.add_page("regions", self._regions)
        self._mesh_patches: dict[int, str] = {}

        self._task_page.add_page("check", self._build_check_page())

        self._run = RunView(
            palette,
            labels,
            log=self._console,
            residuals=self._residuals,
        )
        self._task_page.add_page("run", self._run)

        self._post = PostView(palette, {**labels, **strings.post_strings()}, log=self._console)
        self._task_page.add_page("post", self._post)

        self._task_page.add_page("reference", self._build_reference_page())

    def _build_start_page(self) -> QWidget:
        """What the task page says with nothing open: how to get a case.

        The start document beside it lists recent cases; this is the *task*, and
        an empty column next to a start screen would read as a panel that had
        failed to load.
        """
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(8)
        hint = PlaceholderView(*strings.view_placeholders()["setup"])
        hint.setVisible(False)
        self._start_hint = hint
        from PySide6.QtWidgets import QLabel, QPushButton

        message = QLabel(self._labels["no_recent_cases"])
        message.setWordWrap(True)
        message.setProperty("role", "muted")
        column.addWidget(message)
        for key in ("new_case", "open_case", "library"):
            button = QPushButton(self._labels[f"action.{key}"])
            button.clicked.connect(lambda _checked=False, k=key: self._on_ribbon_action(k))
            column.addWidget(button)
        column.addStretch(1)
        return page

    def _build_files_page(self) -> QWidget:
        """The task page for *Case Files*: the settings, beside the raw files.

        The tree and the editors are the document; this column says what the
        selected step owns, so a user editing ``controlDict`` by hand can see
        the same values named in plain language beside it.
        """
        self._files_properties = PropertyPanel(self._palette, self._labels)
        return self._files_properties

    def _build_check_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(8)
        from PySide6.QtWidgets import QPushButton

        button = QPushButton(self._labels["action.check_case"])
        button.setDefault(True)
        button.clicked.connect(self._check_case)
        column.addWidget(button)
        column.addStretch(1)
        self._check_button = button
        return page

    def _build_reference_page(self) -> QWidget:
        """*Reference Values* opens the advisor, which is a document.

        The task page carries the sentence that says so, rather than being
        blank: a column that empties when a node is selected reads as a failure.
        """
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(8)
        from PySide6.QtWidgets import QLabel

        message = QLabel(self._labels["hint.setup.reference"])
        message.setWordWrap(True)
        message.setProperty("role", "muted")
        column.addWidget(message)
        column.addStretch(1)
        return page

    def _connect(self) -> None:
        self._outline.step_selected.connect(self._on_step_selected)
        self._outline.action_requested.connect(self._on_step_action)
        self._outline.return_to_mesh.connect(self._on_return_to_mesh)

        self._ribbon.action_triggered.connect(self._on_ribbon_action)
        self._ribbon.recent_requested.connect(lambda path: self.open_case(Path(path)))

        # A patch type decides which boundary conditions are legal, so the
        # matrix has to be re-read rather than left showing the old rules.
        self._regions.patches_changed.connect(self._reload_case)
        # Importing a surface is evidence the geometry node is done, so the row
        # has to tick without waiting for the case to be reopened.
        self._editors.case_changed.connect(self._on_case_changed)
        self._editors.validated.connect(self._on_validated)
        self._messages.finding_activated.connect(self._on_finding_activated)
        self._verify.file_requested.connect(lambda path: self._editors.show_line(path, None, None))
        # FR-G2: a diagnosis carries a guide anchor, and following it must land
        # on the section rather than the top of a nine-section page.
        self._run.guide_requested.connect(self.show_guide)
        self._footer.setup_requested.connect(lambda: self._graphics.show_document("setup"))
        self._footer.theme_requested.connect(self.set_theme)
        self._hub.setup_requested.connect(lambda: self._graphics.show_document("setup"))
        self._hub.action_triggered.connect(self._on_ribbon_action)
        self._hub.case_opened.connect(self._on_case_opened)
        self._post.setup_requested.connect(lambda: self._graphics.show_document("setup"))
        # An installed case is opened straight away: a library that leaves the
        # user to go and find what it just wrote has done four fifths of the job.
        self._library.case_installed.connect(self.open_case)
        self._run.run_started.connect(self._on_run_started)
        self._run.run_finished.connect(self._on_run_finished)

    def _install_shortcuts(self) -> None:
        """Shortcuts the ribbon does not carry.

        Everything with a button gets its shortcut from the ribbon's own table,
        so it is discoverable from the tooltip. These two have no button: the
        outline's own filter and the escape from a modal-less window.
        """
        find = QShortcut(QKeySequence("Ctrl+F"), self)
        find.activated.connect(self._outline._search.setFocus)

    # -- the outline -------------------------------------------------------

    @Slot(str)
    def _on_step_selected(self, step_id: str) -> None:
        """Show the task page a node owns, and raise its document."""
        step = step_by_id(step_id)
        if step is None:
            return
        self._current_step = step_id
        self._outline.select(step_id)

        groups = groups_for_step(self._case_path, step_id)
        self._editors.set_property_groups(groups)
        self._files_properties.set_groups(groups)

        # The header is set from the node whatever page it names, so a node
        # whose page is missing shows an empty column rather than the *previous*
        # node's title over the previous node's form — which is a window lying
        # about what the user selected.
        self._task_page.show_page(
            step.page,
            title=self._labels[f"step.{step_id}"],
            caption=self._labels.get(f"hint.{step_id}", ""),
        )
        if step.document:
            self._graphics.show_document(step.document)
        self._refresh_ribbon()
        log_event(_log, Event.UI_VIEW_SHOWN, view=step_id)

    @Slot(str)
    def _on_step_action(self, step_id: str) -> None:
        """Nodes that run something rather than opening a page.

        *Generate the Volume Mesh* is Fluent's task of the same name: it selects
        its own page — which is where the meshing buttons are — rather than
        running immediately, because a mesh is minutes of work and §7.9 rule 2
        forbids starting it without saying so.
        """
        self._on_step_selected(step_id)
        if step_id == "workflow.volume":
            self._dock.show_console()

    def _on_return_to_mesh(self) -> None:
        """Fluent's *Switch to Meshing*.

        The lock is a statement about where the user is, not a restriction on
        what they may do — so getting back costs one click and nothing else.
        """
        for node in ("workflow.describe", "workflow.sizing", "workflow.boundaries"):
            self._outline.model.set_state(node, StepState.AVAILABLE)
        self._outline.refresh()
        self._on_step_selected("workflow.sizing")

    # -- the ribbon --------------------------------------------------------

    @Slot(str)
    def _on_ribbon_action(self, key: str) -> None:
        """Route a ribbon or start-page action.

        Anything in :data:`_ACTION_STEPS` is the outline's, so the two routes
        cannot diverge. The rest are the actions that are not nodes.
        """
        if (step_id := _ACTION_STEPS.get(key)) is not None:
            step = step_by_id(step_id)
            if step is not None and not self._outline.is_actionable(step_id):
                return
            if step is not None and step.kind is StepKind.ACTION:
                self._on_step_action(step_id)
            else:
                self._on_step_selected(step_id)
            return

        handler = self._handlers().get(key)
        if handler is not None:
            handler()

    def _handlers(self) -> dict:
        """Ribbon actions that are not outline nodes.

        A table rather than a chain of branches, so a test can assert that every
        action the ribbon offers is either a node or in here — which is what
        makes "no button does nothing" checkable rather than hopeful.
        """
        return {
            "new_case": self.new_case_dialog,
            "open_case": self.open_case_dialog,
            "import_geometry_menu": lambda: self._on_ribbon_action("import_geometry"),
            "case_folder": self.reveal_case_folder,
            "library": lambda: self._graphics.show_document("library"),
            "guide": lambda: self._graphics.show_document("guide"),
            "settings": lambda: self._graphics.show_document("setup"),
            "exit": self.close,
            "check_mesh": self._check_mesh,
            "display_mesh": lambda: self._graphics.show_document("mesh"),
            "check_case": self._check_case,
            "update": self._update_case,
            "stop_write": lambda: self._run.stop(StopMode.WRITE),
            "paraview": lambda: self._post._open(mesh_only=False),
            "export_csv": self._run._export_csv,
            "reset_view": self._editors.preview.clear_selection,
            "toggle_outline": self.toggle_outline,
            "toggle_task_page": self.toggle_task_page,
            "toggle_console": lambda: self._dock.set_collapsed(not self._dock.collapsed),
            "theme_light": lambda: self.set_theme(ThemeChoice.LIGHT),
            "theme_dark": lambda: self.set_theme(ThemeChoice.DARK),
            "theme_system": lambda: self.set_theme(ThemeChoice.SYSTEM),
            # The Hub's own keys, which predate the ribbon and still arrive
            # from the start document.
            "case_files": lambda: self._on_step_selected("files.case"),
        }

    def _refresh_ribbon(self) -> None:
        """Enable what can be done now, and say why when something cannot.

        Driven from the outline's own model rather than from a second set of
        conditions, so a button and the node it selects always agree about
        whether the work is available (§7.9 rule 3).
        """
        has_case = self._case_path is not None
        for key in self._ribbon.action_keys + self._ribbon.menu_keys:
            if key not in _NEEDS_CASE:
                continue
            step_id = _ACTION_STEPS.get(key)
            if step_id is not None:
                enabled = self._outline.is_actionable(step_id)
                reason = self._explain_blocked(step_id)
            else:
                enabled = has_case
                reason = self._labels["blocked_no_case"]
            self._ribbon.set_enabled(key, enabled, reason=reason)
        self._ribbon.set_enabled("stop_write", self._run.can_stop, reason=self._labels["no_plan"])
        # Disabled *because there is nothing out of date* is information, not an
        # obstacle: it is the answer to "is my result still valid?", which is the
        # question this button exists to settle.
        self._ribbon.set_enabled(
            "update",
            has_case and self._session is not None and self._freshness.anything_to_do,
            reason=(
                self._labels["up_to_date"]
                if has_case and self._session is not None
                else self._labels["blocked_no_case"]
            ),
        )

    def _explain_blocked(self, step_id: str) -> str:
        step = step_by_id(step_id)
        if step is None:
            return ""
        if self._outline.model.awaiting_mesh(step):
            return self._labels["blocked_no_mesh"]
        if self._case_path is None:
            return self._labels["blocked_no_case"]
        return self._labels["locked_explains"]

    # -- actions that are not nodes ---------------------------------------

    def _check_mesh(self) -> None:
        """*Domain → Mesh → Check*: run checkMesh, with its output in the console."""
        self._on_step_selected("workflow.volume")
        self._dock.show_console()
        from foamwb.services.mesh import UTILITIES

        utility = next((u for u in UTILITIES if u.name == "checkMesh"), None)
        if utility is not None:
            self._editors.mesh.run_utility(utility)

    def _update_case(self) -> None:
        """*Solution → Update*: run whatever is out of date, in order (DEC-22).

        Workbench's *Update Project*. The plan is rebuilt here rather than kept,
        because the whole point is that it depends on what the user has edited
        since — a cached one would be answering yesterday's question.

        Nothing to do is said, not done. Launching a plan whose every stage is
        skipped would put an empty stage strip and a "succeeded in 0.0s" in front
        of a user who asked a question and got what looks like an answer.
        """
        if self._case_path is None or self._session is None:
            return
        case = self._open_for_reading(self._case_path)
        if case is None:
            return
        self.refresh_workflow()
        if not self._freshness.anything_to_do:
            self._on_step_selected("solution.run")
            self._run.say(self._strings["up_to_date"])
            return

        try:
            plan = build_update_plan(case, self._freshness)
        except ValueError as exc:
            self._report(self._strings["cannot_plan_title"], str(exc))
            return

        self._on_step_selected("solution.run")
        self._run.start(plan)

    def _check_case(self) -> None:
        """*Solution → Check Case*: validate, and show the findings."""
        self._verify.run_check()
        self._editors.refresh_validation()
        self._dock.show_messages()
        self.refresh_workflow()

    # -- validation --------------------------------------------------------

    @Slot(object)
    def _on_validated(self, validation) -> None:
        self._messages.set_findings(validation, has_case=self._case_path is not None)

    def _on_finding_activated(self, finding) -> None:
        """Open the offending file and, where known, the offending line (§7.4)."""
        if finding is None or not finding.file.is_file():
            return
        self._on_step_selected("files.case")
        self._editors.show_line(finding.file, finding.line, finding.column)

    def _on_case_changed(self) -> None:
        self.refresh_workflow()
        self._refresh_ribbon()

    # -- workflow state ----------------------------------------------------

    def refresh_workflow(self) -> None:
        """Re-read the evidence the outline is drawn from.

        The case is opened once and handed to both readers below. Opening it
        hashes every definition file — on a meshed case that is the whole
        ``constant/polyMesh`` — and this runs on every save, so a second open
        would put the cost of reading the mesh behind each keystroke's worth of
        work the user does (NFR-P7).
        """
        path = self._case_path
        case = self._open_for_reading(path)
        # One walk of the case, not three. ``assess`` already has to find the
        # mesh and the results to date them, so it answers "is there one?" as
        # well — and two readers of the same directory are two chances to
        # disagree about what is on it (NFR-P7).
        self._freshness = assess(path)
        self._outline.set_model(
            WorkflowModel(
                case=path,
                checks_passed=self._checks_pass(case),
                has_geometry=bool(path and existing_surfaces(path)),
                has_mesh=self._freshness.has_mesh,
                has_results=self._freshness.has_results,
                freshness=self._freshness,
                plan_meshes=self._plan_meshes(case),
                empty_steps=self._empty_steps(path),
            )
        )
        self._refresh_mesh_document()
        self._refresh_ribbon()

    def _refresh_mesh_document(self) -> None:
        """Draw the generated mesh, or say why there is none (DEC-23).

        Read only when the mesh has actually been written since last time. The
        cost is a walk of ``constant/polyMesh``, and this runs on every save.
        """
        signature = (
            (str(self._case_path), self._freshness.mesh_written_at)
            if self._case_path is not None
            else None
        )
        if signature == self._mesh_shown:
            return
        self._mesh_shown = signature

        result = read_mesh_surface(self._case_path)
        if isinstance(result, Unavailable):
            self._mesh_patches = {}
            self._mesh_preview.set_sample(None, message=self._labels[f"mesh_{result.value}"])
            return

        self._mesh_patches = dict(result.patch_of)
        self._mesh_preview.set_sample(result.sample, self._labels["doc.mesh"])
        # ``patch_of`` is already face-group to name, which is what the widget
        # colours and labels by.
        self._mesh_preview.set_region_names(result.patch_of, self._patch_colours(result))

    def _patch_colours(self, surface: MeshSurface) -> dict[str, str]:
        """A colour per patch, from the palette rather than a list of its own.

        The same series the imported surface's regions use, for the same reason:
        a second set of colours is a second thing to keep in contrast with two
        themes. Patches past the end of the series repeat, and the patch list
        beside the model is what tells those apart — colour was never carrying
        it alone (NFR-A2).
        """
        series = (
            self._palette.accent,
            self._palette.ready,
            self._palette.degraded,
            self._palette.broken,
            self._palette.missing,
        )
        return {
            name: series[group % len(series)] for group, name in sorted(surface.patch_of.items())
        }

    def _on_mesh_face_picked(self) -> None:
        """A click on the mesh selects the patch it belongs to (DEC-23).

        The task page is not switched and the document is not changed: the user
        pointed at something to find out what it is, and taking the model away
        from under them to answer would be a poor trade. The Regions page is
        where the answer lands, and it is already the page for the boundary
        nodes.
        """
        picked = self._mesh_preview.selected
        if not picked:
            return
        name = self._mesh_patches.get(picked[0])
        if name:
            self._regions.select(name)

    def _empty_steps(self, path: Path | None) -> frozenset[str]:
        """Nodes whose whole content is a settings table with nothing in it.

        Computed from what the property mapping actually returns, so a node
        reappears the moment it has something to show rather than when someone
        remembers to take it off a list. A node whose file is merely *absent*
        still has content — a group saying which file it wants — and stays.

        With no case open nothing is hidden: the outline's job before a case is
        opened is to show the shape of the work ahead, and a tree that grew rows
        as it went would never let the user learn that shape.
        """
        if path is None:
            return frozenset()
        return frozenset(
            step.id for step in STEPS if step.is_property_page and self._is_blank(path, step.id)
        )

    @staticmethod
    def _is_blank(case: Path, step_id: str) -> bool:
        """Whether this node's settings table would open with nothing in it.

        A node with no mapping at all is blank. So is one whose files are all
        *present* and contribute no rows — ``Monitors`` on a case whose
        ``controlDict`` has no ``functions`` entry is a heading over an empty
        table, which is the promise §7.9 rule 1 forbids making and not keeping.

        A node whose file is merely **absent** is not blank: the group says
        which file it wants, and that is content — it tells the user what to
        create.
        """
        groups = groups_for_step(case, step_id)
        return not groups or all(not group.missing and not group.rows for group in groups)

    def _open_for_reading(self, path: Path | None) -> Case | None:
        """Open the case for the outline's readers, or ``None``.

        Swallows its own failures deliberately, as everything below it does: the
        readers decide ticks in a tree, and a case that cannot be opened at all
        says so through the views that exist to report it rather than through an
        exception thrown while drawing the navigation panel.
        """
        if path is None:
            return None
        try:
            return self._cases.open(path)
        except Exception:
            return None

    def _plan_meshes(self, case: Case | None) -> bool:
        """Whether this case's run plan would generate its mesh first.

        Re-read on every refresh rather than kept from the plan built at open,
        because generating meshing dictionaries from an imported surface writes
        a ``blockMeshDict`` into a case that had none — and a stale answer would
        keep *Calculate* blocked on a mesh the plan had since learned to build.
        """
        if case is None:
            return False
        try:
            return plan_generates_mesh(build_plan(case))
        except ValueError:
            # No application in controlDict, so there is no plan and nothing
            # that would mesh. The Run page reports the same fact properly.
            return False

    def _checks_pass(self, case: Case | None) -> bool:
        """Whether validation finds nothing that would stop a run (FR-C3).

        Swallows its own failures deliberately. This decides a tick in a tree; a
        case whose dictionaries cannot be parsed has bigger problems, and they
        are reported by the Check Case page itself.
        """
        if case is None:
            return False
        try:
            return not validate_case(case).blocking
        except Exception:
            return False

    def _resume_workflow(self) -> None:
        """Move to the node the case is actually up to, and select it.

        Opening a case used to land on the Run view whatever the case was, which
        told a user with no mesh to run a solver that could not start. Following
        the outline instead means the tree and the graphics window agree about
        where the user is.
        """
        step = self._outline.model.resume_step
        if step is None:
            self._on_step_selected("solution.run")
            return
        self._on_step_selected(step.id)

    # -- panels ------------------------------------------------------------

    def toggle_outline(self) -> None:
        self._outline.setVisible(not self._outline.isVisibleTo(self))

    def toggle_task_page(self) -> None:
        self._task_page.setVisible(not self._task_page.isVisibleTo(self))

    @Slot(str)
    def show_guide(self, anchor: str) -> bool:
        """Open a guide section by anchor. Returns whether it resolved."""
        if not self._guide.show_anchor(anchor):
            return False
        self._graphics.show_document("guide")
        return True

    def _reload_case(self) -> None:
        """Re-read the open case after something changed it underneath us."""
        if self._case_path is not None:
            self.open_case(self._case_path)

    # -- state -------------------------------------------------------------

    def set_runtime_status(self, status: RuntimeStatus) -> None:
        """Update both the footer and the start banner from one value.

        One setter for both, so they cannot disagree — a footer saying *ready*
        above a banner saying *not installed* would undermine the one guarantee
        §7.9 makes about the footer.
        """
        self._runtime = status
        self._footer.set_runtime_status(status)
        message = strings.runtime_banner_message(
            status.state.value, status.reason.id if status.reason else None
        )
        self._hub.set_runtime_status(status, message)

    def set_openfoam_version(self, version: str | None) -> None:
        self._footer.set_openfoam_version(version)
        # The library labels each item against the runtime actually in use, so
        # it has to learn about it from the same setter the footer does — two
        # sources would eventually disagree about which release is installed.
        self._library.set_runtime_version(version or None)

    @Slot(RuntimeStatus)
    def apply_runtime_status(self, status: RuntimeStatus) -> None:
        """Adopt a detected runtime — state and version together.

        One entry point rather than two calls, so the footer can never show a
        ready runtime beside a stale version, or a version beside "not
        installed". §7.9 rule 4 is about the footer as a whole, not each label.
        """
        self.set_runtime_status(status)
        self.set_openfoam_version(status.openfoam_version)

        # A usable runtime means a session the Run page can execute against.
        # Held here because the shell owns which case is open, and the two have
        # to be handed over together.
        if status.is_usable:
            manager = RuntimeManager()
            installations = manager.discover()
            if installations:
                self._session = manager.session_for(installations[0])
                self._editors.set_session(self._session)

    def set_active_case(self, case_name: str | None) -> None:
        self._footer.set_case(case_name)
        self.setWindowTitle(
            self._strings["title_with_case"].format(case_name, APP_DISPLAY_NAME)
            if case_name
            else APP_DISPLAY_NAME
        )

    def set_run_state(self, run_state: str | None) -> None:
        self._footer.set_run_state(run_state)

    def set_recent_cases(self, cases: list[RecentCase]) -> None:
        self._hub.set_recent_cases(cases)
        self._ribbon.set_recent([str(case.path) for case in cases])

    # -- appearance --------------------------------------------------------

    @property
    def theme(self) -> ThemeChoice:
        """The user's choice, which is not necessarily what is painted.

        ``SYSTEM`` resolves to a light or a dark palette depending on the
        desktop, and the answer can change while the window is open — so the
        choice and the palette are separate facts and both are kept.
        """
        return self._theme

    @property
    def palette_in_use(self) -> Palette:
        """What is actually painted right now.

        Named to stay clear of ``QWidget.palette()``, which is Qt's own platform
        palette and a different thing entirely — this application paints from a
        style sheet, so the two are not interchangeable.
        """
        return self._palette

    @Slot(str)
    def set_theme(self, choice: str | ThemeChoice) -> None:
        """Adopt a theme, persist it, and repaint (NFR-A4).

        Applied first and saved second, deliberately. The window is the thing the
        user asked to change; a preferences file that could not be written is
        worth a log line but is not a reason to refuse them the theme they just
        picked, and :meth:`SettingsService.save` reports rather than raises for
        exactly that reason.

        Accepts the plain string a signal carries, because a Qt signal cannot
        carry an enum without registering a metatype — and the coercion here is
        also the validation, so a value from anywhere else is checked too.
        """
        self._theme = ThemeChoice(choice)
        self._footer.set_theme_choice(self._theme)
        self._repaint()
        self._settings.set_theme(self._theme)
        log_event(_log, Event.APP_THEME, theme=self._theme.value)

    def refresh_system_theme(self, _scheme: object = None) -> None:
        """Repaint if — and only if — the user asked to follow the desktop.

        Connected unconditionally to Qt's scheme-changed signal, because the
        alternative is connecting and disconnecting as the choice changes, and a
        missed disconnection would silently override an explicit Light or Dark
        the next time the desktop switched.

        The scheme the signal carries is ignored and re-queried, so this is also
        the method to call when *something else* changed — and taking the
        argument at all is what lets it be connected as a bound method, which Qt
        disconnects automatically when the window is destroyed. A lambda would
        outlive it and fire into a deleted object.
        """
        if self._theme is ThemeChoice.SYSTEM:
            self._repaint()

    def _repaint(self) -> None:
        """Resolve the current choice and push the palette through the window.

        The style sheet covers most of it, but not all: item brushes, syntax
        highlighting, the ribbon's icons and the plot canvas are set per widget
        and would otherwise keep the previous theme's colours. So each widget
        that holds a palette is handed the new one and re-renders what it had
        already drawn.
        """
        palette = resolve_palette(self._theme)
        self._palette = palette

        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(stylesheet(palette))

        for widget in (
            self._ribbon,
            self._outline,
            self._footer,
            self._console,
            self._messages,
            self._residuals,
            self._run,
            self._post,
            self._editors,
            self._verify,
            self._regions,
            self._library,
            self._guide,
            self._vandv,
            self._files_properties,
            self._mesh_preview,
        ):
            widget.set_palette(palette)
        # The patch colours come from the palette, so they are re-derived rather
        # than left showing the previous theme's series.
        self._mesh_shown = None
        self._refresh_mesh_document()

    # -- handlers ----------------------------------------------------------

    def new_case_dialog(self) -> None:
        """Ask where and what to call it, create it, and open it (FR-C1).

        Two questions rather than one save dialog, because a save dialog asks for
        a *file* and what is being created is a directory — on every platform
        that dialog then warns about replacing a folder that does not exist yet.
        """
        parent = self._choose_directory(self._strings["new_case_where"])
        if parent is None:
            return

        name = self._ask_text(
            self._strings["new_case_name_title"],
            self._strings["new_case_name_prompt"],
            self._strings["new_case_default"],
        )
        if not name:
            return

        try:
            created = create_case(parent, name)
        except NewCaseError as exc:
            # The code travels with the message: a name that cannot be used and a
            # destination that is occupied need different corrections.
            self._report(
                self._strings["new_case_failed_title"],
                self._strings["new_case_failed"].format(exc.message, exc.code.id),
            )
            log_event(_log, Event.ERROR_RAISED, where="shell.new_case", error=exc.code.id)
            return

        self.open_case(created.path)
        # Straight to the import task: a case with no mesh and no fields exists
        # to have something imported into it, and leaving the user on a page
        # that says "no problems found" would hide the one action that follows.
        self._on_step_selected("workflow.import")

    def reveal_case_folder(self) -> None:
        """Show the open case's folder in the desktop's file manager."""
        if self._case_path is None:
            self._report(self._strings["no_case_open_title"], self._strings["no_case_open_body"])
            return
        if not self._reveal(self._case_path):
            self._report(
                self._strings["reveal_failed_title"],
                self._strings["reveal_failed_body"].format(str(self._case_path)),
            )

    @staticmethod
    def _open_in_file_manager(path: Path) -> bool:
        """Hand a directory to the desktop. Returns whether it was accepted.

        ``QDesktopServices`` rather than a per-platform command, because it is
        the one call that already knows what each desktop uses and it does not
        put a user-supplied path anywhere near a shell.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot(RecentCase)
    def _on_case_opened(self, case: RecentCase) -> None:
        self.open_case(case.path)

    def _on_run_started(self) -> None:
        self.set_run_state(self._strings["run_state_running"])
        # The transcript is what the user watches during a run, so the console
        # comes up rather than waiting to be found.
        self._dock.show_console()
        self._refresh_ribbon()

    def _on_run_finished(self, _result) -> None:
        # A finished run creates time directories and possibly a mesh, both of
        # which the outline reports. Re-read rather than assume.
        self.refresh_workflow()
        # Back to idle whatever the outcome. The footer reports *what the
        # application is doing*, and the Run page already says how it went — two
        # places claiming to own the verdict is how they end up disagreeing.
        self.set_run_state(None)

    # -- opening a case ----------------------------------------------------

    def open_case_dialog(self) -> None:
        """Ask for a folder and open it. Cancelling changes nothing."""
        directory = self._choose_directory(self._strings["choose_case"])
        if directory is not None:
            self.open_case(directory)

    def _ask_for_directory(self, title: str) -> Path | None:
        """Ask for a folder, opening on the desktop.

        The starting directory belongs to the dialog rather than to the question,
        which is why it is not a parameter: a test that injects this replaces the
        whole dialog, and would gain nothing from being handed a path it never
        shows. See :func:`~foamwb.paths.desktop_dir` for why the desktop.
        """
        chosen = QFileDialog.getExistingDirectory(self, title, str(desktop_dir()))
        return Path(chosen) if chosen else None

    def _show_message(self, title: str, body: str) -> None:
        QMessageBox.warning(self, title, body)

    def _ask_for_text(self, title: str, prompt: str, default: str) -> str | None:
        chosen, accepted = QInputDialog.getText(self, title, prompt, text=default)
        return chosen.strip() if accepted else None

    def set_dialogs(
        self,
        *,
        choose_directory=None,
        report=None,
        ask_text=None,
        reveal=None,
    ) -> None:
        """Replace the modal dialogs, for tests and for scripted runs."""
        if choose_directory is not None:
            self._choose_directory = choose_directory
        if report is not None:
            self._report = report
        if ask_text is not None:
            self._ask_text = ask_text
        if reveal is not None:
            self._reveal = reveal

    def open_case(self, path: Path) -> None:
        """Open a case, build its plan, and resume where the case is up to.

        Every failure here is reported and survivable. Opening a folder that is
        not a case, or one whose controlDict names no solver, is an ordinary
        mistake — the user picked the wrong directory — and must not leave the
        application in a state where the previous case has been forgotten and no
        new one has been adopted.
        """
        try:
            case = self._cases.open(path)
        except CaseError as exc:
            self._report(self._strings["not_a_case_title"], str(exc))
            return

        # Most tutorials ship 0.orig and no 0, so this is the common path rather
        # than a corner: without it the solver fails on a case that is perfectly
        # good (351 of the v2512 tutorials are like this).
        restored = self._cases.restore_initial_conditions(case)

        try:
            plan = build_plan(case)
        except ValueError as exc:
            self._report(self._strings["cannot_plan_title"], str(exc))
            return

        self._case_path = case.path
        self.set_active_case(case.name)
        self.refresh_workflow()
        self._editors.set_case(case)
        self._vandv.set_case(
            case,
            version=self._runtime.openfoam_version if self._runtime else "",
            dictionary_name=self._turbulence_dictionary(),
        )
        self._post.set_context(self._session, case.path)
        self._regions.set_case(case.path)
        self._verify.set_case(case.path)
        # New cases land beside the one just opened, which is where a user who
        # keeps their work in one folder expects to find them.
        self._library.set_destination(case.path.parent)
        if self._session is not None:
            self._run.set_context(self._session, case.path, plan)
            self._resume_workflow()
        else:
            # A case can be opened without a runtime; it just cannot be run. Said
            # plainly rather than by leaving Calculate mysteriously dead.
            self._resume_workflow()
            self._report(self._strings["no_runtime_title"], self._strings["no_runtime_body"])

        if restored:
            log_event(_log, Event.CASE_WRITE, case=str(path), action="restore_initial")

    def _turbulence_dictionary(self) -> str:
        """The lineage's name for the turbulence dictionary (NFR-M3, DEC-15).

        Read from the manifest rather than spelled out: ESI and the Foundation
        call this file different things, and the indirection is what keeps
        supporting both a data change.
        """
        version = self._runtime.openfoam_version if self._runtime else None
        manifest = load_manifest()
        release = (
            manifest.release(version)
            if version and manifest.supports(version)
            else manifest.default_release()
        )
        return release.dictionary("turbulence")

    def closeEvent(self, event) -> None:
        """Reap a running solver before the window goes away (FR-S10, NFR-R6).

        Force-quitting must leave no ``simpleFoam`` or ``mpirun`` behind. Doing
        this in ``closeEvent`` rather than at interpreter exit means the process
        group is signalled while Qt is still alive to wait for it.
        """
        self._run.shutdown()
        self._editors.shutdown()
        super().closeEvent(event)

    # -- for tests ---------------------------------------------------------

    @property
    def ribbon(self) -> Ribbon:
        return self._ribbon

    @property
    def outline(self) -> Outline:
        return self._outline

    @property
    def task_page(self) -> TaskPage:
        return self._task_page

    @property
    def graphics(self) -> GraphicsWindow:
        return self._graphics

    @property
    def console(self) -> ConsoleDock:
        return self._dock

    @property
    def messages(self) -> MessagesPane:
        return self._messages

    @property
    def footer(self) -> StatusFooter:
        return self._footer

    @property
    def properties(self) -> PropertyPanel:
        return self._editors.properties

    @property
    def editors(self) -> CaseEditors:
        return self._editors

    @property
    def regions(self) -> RegionsView:
        return self._regions

    @property
    def verify(self) -> VerifyView:
        return self._verify

    @property
    def guide(self) -> GuideView:
        return self._guide

    @property
    def initial(self):
        return self._editors.initial

    @property
    def hub(self) -> HubView:
        return self._hub

    @property
    def run_view(self) -> RunView:
        return self._run

    @property
    def vandv(self) -> VandVView:
        return self._vandv

    @property
    def post(self) -> PostView:
        return self._post

    @property
    def library(self) -> LibraryView:
        return self._library

    @property
    def current_step(self) -> str | None:
        return self._current_step

    @property
    def current_document(self) -> str:
        return self._graphics.current

    @property
    def current_page(self) -> str:
        return self._task_page.current
