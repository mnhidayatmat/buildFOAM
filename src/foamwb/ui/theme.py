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
    """
    return f"""
QWidget {{
    background-color: {palette.bg};
    color: {palette.text};
    font-size: 13px;
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

QListWidget {{
    background-color: {palette.bg};
    border: 1px solid {palette.border};
    border-radius: 8px;
}}

QListWidget::item {{
    padding: 10px 12px;
    border-bottom: 1px solid {palette.border};
}}

QListWidget::item:selected {{
    background-color: {palette.accent};
    color: {palette.on_accent};
}}

/* Focus is always visible, on every focusable control (NFR-A1). Stated once
   here rather than per widget, so a new control cannot forget it. */
*:focus {{
    outline: none;
    border: 2px solid {palette.focus};
}}
"""
