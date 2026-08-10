"""The left navigation rail (§7.1).

Icon plus label, collapsible to icons only. One button per view, exclusive
selection, and the selected button drives the main panel's stack.

Views are declared as data rather than as seven near-identical constructor calls,
so the rail, the stack and the keyboard shortcuts cannot fall out of step — a
view added to the list gets all three or none.

Glyphs stand in for icons. §7.1 specifies icon + label and NFR-A3 forbids
rasterised assets below 2x; text glyphs are resolution-independent by
construction, so they are the honest placeholder until drawn icons exist, rather
than a bitmap that would have to be redone at 2x and 3x.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["NAV_ITEMS", "NavItem", "NavRail"]


@dataclass(frozen=True, slots=True)
class NavItem:
    key: str
    """Stable identifier. Used by the stack, run history and diagnostics; never
    shown to the user, so it is not translated."""

    glyph: str
    shortcut: str
    """``Ctrl+<n>`` — every view reachable from the keyboard alone (NFR-A1)."""


#: Order matches §7.1, which is also workflow order: set up, prepare, run, look
#: at results. Cases sits second because a returning user's first action is
#: almost always to reopen one.
NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("hub", "⌂", "Ctrl+1"),
    NavItem("cases", "▤", "Ctrl+2"),
    NavItem("setup", "⚙", "Ctrl+3"),
    NavItem("run", "▶", "Ctrl+4"),
    NavItem("post", "◈", "Ctrl+5"),
    NavItem("vv", "∿", "Ctrl+6"),
    NavItem("library", "⧉", "Ctrl+7"),
    NavItem("guide", "?", "Ctrl+8"),
)


class NavRail(QFrame):
    """Exclusive, keyboard-navigable view selector."""

    view_selected = Signal(str)

    EXPANDED_WIDTH = 148
    COLLAPSED_WIDTH = 52

    def __init__(
        self,
        labels: dict[str, str],
        item_format: str,
        tooltip_format: str,
        parent: QWidget | None = None,
    ) -> None:
        """``labels`` maps each item key to its translated display name.

        ``item_format`` and ``tooltip_format`` compose the glyph with the label
        and the shortcut. They are format strings from the catalogue rather than
        f-strings here, so a right-to-left locale can reorder the parts (NFR-A5).

        All three are passed in rather than looked up, so the rail owns no
        user-visible text of its own.
        """
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setFixedWidth(self.EXPANDED_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._labels = labels
        self._item_format = item_format
        self._tooltip_format = tooltip_format
        self._collapsed = False
        self._buttons: dict[str, QToolButton] = {}

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(2)

        for item in NAV_ITEMS:
            button = self._make_button(item)
            self._buttons[item.key] = button
            self._group.addButton(button)
            layout.addWidget(button)

        layout.addStretch(1)
        self.select("hub")

    def _make_button(self, item: NavItem) -> QToolButton:
        button = QToolButton()
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setShortcut(item.shortcut)
        button.setText(self._item_text(item))

        # The accessible name is the plain label: a screen reader should say
        # "Library", not "⧉ Library".
        button.setAccessibleName(self._labels[item.key])
        button.setToolTip(self._tooltip_format.format(self._labels[item.key], item.shortcut))
        button.clicked.connect(lambda _=False, key=item.key: self.view_selected.emit(key))
        return button

    def _item_text(self, item: NavItem) -> str:
        return self._item_format.format(item.glyph, self._labels[item.key])

    # -- selection ---------------------------------------------------------

    def select(self, key: str) -> None:
        """Check the button for ``key`` without emitting :attr:`view_selected`.

        Silent because this is how the *shell* tells the rail what is showing.
        Emitting here would loop back through the shell and, worse, would make a
        programmatic restore indistinguishable from a user click in the logs.
        """
        button = self._buttons.get(key)
        if button is None:
            raise KeyError(f"Unknown view: {key!r}")
        button.setChecked(True)

    @property
    def current(self) -> str | None:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return None

    def button(self, key: str) -> QToolButton:
        return self._buttons[key]

    # -- collapse ----------------------------------------------------------

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Collapse to icons only, or expand back to icon + label (§7.1).

        The tooltip already carries the label, so a collapsed rail is still
        self-describing on hover, and the accessible name is left untouched so it
        stays self-describing to a screen reader too.
        """
        self._collapsed = collapsed
        self.setFixedWidth(self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH)
        for item in NAV_ITEMS:
            button = self._buttons[item.key]
            button.setText(item.glyph if collapsed else self._item_text(item))

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)
