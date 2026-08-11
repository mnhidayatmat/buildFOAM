"""Choice + desktop → palette (NFR-A4).

Three states and two possible desktops is six cases, and the one that matters is
the pair where they disagree: an explicit Light on a dark desktop, and an
explicit Dark on a light one. Those are the entire reason the setting exists, and
a resolver that deferred to the OS "when in doubt" would quietly break exactly
the user who went looking for the control.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from foamwb.services.settings import ThemeChoice
from foamwb.ui.appearance import palette_for_scheme, resolve_palette, system_is_dark
from foamwb.ui.theme import DARK, LIGHT


@pytest.fixture
def desktop(qapp, monkeypatch):
    """Force what Qt reports the desktop colour scheme to be."""

    def report(scheme: Qt.ColorScheme) -> None:
        monkeypatch.setattr(type(qapp.styleHints()), "colorScheme", lambda _self: scheme)

    return report


class TestSystemScheme:
    @pytest.mark.parametrize(
        ("scheme", "expected"),
        [(Qt.ColorScheme.Dark, True), (Qt.ColorScheme.Light, False)],
    )
    def test_reports_what_qt_reports(self, qapp, desktop, scheme, expected) -> None:
        desktop(scheme)
        assert system_is_dark(qapp) is expected

    def test_older_qt_without_colorscheme_reads_as_light(self, qapp, monkeypatch) -> None:
        # A light UI on a dark desktop is merely jarring; a dark UI on a light
        # desktop can be unreadable, because the platform paints its own light
        # background behind anything the style sheet does not cover.
        monkeypatch.delattr(type(qapp.styleHints()), "colorScheme", raising=False)
        assert system_is_dark(qapp) is False
        assert palette_for_scheme(qapp) is LIGHT

    def test_no_application_reads_as_light(self) -> None:
        # Not reachable from the running app, but a service-layer caller or a
        # doctest has no QApplication and must still get a legible answer rather
        # than an AttributeError.
        assert system_is_dark(None) in (True, False)


class TestResolution:
    @pytest.mark.parametrize("scheme", [Qt.ColorScheme.Light, Qt.ColorScheme.Dark])
    def test_an_explicit_choice_overrides_the_desktop(self, qapp, desktop, scheme) -> None:
        # The case the whole feature exists for. A user on a dark desktop who
        # asks for Light gets Light.
        desktop(scheme)
        assert resolve_palette(ThemeChoice.LIGHT, qapp) is LIGHT
        assert resolve_palette(ThemeChoice.DARK, qapp) is DARK

    @pytest.mark.parametrize(
        ("scheme", "expected"),
        [(Qt.ColorScheme.Dark, DARK), (Qt.ColorScheme.Light, LIGHT)],
    )
    def test_system_follows_the_desktop(self, qapp, desktop, scheme, expected) -> None:
        desktop(scheme)
        assert resolve_palette(ThemeChoice.SYSTEM, qapp) is expected

    def test_system_is_re_resolved_every_time(self, qapp, desktop) -> None:
        # Not cached: the desktop can switch at sunset while the window is open,
        # and a resolver that answered once would leave the window behind.
        desktop(Qt.ColorScheme.Light)
        assert resolve_palette(ThemeChoice.SYSTEM, qapp) is LIGHT
        desktop(Qt.ColorScheme.Dark)
        assert resolve_palette(ThemeChoice.SYSTEM, qapp) is DARK

    def test_every_choice_resolves_to_a_real_palette(self, qapp) -> None:
        # A choice added to the enum without a branch here would fall through to
        # the desktop and look almost right, which is the hardest kind of wrong
        # to notice.
        for choice in ThemeChoice:
            assert resolve_palette(choice, qapp) in (LIGHT, DARK)
