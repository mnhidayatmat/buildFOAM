"""Design tokens, light and dark, with contrast as a checked property (NFR-A2/A4).

Two requirements shape everything here.

**Contrast is verified, not eyeballed.** NFR-A2 requires WCAG 2.1 AA — 4.5:1 for
body text, 3:1 for large text and UI boundaries. §12.5 requires an automated
contrast check in CI. Both are satisfiable in pure Python, so the palettes below
are asserted against the WCAG formula in ``test_theme.py`` rather than trusted.
A token pair that fails is a build failure, which means a well-meant colour tweak
cannot quietly push the status footer below legibility.

**Colour is never the sole carrier of meaning.** The runtime dot is the obvious
trap: green/amber/red is unreadable to a red-green colourblind user and invisible
in a greyscale screenshot attached to a support ticket. Every status therefore
carries a distinct *glyph shape* and a *text label* alongside its colour, and
:func:`status_glyph` is the single place that mapping lives.

Palettes are plain data with no Qt dependency, so the contrast tests need neither
a display nor a QApplication.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DARK",
    "LIGHT",
    "Palette",
    "contrast_ratio",
    "status_glyph",
    "stylesheet",
    "theme_glyph",
]


@dataclass(frozen=True, slots=True)
class Palette:
    """Semantic colour tokens. Names describe role, never appearance.

    ``surface`` rather than ``light_grey``: the dark palette assigns the same role
    a near-black value, and a name that describes the pigment would be a lie in
    one of the two themes.
    """

    name: str

    bg: str
    """Window background — the main panel."""

    surface: str
    """Raised regions: the nav rail and the footer."""

    surface_alt: str
    """Hover and selection fills."""

    border: str
    """Separators and control outlines. Held to the 3:1 non-text minimum."""

    text: str
    text_muted: str
    """Secondary text. Still held to 4.5:1 — "muted" is not licence to be unreadable."""

    accent: str
    """Primary action and selection."""

    on_accent: str
    """Text drawn on ``accent``."""

    focus: str
    """Keyboard focus ring (NFR-A1). Distinct from ``accent`` so a focused
    primary button still shows a visible ring."""

    ready: str
    degraded: str
    missing: str
    broken: str


LIGHT = Palette(
    name="light",
    bg="#FFFFFF",
    surface="#F2F5F8",
    surface_alt="#E4EAF0",
    border="#76818D",
    text="#151B21",
    text_muted="#586470",
    accent="#0B5FA5",
    on_accent="#FFFFFF",
    focus="#0B5FA5",
    ready="#136B3C",
    degraded="#7A4E00",
    missing="#586470",
    broken="#A3170F",
)

DARK = Palette(
    name="dark",
    bg="#12171D",
    surface="#1A2129",
    surface_alt="#252E38",
    border="#6B7885",
    text="#E7ECF1",
    text_muted="#A7B2BE",
    accent="#6FB4EF",
    on_accent="#0A1219",
    focus="#8FC7F5",
    ready="#4FCB83",
    degraded="#E0A83A",
    missing="#A7B2BE",
    broken="#F08A82",
)


#: Status → (glyph, whether the glyph is filled). The glyph differs in *shape*,
#: not only colour, so the footer stays readable in greyscale and to a
#: colourblind user (NFR-A2).
_STATUS_GLYPHS = {
    "ready": "●",
    "degraded": "◐",
    "missing": "○",
    "broken": "✕",
}


def status_glyph(state: str) -> str:
    """Glyph for a runtime state. Unknown states get a neutral marker.

    Never raises: a footer that throws because it met an unfamiliar state would
    take down the one part of the UI that is supposed to always be truthful.
    """
    return _STATUS_GLYPHS.get(state, "○")


#: Theme choice → glyph, keyed by :class:`~foamwb.services.settings.ThemeChoice`
#: *values* rather than the enum itself, so this module keeps its promise of
#: depending on nothing (the contrast tests import it without a service layer).
#:
#: Shapes again, not colours: the theme control sits in the footer beside the
#: runtime indicator, and the two must stay distinguishable in a greyscale
#: screenshot for the same reason (NFR-A2).
_THEME_GLYPHS = {
    "light": "☀",
    "dark": "☾",
    "system": "◑",
}


def theme_glyph(choice: str) -> str:
    """Glyph for a theme choice. Never raises, for the reason above."""
    return _THEME_GLYPHS.get(choice, "◑")


def _channel(value: float) -> float:
    """sRGB channel → linear, per the WCAG relative-luminance definition."""
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: str) -> float:
    """WCAG 2.1 relative luminance of a ``#rrggbb`` colour."""
    hex_digits = colour.lstrip("#")
    if len(hex_digits) != 6:
        raise ValueError(f"Expected a #rrggbb colour, got {colour!r}")
    red, green, blue = (int(hex_digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.1 contrast ratio, from 1.0 (identical) to 21.0 (black on white)."""
    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def stylesheet(palette: Palette) -> str:
    """Qt style sheet for a palette.

    A style sheet rather than a QPalette because the shell needs component-level
    control the platform palette does not express — the nav rail's selected state,
    the footer's separator — and because one string keeps the light and dark
    definitions impossible to drift apart.

    **Every widget class the application uses is covered here.** Qt falls back to
    the *native* style for anything a sheet does not mention, and every native
    style ships light-biased defaults: a tree header painted near-white, a scroll
    bar track painted near-white, a text field whose border is a hairline chosen
    to sit on a light window. Those defaults are invisible against
    :attr:`Palette.bg` in the dark palette — a text field with no discernible
    border stops reading as something you can type into — and they ignore the
    palette entirely, so a view built from unstyled widgets silently opts out of
    the WCAG guarantee the tokens above are checked against.

    So the rules below are deliberately exhaustive rather than minimal. A widget
    class that appears in a view and not in this sheet is a defect waiting for a
    dark-theme screenshot, and ``test_theme.py`` asserts the classes actually in
    use are all mentioned.
    """
    return f"""
QWidget {{
    background-color: {palette.bg};
    color: {palette.text};
    font-size: 13px;
}}

/* Text-bearing widgets inherit whatever is painted behind them instead of
   repainting the window background over it. Without this, every label inside a
   filled container — a library card, the Hub's runtime banner, the
   post-processing notice — draws its own {palette.bg} rectangle, which reads as
   banding across the card. The alternative is remembering a
   `#thing QLabel {{ background: transparent }}` rule for every new container,
   and the one that gets forgotten is the one that ships. */
QLabel,
QCheckBox,
QRadioButton {{
    background-color: transparent;
}}

QLabel[role="heading"] {{
    font-size: 22px;
    font-weight: 600;
}}

QLabel[role="subheading"] {{
    font-size: 15px;
    font-weight: 600;
}}

QLabel[role="muted"] {{
    color: {palette.text_muted};
}}

/* -- nav rail ------------------------------------------------------------ */

#navRail {{
    background-color: {palette.surface};
    border-right: 1px solid {palette.border};
}}

#navRail QToolButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 8px 10px;
    text-align: left;
    color: {palette.text};
}}

#navRail QToolButton:hover {{
    background-color: {palette.surface_alt};
}}

#navRail QToolButton:checked {{
    background-color: {palette.accent};
    color: {palette.on_accent};
    font-weight: 600;
}}

/* -- footer -------------------------------------------------------------- */

#statusFooter {{
    background-color: {palette.surface};
    border-top: 1px solid {palette.border};
}}

#statusFooter QLabel {{
    background-color: transparent;
}}

#runtimeIndicator {{
    background-color: transparent;
    border: none;
    padding: 2px 6px;
    border-radius: 4px;
    text-align: left;
}}

#runtimeIndicator:hover {{
    background-color: {palette.surface_alt};
}}

#themeSelector {{
    background-color: transparent;
    border: none;
    padding: 2px 6px;
    border-radius: 4px;
    color: {palette.text_muted};
}}

#themeSelector:hover {{
    background-color: {palette.surface_alt};
    color: {palette.text};
}}

/* -- hub ----------------------------------------------------------------- */

QPushButton[role="hubAction"] {{
    background-color: {palette.surface};
    border: 1px solid {palette.border};
    border-radius: 8px;
    padding: 18px 14px;
    font-size: 14px;
    font-weight: 600;
    text-align: left;
}}

QPushButton[role="hubAction"]:hover {{
    background-color: {palette.surface_alt};
    border-color: {palette.accent};
}}

#runtimeBanner {{
    background-color: {palette.surface_alt};
    border: 1px solid {palette.border};
    border-radius: 8px;
}}

/* Children inherit the banner's fill rather than repainting the window
   background over it, which is what the blanket QWidget rule would otherwise
   do — visible as a darker rectangle inside the banner. */
#runtimeBanner QLabel {{
    background-color: transparent;
    border: none;
}}

QPushButton {{
    background-color: {palette.surface};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 6px;
    padding: 7px 14px;
}}

QPushButton:hover {{
    background-color: {palette.surface_alt};
    border-color: {palette.accent};
}}

QPushButton:default {{
    background-color: {palette.accent};
    color: {palette.on_accent};
    border-color: {palette.accent};
    font-weight: 600;
}}

/* A disabled primary button drops its accent fill rather than merely dimming its
   text. Keeping the fill and greying the label puts {palette.text_muted} on
   {palette.accent}, which is a pair the contrast tests do not vouch for and
   which reads, on the dark palette, as a button that is still the primary
   action. Unavailable should look unavailable. */
QPushButton:disabled,
QPushButton:default:disabled {{
    background-color: {palette.surface};
    color: {palette.text_muted};
    border-color: {palette.border};
    font-weight: normal;
}}

/* -- text entry ----------------------------------------------------------- */

/* Filled with {palette.bg} and outlined with {palette.border}, which is held to
   the 3:1 non-text minimum against it — so "you can type here" is carried by a
   boundary the dark palette can actually show, rather than by the native
   hairline that vanishes on a dark window. */
QLineEdit,
QPlainTextEdit,
QTextEdit,
QSpinBox,
QDoubleSpinBox {{
    background-color: {palette.bg};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {palette.accent};
    selection-color: {palette.on_accent};
}}

QLineEdit:disabled,
QPlainTextEdit:disabled,
QTextEdit:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {{
    color: {palette.text_muted};
    background-color: {palette.surface};
}}

QComboBox {{
    background-color: {palette.bg};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 6px;
    padding: 5px 8px;
}}

QComboBox:hover {{
    border-color: {palette.accent};
}}

/* The drop-down indicator is deliberately left to the native style. Qt style
   sheets have no transform, so a chevron built from borders can only be drawn as
   the corner it literally is — and replacing it with an image would mean
   shipping a light and a dark copy of an arrow the platform already draws in the
   right place, at the right size, in the current text colour. */

/* The popup is a separate top-level window, so it does not inherit the view's
   fill and has to be told the palette itself. */
QComboBox QAbstractItemView {{
    background-color: {palette.surface};
    color: {palette.text};
    border: 1px solid {palette.border};
    selection-background-color: {palette.accent};
    selection-color: {palette.on_accent};
}}

/* -- choices -------------------------------------------------------------- */

/* Checked is a *filled* box against an empty outlined one, so the state survives
   greyscale and colour blindness (NFR-A2) — the fill differs in lightness, not
   only in hue. Qt draws no tick once an indicator is styled without an image,
   which is why the filled box has to carry the meaning on its own. */
QCheckBox::indicator,
QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    background-color: {palette.bg};
    border: 1px solid {palette.border};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QCheckBox::indicator:hover,
QRadioButton::indicator:hover {{
    border-color: {palette.accent};
}}

QCheckBox::indicator:checked,
QRadioButton::indicator:checked {{
    background-color: {palette.accent};
    border-color: {palette.accent};
}}

QCheckBox::indicator:disabled,
QRadioButton::indicator:disabled {{
    border-color: {palette.text_muted};
    background-color: {palette.surface};
}}

/* -- lists, trees and tables ---------------------------------------------- */

/* Selection is the palette's accent, not the platform's. The native highlight is
   whatever the desktop was set to, so it changes between machines, is not one of
   the pairs the contrast tests check, and in a screenshot attached to a support
   ticket it looks like a different application. */
QListWidget,
QListView,
QTreeWidget,
QTreeView,
QTableWidget,
QTableView {{
    background-color: {palette.bg};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 8px;
    alternate-background-color: {palette.surface};
    selection-background-color: {palette.accent};
    selection-color: {palette.on_accent};
    outline: none;
}}

QListWidget::item,
QListView::item,
QTreeWidget::item,
QTreeView::item,
QTableWidget::item,
QTableView::item {{
    /* Rows the native style packs to the pixel are given a readable rhythm; a
       patch table at 16px per row reads as one block of text rather than as
       rows a user can aim a mouse at. */
    padding: 5px 6px;
    border: none;
}}

QListWidget::item {{
    padding: 10px 12px;
    border-bottom: 1px solid {palette.border};
}}

QListWidget::item:hover,
QListView::item:hover,
QTreeWidget::item:hover,
QTreeView::item:hover,
QTableWidget::item:hover,
QTableView::item:hover {{
    background-color: {palette.surface_alt};
    color: {palette.text};
}}

QListWidget::item:selected,
QListView::item:selected,
QTreeWidget::item:selected,
QTreeView::item:selected,
QTableWidget::item:selected,
QTableView::item:selected {{
    background-color: {palette.accent};
    color: {palette.on_accent};
}}

QHeaderView {{
    background-color: {palette.surface};
}}

QHeaderView::section {{
    background-color: {palette.surface};
    color: {palette.text_muted};
    padding: 6px 6px;
    border: none;
    border-bottom: 1px solid {palette.border};
    font-weight: 600;
}}

QTableWidget QTableCornerButton::section,
QTableView QTableCornerButton::section {{
    background-color: {palette.surface};
    border: none;
    border-bottom: 1px solid {palette.border};
}}

/* -- tabs ----------------------------------------------------------------- */

QTabWidget::pane {{
    border: 1px solid {palette.border};
    border-radius: 8px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: {palette.surface};
    color: {palette.text_muted};
    border: 1px solid {palette.border};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 14px;
    margin-right: 2px;
}}

/* The selected tab joins the pane it opens onto: same fill, and the accent bar
   states the selection in a second way, so it does not rest on fill alone. */
QTabBar::tab:selected {{
    background-color: {palette.bg};
    color: {palette.text};
    border-bottom: 2px solid {palette.accent};
    font-weight: 600;
}}

QTabBar::tab:hover:!selected {{
    background-color: {palette.surface_alt};
    color: {palette.text};
}}

/* -- scroll bars ---------------------------------------------------------- */

/* The native track is painted near-white by every platform style, which on the
   dark palette is a bright stripe down the side of the window — the single most
   visible way an unstyled widget breaks the theme. The handle uses
   {palette.border}, the token already held to 3:1 against the surfaces it is
   drawn on, so it stays visible without becoming the loudest thing on screen. */
QScrollBar:vertical,
QScrollBar:horizontal {{
    background: transparent;
    border: none;
    margin: 0px;
}}

QScrollBar:vertical {{
    width: 11px;
}}

QScrollBar:horizontal {{
    height: 11px;
}}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {{
    background-color: {palette.border};
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    min-height: 28px;
    margin: 2px 2px 2px 2px;
}}

QScrollBar::handle:horizontal {{
    min-width: 28px;
    margin: 2px 2px 2px 2px;
}}

QScrollBar::handle:hover {{
    background-color: {palette.accent};
}}

/* Stepper arrows removed rather than restyled: they are a 11px target nobody
   can hit reliably, and the pair of arrow boxes is most of what makes the
   native bar look pasted on. */
QScrollBar::add-line,
QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
    border: none;
    background: none;
}}

QScrollBar::add-page,
QScrollBar::sub-page {{
    background: none;
}}

QScrollArea {{
    border: none;
}}

/* -- chrome --------------------------------------------------------------- */

/* Painted flat, so the splitter reads as the gap between two panels rather than
   as the native handle's row of dots. */
QSplitter::handle {{
    background-color: {palette.bg};
}}

QSplitter::handle:hover {{
    background-color: {palette.surface_alt};
}}

QMenu {{
    background-color: {palette.surface};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {palette.accent};
    color: {palette.on_accent};
}}

QMenu::separator {{
    height: 1px;
    background-color: {palette.border};
    margin: 4px 6px;
}}

/* A tooltip is its own top-level window and inherits nothing, so an unstyled one
   stays light while the rest of the window is dark. */
QToolTip {{
    background-color: {palette.surface};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 4px;
    padding: 4px 6px;
}}

QGroupBox {{
    border: 1px solid {palette.border};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0px 4px;
    color: {palette.text_muted};
}}

/* Focus is always visible, on every focusable control (NFR-A1). Stated once
   here rather than per widget, so a new control cannot forget it. */
*:focus {{
    outline: none;
    border: 2px solid {palette.focus};
}}

/* The ring would otherwise be drawn *around the whole scrolling widget* when
   focus lands inside it, and around a scroll bar the user merely dragged —
   neither of which is where the keyboard actually is. */
QScrollArea:focus,
QScrollBar:focus,
QSplitter:focus,
QTabWidget:focus,
QStackedWidget:focus {{
    border: none;
}}
"""
