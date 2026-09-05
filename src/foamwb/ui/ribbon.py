"""The ribbon (§7.1, DEC-21).

Fluent's single window puts every action in a ribbon of tabs — *File, Domain,
Physics, Solution, Results, View* — each a row of grouped, captioned buttons.
The same shape here, for the reason P3 exists: an engineer arriving from
commercial CFD looks for *Solution → Run Calculation → Calculate*, and a window
that has it where they expect it is a window they can use without the guide.

Tabs, groups and actions are **declared as data** and the labels come from the
catalogue, so the ribbon, its shortcuts and its tooltips cannot fall out of
step: an action added to the table gets all three or none. The ribbon emits an
action key and does nothing else; what the key *does* is the shell's business,
which is what lets this widget be built and pressed in a test without a case,
a runtime or a display.

*File* is a menu rather than a tab, as it is in Fluent: its entries are dialogs
and destinations, not a row of tools, and a tab full of one-shot commands would
leave the ribbon showing an empty toolbar after each. *Help* sits at the right
end of the tab strip for the same reason.

Every action has a keyboard route (NFR-A1): a shortcut where one is worth
learning, and tab-and-arrow navigation for the rest. Tooltips name the shortcut
so it can be discovered rather than remembered.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.ui.icons import glyph_icon
from foamwb.ui.theme import Palette

__all__ = ["FILE_MENU", "RIBBON_TABS", "Ribbon", "RibbonAction", "RibbonGroup", "RibbonTab"]


@dataclass(frozen=True, slots=True)
class RibbonAction:
    key: str
    """Stable identifier, emitted when pressed. Never shown, so not translated."""

    glyph: str
    shortcut: str = ""


@dataclass(frozen=True, slots=True)
class RibbonGroup:
    key: str
    actions: tuple[RibbonAction, ...]


@dataclass(frozen=True, slots=True)
class RibbonTab:
    key: str
    groups: tuple[RibbonGroup, ...]


#: The File menu, top to bottom. ``None`` is a separator. ``recent`` is a
#: submenu the shell fills.
FILE_MENU: tuple[str | None, ...] = (
    "new_case",
    "open_case",
    "recent",
    None,
    "import_geometry_menu",
    "case_files",
    None,
    "library",
    "case_folder",
    None,
    "settings",
    None,
    "exit",
)

#: Shortcuts for menu entries. Ctrl+N and Ctrl+O are the two every desktop
#: application shares; the rest are left to the menu.
FILE_SHORTCUTS: dict[str, str] = {"new_case": "Ctrl+N", "open_case": "Ctrl+O"}

#: The tabs, in order. Groups mirror Fluent's where the action exists here.
RIBBON_TABS: tuple[RibbonTab, ...] = (
    RibbonTab(
        "domain",
        (
            RibbonGroup(
                "mesh",
                (RibbonAction("check_mesh", "✓"), RibbonAction("display_mesh", "▦", "Ctrl+M")),
            ),
            RibbonGroup(
                "geometry",
                (RibbonAction("import_geometry", "⤓"), RibbonAction("describe_geometry", "◐")),
            ),
            RibbonGroup("sizing", (RibbonAction("local_sizing", "⊞"),)),
            RibbonGroup("zones", (RibbonAction("update_boundaries", "▭"),)),
            RibbonGroup("generate", (RibbonAction("volume_mesh", "⬢", "Ctrl+G"),)),
        ),
    ),
    RibbonTab(
        "physics",
        (
            RibbonGroup("solver", (RibbonAction("general", "⚙"),)),
            RibbonGroup("models", (RibbonAction("models", "∿"),)),
            RibbonGroup("materials", (RibbonAction("materials", "◍"),)),
            RibbonGroup("zones", (RibbonAction("boundary_conditions", "▤"),)),
            RibbonGroup("reference", (RibbonAction("reference_values", "≡"),)),
        ),
    ),
    RibbonTab(
        "solution",
        (
            RibbonGroup("methods", (RibbonAction("methods", "∂"),)),
            RibbonGroup("controls", (RibbonAction("controls", "⇅"),)),
            RibbonGroup("monitors", (RibbonAction("monitors", "◉"),)),
            RibbonGroup("initialization", (RibbonAction("initialization", "⟲"),)),
            RibbonGroup("activities", (RibbonAction("activities", "⏱"),)),
            RibbonGroup(
                "run",
                (
                    RibbonAction("check_case", "☑", "Ctrl+K"),
                    # F5 is the chord Workbench users already have for *Update
                    # Project*, and it is the one action here that answers "make
                    # this case true again" rather than "run this stage".
                    RibbonAction("update", "↻", "F5"),
                    RibbonAction("calculate", "▶", "Ctrl+R"),
                    RibbonAction("stop_write", "■", "Ctrl+."),
                ),
            ),
        ),
    ),
    RibbonTab(
        "results",
        (
            RibbonGroup("graphics", (RibbonAction("graphics", "▦"), RibbonAction("paraview", "◈"))),
            RibbonGroup("plots", (RibbonAction("residuals", "∿", "Ctrl+Shift+R"),)),
            RibbonGroup("reports", (RibbonAction("reports", "▤"),)),
            RibbonGroup("export", (RibbonAction("export_csv", "⇩"),)),
        ),
    ),
    RibbonTab(
        "view",
        (
            RibbonGroup("display", (RibbonAction("reset_view", "⌂"),)),
            RibbonGroup(
                "layout",
                (
                    RibbonAction("toggle_outline", "▯", "Ctrl+B"),
                    RibbonAction("toggle_task_page", "▯"),
                    RibbonAction("toggle_console", "▁", "Ctrl+J"),
                ),
            ),
            RibbonGroup(
                "appearance",
                (
                    RibbonAction("theme_light", "☀"),
                    RibbonAction("theme_dark", "☾"),
                    RibbonAction("theme_system", "◐"),
                ),
            ),
        ),
    ),
)


def _every_action() -> tuple[RibbonAction, ...]:
    return tuple(action for tab in RIBBON_TABS for group in tab.groups for action in group.actions)


class Ribbon(QWidget):
    """Tabs of grouped, captioned buttons. Emits action keys; decides nothing."""

    action_triggered = Signal(str)
    recent_requested = Signal(str)
    """A path from the Recent Cases submenu."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ribbon")
        self._palette = palette
        self._labels = labels
        self._buttons: dict[str, QToolButton] = {}
        self._menu_actions: dict[str, QAction] = {}
        self._glyphs: dict[str, str] = {}
        #: Each button's own tooltip, kept so that re-enabling an action can put
        #: back the sentence *with its shortcut*. Recomposing it instead lost
        #: the shortcut, which is the only place NFR-A1's keyboard route is
        #: advertised.
        self._tooltips: dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("ribbonTabs")
        self._tabs.setDocumentMode(True)
        self._tabs.setAccessibleName(labels["tab.file"])
        for tab in RIBBON_TABS:
            self._tabs.addTab(self._build_tab(tab), labels[f"tab.{tab.key}"])
        self._tabs.setCornerWidget(self._build_file_button(), Qt.Corner.TopLeftCorner)
        self._tabs.setCornerWidget(self._build_help_button(), Qt.Corner.TopRightCorner)
        layout.addWidget(self._tabs)

        self.set_palette(palette)

    # -- construction ------------------------------------------------------

    def _build_tab(self, tab: RibbonTab) -> QWidget:
        page = QWidget()
        page.setObjectName("ribbonPage")
        row = QHBoxLayout(page)
        row.setContentsMargins(8, 4, 8, 2)
        row.setSpacing(4)
        for index, group in enumerate(tab.groups):
            if index:
                row.addWidget(self._separator())
            row.addWidget(self._build_group(group))
        row.addStretch(1)
        return page

    def _build_group(self, group: RibbonGroup) -> QWidget:
        box = QWidget()
        box.setObjectName("ribbonGroup")
        column = QVBoxLayout(box)
        column.setContentsMargins(4, 0, 4, 0)
        column.setSpacing(2)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(2)
        for action in group.actions:
            buttons.addWidget(self._build_button(action))
        column.addLayout(buttons)

        # The caption under the buttons is what makes a ribbon readable as a
        # ribbon rather than as a toolbar: it names the *kind* of thing the
        # buttons above it do.
        caption = QLabel(self._labels[f"group.{group.key}"])
        caption.setProperty("role", "ribbonCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(caption)
        return box

    def _build_button(self, action: RibbonAction) -> QToolButton:
        label = self._labels[f"action.{action.key}"]
        button = QToolButton()
        button.setObjectName("ribbonButton")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setText(label)
        button.setAccessibleName(label)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        tip = self._labels.get(f"tip.{action.key}", label)
        if action.shortcut:
            button.setShortcut(QKeySequence(action.shortcut))
            tip = self._labels["tip.with_shortcut"].format(tip, action.shortcut)
        button.setToolTip(tip)
        self._tooltips[action.key] = tip
        button.clicked.connect(
            lambda _checked=False, key=action.key: self.action_triggered.emit(key)
        )
        self._buttons[action.key] = button
        self._glyphs[action.key] = action.glyph
        return button

    def _build_file_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ribbonFile")
        button.setText(self._labels["tab.file"])
        button.setAccessibleName(self._labels["tab.file"])
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        menu = QMenu(button)
        for key in FILE_MENU:
            if key is None:
                menu.addSeparator()
                continue
            if key == "recent":
                self._recent = menu.addMenu(self._labels["recent_menu"])
                self.set_recent([])
                continue
            entry = menu.addAction(self._labels[f"action.{key}"])
            if key in FILE_SHORTCUTS:
                entry.setShortcut(QKeySequence(FILE_SHORTCUTS[key]))
                # The shortcut must work while the menu is closed, which a menu
                # action's own shortcut does not: it is scoped to the menu.
                entry.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            entry.triggered.connect(lambda _checked=False, k=key: self.action_triggered.emit(k))
            self._menu_actions[key] = entry
        button.setMenu(menu)
        # The menu's shortcuts need a live parent to be active from; the button
        # is always in the window, so adding them to it is what arms them.
        for entry in self._menu_actions.values():
            button.addAction(entry)
        self._file_button = button
        return button

    def _build_help_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ribbonHelp")
        button.setText(self._labels["action.guide"])
        button.setAccessibleName(self._labels["action.guide"])
        self._tooltips["guide"] = self._labels["tip.with_shortcut"].format(
            self._labels["tip.guide"], "F1"
        )
        button.setToolTip(self._tooltips["guide"])
        button.setShortcut(QKeySequence("F1"))
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.clicked.connect(lambda: self.action_triggered.emit("guide"))
        self._buttons["guide"] = button
        return button

    @staticmethod
    def _separator() -> QWidget:
        line = QWidget()
        line.setObjectName("ribbonSeparator")
        line.setFixedWidth(1)
        return line

    # -- state -------------------------------------------------------------

    def set_recent(self, paths: list[str]) -> None:
        """Fill the Recent Cases submenu."""
        self._recent.clear()
        if not paths:
            empty = self._recent.addAction(self._labels["no_recent_menu"])
            empty.setEnabled(False)
            return
        for path in paths:
            entry = self._recent.addAction(path)
            entry.triggered.connect(lambda _checked=False, p=path: self.recent_requested.emit(p))

    def set_enabled(self, key: str, enabled: bool, *, reason: str = "") -> None:
        """Enable or disable one action, saying why when disabled.

        A greyed button with no explanation is the "why can I not click this?"
        that §7.9 rule 3 exists to answer, so the reason goes into the tooltip.
        """
        button = self._buttons.get(key)
        if button is None:
            entry = self._menu_actions.get(key)
            if entry is not None:
                entry.setEnabled(enabled)
            return
        button.setEnabled(enabled)
        button.setToolTip(reason if (reason and not enabled) else self._tooltips[key])

    def show_tab(self, key: str) -> None:
        for index, tab in enumerate(RIBBON_TABS):
            if tab.key == key:
                self._tabs.setCurrentIndex(index)
                return

    @property
    def current_tab(self) -> str:
        return RIBBON_TABS[self._tabs.currentIndex()].key

    def trigger(self, key: str) -> None:
        """Press an action by key, the way a test or a shortcut would."""
        button = self._buttons.get(key)
        if button is not None:
            if button.isEnabled():
                button.click()
            return
        entry = self._menu_actions.get(key)
        if entry is not None and entry.isEnabled():
            entry.trigger()

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        for key, button in self._buttons.items():
            glyph = self._glyphs.get(key)
            if glyph:
                button.setIcon(glyph_icon(glyph, palette.text))

    # -- inspection --------------------------------------------------------

    @property
    def action_keys(self) -> list[str]:
        return [action.key for action in _every_action()] + ["guide"]

    @property
    def menu_keys(self) -> list[str]:
        return list(self._menu_actions)

    @property
    def tab_keys(self) -> list[str]:
        return [tab.key for tab in RIBBON_TABS]

    def is_enabled(self, key: str) -> bool:
        button = self._buttons.get(key)
        if button is not None:
            return button.isEnabled()
        entry = self._menu_actions.get(key)
        return entry is not None and entry.isEnabled()

    def button(self, key: str) -> QToolButton:
        return self._buttons[key]

    def tooltip_of(self, key: str) -> str:
        button = self._buttons.get(key)
        return button.toolTip() if button is not None else ""
