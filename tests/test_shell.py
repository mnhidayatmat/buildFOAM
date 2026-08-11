"""Shell, nav rail, footer and Hub (§7.1, §7.2, FR-A1, FR-A2).

§12.5 asks for pytest-qt smoke tests for every view. These go further where the
PRD makes a checkable promise — the footer never lying, colour never being the
sole carrier of meaning, every view reachable from the keyboard — because those
are the claims that quietly stop being true as the UI grows.

Runs offscreen, so the suite needs no display and works on a CI runner and over
ssh.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton

from foamwb.branding import APP_DISPLAY_NAME
from foamwb.codes import ErrorCode
from foamwb.services.recents import RecentCase
from foamwb.services.runtime import RuntimeKind, RuntimeState, RuntimeStatus
from foamwb.services.settings import SettingsService, ThemeChoice
from foamwb.ui.navrail import NAV_ITEMS
from foamwb.ui.shell import Shell
from foamwb.ui.theme import DARK, LIGHT

READY = RuntimeStatus(state=RuntimeState.READY, kind=RuntimeKind.NATIVE)
MISSING = RuntimeStatus(state=RuntimeState.MISSING, reason=ErrorCode.NOT_PROVISIONED)
BROKEN = RuntimeStatus(
    state=RuntimeState.BROKEN,
    reason=ErrorCode.RUNTIME_BROKEN,
    detail="foamVersion: command not found",
)
DEGRADED = RuntimeStatus(
    state=RuntimeState.DEGRADED,
    reason=ErrorCode.MACOS_INTEL_UNSUPPORTED,
    kind=RuntimeKind.DOCKER,
)


@pytest.fixture
def shell(qtbot) -> Shell:
    window = Shell(LIGHT)
    qtbot.addWidget(window)
    # Modal dialogs block their thread until a human answers, so a test that
    # reached one would hang rather than fail — and the paths users take most
    # would be the paths never exercised. Both are replaced with recorders.
    window.dialogs_shown = []
    window.set_dialogs(
        choose_directory=lambda _title: None,
        report=lambda title, body: window.dialogs_shown.append((title, body)),
    )
    return window


class TestLayout:
    """§7.1 — three regions: nav rail, main panel stack, status footer."""

    def test_opens_on_the_hub(self, shell: Shell) -> None:
        assert shell.current_view == "hub"

    def test_every_nav_item_has_a_view(self, shell: Shell) -> None:
        # The rail, the stack and the shortcuts are built from one list. A rail
        # button with no view would be a dead end (§7.9 rule 1).
        for item in NAV_ITEMS:
            assert shell.view(item.key) is not None

    def test_window_title_is_the_product_name(self, shell: Shell) -> None:
        assert shell.windowTitle() == APP_DISPLAY_NAME

    def test_footer_is_always_visible(self, shell: Shell) -> None:
        shell.show()
        for key in (item.key for item in NAV_ITEMS):
            shell.show_view(key)
            assert shell.footer.isVisible(), f"footer hidden on {key}"

    def test_unknown_view_is_refused_loudly(self, shell: Shell) -> None:
        with pytest.raises(KeyError):
            shell.show_view("nope")


class TestNavigation:
    def test_selecting_a_rail_item_switches_the_view(self, shell: Shell) -> None:
        shell.rail.view_selected.emit("library")
        assert shell.current_view == "library"

    def test_clicking_a_rail_button_switches_the_view(self, shell: Shell, qtbot) -> None:
        button = shell.rail.button("guide")
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert shell.current_view == "guide"

    def test_rail_and_stack_never_disagree(self, shell: Shell) -> None:
        for item in NAV_ITEMS:
            shell.show_view(item.key)
            assert shell.rail.current == item.key

    def test_selection_is_exclusive(self, shell: Shell) -> None:
        shell.show_view("run")
        checked = [i.key for i in NAV_ITEMS if shell.rail.button(i.key).isChecked()]
        assert checked == ["run"]

    def test_every_view_has_a_distinct_keyboard_shortcut(self) -> None:
        # NFR-A1: full keyboard navigation. M7's exit criterion is a keyboard-only
        # pass over every task, which is impossible if a view can only be reached
        # by clicking.
        shortcuts = [item.shortcut for item in NAV_ITEMS]
        assert len(shortcuts) == len(set(shortcuts))
        assert all(s.startswith("Ctrl+") for s in shortcuts)

    def test_every_rail_button_is_keyboard_focusable(self, shell: Shell) -> None:
        for item in NAV_ITEMS:
            button = shell.rail.button(item.key)
            assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus


class TestNavRailCollapse:
    """§7.1 — collapsible to icons only."""

    def test_starts_expanded_with_labels(self, shell: Shell) -> None:
        assert not shell.rail.collapsed
        assert "Library" in shell.rail.button("library").text()

    def test_collapsing_hides_labels_but_keeps_glyphs(self, shell: Shell) -> None:
        shell.rail.set_collapsed(True)
        text = shell.rail.button("library").text()
        assert "Library" not in text
        assert text.strip()

    def test_collapsing_narrows_the_rail(self, shell: Shell) -> None:
        expanded = shell.rail.width()
        shell.rail.set_collapsed(True)
        assert shell.rail.width() < expanded

    def test_a_collapsed_rail_is_still_self_describing(self, shell: Shell) -> None:
        # The label is gone from the face of the button, so the tooltip and the
        # accessible name have to carry it — otherwise collapsing the rail would
        # make the app unusable with a screen reader.
        shell.rail.set_collapsed(True)
        button = shell.rail.button("library")
        assert "Library" in button.toolTip()
        assert button.accessibleName() == "Library"

    def test_toggle_round_trips(self, shell: Shell) -> None:
        original = shell.rail.button("library").text()
        shell.rail.toggle_collapsed()
        shell.rail.toggle_collapsed()
        assert shell.rail.button("library").text() == original
        assert not shell.rail.collapsed


class TestStatusFooter:
    """FR-A2 and §7.9 rule 4 — the footer never lies."""

    def test_starts_in_the_honest_undetected_state(self, shell: Shell) -> None:
        # Nothing has been probed at construction, so claiming a ready runtime
        # would be the one thing the footer must never do.
        assert "not installed" in shell.footer.runtime_text.lower()
        assert "No OpenFOAM" in shell.footer.version_text

    @pytest.mark.parametrize(
        ("status", "fragment"),
        [
            (READY, "ready"),
            (DEGRADED, "degraded"),
            (MISSING, "not installed"),
            (BROKEN, "broken"),
        ],
    )
    def test_every_state_is_rendered_in_words(
        self, shell: Shell, status: RuntimeStatus, fragment: str
    ) -> None:
        shell.set_runtime_status(status)
        assert fragment in shell.footer.runtime_text.lower()

    def test_a_non_ready_state_shows_its_error_code(self, shell: Shell) -> None:
        # So a support conversation starts from a code rather than a screenshot.
        shell.set_runtime_status(BROKEN)
        assert ErrorCode.RUNTIME_BROKEN.id in shell.footer.runtime_text

    def test_a_ready_state_shows_no_code(self, shell: Shell) -> None:
        shell.set_runtime_status(READY)
        assert "E-R" not in shell.footer.runtime_text

    def test_state_is_carried_by_shape_as_well_as_colour(self, shell: Shell) -> None:
        # NFR-A2: colour is never the sole carrier of meaning. Distinct glyphs
        # keep the footer readable in greyscale and to a colourblind user.
        glyphs = set()
        for status in (READY, DEGRADED, MISSING, BROKEN):
            shell.set_runtime_status(status)
            glyphs.add(shell.footer.runtime_text.strip()[0])
        assert len(glyphs) == 4

    def test_accessible_name_repeats_the_meaning_not_the_glyph(self, shell: Shell) -> None:
        shell.set_runtime_status(BROKEN)
        name = shell.footer._indicator.accessibleName()
        assert "broken" in name.lower()
        assert "✕" not in name

    def test_reports_the_openfoam_version(self, shell: Shell) -> None:
        shell.set_openfoam_version("v2512")
        assert "v2512" in shell.footer.version_text

    def test_reports_the_active_case_and_run_state(self, shell: Shell) -> None:
        shell.set_active_case("pitzDaily")
        shell.set_run_state("running")
        assert shell.footer.case_text == "pitzDaily"
        assert shell.footer.run_state_text == "running"

    def test_clearing_the_case_restores_the_placeholder(self, shell: Shell) -> None:
        shell.set_active_case("pitzDaily")
        shell.set_active_case(None)
        assert "No case" in shell.footer.case_text
        assert shell.windowTitle() == APP_DISPLAY_NAME

    def test_active_case_appears_in_the_window_title(self, shell: Shell) -> None:
        shell.set_active_case("cavity")
        assert "cavity" in shell.windowTitle()
        assert APP_DISPLAY_NAME in shell.windowTitle()

    def test_clicking_the_indicator_jumps_to_setup(self, shell: Shell, qtbot) -> None:
        # §7.1: clicking the runtime dot goes to Setup.
        indicator = shell.footer.findChild(QToolButton, "runtimeIndicator")
        qtbot.mouseClick(indicator, Qt.MouseButton.LeftButton)
        assert shell.current_view == "setup"


class TestHub:
    """FR-A1, §7.2."""

    def test_every_action_target_exists(self, shell: Shell) -> None:
        for key, _primary in shell.hub.ACTIONS:
            assert shell.hub.action_button(key) is not None

    @pytest.mark.parametrize(
        ("action", "destination"),
        [("library", "library"), ("guide", "guide"), ("settings", "setup")],
    )
    def test_actions_reach_their_view_in_one_click(
        self, shell: Shell, qtbot, action: str, destination: str
    ) -> None:
        qtbot.mouseClick(shell.hub.action_button(action), Qt.MouseButton.LeftButton)
        assert shell.current_view == destination

    def test_no_action_button_is_inert(self, shell: Shell, qtbot) -> None:
        # FR-A1: every target reachable in one click. A button wired to nothing
        # would pass a smoke test while being useless.
        asked: list[str] = []
        shell.set_dialogs(choose_directory=lambda title: asked.append(title))

        for key, _primary in shell.hub.ACTIONS:
            shell.show_view("hub")
            qtbot.mouseClick(shell.hub.action_button(key), Qt.MouseButton.LeftButton)
            if key == "open_case":
                # Cancelling deliberately leaves the view alone; what matters is
                # that the button asked.
                assert asked, "Open Case did not ask for a folder"
            else:
                assert shell.current_view != "hub", f"{key} did nothing"

    def test_empty_state_explains_what_to_do(self, shell: Shell) -> None:
        shell.set_recent_cases([])
        assert shell.hub.recent_count == 0
        assert shell.hub._empty_hint.isVisibleTo(shell.hub)

    def test_recent_cases_are_listed(self, shell: Shell) -> None:
        shell.set_recent_cases(
            [
                RecentCase(Path("/cases/pitzDaily"), solver="simpleFoam"),
                RecentCase(
                    Path("/cases/cavity"),
                    solver="icoFoam",
                    last_run=datetime(2026, 8, 10, 9, 14),
                    last_exit=0,
                ),
            ]
        )
        assert shell.hub.recent_count == 2

    def test_run_status_is_words_not_an_exit_number(self, shell: Shell) -> None:
        # NFR-A6 forbids jargon without an inline explanation, and "exit 137"
        # means nothing to a student.
        shell.set_recent_cases(
            [
                RecentCase(
                    Path("/cases/cavity"),
                    last_run=datetime(2026, 8, 10, 9, 14),
                    last_exit=137,
                )
            ]
        )
        text = shell.hub._recent_list.item(0).text()
        assert "137" not in text
        assert "failed" in text

    def test_activating_a_recent_case_opens_it(self, shell: Shell, tmp_path) -> None:
        # A real directory, because activating a recent case now genuinely opens
        # it rather than only relabelling the footer.
        case = tmp_path / "pitzDaily"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("application simpleFoam;\n")

        shell.set_recent_cases([RecentCase(case)])
        shell.hub._recent_list.itemActivated.emit(shell.hub._recent_list.item(0))
        assert shell.footer.case_text == "pitzDaily"

    def test_opening_a_folder_that_is_not_a_case_is_reported(self, shell: Shell, tmp_path) -> None:
        # E-C01. The user picked the wrong folder, which is an ordinary mistake:
        # it must be said plainly and must not disturb what is already open.
        shell.open_case(tmp_path)
        assert shell.dialogs_shown
        assert "No case" in shell.footer.case_text


class TestRuntimeBanner:
    """§7.2 — the banner appears only when the runtime is not ready."""

    def test_hidden_when_ready(self, shell: Shell) -> None:
        shell.set_runtime_status(READY)
        assert not shell.hub.banner_visible

    @pytest.mark.parametrize("status", [MISSING, BROKEN, DEGRADED])
    def test_shown_when_not_ready(self, shell: Shell, status: RuntimeStatus) -> None:
        shell.set_runtime_status(READY)
        shell.set_runtime_status(status)
        assert shell.hub.banner_visible
        assert shell.hub.banner_text.strip()

    def test_banner_explains_in_plain_language(self, shell: Shell) -> None:
        # NFR-A6: no jargon without an inline definition. The message must stand
        # on its own; the code is an addendum, not the explanation.
        shell.set_runtime_status(MISSING)
        text = shell.hub.banner_text
        assert "OpenFOAM is not installed yet" in text
        assert len(text.split("(")[0].split()) > 8

    def test_banner_offers_an_action(self, shell: Shell, qtbot) -> None:
        # §7.9 rule 1: every error state offers at least one action.
        shell.set_runtime_status(MISSING)
        qtbot.mouseClick(shell.hub._banner_action, Qt.MouseButton.LeftButton)
        assert shell.current_view == "setup"

    def test_footer_and_banner_cannot_disagree(self, shell: Shell) -> None:
        # One setter drives both, so a footer saying "ready" above a banner
        # saying "not installed" is unreachable.
        shell.set_runtime_status(BROKEN)
        assert shell.hub.banner_visible
        assert "broken" in shell.footer.runtime_text.lower()

        shell.set_runtime_status(READY)
        assert not shell.hub.banner_visible
        assert "ready" in shell.footer.runtime_text.lower()


class TestPlaceholderViews:
    """§7.9 rule 1 applies to unfinished software too."""

    @pytest.mark.parametrize("key", [i.key for i in NAV_ITEMS if i.key != "hub"])
    def test_each_says_what_is_coming(self, shell: Shell, key: str) -> None:
        text = " ".join(label.text() for label in shell.view(key).findChildren(QLabel))
        assert len(text.split()) > 8, f"{key} placeholder says too little"


class TestThemes:
    """NFR-A4 — light and dark, following the OS setting."""

    @pytest.mark.parametrize("palette", [LIGHT, DARK])
    def test_shell_builds_under_either_palette(self, qtbot, palette) -> None:
        window = Shell(palette)
        qtbot.addWidget(window)
        assert window.current_view == "hub"

    @pytest.mark.parametrize("palette", [LIGHT, DARK])
    def test_status_colours_come_from_the_palette(self, qtbot, palette) -> None:
        window = Shell(palette)
        qtbot.addWidget(window)
        window.set_runtime_status(BROKEN)
        assert palette.broken.lower() in window.footer._indicator.styleSheet().lower()


@pytest.fixture
def themed(qtbot, qapp, tmp_path):
    """A shell whose preferences go to a temporary file, never the user's own.

    The application style sheet is global, so it is restored afterwards — a test
    that left the window dark would leak into whatever ran next, and the failure
    would appear in an unrelated module.
    """
    service = SettingsService(tmp_path / "config.json")
    window = Shell(LIGHT, settings=service, theme=ThemeChoice.LIGHT)
    qtbot.addWidget(window)
    original = qapp.styleSheet()
    yield window, service
    qapp.setStyleSheet(original)


class TestThemeToggle:
    """NFR-A4's control: Light, Dark, or follow the desktop."""

    def test_opens_in_light(self, themed) -> None:
        window, _service = themed
        assert window.theme is ThemeChoice.LIGHT
        assert window.palette_in_use is LIGHT
        assert window.footer.theme_choice is ThemeChoice.LIGHT

    def test_the_footer_names_the_theme_in_force(self, themed) -> None:
        window, _service = themed
        window.set_theme(ThemeChoice.DARK)
        # Not colour alone, and not a glyph alone: the control says which theme
        # is in force in words (NFR-A2).
        assert "Dark" in window.footer.theme_text

    def test_choosing_dark_repaints_the_window(self, qapp, themed) -> None:
        window, _service = themed
        window.set_theme(ThemeChoice.DARK)
        assert window.palette_in_use is DARK
        assert DARK.bg.lower() in qapp.styleSheet().lower()
        assert LIGHT.bg.lower() not in qapp.styleSheet().lower()

    def test_the_choice_is_persisted(self, themed) -> None:
        window, service = themed
        window.set_theme(ThemeChoice.DARK)
        # Read back through a fresh service: a value cached in memory would pass
        # a weaker assertion and still be gone after a restart.
        assert SettingsService(service.path).load().theme is ThemeChoice.DARK

    def test_the_menu_drives_it(self, themed) -> None:
        # The path a user actually takes. Calling set_theme directly would leave
        # the footer's menu untested, which is the whole control.
        window, _service = themed
        window.footer.choose_theme(ThemeChoice.DARK)
        assert window.theme is ThemeChoice.DARK
        assert window.palette_in_use is DARK

    def test_widgets_that_hold_a_palette_are_given_the_new_one(self, themed) -> None:
        # The style sheet does not reach item brushes, syntax highlighting or the
        # plot canvas, so each of these keeps its own copy and would otherwise
        # stay on the previous theme.
        window, _service = themed
        window.set_theme(ThemeChoice.DARK)
        for widget in (
            window.footer,
            window.run_view,
            window.run_view.log,
            window.run_view.residuals,
            window.run_view.strip,
            window.preprocessor,
            window.preprocessor.form,
            window.preprocessor.text,
        ):
            assert widget._palette is DARK, type(widget).__name__

    def test_the_footer_repaints_rather_than_keeping_the_old_red(self, themed) -> None:
        # §7.9 rule 4: the footer is the part that must still be telling the
        # truth when everything else has gone wrong, so a stale colour here is
        # worse than a stale colour anywhere else.
        window, _service = themed
        window.set_runtime_status(BROKEN)
        window.set_theme(ThemeChoice.DARK)
        assert DARK.broken.lower() in window.footer._indicator.styleSheet().lower()

    def test_a_running_plan_is_not_reset_by_a_theme_change(self, themed) -> None:
        # Rebuilding the strip would be the simple implementation and would put
        # every stage back to pending in front of someone watching a run.
        from foamwb.services.run import RunPlan, Stage, StageState

        window, _service = themed
        plan = RunPlan(case=Path("/tmp/case"), stages=(Stage("blockMesh", ("blockMesh",)),))
        window.run_view.strip.set_plan(plan)
        window.run_view.strip.set_state("blockMesh", StageState.RUNNING)

        window.set_theme(ThemeChoice.DARK)
        assert window.run_view.strip.state_of("blockMesh") is StageState.RUNNING


class TestFollowingTheDesktop:
    """SYSTEM is a standing instruction, not a one-off reading."""

    @pytest.fixture
    def desktop(self, qapp, monkeypatch):
        def report(scheme: Qt.ColorScheme) -> None:
            monkeypatch.setattr(type(qapp.styleHints()), "colorScheme", lambda _self: scheme)

        return report

    def test_system_takes_the_desktop_colour(self, themed, desktop) -> None:
        window, _service = themed
        desktop(Qt.ColorScheme.Dark)
        window.set_theme(ThemeChoice.SYSTEM)
        assert window.palette_in_use is DARK

    def test_a_desktop_switch_is_followed(self, themed, desktop) -> None:
        window, _service = themed
        desktop(Qt.ColorScheme.Light)
        window.set_theme(ThemeChoice.SYSTEM)
        assert window.palette_in_use is LIGHT

        desktop(Qt.ColorScheme.Dark)
        window.refresh_system_theme()
        assert window.palette_in_use is DARK

    def test_a_desktop_switch_does_not_override_an_explicit_choice(self, themed, desktop) -> None:
        # The setting would be worthless otherwise: a user who chose Light
        # precisely because their desktop is dark would be overruled at sunset.
        window, _service = themed
        window.set_theme(ThemeChoice.LIGHT)
        desktop(Qt.ColorScheme.Dark)
        window.refresh_system_theme()
        assert window.palette_in_use is LIGHT

    def test_the_stored_choice_stays_system_not_the_colour_it_resolved_to(
        self, themed, desktop
    ) -> None:
        window, service = themed
        desktop(Qt.ColorScheme.Dark)
        window.set_theme(ThemeChoice.SYSTEM)
        assert SettingsService(service.path).load().theme is ThemeChoice.SYSTEM
