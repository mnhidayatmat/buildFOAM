"""Error taxonomy (§9) and host paths (§5.3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from foamwb import paths
from foamwb.codes import ALL_CODES, Code, ErrorCode, by_id


class TestErrorTaxonomy:
    def test_ids_are_unique(self) -> None:
        assert len(ALL_CODES) == len([v for v in vars(ErrorCode).values() if isinstance(v, Code)])

    def test_ids_follow_the_group_scheme(self) -> None:
        # E-<group><number>, where the group letter is the §9 section.
        for code_id in ALL_CODES:
            assert re.fullmatch(r"E-[RCSLVA][0-9]{2}", code_id), code_id

    def test_every_code_has_a_guide_anchor(self) -> None:
        # FR-G2: 100% of error codes have a target page. M7's exit criterion is
        # an automated link check with zero dangling anchors, and it iterates
        # exactly this table.
        for code in ALL_CODES.values():
            assert code.guide_anchor
            assert re.fullmatch(r"[a-z0-9]+(/[a-z0-9-]+)+", code.guide_anchor), code

    def test_guide_anchors_are_unique(self) -> None:
        anchors = [c.guide_anchor for c in ALL_CODES.values()]
        assert len(anchors) == len(set(anchors))

    def test_every_code_has_a_single_line_condition(self) -> None:
        # Not asserted to start uppercase: "apt or Homebrew failure" names a
        # command, and capitalising it would misspell the command.
        for code in ALL_CODES.values():
            assert code.condition.strip() == code.condition
            assert "\n" not in code.condition

    def test_all_nine_runtime_codes_are_present(self) -> None:
        # §9 table R is enumerated in FR-R2's acceptance criterion; every code
        # must be reachable and shown in the status footer.
        runtime = sorted(c for c in ALL_CODES if c.startswith("E-R"))
        assert runtime == [f"E-R{n:02d}" for n in range(1, 10)]

    def test_lookup_by_id(self) -> None:
        assert by_id("E-S03") is ErrorCode.DIVERGED
        with pytest.raises(KeyError):
            by_id("E-Z99")

    def test_codes_are_immutable(self) -> None:
        with pytest.raises(AttributeError):
            ErrorCode.DIVERGED.id = "E-S99"  # type: ignore[misc]

    def test_taxonomy_holds_no_user_facing_message_text(self) -> None:
        # Messages are translatable (NFR-A5) and belong in the presentation
        # layer's catalogue; this table is the stable machine vocabulary.
        for code in ALL_CODES.values():
            assert not code.condition.endswith((".", "!", "?"))


class TestPaths:
    def test_all_host_paths_are_absolute(self) -> None:
        for factory in (
            paths.user_data_dir,
            paths.config_file,
            paths.manifest_dir,
            paths.log_dir,
            paths.cache_dir,
        ):
            assert factory().is_absolute(), factory.__name__

    def test_roaming_and_local_data_are_distinguished(self) -> None:
        # A roaming profile must not carry a multi-gigabyte download cache across
        # the network (§14.1).
        assert paths.cache_dir() != paths.user_data_dir()

    def test_config_lives_under_the_user_data_dir(self) -> None:
        assert paths.config_file().parent == paths.user_data_dir()
        assert paths.config_file().name == "config.json"

    def test_runtime_content_path_is_posix(self) -> None:
        # This is a path inside the Linux runtime, not on the host.
        assert "\\" not in str(paths.runtime_content_subpath())
        assert str(paths.runtime_content_subpath()).endswith("/content")

    def test_no_path_segment_is_empty(self) -> None:
        for part in paths.log_dir().parts:
            assert part.strip()

    def test_unsupported_platform_is_refused_explicitly(self, monkeypatch) -> None:
        # NG4: no native Linux desktop build. Failing loudly beats silently
        # writing to a path nobody supports.
        monkeypatch.setattr(paths.sys, "platform", "linux")
        with pytest.raises(RuntimeError, match="Unsupported host platform"):
            paths.current_platform()


class TestWindowsPaths:
    """§5.3's Windows column, forced on whichever host runs the suite.

    Without this, the Windows branches are dead code on the macOS runner and the
    macOS branches are dead code on the Windows one — so half of §5.3 would go
    untested on every machine while the coverage number looked fine. The WSL
    bridge does not arrive until M3, but these are plain environment lookups and
    there is no reason to leave them unverified until then.
    """

    @pytest.fixture(autouse=True)
    def _as_windows(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(paths.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    def test_config_is_roaming(self, tmp_path) -> None:
        assert paths.config_file().parent.parent == tmp_path / "Roaming"

    @pytest.mark.parametrize(
        ("factory", "leaf"),
        [("manifest_dir", "manifest"), ("log_dir", "logs"), ("cache_dir", "cache")],
    )
    def test_bulky_data_is_machine_local_not_roaming(
        self, tmp_path, factory: str, leaf: str
    ) -> None:
        # A roaming profile must not drag a multi-gigabyte download cache across
        # the network at every logon (§14.1).
        path = getattr(paths, factory)()
        assert path.name == leaf
        assert path.is_relative_to(tmp_path / "Local")

    def test_falls_back_when_the_environment_variable_is_absent(self, monkeypatch) -> None:
        # A stripped service account or a managed image may not set these.
        monkeypatch.delenv("APPDATA", raising=False)
        assert paths.user_data_dir().is_relative_to(Path.home())


class TestMacOSPaths:
    @pytest.fixture(autouse=True)
    def _as_macos(self, monkeypatch) -> None:
        monkeypatch.setattr(paths.sys, "platform", "darwin")

    def test_follows_the_apple_directory_conventions(self) -> None:
        library = Path.home() / "Library"
        assert paths.user_data_dir().is_relative_to(library / "Application Support")
        assert paths.log_dir().is_relative_to(library / "Logs")
        assert paths.cache_dir().is_relative_to(library / "Caches")

    def test_cases_and_content_sit_in_a_visible_home_folder(self) -> None:
        # Native APFS, no bridge required (§3.3) — and somewhere a student can
        # actually find, since D4 promises the files stay hand-editable.
        assert paths.macos_cases_dir().parent == paths.macos_content_dir().parent
        assert paths.macos_cases_dir().parent.parent == Path.home()
        assert paths.macos_cases_dir().name == "cases"
        assert paths.macos_content_dir().name == "content"
