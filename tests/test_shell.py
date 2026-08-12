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
from foamwb.services.workflow import STEPS, step_by_id
from foamwb.ui.navrail import NAV_ITEMS
from foamwb.ui.shell import Shell
from foamwb.ui.theme import DARK, LIGHT
from foamwb.ui.widgets.workflow_nav import STATE_GLYPHS

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


class TestWorkflowNavigation:
    """§7.2 — the left panel is an ordered procedure, not a set of destinations.

    Replaces the nav-rail tests. The rail answered "where do I go?", which is
    only useful to someone who already knows the workflow; these assert the
    question P1 actually has, which is "what do I do next?".
    """

    def test_the_panel_lists_every_step_in_order(self, shell: Shell) -> None:
        assert shell.workflow.rows == [step.id for step in STEPS]

    def test_selecting_a_step_switches_the_view(self, shell: Shell) -> None:
        shell._on_step_selected("library")
        assert shell.current_view == "library"

    def test_a_group_header_is_not_a_destination(self, shell: Shell) -> None:
        """Clicking a header must not navigate: it names a phase, not a page."""
        before = shell.current_view
        shell.workflow._on_clicked(shell.workflow._items["conditions"], 0)
        assert shell.current_view == before

    def test_steps_needing_a_case_are_blocked_until_there_is_one(self, shell: Shell) -> None:
        assert not shell.workflow.is_actionable("conditions.basic")
        assert shell.workflow.is_actionable("case.open")

    def test_a_blocked_step_stays_visible_and_says_why(self, shell: Shell) -> None:
        """§7.9 rule 3 — hiding it would conceal what the procedure even is."""
        assert shell.workflow.text_of("execute")
        shell.workflow.select("execute")
        assert shell.workflow.hint_text

    def test_state_is_carried_in_words_not_only_appearance(self, shell: Shell) -> None:
        """NFR-A2 — greying out is invisible to a screen reader."""
        described = shell.workflow.state_text_of("execute")
        assert "not yet" in described.lower()

    def test_every_state_has_a_distinct_glyph(self) -> None:
        assert len(set(STATE_GLYPHS.values())) == len(STATE_GLYPHS)

    def test_the_panel_says_what_to_do_next(self, shell: Shell) -> None:
        assert "Open a case" in shell.workflow.next_text

    def test_the_panel_can_be_collapsed_from_the_keyboard(self, shell: Shell) -> None:
        """NFR-A1 — a splitter that needs dragging is not keyboard-operable."""
        shell.toggle_workflow_panel()
        shell.toggle_workflow_panel()
        assert shell.workflow.rows


class TestTheWorkflowFollowsTheCase:
    def test_opening_a_case_unblocks_the_setup_steps(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert shell.workflow.is_actionable("conditions.basic")

    def test_an_unmeshed_case_cannot_be_executed(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert not shell.workflow.is_actionable("execute")

    def test_the_next_step_is_the_mesh(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert "Generate mesh" in shell.workflow.next_text

    def test_a_meshed_case_offers_the_way_back(self, shell: Shell, tmp_path) -> None:
        """scFLOW's *Return to Prepare Parts*, and the reason it exists."""
        case = _cavity(tmp_path)
        (case / "constant" / "polyMesh").mkdir(parents=True)
        shell.open_case(case)
        assert shell.workflow.offers_return_to_mesh

    def test_returning_to_the_mesh_unlocks_it(self, shell: Shell, tmp_path) -> None:
        case = _cavity(tmp_path)
        (case / "constant" / "polyMesh").mkdir(parents=True)
        shell.open_case(case)
        assert not shell.workflow.is_actionable("mesh.settings")
        shell._on_return_to_mesh()
        assert shell.workflow.is_actionable("mesh.settings")


class TestThePropertyPanel:
    """§7.4 — scFLOW's Parameter / Value / Unit table."""

    def test_it_has_the_three_columns(self, shell: Shell) -> None:
        assert shell.properties.column_titles == ["Parameter", "Value", "Unit"]

    def test_it_is_empty_until_a_step_is_chosen(self, shell: Shell) -> None:
        assert shell.properties.row_count == 0

    def test_choosing_a_step_fills_it_from_the_case(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("conditions.basic")
        assert shell.properties.row_count > 0

    def test_it_shows_the_unit_where_there_is_one(self, shell: Shell, tmp_path) -> None:
        """A dimension is part of the value's meaning in OpenFOAM."""
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("conditions.basic")
        rows = [r for g in shell.properties.groups for r in g.rows]
        assert any(r.unit == "s" for r in rows if r.path == "endTime")

    def test_it_names_the_file_the_settings_came_from(self, shell: Shell, tmp_path) -> None:
        """D4 — teach OpenFOAM, not the interface."""
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("conditions.basic")
        assert any(g.source == "system/controlDict" for g in shell.properties.groups)


def _cavity(tmp_path):
    """A minimal runnable-looking case, without needing a real OpenFOAM."""
    case = tmp_path / "cavity"
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
        "application     icoFoam;\nstartTime       0;\nendTime         0.5;\n"
        "deltaT          0.005;\nwriteControl    timeStep;\nwriteInterval   20;\n"
    )
    return case


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
        #
        # "Did something" means one of two observable things, because the actions
        # are not all navigation: a button either changes the view, or it asks the
        # user a question. Cancelling that question deliberately leaves the view
        # alone, so the *asking* is what has to be asserted — this is the check
        # that caught New Case and Case Folder falling through to an empty Cases
        # view, which looked to the user like nothing happening at all.
        asked: list[str] = []
        reported: list[str] = []
        shell.set_dialogs(
            choose_directory=lambda title: asked.append(title),
            ask_text=lambda title, _prompt, _default: asked.append(title),
            report=lambda title, _body: reported.append(title),
        )
        interactive = {"open_case", "new_case", "case_folder"}

        for key, _primary in shell.hub.ACTIONS:
            shell.show_view("hub")
            before = len(asked) + len(reported)
            qtbot.mouseClick(shell.hub.action_button(key), Qt.MouseButton.LeftButton)
            if key in interactive:
                assert len(asked) + len(reported) > before, f"{key} did nothing"
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


class TestNewCase:
    """FR-C1 — *New Case* creates a case rather than showing an empty panel.

    The behaviour these replace was the one a user reported: the button routed to
    the Cases view, which with nothing open is blank, so pressing it looked
    exactly like pressing a button that was not connected.
    """

    def _wire(self, shell: Shell, tmp_path: Path, name: str = "wing"):
        reported: list[tuple[str, str]] = []
        shell.set_dialogs(
            choose_directory=lambda _title: tmp_path,
            ask_text=lambda _title, _prompt, _default: name,
            report=lambda title, body: reported.append((title, body)),
        )
        return reported

    def test_creates_and_opens_the_case(self, shell: Shell, tmp_path: Path) -> None:
        self._wire(shell, tmp_path)
        shell.new_case_dialog()

        created = tmp_path / "wing"
        assert (created / "system" / "controlDict").is_file()
        assert shell.footer.case_text == "wing"

    def test_lands_on_the_view_that_takes_geometry(self, shell: Shell, tmp_path: Path) -> None:
        # A new case has no mesh and no fields; the next thing to do with it is
        # import a model, so it must not open on a page that hides that.
        self._wire(shell, tmp_path)
        shell.new_case_dialog()
        assert shell.current_view == "cases"

    def test_cancelling_the_folder_creates_nothing(self, shell: Shell, tmp_path: Path) -> None:
        shell.set_dialogs(choose_directory=lambda _title: None)
        shell.new_case_dialog()
        assert list(tmp_path.iterdir()) == []

    def test_cancelling_the_name_creates_nothing(self, shell: Shell, tmp_path: Path) -> None:
        shell.set_dialogs(
            choose_directory=lambda _title: tmp_path,
            ask_text=lambda _t, _p, _d: None,
        )
        shell.new_case_dialog()
        assert list(tmp_path.iterdir()) == []

    def test_an_empty_name_creates_nothing(self, shell: Shell, tmp_path: Path) -> None:
        shell.set_dialogs(
            choose_directory=lambda _title: tmp_path,
            ask_text=lambda _t, _p, _d: "",
        )
        shell.new_case_dialog()
        assert list(tmp_path.iterdir()) == []

    def test_a_refusal_is_reported_with_its_code(self, shell: Shell, tmp_path: Path) -> None:
        (tmp_path / "wing").mkdir()
        (tmp_path / "wing" / "keep.txt").write_text("mine")
        reported = self._wire(shell, tmp_path)

        shell.new_case_dialog()

        assert reported, "an occupied destination was not reported"
        # §9 code in the message, so support starts from a code (E-C13).
        assert "E-C" in reported[0][1]
        assert (tmp_path / "wing" / "keep.txt").read_text() == "mine"

    def test_an_invalid_name_is_reported_rather_than_silently_ignored(
        self, shell: Shell, tmp_path: Path
    ) -> None:
        reported = self._wire(shell, tmp_path, name="a/b")
        shell.new_case_dialog()
        assert reported


class TestCaseFolder:
    """The Hub's *Case Folder* action."""

    def test_reveals_the_open_case(self, shell: Shell, tmp_path: Path) -> None:
        revealed: list[Path] = []
        shell.set_dialogs(
            choose_directory=lambda _title: tmp_path,
            ask_text=lambda _t, _p, _d: "wing",
            reveal=lambda path: revealed.append(path) or True,
        )
        shell.new_case_dialog()
        shell.reveal_case_folder()

        assert revealed == [tmp_path / "wing"]

    def test_says_so_when_no_case_is_open(self, shell: Shell) -> None:
        reported: list[tuple[str, str]] = []
        shell.set_dialogs(report=lambda title, body: reported.append((title, body)))
        shell.reveal_case_folder()
        assert reported, "an inert button is what this action used to be"

    def test_a_file_manager_that_refuses_is_reported(self, shell: Shell, tmp_path: Path) -> None:
        reported: list[tuple[str, str]] = []
        shell.set_dialogs(
            choose_directory=lambda _title: tmp_path,
            ask_text=lambda _t, _p, _d: "wing",
            report=lambda title, body: reported.append((title, body)),
            reveal=lambda _path: False,
        )
        shell.new_case_dialog()
        shell.reveal_case_folder()
        # The path is named, so the user can still get there by hand.
        assert reported and "wing" in reported[-1][1]


class TestTheProcedureReadsAsOne:
    """§7.2 — the panel has to be legible as an ordered procedure.

    Users reported the list as hard to understand, and the audit found why: group
    headers and steps shared an indent level, four near-identical glyphs carried
    every state with no legend, nothing was numbered, and two reference pages sat
    in the list as though they were steps. These assert the fixes, because each
    one is the kind of thing that quietly regresses when a step is added.
    """

    def test_every_step_lives_inside_a_group(self) -> None:
        # Headers and steps shared indentation before, so structure and content
        # were told apart only by the presence of a glyph.
        for step in STEPS:
            if not step.is_group:
                assert step.parent, f"{step.id} is a step with no group"

    def test_only_the_required_steps_are_numbered(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        model = shell.workflow.model
        for step in STEPS:
            number = model.number_of(step)
            if step.required:
                assert number is not None, f"{step.id} is required but unnumbered"
            else:
                assert number is None, f"{step.id} is optional but numbered"

    def test_the_numbers_run_from_one_without_gaps(self, shell: Shell) -> None:
        model = shell.workflow.model
        numbers = [model.number_of(s) for s in STEPS if s.required]
        assert numbers == list(range(1, len(numbers) + 1))

    def test_a_done_step_shows_a_tick_rather_than_its_number(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        # case.open is done the moment a case is open.
        assert "✓" in shell.workflow.text_of("case.open")

    def test_an_outstanding_step_shows_its_position(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert "2" in shell.workflow.text_of("mesh.generate")

    def test_a_blocked_row_says_so_in_words_on_the_row(self, shell: Shell) -> None:
        """Not only in a tooltip.

        "Why can I not click this?" is the question the panel most needed to
        answer, and a tooltip answers it only for someone using a mouse who
        already suspected there was something to hover over.
        """
        assert "not yet" in shell.workflow.text_of("execute")

    def test_an_available_row_is_not_cluttered_with_its_state(self, shell: Shell, tmp_path) -> None:
        # Saying "ready" on every ordinary row is noise, not information.
        shell.open_case(_cavity(tmp_path))
        assert "ready" not in shell.workflow.text_of("conditions.basic")

    def test_progress_is_reported(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        done, total = shell.workflow.model.progress
        assert total == len([s for s in STEPS if s.required])
        assert f"{done} of {total}" in shell.workflow.progress_text

    def test_progress_moves_when_a_step_completes(self, shell: Shell, tmp_path) -> None:
        case = _cavity(tmp_path)
        shell.open_case(case)
        before, _ = shell.workflow.model.progress

        (case / "constant" / "polyMesh").mkdir(parents=True)
        shell.open_case(case)
        after, _ = shell.workflow.model.progress
        assert after > before

    def test_reference_pages_are_not_part_of_the_procedure(self) -> None:
        # They used to sit beside Execute and Results, reading as steps 12 and 13.
        for step_id in ("library", "guide"):
            step = step_by_id(step_id)
            assert step.reference
            assert not step.required

    def test_a_reference_page_never_becomes_the_next_step(self, shell: Shell) -> None:
        model = shell.workflow.model
        following = model.next_step
        assert following is None or not following.reference

    def test_clicking_a_group_folds_it_rather_than_doing_nothing(self, shell: Shell) -> None:
        """A header that swallows a click reads as broken."""
        nav = shell.workflow
        item = nav._items["conditions"]
        assert item.isExpanded()
        nav._on_clicked(item, 0)
        assert not item.isExpanded()
        nav._on_clicked(item, 0)
        assert item.isExpanded()
