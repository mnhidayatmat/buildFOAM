"""The Hub view (FR-A1, §7.2).

Recent cases are the *primary* content and the actions are secondary, which is
the opposite of the usual launcher layout and is deliberate: a returning user's
first action is almost always "continue what I was doing", so making them hunt
past a wall of buttons to find yesterday's case would tax the common path to
decorate the rare one.

The runtime banner appears **only when the runtime is not ready** (§7.2). A
permanent "everything is fine" strip trains users to ignore the region, which is
exactly the region that has to be noticed on the day it says something else.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.recents import RecentCase
from foamwb.services.runtime import RuntimeStatus

__all__ = ["HubView"]


class HubView(QWidget):
    """Landing view: recent cases, then large launch targets."""

    case_opened = Signal(RecentCase)
    action_triggered = Signal(str)
    """Carries an action key: ``new_case``, ``open_case``, ``library``,
    ``guide``, ``case_folder``, ``settings``."""

    setup_requested = Signal()

    #: (key, whether it is a primary action). Order is §7.2's.
    ACTIONS: tuple[tuple[str, bool], ...] = (
        ("new_case", True),
        ("open_case", True),
        ("library", False),
        ("guide", False),
        ("case_folder", False),
        ("settings", False),
    )

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels = labels

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        heading = QLabel(labels["hub_heading"])
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        self._banner = self._build_banner(labels)
        layout.addWidget(self._banner)

        recent_heading = QLabel(labels["recent_cases"])
        recent_heading.setProperty("role", "subheading")
        layout.addWidget(recent_heading)

        self._recent_list = QListWidget()
        self._recent_list.setAccessibleName(labels["recent_cases"])
        self._recent_list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self._recent_list, stretch=1)

        self._empty_hint = QLabel(labels["no_recent_cases"])
        self._empty_hint.setProperty("role", "muted")
        self._empty_hint.setWordWrap(True)
        # Takes the list's stretch when the list is hidden, aligned to the top so
        # the hint sits under its heading instead of drifting into the middle of
        # an empty pane.
        layout.addWidget(self._empty_hint, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(self._build_actions(labels))

        self.set_recent_cases([])

    # -- construction ------------------------------------------------------

    def _build_banner(self, labels: dict[str, str]) -> QFrame:
        banner = QFrame()
        banner.setObjectName("runtimeBanner")
        banner.setVisible(False)

        row = QHBoxLayout(banner)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        self._banner_text = QLabel()
        self._banner_text.setWordWrap(True)
        row.addWidget(self._banner_text, stretch=1)

        # §7.9 rule 1: every error state offers at least one action. Marked as
        # the default button so it is styled as the primary action and answers
        # Enter, which is what a keyboard user will press (NFR-A1).
        self._banner_action = QPushButton(labels["go_to_setup"])
        self._banner_action.setDefault(True)
        self._banner_action.clicked.connect(self.setup_requested)
        row.addWidget(self._banner_action)
        return banner

    def _build_actions(self, labels: dict[str, str]) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        self._action_buttons: dict[str, QPushButton] = {}
        for index, (key, _primary) in enumerate(self.ACTIONS):
            button = QPushButton(labels[f"action_{key}"])
            button.setProperty("role", "hubAction")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setAccessibleName(labels[f"action_{key}"])
            button.clicked.connect(lambda _=False, k=key: self.action_triggered.emit(k))
            grid.addWidget(button, index // 3, index % 3)
            self._action_buttons[key] = button
        return container

    # -- state -------------------------------------------------------------

    def set_recent_cases(self, cases: list[RecentCase]) -> None:
        """Populate the recent list, or show the first-run hint when empty."""
        self._recent_list.clear()
        for case in cases:
            item = QListWidgetItem(self._describe(case))
            item.setData(Qt.ItemDataRole.UserRole, case)
            item.setToolTip(str(case.path))
            self._recent_list.addItem(item)

        has_cases = bool(cases)
        self._recent_list.setVisible(has_cases)
        self._empty_hint.setVisible(not has_cases)

    def _describe(self, case: RecentCase) -> str:
        parts = [case.name]
        if case.solver:
            parts.append(case.solver)
        if case.last_run is not None:
            parts.append(case.last_run.strftime("%Y-%m-%d %H:%M"))
            # Exit status in words, not a bare number: "exit 137" means nothing
            # to P1, and NFR-A6 forbids jargon without an inline explanation.
            parts.append(
                self._labels["run_succeeded"] if case.last_exit == 0 else self._labels["run_failed"]
            )
        else:
            parts.append(self._labels["never_run"])
        return "   ·   ".join(parts)

    def set_runtime_status(self, status: RuntimeStatus, message: str) -> None:
        """Show or hide the runtime banner (§7.2)."""
        if status.state.value == "ready":
            self._banner.setVisible(False)
            return
        self._banner_text.setText(message)
        self._banner.setVisible(True)

    # -- signals -----------------------------------------------------------

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        case = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(case, RecentCase):
            self.case_opened.emit(case)

    # -- for tests ---------------------------------------------------------

    @property
    def banner_visible(self) -> bool:
        # isVisibleTo, not isVisible: the latter is False for every descendant of
        # a window that has not been shown, which would make this report "hidden"
        # for reasons that have nothing to do with the runtime.
        return self._banner.isVisibleTo(self)

    @property
    def banner_text(self) -> str:
        return self._banner_text.text()

    @property
    def recent_count(self) -> int:
        return self._recent_list.count()

    def action_button(self, key: str) -> QPushButton:
        return self._action_buttons[key]
