"""M7 — automated contrast on every view (NFR-A2).

``tests/test_theme.py`` proves the *palette* is sound: every token pair someone
listed meets WCAG. That is necessary and not sufficient. It says nothing about
which pairs a view actually puts together, and a widget combining two tokens
nobody thought to list would pass every existing test while being unreadable.

This sweep constructs each view for real, walks its widget tree, resolves the
foreground and background actually in force for each widget — through its own
stylesheet, then its ancestors', then the application stylesheet — and checks
the pair. In both themes.

Resolution goes through ancestors because that is how Qt style sheets cascade: a
label inside a frame that sets a background is drawn on that background, and
checking the label's own (absent) background against the window default would be
checking a pair that never appears on screen.
"""

from __future__ import annotations

import dataclasses
import re

import pytest
from PySide6.QtWidgets import QWidget

from foamwb.services.guide import load_guide
from foamwb.ui import strings
from foamwb.ui.theme import DARK, LIGHT, Palette, contrast_ratio, stylesheet
from foamwb.ui.views.guide import GuideView
from foamwb.ui.views.hub import HubView
from foamwb.ui.views.initial import InitialConditionsView
from foamwb.ui.views.library import LibraryView
from foamwb.ui.views.post import PostView
from foamwb.ui.views.preprocessor import PreprocessorView
from foamwb.ui.views.regions import RegionsView
from foamwb.ui.views.run import RunView
from foamwb.ui.views.vandv import VandVView
from foamwb.ui.views.verify import VerifyView
from foamwb.ui.widgets.diagnosis_banner import DiagnosisBanner
from foamwb.ui.widgets.property_panel import PropertyPanel
from foamwb.ui.widgets.workflow_nav import WorkflowNav

#: WCAG 2.1 AA for body text. Large text may use 3.0, but nothing here is
#: guaranteed large, so the stricter figure is applied throughout.
AA_TEXT = 4.5

_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.MULTILINE)
_DECL = re.compile(r"([a-z-]+)\s*:\s*([^;]+)", re.IGNORECASE)
_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}")


def _declarations(sheet: str) -> list[dict[str, str]]:
    """Every rule body in a stylesheet, as property maps."""
    if not sheet:
        return []
    found = [
        {name.lower(): value.strip() for name, value in _DECL.findall(body)}
        for _selector, body in _RULE.findall(sheet)
    ]
    # A sheet with no braces is a bare declaration list, which Qt also accepts.
    if not found and ":" in sheet:
        found = [{name.lower(): value.strip() for name, value in _DECL.findall(sheet)}]
    return found


def _colour_in(value: str) -> str | None:
    match = _COLOUR.search(value)
    return match.group(0) if match else None


def _own(widget: QWidget, properties: tuple[str, ...]) -> str | None:
    """A colour this widget's own stylesheet sets, if any."""
    for rule in _declarations(widget.styleSheet()):
        for name in properties:
            if name in rule and (colour := _colour_in(rule[name])):
                return colour
    return None


_FOREGROUND = ("color",)
_BACKGROUND = ("background", "background-color")


def _resolved(widget: QWidget, properties: tuple[str, ...], fallback: str) -> str:
    """Walk up the tree for the colour actually in force."""
    node: QWidget | None = widget
    while node is not None:
        if (colour := _own(node, properties)) is not None:
            return colour
        node = node.parentWidget()
    return fallback


def _walk(root: QWidget):
    yield root
    yield from root.findChildren(QWidget)


def _views(palette: Palette, qtbot) -> list[tuple[str, QWidget]]:
    """One of every view and stateful widget, constructed for real."""
    shell = strings.shell_strings()
    guide = load_guide()
    built: list[tuple[str, QWidget]] = [
        ("hub", HubView(shell)),
        ("run", RunView(palette, {**shell, **strings.run_strings()})),
        ("preprocessor", PreprocessorView(palette, {**shell, **strings.preprocessor_strings()})),
        ("vandv", VandVView(palette, {**shell, **strings.vandv_strings()})),
        ("library", LibraryView(palette, {**shell, **strings.library_strings()})),
        ("post", PostView(palette, {**shell, **strings.post_strings()})),
        ("regions", RegionsView(palette, {**shell, **strings.regions_strings()})),
        ("initial", InitialConditionsView(palette, {**shell, **strings.initial_strings()})),
        ("verify", VerifyView(palette, {**shell, **strings.verify_strings()})),
        ("guide", GuideView(palette, {**shell, **strings.guide_strings()}, guide=guide)),
        ("workflow", WorkflowNav(palette, {**shell, **strings.workflow_strings()})),
        ("properties", PropertyPanel(palette, {**shell, **strings.workflow_strings()})),
        ("diagnosis", DiagnosisBanner(palette, {**shell, **strings.run_strings()})),
    ]
    for _name, widget in built:
        qtbot.addWidget(widget)
    return built


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
class TestEveryViewIsReadable:
    def test_every_widget_pair_meets_wcag_aa(self, qtbot, palette: Palette) -> None:
        """The check M7 asks for: on every view, not just in the palette table."""
        failures: list[str] = []

        for name, view in _views(palette, qtbot):
            for widget in _walk(view):
                foreground = _resolved(widget, _FOREGROUND, palette.text)
                background = _resolved(widget, _BACKGROUND, palette.bg)
                ratio = contrast_ratio(foreground, background)
                if ratio < AA_TEXT:
                    failures.append(
                        f"{name}/{type(widget).__name__}: "
                        f"{foreground} on {background} = {ratio:.2f}"
                    )

        assert not failures, "contrast below AA:\n" + "\n".join(sorted(set(failures)))

    def test_every_stylesheet_colour_is_a_palette_token(self, qtbot, palette: Palette) -> None:
        """A literal survives every palette test by being wrong in one theme."""
        # `Palette` uses slots, so `vars()` raises; the field list is the API.
        tokens = {
            value.lower()
            for value in (getattr(palette, f.name) for f in dataclasses.fields(palette))
            if isinstance(value, str) and value.startswith("#")
        }
        strays: list[str] = []

        for name, view in _views(palette, qtbot):
            for widget in _walk(view):
                for rule in _declarations(widget.styleSheet()):
                    for value in rule.values():
                        found = _colour_in(value)
                        if found and found.lower() not in tokens:
                            strays.append(f"{name}/{type(widget).__name__}: {found}")

        assert not strays, "colours not from the palette:\n" + "\n".join(sorted(set(strays)))


class TestTheApplicationStylesheet:
    @pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
    def test_every_rule_that_sets_both_is_readable(self, palette: Palette) -> None:
        """The shell's own sheet, checked rule by rule rather than as a whole."""
        failures = []
        for rule in _declarations(stylesheet(palette)):
            foreground = next(
                (_colour_in(rule[p]) for p in _FOREGROUND if p in rule and _colour_in(rule[p])),
                None,
            )
            background = next(
                (_colour_in(rule[p]) for p in _BACKGROUND if p in rule and _colour_in(rule[p])),
                None,
            )
            if foreground and background:
                ratio = contrast_ratio(foreground, background)
                if ratio < AA_TEXT:
                    failures.append(f"{foreground} on {background} = {ratio:.2f}")
        assert not failures, "\n".join(failures)


class TestRoleColoursOnEverySurface:
    """The gap a per-widget walk leaves.

    Role colours — ``QLabel[role="muted"]`` and friends — are set by the
    *application* stylesheet on a property selector, so no widget carries them in
    its own sheet and the tree walk never sees them. They are also the colours
    most at risk: a muted grey chosen against a white window can fall below AA
    once the same label is placed on a raised panel.

    A rule that sets only a colour is therefore checked against every surface the
    application actually draws on, because the selector does not say which one it
    will land on and all three occur.
    """

    @pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
    def test_a_text_colour_is_readable_on_every_surface(self, palette: Palette) -> None:
        surfaces = {
            "bg": palette.bg,
            "surface": palette.surface,
            "surface_alt": palette.surface_alt,
        }
        failures: list[str] = []

        for selector, body in _RULE.findall(stylesheet(palette)):
            rule = {n.lower(): v.strip() for n, v in _DECL.findall(body)}
            foreground = next(
                (_colour_in(rule[p]) for p in _FOREGROUND if p in rule and _colour_in(rule[p])),
                None,
            )
            if foreground is None:
                continue
            # A rule that names its own background is already checked exactly.
            if any(p in rule and _colour_in(rule[p]) for p in _BACKGROUND):
                continue
            for name, background in surfaces.items():
                ratio = contrast_ratio(foreground, background)
                if ratio < AA_TEXT:
                    failures.append(
                        f"{selector.strip()}: {foreground} on {name} ({background}) = {ratio:.2f}"
                    )

        assert not failures, "role colours below AA:\n" + "\n".join(sorted(set(failures)))

    @pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
    def test_muted_text_survives_a_raised_panel(self, palette: Palette) -> None:
        """The specific case: "muted" is still body text and still needs 4.5."""
        for background in (palette.bg, palette.surface, palette.surface_alt):
            assert contrast_ratio(palette.text_muted, background) >= AA_TEXT


class TestTheSweepCanFail:
    """A check that cannot fail guards nothing."""

    def test_an_unreadable_pair_is_caught(self, qtbot) -> None:
        widget = QWidget()
        qtbot.addWidget(widget)
        widget.setStyleSheet("QWidget { color: #777777; background: #808080; }")
        foreground = _resolved(widget, _FOREGROUND, LIGHT.text)
        background = _resolved(widget, _BACKGROUND, LIGHT.bg)
        assert contrast_ratio(foreground, background) < AA_TEXT

    def test_a_child_inherits_its_parents_background(self, qtbot) -> None:
        """Checking a label's absent background against the window default would
        check a pair that never appears on screen."""
        parent = QWidget()
        qtbot.addWidget(parent)
        parent.setStyleSheet("QWidget { background: #101010; }")
        child = QWidget(parent)
        assert _resolved(child, _BACKGROUND, LIGHT.bg) == "#101010"
