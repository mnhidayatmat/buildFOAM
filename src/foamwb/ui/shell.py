"""The application shell: nav rail, view stack, status footer (§7.1).

Three regions, as specified. The shell owns the wiring and nothing else — it
holds no case, runs no command and parses no dictionary. Everything it displays
arrives through a setter, which is what lets the whole window be driven from a
test without a runtime, a case, or a display.

The one piece of *state* it does own is the appearance setting (NFR-A4), and for
the same reason it owns the runtime status: the theme is global, it belongs to no
view, and one setter driving both the stored preference and every widget's
palette is what keeps the window from disagreeing with its own footer about which
theme is in force.

The stack is built from :data:`~foamwb.ui.navrail.NAV_ITEMS`, the same list that
builds the rail and the shortcuts, so a view cannot exist in one and be missing
from another.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from foamwb.branding import APP_DISPLAY_NAME
from foamwb.codes import ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.case import CaseError, CaseService
from foamwb.services.recents import RecentCase
from foamwb.services.run import build_plan
from foamwb.services.runtime import (
    RuntimeManager,
    RuntimeState,
    RuntimeStatus,
    load_manifest,
)
from foamwb.services.settings import DEFAULT_THEME, SettingsService, ThemeChoice
from foamwb.ui import strings
from foamwb.ui.appearance import resolve_palette
from foamwb.ui.footer import StatusFooter
from foamwb.ui.navrail import NAV_ITEMS, NavRail
from foamwb.ui.theme import Palette, stylesheet
from foamwb.ui.views.hub import HubView
from foamwb.ui.views.library import LibraryView
from foamwb.ui.views.placeholder import PlaceholderView
from foamwb.ui.views.post import PostView
from foamwb.ui.views.preprocessor import PreprocessorView
from foamwb.ui.views.run import RunView
from foamwb.ui.views.vandv import VandVView

__all__ = ["Shell"]

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
        self._placeholders = strings.view_placeholders()
        self._palette = palette
        self._settings = settings or SettingsService()
        self._theme = ThemeChoice(theme)

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumSize(960, 640)

        self._rail = NavRail(
            strings.nav_labels(),
            item_format=self._strings["nav_item"],
            tooltip_format=self._strings["nav_tooltip"],
        )
        self._stack = QStackedWidget()
        self._footer = StatusFooter(palette)

        self._cases = CaseService()
        self._runtime: RuntimeStatus | None = None
        self._session = None

        # How the user is asked for a folder, and how they are told something
        # went wrong. Injectable because a modal dialog blocks its thread until a
        # human answers: with these hard-coded, no test could press "Open Case"
        # without hanging forever, and the one path a user takes most would be
        # the one path never exercised.
        self._choose_directory = self._ask_for_directory
        self._report = self._show_message

        self._views: dict[str, QWidget] = {}
        self._build_views()

        central = QWidget()
        body = QVBoxLayout(central)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.addWidget(self._stack)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.addWidget(self._rail)
        row_layout.addWidget(upper, stretch=1)

        body.addWidget(row, stretch=1)
        body.addWidget(self._footer)
        self.setCentralWidget(central)

        self._connect()
        self._install_shortcuts()

        # Start honest: nothing has been detected yet, so the footer says exactly
        # that rather than implying a working runtime (§7.9 rule 4).
        self.set_runtime_status(
            RuntimeStatus(state=RuntimeState.MISSING, reason=ErrorCode.NOT_PROVISIONED)
        )
        self.set_openfoam_version(None)
        self._footer.set_theme_choice(self._theme)
        self.show_view("hub")

    # -- construction ------------------------------------------------------

    def _build_views(self) -> None:
        self._hub = HubView(self._strings)
        self._views["hub"] = self._hub
        self._stack.addWidget(self._hub)

        self._run = RunView(self._palette, {**self._strings, **strings.run_strings()})
        self._views["run"] = self._run
        self._stack.addWidget(self._run)

        self._preprocessor = PreprocessorView(
            self._palette, {**self._strings, **strings.preprocessor_strings()}
        )
        self._views["cases"] = self._preprocessor
        self._stack.addWidget(self._preprocessor)

        self._vandv = VandVView(self._palette, {**self._strings, **strings.vandv_strings()})
        self._views["vv"] = self._vandv
        self._stack.addWidget(self._vandv)

        self._post = PostView(self._palette, {**self._strings, **strings.post_strings()})
        self._views["post"] = self._post
        self._stack.addWidget(self._post)

        self._library = LibraryView(self._palette, {**self._strings, **strings.library_strings()})
        self._views["library"] = self._library
        self._stack.addWidget(self._library)

        for item in NAV_ITEMS:
            if item.key in self._views:
                continue
            title, detail = self._placeholders[item.key]
            view = PlaceholderView(title, detail)
            self._views[item.key] = view
            self._stack.addWidget(view)

    def _connect(self) -> None:
        self._rail.view_selected.connect(self.show_view)
        self._footer.setup_requested.connect(lambda: self.show_view("setup"))
        self._footer.theme_requested.connect(self.set_theme)
        self._hub.setup_requested.connect(lambda: self.show_view("setup"))
        self._hub.action_triggered.connect(self._on_hub_action)
        self._hub.case_opened.connect(self._on_case_opened)
        self._post.setup_requested.connect(lambda: self.show_view("setup"))
        # An installed case is opened straight away: a library that leaves the
        # user to go and find what it just wrote has done four fifths of the job.
        self._library.case_installed.connect(self.open_case)
        self._run.run_started.connect(
            lambda: self.set_run_state(self._strings["run_state_running"])
        )
        self._run.run_finished.connect(self._on_run_finished)

    def _install_shortcuts(self) -> None:
        # Ctrl+B collapses the rail, matching the convention users already have
        # from editors. NFR-A1 requires the whole shell to be operable without a
        # mouse, and a rail that could only be collapsed by clicking would not be.
        collapse = QShortcut(QKeySequence("Ctrl+B"), self)
        collapse.activated.connect(self._rail.toggle_collapsed)

    # -- navigation --------------------------------------------------------

    @Slot(str)
    def show_view(self, key: str) -> None:
        """Switch the main panel and keep the rail in step."""
        view = self._views.get(key)
        if view is None:
            raise KeyError(f"Unknown view: {key!r}")
        self._stack.setCurrentWidget(view)
        self._rail.select(key)
        log_event(_log, Event.UI_VIEW_SHOWN, view=key)

    @property
    def current_view(self) -> str | None:
        return self._rail.current

    # -- state -------------------------------------------------------------

    def set_runtime_status(self, status: RuntimeStatus) -> None:
        """Update both the footer and the Hub banner from one value.

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

        # A usable runtime means a session the Run view can execute against.
        # Held here because the shell owns which case is open, and the two have
        # to be handed over together.
        if status.is_usable:
            manager = RuntimeManager()
            installations = manager.discover()
            if installations:
                self._session = manager.session_for(installations[0])
                self._preprocessor.set_session(self._session)

    def set_active_case(self, case_name: str | None) -> None:
        self._footer.set_case(case_name)
        self.setWindowTitle(f"{case_name} — {APP_DISPLAY_NAME}" if case_name else APP_DISPLAY_NAME)

    def set_run_state(self, run_state: str | None) -> None:
        self._footer.set_run_state(run_state)

    def set_recent_cases(self, cases: list[RecentCase]) -> None:
        self._hub.set_recent_cases(cases)

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

        Accepts the plain string the footer's signal carries, because a Qt signal
        cannot carry an enum without registering a metatype — and the coercion
        here is also the validation, so a value from anywhere else is checked too.
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
        highlighting and the plot canvas are set per widget and would otherwise
        keep the previous theme's colours. So each widget that holds a palette is
        handed the new one and re-renders what it had already drawn.
        """
        palette = resolve_palette(self._theme)
        self._palette = palette

        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(stylesheet(palette))

        self._footer.set_palette(palette)
        self._run.set_palette(palette)
        self._preprocessor.set_palette(palette)

    # -- handlers ----------------------------------------------------------

    @Slot(str)
    def _on_hub_action(self, action: str) -> None:
        """Route a Hub action.

        Everything except navigation needs a service that does not exist yet, so
        those actions route to the view that will own them. Wiring them to
        nothing would make the Hub's buttons dead on arrival, which FR-A1's
        "every target reachable in one click" forbids.
        """
        if action == "open_case":
            self.open_case_dialog()
            return
        destinations = {"library": "library", "guide": "guide", "settings": "setup"}
        if action in destinations:
            self.show_view(destinations[action])
        else:
            self.show_view("cases")

    @Slot(RecentCase)
    def _on_case_opened(self, case: RecentCase) -> None:
        self.open_case(case.path)

    def _on_run_finished(self, _result) -> None:
        # Back to idle whatever the outcome. The footer reports *what the
        # application is doing*, and the Run view already says how it went — two
        # places claiming to own the verdict is how they end up disagreeing.
        self.set_run_state(None)

    # -- opening a case ----------------------------------------------------

    def open_case_dialog(self) -> None:
        """Ask for a folder and open it. Cancelling changes nothing."""
        directory = self._choose_directory(self._strings["choose_case"])
        if directory is not None:
            self.open_case(directory)

    def _ask_for_directory(self, title: str) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(self, title)
        return Path(chosen) if chosen else None

    def _show_message(self, title: str, body: str) -> None:
        QMessageBox.warning(self, title, body)

    def set_dialogs(
        self,
        *,
        choose_directory=None,
        report=None,
    ) -> None:
        """Replace the modal dialogs, for tests and for scripted runs."""
        if choose_directory is not None:
            self._choose_directory = choose_directory
        if report is not None:
            self._report = report

    def open_case(self, path: Path) -> None:
        """Open a case, build its plan, and show it in the Run view.

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

        self.set_active_case(case.name)
        self._preprocessor.set_case(case)
        self._vandv.set_case(
            case,
            version=self._runtime.openfoam_version if self._runtime else "",
            dictionary_name=self._turbulence_dictionary(),
        )
        self._post.set_context(self._session, case.path)
        # New cases land beside the one just opened, which is where a user who
        # keeps their work in one folder expects to find them.
        self._library.set_destination(case.path.parent)
        if self._session is not None:
            self._run.set_context(self._session, case.path, plan)
            self.show_view("run")
        else:
            # A case can be opened without a runtime; it just cannot be run. Said
            # plainly rather than by leaving the Run button mysteriously dead.
            self._report(self._strings["no_runtime_title"], self._strings["no_runtime_body"])
            self.show_view("setup")

        if restored:
            log_event(_log, Event.CASE_WRITE, case=str(path), action="restore_initial")

    # -- for tests ---------------------------------------------------------

    @property
    def footer(self) -> StatusFooter:
        return self._footer

    @property
    def rail(self) -> NavRail:
        return self._rail

    @property
    def hub(self) -> HubView:
        return self._hub

    def view(self, key: str) -> QWidget:
        return self._views[key]

    @property
    def run_view(self) -> RunView:
        return self._run

    @property
    def preprocessor(self) -> PreprocessorView:
        return self._preprocessor

    @property
    def vandv(self) -> VandVView:
        return self._vandv

    @property
    def post(self) -> PostView:
        return self._post

    @property
    def library(self) -> LibraryView:
        return self._library

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
        self._preprocessor.shutdown()
        super().closeEvent(event)
