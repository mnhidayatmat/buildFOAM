"""The automated contrast check (§12.5, NFR-A2).

§12.5 requires "automated contrast check in CI" and M7's exit criterion is that
it passes on every view. This file is that check.

It is arithmetic on the palette rather than pixel sampling of a rendered window,
which makes it deterministic, instant, and able to run before any widget exists.
The trade is that it verifies the *tokens*, not the composition — a widget that
paints its own colour outside the palette would slip past. The style sheet is
therefore the only place colours are set, and the tokens are the only place
colours are defined.

The point is not that today's palette passes. It is that the next person to
adjust a colour cannot push it below legibility without the build saying so.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from foamwb.ui.theme import (
    DARK,
    LIGHT,
    Palette,
    contrast_ratio,
    relative_luminance,
    status_glyph,
    stylesheet,
    theme_glyph,
)

PALETTES = [LIGHT, DARK]
PALETTE_IDS = [p.name for p in PALETTES]

#: WCAG 2.1 AA: 4.5:1 for body text, 3:1 for large text and UI boundaries.
BODY_MINIMUM = 4.5
NON_TEXT_MINIMUM = 3.0


def _text_pairs(palette: Palette) -> list[tuple[str, str, str]]:
    """(description, foreground, background) for everything rendered as text."""
    return [
        ("body text on the main panel", palette.text, palette.bg),
        ("body text on a raised surface", palette.text, palette.surface),
        ("body text on a hover fill", palette.text, palette.surface_alt),
        # "Muted" describes emphasis, not legibility, so secondary text is held
        # to the same 4.5:1 as primary text.
        ("secondary text on the main panel", palette.text_muted, palette.bg),
        ("secondary text on a raised surface", palette.text_muted, palette.surface),
        ("accent text on the main panel", palette.accent, palette.bg),
        ("text on an accent fill", palette.on_accent, palette.accent),
        ("ready status", palette.ready, palette.surface),
        ("degraded status", palette.degraded, palette.surface),
        ("missing status", palette.missing, palette.surface),
        ("broken status", palette.broken, palette.surface),
    ]


def _non_text_pairs(palette: Palette) -> list[tuple[str, str, str]]:
    return [
        ("border on the main panel", palette.border, palette.bg),
        ("border on a raised surface", palette.border, palette.surface),
        ("border on a hover fill", palette.border, palette.surface_alt),
        ("focus ring on the main panel", palette.focus, palette.bg),
        ("focus ring on a raised surface", palette.focus, palette.surface),
    ]


class TestContrast:
    @pytest.mark.parametrize("palette", PALETTES, ids=PALETTE_IDS)
    def test_all_text_meets_wcag_aa(self, palette: Palette) -> None:
        failures = [
            f"{palette.name}: {what} — {contrast_ratio(fg, bg):.2f}:1 "
            f"({fg} on {bg}), needs {BODY_MINIMUM}:1"
            for what, fg, bg in _text_pairs(palette)
            if contrast_ratio(fg, bg) < BODY_MINIMUM
        ]
        assert not failures, "\n".join(failures)

    @pytest.mark.parametrize("palette", PALETTES, ids=PALETTE_IDS)
    def test_borders_and_focus_rings_meet_the_non_text_minimum(self, palette: Palette) -> None:
        # A focus ring below 3:1 is invisible, which would silently break the
        # keyboard-only pass M7 gates on (NFR-A1).
        failures = [
            f"{palette.name}: {what} — {contrast_ratio(fg, bg):.2f}:1, needs {NON_TEXT_MINIMUM}:1"
            for what, fg, bg in _non_text_pairs(palette)
            if contrast_ratio(fg, bg) < NON_TEXT_MINIMUM
        ]
        assert not failures, "\n".join(failures)

    def test_the_formula_matches_known_reference_values(self) -> None:
        # Anchors the implementation against the published examples, so a bug in
        # the luminance maths cannot make a failing palette look compliant.
        assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
        assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0, abs=0.001)
        assert contrast_ratio("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)

    def test_ratio_is_symmetric(self) -> None:
        assert contrast_ratio("#123456", "#ABCDEF") == pytest.approx(
            contrast_ratio("#ABCDEF", "#123456")
        )

    def test_luminance_bounds(self) -> None:
        assert relative_luminance("#000000") == pytest.approx(0.0)
        assert relative_luminance("#FFFFFF") == pytest.approx(1.0)

    @pytest.mark.parametrize("bad", ["#FFF", "red", "", "#GGGGGG!"])
    def test_malformed_colours_are_refused(self, bad: str) -> None:
        with pytest.raises(ValueError):
            relative_luminance(bad)


class TestColourIsNeverTheSoleCarrier:
    """NFR-A2's second clause, which is the one that is easy to forget."""

    def test_every_status_has_a_distinct_glyph(self) -> None:
        glyphs = [status_glyph(s) for s in ("ready", "degraded", "missing", "broken")]
        assert len(set(glyphs)) == len(glyphs)

    def test_an_unknown_state_does_not_raise(self) -> None:
        # The footer must never be the thing that crashes: it is the component
        # that is supposed to still be telling the truth when everything else has
        # gone wrong.
        assert status_glyph("something-new")

    def test_every_theme_choice_has_a_distinct_glyph(self) -> None:
        glyphs = [theme_glyph(c) for c in ("light", "dark", "system")]
        assert len(set(glyphs)) == len(glyphs)

    def test_theme_and_status_glyphs_do_not_collide(self) -> None:
        # The two controls sit side by side in the footer, so a shared glyph
        # would make them ambiguous in exactly the greyscale screenshot NFR-A2
        # exists to keep readable.
        statuses = {status_glyph(s) for s in ("ready", "degraded", "missing", "broken")}
        themes = {theme_glyph(c) for c in ("light", "dark", "system")}
        assert not statuses & themes

    def test_an_unknown_choice_does_not_raise(self) -> None:
        assert theme_glyph("solarized")


class TestPalettes:
    def test_light_and_dark_define_the_same_tokens(self) -> None:
        # A token defined in one theme and missing from the other would render as
        # an empty string in a style sheet and silently fall back to the platform
        # colour, which is how a dark theme ends up with one white panel.
        assert LIGHT.__slots__ == DARK.__slots__

    def test_every_token_is_a_hex_colour(self) -> None:
        for palette in PALETTES:
            for field in palette.__slots__:
                value = getattr(palette, field)
                if field == "name":
                    continue
                assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"{palette.name}.{field}"

    def test_the_two_themes_are_actually_different(self) -> None:
        assert relative_luminance(LIGHT.bg) > relative_luminance(DARK.bg)


class TestStylesheet:
    @pytest.mark.parametrize("palette", PALETTES, ids=PALETTE_IDS)
    def test_renders_and_uses_only_palette_colours(self, palette: Palette) -> None:
        css = stylesheet(palette)
        assert css.strip()
        allowed = {getattr(palette, f).lower() for f in palette.__slots__ if f != "name"}
        used = {c.lower() for c in re.findall(r"#[0-9A-Fa-f]{6}", css)}
        assert used <= allowed, f"colours outside the palette: {sorted(used - allowed)}"

    @pytest.mark.parametrize("palette", PALETTES, ids=PALETTE_IDS)
    def test_defines_a_visible_focus_indicator(self, palette: Palette) -> None:
        # NFR-A1 requires visible focus indicators throughout. Declared once for
        # every focusable widget so a new control cannot forget it.
        css = stylesheet(palette)
        assert "*:focus" in css
        assert palette.focus.lower() in css.lower()

    @pytest.mark.parametrize("palette", PALETTES, ids=PALETTE_IDS)
    def test_braces_are_balanced(self, palette: Palette) -> None:
        # A stray brace from an f-string mistake silently truncates every rule
        # after it, and Qt reports nothing.
        css = stylesheet(palette)
        assert css.count("{") == css.count("}")


#: Widget classes the sheet deliberately does not name, and why.
#:
#: These are containers and layout devices with nothing of their own to paint —
#: they show whatever their children and the blanket ``QWidget`` rule put on
#: screen — so a rule for them would style nothing.
_NEEDS_NO_RULE = {
    "QApplication",
    "QDialog",
    "QFileDialog",
    "QInputDialog",
    "QFrame",
    "QGridLayout",
    "QHBoxLayout",
    "QFormLayout",
    "QMainWindow",
    "QMessageBox",
    "QStackedWidget",
    "QVBoxLayout",
    "QWidget",
    "QListWidgetItem",
    "QTreeWidgetItem",
    "QTableWidgetItem",
    "QActionGroup",
    "QAction",
    # Not a widget: it coordinates buttons that are themselves styled, and
    # paints nothing of its own.
    "QButtonGroup",
    "QSizePolicy",
    "QKeySequence",
    "QShortcut",
}


class TestWidgetCoverage:
    """Every widget class a view uses is styled from the palette.

    Qt renders anything the sheet does not mention in the *native* style, whose
    defaults are chosen for a light window: a near-white scroll bar track, a
    near-white header, a text field outlined by a hairline meant to sit on white.
    On the dark palette those are wrong in a way no contrast check catches,
    because they never consult the palette at all — the sweep in
    ``test_contrast_sweep.py`` resolves colours *from the style sheet*, so a
    widget the sheet says nothing about is a widget it cannot judge.

    This is the guard that failed silently before: nineteen tree widgets, ten
    line edits and six tab widgets had accumulated across the views without one
    rule between them, and nothing said so until someone opened the application
    in dark mode.
    """

    def _classes_used(self) -> set[str]:
        source_root = Path(__file__).resolve().parent.parent / "src" / "foamwb" / "ui"
        found: set[str] = set()
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # The import is what states the dependency; a bare Name would
                # also match strings and attribute chains that are not widgets.
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "PySide6.QtWidgets"
                ):
                    found.update(alias.name for alias in node.names)
        return {name for name in found if name.startswith("Q")}

    def test_every_widget_class_in_use_is_styled(self) -> None:
        css = stylesheet(LIGHT)
        unstyled = sorted(
            name
            for name in self._classes_used() - _NEEDS_NO_RULE
            if not re.search(rf"\b{name}\b", css)
        )
        assert not unstyled, (
            "these widget classes are used in a view but have no rule in "
            f"theme.stylesheet(), so Qt will draw them in the native style: {unstyled}"
        )
