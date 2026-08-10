"""The application shell: nav rail, view stack, status footer (§7.1).

Three regions, as specified. The shell owns the wiring and nothing else — it
holds no case, runs no command and parses no dictionary. Everything it displays
arrives through a setter, which is what lets the whole window be driven from a
test without a runtime, a case, or a display.

The stack is built from :data:`~foamwb.ui.navrail.NAV_ITEMS`, the same list that
builds the rail and the shortcuts, so a view cannot exist in one and be missing
from another.
"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from foamwb.branding import APP_DISPLAY_NAME
from foamwb.codes import ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.recents import RecentCase
from foamwb.services.runtime import RuntimeState, RuntimeStatus
from foamwb.ui import strings
from foamwb.ui.footer import StatusFooter
from foamwb.ui.navrail import NAV_ITEMS, NavRail
from foamwb.ui.theme import Palette
from foamwb.ui.views.hub import HubView
from foamwb.ui.views.placeholder import PlaceholderView

__all__ = ["Shell"]

_log = get_logger("ui.shell")


class Shell(QMainWindow):
    """Main window."""

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._strings = strings.shell_strings()
        self._placeholders = strings.view_placeholders()

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumSize(960, 640)

        self._rail = NavRail(
            strings.nav_labels(),
            item_format=self._strings["nav_item"],
            tooltip_format=self._strings["nav_tooltip"],
        )
        self._stack = QStackedWidget()
        self._footer = StatusFooter(palette)

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
        self.show_view("hub")

    # -- construction ------------------------------------------------------

    def _build_views(self) -> None:
        self._hub = HubView(self._strings)
        self._views["hub"] = self._hub
        self._stack.addWidget(self._hub)

        for item in NAV_ITEMS:
            if item.key == "hub":
                continue
            title, detail = self._placeholders[item.key]
            view = PlaceholderView(title, detail)
            self._views[item.key] = view
            self._stack.addWidget(view)

    def _connect(self) -> None:
        self._rail.view_selected.connect(self.show_view)
        self._footer.setup_requested.connect(lambda: self.show_view("setup"))
        self._hub.setup_requested.connect(lambda: self.show_view("setup"))
        self._hub.action_triggered.connect(self._on_hub_action)
        self._hub.case_opened.connect(self._on_case_opened)

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
        self._footer.set_runtime_status(status)
        message = strings.runtime_banner_message(
            status.state.value, status.reason.id if status.reason else None
        )
        self._hub.set_runtime_status(status, message)

    def set_openfoam_version(self, version: str | None) -> None:
        self._footer.set_openfoam_version(version)

    def set_active_case(self, case_name: str | None) -> None:
        self._footer.set_case(case_name)
        self.setWindowTitle(f"{case_name} — {APP_DISPLAY_NAME}" if case_name else APP_DISPLAY_NAME)

    def set_run_state(self, run_state: str | None) -> None:
        self._footer.set_run_state(run_state)

    def set_recent_cases(self, cases: list[RecentCase]) -> None:
        self._hub.set_recent_cases(cases)

    # -- handlers ----------------------------------------------------------

    @Slot(str)
    def _on_hub_action(self, action: str) -> None:
        """Route a Hub action.

        Everything except navigation needs a service that does not exist yet, so
        those actions route to the view that will own them. Wiring them to
        nothing would make the Hub's buttons dead on arrival, which FR-A1's
        "every target reachable in one click" forbids.
        """
        destinations = {"library": "library", "guide": "guide", "settings": "setup"}
        if action in destinations:
            self.show_view(destinations[action])
        else:
            self.show_view("cases")

    @Slot(RecentCase)
    def _on_case_opened(self, case: RecentCase) -> None:
        self.set_active_case(case.name)
        self.show_view("cases")

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
