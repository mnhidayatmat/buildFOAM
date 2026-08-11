"""Application construction (NFR-P1, NFR-A4).

The entry point is thin by design, but two of its decisions are load-bearing and
neither is visible by reading the window: that the shell opens *before* anything
slow happens, and that the stored theme is read *before* the first paint, so the
window never opens in one theme and visibly corrects itself to another.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from foamwb import __version__
from foamwb.branding import APP_DISPLAY_NAME
from foamwb.services.settings import SettingsService, ThemeChoice
from foamwb.ui import app as app_module
from foamwb.ui.app import build_application, palette_for_scheme
from foamwb.ui.theme import DARK, LIGHT


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Never read or write the developer's own preferences file.

    Autouse because ``build_application`` constructs its own service: a test that
    forgot this would pass or fail depending on the theme the person running it
    happens to prefer.
    """
    path = tmp_path / "config.json"
    monkeypatch.setattr(app_module, "SettingsService", lambda: SettingsService(path))
    return SettingsService(path)


@pytest.fixture
def built(qapp):
    original = qapp.styleSheet()
    application, shell = build_application([])
    yield application, shell
    shell.deleteLater()
    qapp.setStyleSheet(original)


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


class TestStartupTheme:
    """The stored preference decides the first paint (NFR-A4)."""

    def test_a_first_run_opens_in_light(self, built) -> None:
        # No preferences file yet. Light is this build's default, so a first run
        # looks the same on every machine.
        _application, shell = built
        assert shell.theme is ThemeChoice.LIGHT
        assert shell.palette_in_use is LIGHT

    @pytest.mark.parametrize(
        ("choice", "expected"),
        [(ThemeChoice.DARK, DARK), (ThemeChoice.LIGHT, LIGHT)],
    )
    def test_a_stored_choice_is_applied_before_the_window_appears(
        self, qapp, isolated_settings, choice, expected
    ) -> None:
        isolated_settings.set_theme(choice)
        original = qapp.styleSheet()
        _application, shell = build_application([])
        try:
            # Both, not just the shell: the style sheet is what paints the first
            # frame, and a shell that agreed with the preference while the
            # application did not would flash the wrong theme on open.
            assert shell.palette_in_use is expected
            assert expected.bg.lower() in qapp.styleSheet().lower()
        finally:
            shell.deleteLater()
            qapp.setStyleSheet(original)

    def test_the_footer_control_reflects_the_stored_choice(self, qapp, isolated_settings) -> None:
        isolated_settings.set_theme(ThemeChoice.SYSTEM)
        original = qapp.styleSheet()
        _application, shell = build_application([])
        try:
            assert shell.footer.theme_choice is ThemeChoice.SYSTEM
        finally:
            shell.deleteLater()
            qapp.setStyleSheet(original)


class TestThemeFollowsTheOS:
    """What the desktop implies, before any preference is applied."""

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
