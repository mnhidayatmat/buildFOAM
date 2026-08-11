"""Preferences persistence (§5.3, NFR-A4).

The interesting cases are all the ones where the file is wrong. A preferences
file is written by one version and read by another, hand-edited, truncated by a
full disk, or synced half-way by a roaming profile — and none of those may stop a
user opening their cases. So most of this module is about damaged input, and the
assertion is always the same: the defaults come back and the application carries
on.

No Qt here, and none needed: the preference is a value, not a widget.
"""

from __future__ import annotations

import json

import pytest

from foamwb.services import settings as settings_module
from foamwb.services.settings import (
    DEFAULT_THEME,
    Settings,
    SettingsService,
    ThemeChoice,
)


@pytest.fixture
def service(tmp_path) -> SettingsService:
    """Always an explicit path — a test must never touch the user's own config."""
    return SettingsService(tmp_path / "config.json")


class TestDefaults:
    def test_the_default_theme_is_light(self) -> None:
        # The product decision, asserted rather than left implicit: a first run
        # looks the same on every machine and in every screenshot in the
        # teaching material.
        assert DEFAULT_THEME is ThemeChoice.LIGHT
        assert Settings().theme is ThemeChoice.LIGHT

    def test_a_missing_file_is_the_ordinary_first_run(self, service) -> None:
        assert service.load() == Settings()
        # And reading did not create one. Nothing has been chosen yet, and a
        # file full of defaults would be indistinguishable from a file full of
        # deliberate choices the next time the defaults change.
        assert not service.path.exists()


class TestRoundTrip:
    @pytest.mark.parametrize("choice", list(ThemeChoice))
    def test_every_choice_survives(self, service, choice) -> None:
        assert service.set_theme(choice).theme is choice
        assert SettingsService(service.path).load().theme is choice

    def test_system_is_stored_as_a_choice_not_a_resolved_palette(self, service) -> None:
        # The whole point of SYSTEM: storing whatever the desktop happened to be
        # at the moment of choosing would freeze the window at that answer and
        # silently stop following the desktop.
        service.set_theme(ThemeChoice.SYSTEM)
        assert json.loads(service.path.read_text())["theme"] == "system"

    def test_the_parent_directory_is_created(self, tmp_path) -> None:
        service = SettingsService(tmp_path / "nested" / "deeper" / "config.json")
        assert service.set_theme(ThemeChoice.DARK)
        assert service.load().theme is ThemeChoice.DARK

    def test_no_temporary_file_is_left_behind(self, service) -> None:
        service.set_theme(ThemeChoice.DARK)
        assert [p.name for p in service.path.parent.iterdir()] == ["config.json"]


class TestDamagedInput:
    """None of these may raise. That is the requirement, not a nicety."""

    def test_unparseable_json_yields_defaults(self, service) -> None:
        service.path.write_text("{ this is not json")
        assert service.load() == Settings()

    def test_the_damaged_file_is_left_alone(self, service) -> None:
        # Not deleted and not overwritten on read: a later version may still be
        # able to make sense of it, and a user may want to look at it.
        service.path.write_text("{ this is not json")
        service.load()
        assert service.path.read_text() == "{ this is not json"

    @pytest.mark.parametrize("document", ["[]", '"light"', "42", "null"])
    def test_a_root_that_is_not_an_object_yields_defaults(self, service, document) -> None:
        service.path.write_text(document)
        assert service.load() == Settings()

    def test_an_unrecognised_theme_yields_the_default(self, service) -> None:
        # What a *newer* build's value looks like from here. The default is the
        # right answer for it; refusing to start is not.
        service.path.write_text(json.dumps({"theme": "solarized"}))
        assert service.load().theme is DEFAULT_THEME

    @pytest.mark.parametrize("value", [None, 3, [], {}])
    def test_a_theme_of_the_wrong_type_yields_the_default(self, service, value) -> None:
        service.path.write_text(json.dumps({"theme": value}))
        assert service.load().theme is DEFAULT_THEME

    def test_an_unreadable_file_yields_defaults(self, service, monkeypatch) -> None:
        service.path.write_text(json.dumps({"theme": "dark"}))

        def refuse(*_args, **_kwargs):
            raise PermissionError("locked by another process")

        monkeypatch.setattr(type(service.path), "read_text", refuse)
        assert service.load() == Settings()


class TestUnknownKeysAreCarried:
    """A newer build's settings must survive a trip through this one."""

    def test_keys_this_build_does_not_understand_are_preserved(self, service) -> None:
        service.path.write_text(json.dumps({"theme": "dark", "futureSetting": {"a": 1}}))
        service.set_theme(ThemeChoice.LIGHT)

        document = json.loads(service.path.read_text())
        assert document["theme"] == "light"
        assert document["futureSetting"] == {"a": 1}


class TestWhenThereIsNowhereToWrite:
    """Neither of these is a reason to interrupt the user."""

    def test_an_unsupported_platform_yields_defaults(self, monkeypatch) -> None:
        def unsupported():
            raise RuntimeError("Unsupported host platform 'linux'")

        monkeypatch.setattr(settings_module, "config_file", unsupported)
        service = SettingsService()
        assert service.path is None
        assert service.load() == Settings()
        assert service.save(Settings(theme=ThemeChoice.DARK)) is False

    def test_a_failing_write_is_reported_not_raised(self, service, monkeypatch) -> None:
        def refuse(*_args, **_kwargs):
            raise OSError("no space left on device")

        monkeypatch.setattr(type(service.path), "write_text", refuse)
        assert service.save(Settings(theme=ThemeChoice.DARK)) is False
