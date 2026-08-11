"""The persistent status footer (FR-A2, §7.1).

"The status footer never lies" is §7.9's fourth interaction principle, and it is
the reason this widget renders from a :class:`RuntimeStatus` value rather than
from strings its callers assemble. A caller cannot forget to update it, and it
cannot show *ready* while holding an error code, because
:class:`~foamwb.services.runtime.status.RuntimeStatus` refuses to be constructed
that way (FR-R2).

The runtime indicator is a button, not a label: §7.1 requires clicking it to jump
to Setup. That also makes it keyboard-reachable, which a label would not be
(NFR-A1).

The theme selector lives here for the same reason the runtime indicator does: it
is global, it belongs to no view, and the footer is the only chrome visible from
all of them. It is a menu rather than a button that cycles, because cycling three
states means a user who overshoots has to go round again, and because a menu can
show which one is currently in force — which a cycling button cannot.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget

from foamwb.services.runtime import RuntimeStatus
from foamwb.services.settings import DEFAULT_THEME, ThemeChoice
from foamwb.ui.theme import Palette, status_glyph, theme_glyph

__all__ = ["StatusFooter"]


class StatusFooter(QFrame):
    """Always-visible strip: runtime state, OpenFOAM version, case, run state."""

    setup_requested = Signal()
    """Emitted when the user activates the runtime indicator (§7.1)."""

    theme_requested = Signal(str)
    """A :class:`~foamwb.services.settings.ThemeChoice` value the user picked.

    A request, not a change: the footer does not repaint anything or write any
    preference. The shell owns both, so the window and the stored setting cannot
    end up disagreeing about which theme is in force.
    """

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusFooter")
        self._palette = palette
        # The last status rendered, so a theme change can repaint it. Without
        # this the indicator would keep the old theme's colour until the next
        # detection — which on a ready runtime is never.
        self._status: RuntimeStatus | None = None

        self._indicator = QToolButton()
        self._indicator.setObjectName("runtimeIndicator")
        self._indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self._indicator.clicked.connect(self.setup_requested)
        self._indicator.setToolTip(self.tr("Go to Setup"))

        self._version = QLabel()
        self._case = QLabel()
        self._run_state = QLabel()
        for label in (self._version, self._case, self._run_state):
            label.setProperty("role", "muted")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 12, 4)
        layout.setSpacing(10)
        layout.addWidget(self._indicator)
        layout.addWidget(self._separator())
        layout.addWidget(self._version)
        layout.addWidget(self._separator())
        layout.addWidget(self._case)
        layout.addStretch(1)
        layout.addWidget(self._run_state)
        layout.addWidget(self._separator())
        layout.addWidget(self._build_theme_selector())

        self.set_case(None)
        self.set_run_state(None)

    def _separator(self) -> QLabel:
        dot = QLabel("·")
        dot.setProperty("role", "muted")
        return dot

    def _build_theme_selector(self) -> QToolButton:
        """The appearance menu: Light, Dark, or follow the desktop (NFR-A4)."""
        self._theme = ThemeChoice(DEFAULT_THEME)
        self._theme_labels = {
            ThemeChoice.LIGHT: self.tr("Light"),
            ThemeChoice.DARK: self.tr("Dark"),
            ThemeChoice.SYSTEM: self.tr("System"),
        }

        button = QToolButton()
        button.setObjectName("themeSelector")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setToolTip(self.tr("Appearance"))
        # InstantPopup rather than a click-then-hold: there is no default action
        # a single click could mean, and a button that silently did nothing on
        # click would read as broken.
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(button)
        # Exclusive, so the menu states a fact — exactly one theme is in force —
        # rather than offering three independent switches.
        group = QActionGroup(menu)
        group.setExclusive(True)

        self._theme_actions: dict[ThemeChoice, QAction] = {}
        for choice, label in self._theme_labels.items():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, c=choice: self.theme_requested.emit(c.value)
            )
            group.addAction(action)
            self._theme_actions[choice] = action

        button.setMenu(menu)
        self._theme_button = button
        self._theme_menu = menu
        self.set_theme_choice(self._theme)
        return button

    def set_theme_choice(self, choice: ThemeChoice) -> None:
        """Show which theme is in force. Does not emit :attr:`theme_requested`.

        Silent for the same reason :meth:`~foamwb.ui.navrail.NavRail.select` is:
        this is how the *shell* tells the footer what happened, and echoing it
        back would loop, as well as making a restore at startup indistinguishable
        from a user choosing the same value.
        """
        self._theme = ThemeChoice(choice)
        for candidate, action in self._theme_actions.items():
            action.setChecked(candidate is self._theme)

        label = self._theme_labels[self._theme]
        # A catalogue format string, not an f-string, so a right-to-left locale
        # can put the glyph after the label (NFR-A5).
        glyph = theme_glyph(self._theme.value)
        self._theme_button.setText(self.tr("{0}  {1}").format(glyph, label))
        self._theme_button.setAccessibleName(self.tr("Appearance: {0}").format(label))

    # -- state -------------------------------------------------------------

    def set_runtime_status(self, status: RuntimeStatus) -> None:
        """Render a runtime status.

        Colour, glyph *and* text all change together — NFR-A2 forbids colour as
        the sole carrier of meaning, so this reads correctly in greyscale and to a
        colourblind user. A non-ready state also shows its §9 code, because that
        is what turns a support conversation into something that starts from a
        code rather than a screenshot.
        """
        self._status = status
        state = status.state.value
        labels = {
            "ready": self.tr("Runtime ready"),
            "degraded": self.tr("Runtime degraded"),
            "missing": self.tr("Runtime not installed"),
            "broken": self.tr("Runtime broken"),
        }
        text = labels.get(state, self.tr("Runtime unknown"))
        if status.reason is not None:
            text = f"{text} ({status.reason.id})"

        # A format string rather than an f-string, so a right-to-left locale can
        # put the glyph after the label (NFR-A5).
        self._indicator.setText(self.tr("{0}  {1}").format(status_glyph(state), text))
        colour = getattr(self._palette, state, self._palette.text_muted)
        self._indicator.setStyleSheet(f"#runtimeIndicator {{ color: {colour}; }}")

        # The accessible name carries the same information as the glyph, so a
        # screen reader is not told to interpret a bullet character.
        self._indicator.setAccessibleName(text)

    def set_openfoam_version(self, version: str | None) -> None:
        # Never a literal in code — the version comes from the runtime manifest
        # via the canary command (NFR-M3, FR-R5).
        self._version.setText(
            self.tr("OpenFOAM {0}").format(version) if version else self.tr("No OpenFOAM detected")
        )

    def set_case(self, case_name: str | None) -> None:
        self._case.setText(case_name if case_name else self.tr("No case open"))

    def set_run_state(self, run_state: str | None) -> None:
        self._run_state.setText(run_state if run_state else self.tr("idle"))

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette and repaint what was already drawn (NFR-A4).

        The runtime indicator is the only thing here that carries an inline
        colour, and it is the one part of the window §7.9 rule 4 says must never
        be wrong — so it is re-rendered from the stored status rather than left
        showing the previous theme's green.
        """
        self._palette = palette
        if self._status is not None:
            self.set_runtime_status(self._status)

    # -- for tests ---------------------------------------------------------

    @property
    def runtime_text(self) -> str:
        return self._indicator.text()

    @property
    def version_text(self) -> str:
        return self._version.text()

    @property
    def case_text(self) -> str:
        return self._case.text()

    @property
    def run_state_text(self) -> str:
        return self._run_state.text()

    @property
    def theme_choice(self) -> ThemeChoice:
        return self._theme

    @property
    def theme_text(self) -> str:
        return self._theme_button.text()

    def choose_theme(self, choice: ThemeChoice) -> None:
        """Activate the menu entry for ``choice``, as a click would."""
        self._theme_actions[ThemeChoice(choice)].trigger()
