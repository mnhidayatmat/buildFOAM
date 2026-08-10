"""Application construction (NFR-P1, NFR-A4).

The entry point is thin by design, but two of its decisions are load-bearing and
neither is visible by reading the window: that the shell opens *before* anything
slow happens, and that the theme follows the OS rather than a preference the app
invents.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from foamwb import __version__
from foamwb.branding import APP_DISPLAY_NAME
from foamwb.ui.app import build_application, palette_for_scheme
from foamwb.ui.theme import DARK, LIGHT


@pytest.fixture
def built(qapp):
    application, shell = build_application([])
    yield application, shell
    shell.deleteLater()


class TestBuildApplication:
    def test_produces_a_shell_on_the_hub(self, built) -> None:
        _application, shell = built
        assert shell.current_view == "hub"

    def test_reuses_an_existing_qapplication(self, built) -> None:
        # Constructing a second QApplication aborts the process, so this is the
        # difference between a testable entry point and one that can only be run.
        application, _shell = built
        assert application is QApplication.instance()

    def test_identifies_itself_for_the_platform(self, built) -> None:
        application, _shell = built
        assert application.applicationName() == APP_DISPLAY_NAME
        assert application.applicationVersion() == __version__

    def test_applies_a_stylesheet(self, built) -> None:
        application, _shell = built
        assert application.styleSheet().strip()

    def test_opens_before_any_runtime_detection(self, built) -> None:
        # NFR-P1 gives cold start a 3-second budget, and probing for OpenFOAM can
        # take seconds on a cold WSL distribution. The window therefore appears
        # first, in its honest "not detected yet" state, and is corrected when the
        # answer arrives — rather than holding a splash screen over an empty one.
        _application, shell = built
        assert "not installed" in shell.footer.runtime_text.lower()
        assert "No OpenFOAM" in shell.footer.version_text


class TestThemeFollowsTheOS:
    """NFR-A4 — light and dark, following the OS setting by default."""

    def test_returns_a_palette(self, qapp) -> None:
        assert palette_for_scheme(qapp) in (LIGHT, DARK)

    @pytest.mark.parametrize(
        ("scheme", "expected"),
        [(Qt.ColorScheme.Dark, DARK), (Qt.ColorScheme.Light, LIGHT)],
    )
    def test_maps_the_reported_scheme(self, qapp, monkeypatch, scheme, expected) -> None:
        monkeypatch.setattr(type(qapp.styleHints()), "colorScheme", lambda _self: scheme)
        assert palette_for_scheme(qapp) is expected

    def test_falls_back_to_light_when_qt_cannot_report(self, qapp, monkeypatch) -> None:
        # Older Qt has no colorScheme(). Light is the safer default: a light UI on
        # a dark desktop is merely jarring, while a dark UI on a light desktop can
        # be unreadable if the platform paints its own light background behind it.
        monkeypatch.delattr(type(qapp.styleHints()), "colorScheme", raising=False)
        assert palette_for_scheme(qapp) is LIGHT
