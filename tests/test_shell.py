"""The shell: ribbon, outline, task page, graphics window, console, footer.

§12.5 asks for pytest-qt smoke tests for every view. These go further where the
PRD makes a checkable promise — the footer never lying, colour never being the
sole carrier of meaning, every action reachable from the keyboard — because
those are the claims that quietly stop being true as the UI grows.

The Fluent-shaped window (DEC-21) adds one claim of its own worth pinning: the
ribbon, the outline and the graphics window are three views of *one* list, so a
button, the node it selects and the document it raises can never disagree.

Runs offscreen, so the suite needs no display and works on a CI runner and over
ssh.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from fakes import FakeSession
from foamwb.branding import APP_DISPLAY_NAME
from foamwb.codes import ErrorCode
from foamwb.services.recents import RecentCase
from foamwb.services.run import StageState
from foamwb.services.runtime import RuntimeKind, RuntimeState, RuntimeStatus
from foamwb.services.settings import SettingsService, ThemeChoice
from foamwb.services.workflow import STEPS, StepState, step_by_id
from foamwb.ui.ribbon import FILE_MENU, RIBBON_TABS
from foamwb.ui.shell import _ACTION_STEPS, Shell
from foamwb.ui.theme import DARK, LIGHT
from foamwb.ui.widgets.outline import STATE_GLYPHS

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

_BLOCK_MESH_DICT = (
    "FoamFile { version 2.0; format ascii; class dictionary; object blockMeshDict; }\n"
    "convertToMeters 1;\n"
)


def _mesh(case: Path) -> Path:
    """Give a case a mesh — files, not merely the directory.

    An empty ``constant/polyMesh`` is not a mesh: nothing can be run against it
    and ``checkMesh`` would fail on it. Since DEC-22 the application dates the
    mesh from the files inside it, so a fixture that made only the directory
    would be claiming a mesh the application would then have to disown.
    """
    polymesh = case / "constant" / "polyMesh"
    polymesh.mkdir(parents=True, exist_ok=True)
    (polymesh / "points").write_text("0\n()\n")
    return polymesh


def _cavity(tmp_path, *, meshable: bool = False):
    """A minimal runnable-looking case, without needing a real OpenFOAM.

    ``meshable`` adds a ``blockMeshDict``, which is what makes the run plan
    begin by meshing — the ordinary shape of an OpenFOAM tutorial, and the case
    the outline has to treat as runnable before a mesh exists.
    """
    case = tmp_path / "cavity"
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
        "application     icoFoam;\nstartTime       0;\nendTime         0.5;\n"
        "deltaT          0.005;\nwriteControl    timeStep;\nwriteInterval   20;\n"
    )
    if meshable:
        (case / "system" / "blockMeshDict").write_text(_BLOCK_MESH_DICT)
    return case


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
    """§7.1, DEC-21 — five regions: ribbon, outline, task page, graphics, console."""

    def test_opens_on_the_start_document(self, shell: Shell) -> None:
        assert shell.current_document == "start"

    def test_every_region_is_present(self, shell: Shell) -> None:
        shell.show()
        for region in (shell.ribbon, shell.outline, shell.task_page, shell.graphics, shell.console):
            assert region.isVisible(), type(region).__name__

    def test_window_title_is_the_product_name(self, shell: Shell) -> None:
        assert shell.windowTitle() == APP_DISPLAY_NAME

    def test_footer_is_always_visible(self, shell: Shell) -> None:
        shell.show()
        for step in STEPS:
            if step.is_group:
                continue
            shell._on_step_selected(step.id)
            assert shell.footer.isVisible(), f"footer hidden on {step.id}"

    def test_the_graphics_window_is_never_replaced_by_a_form(self, shell: Shell, tmp_path) -> None:
        """The centre stays a document whatever node is selected.

        This is the property that distinguishes the layout from a stack of
        views: a task page can be empty, but the graphics window always has
        something in it, so the user never loses the thing they are working on
        to a settings panel.
        """
        shell.open_case(_cavity(tmp_path))
        for step in STEPS:
            if step.is_group:
                continue
            shell._on_step_selected(step.id)
            assert shell.current_document, f"{step.id} emptied the graphics window"


class TestTheThreeViewsAgree:
    """The ribbon, the outline and the graphics window come from one list."""

    def test_every_node_names_a_task_page_that_exists(self, shell: Shell) -> None:
        pages = set(shell.task_page.pages)
        for step in STEPS:
            if step.is_group or not step.page:
                continue
            assert step.page in pages, f"{step.id} names a missing page {step.page!r}"

    def test_every_node_names_a_document_that_exists(self, shell: Shell) -> None:
        documents = set(shell.graphics.documents)
        for step in STEPS:
            if not step.document:
                continue
            assert step.document in documents, f"{step.id} names a missing document"

    def test_every_ribbon_action_that_names_a_node_names_a_real_one(self) -> None:
        for key, step_id in _ACTION_STEPS.items():
            assert step_by_id(step_id) is not None, f"{key} names no node"

    def test_every_ribbon_action_is_wired(self, shell: Shell) -> None:
        """§7.9 rule 1: a button wired to nothing would pass a smoke test.

        An action either selects an outline node or has a handler; there is no
        third kind, and one that fell through both would be a button that looks
        live and is not.
        """
        wired = set(_ACTION_STEPS) | set(shell._handlers())
        for key in shell.ribbon.action_keys + shell.ribbon.menu_keys:
            assert key in wired, f"{key} is wired to nothing"

    def test_no_handler_names_an_action_the_ribbon_does_not_offer(self, shell: Shell) -> None:
        """The other direction: dead code that looks like a working feature."""
        offered = set(shell.ribbon.action_keys) | set(shell.ribbon.menu_keys)
        # The start document sends its own keys through the same router, so
        # those are legitimate handlers with no ribbon button behind them.
        from_start = {key for key, _primary in shell.hub.ACTIONS}
        for key in set(shell._handlers()) - from_start:
            assert key in offered, f"{key} is handled but offered nowhere"

    def test_pressing_a_ribbon_action_selects_its_node(self, shell: Shell, tmp_path) -> None:
        """The ribbon is a second route to the work, not a second implementation."""
        shell.open_case(_cavity(tmp_path))
        shell.ribbon.trigger("materials")
        assert shell.current_step == "setup.materials"
        assert shell.outline.current_step == "setup.materials"

    def test_selecting_a_node_raises_its_document(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("setup.boundary")
        assert shell.current_document == "boundary"
        shell._on_step_selected("files.case")
        assert shell.current_document == "files"

    def test_the_task_page_header_always_names_the_selected_node(
        self, shell: Shell, tmp_path
    ) -> None:
        """A header left over from the previous node is a window that lies.

        The regression: a node whose page did not exist left the title and the
        form belonging to whatever was selected before it, so the outline said
        *Boundary Conditions* over a page headed *Materials*.
        """
        shell.open_case(_cavity(tmp_path))
        for step in STEPS:
            if step.is_group:
                continue
            shell._on_step_selected(step.id)
            assert shell.task_page.title_text == shell._labels[f"step.{step.id}"], step.id


class TestTheOutline:
    """§7.2 — the structure of the case, in the order it is set up."""

    def test_it_lists_every_node_in_order(self, shell: Shell) -> None:
        assert shell.outline.rows == [step.id for step in STEPS]

    def test_selecting_a_node_switches_the_task_page(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("solution.initialization")
        assert shell.current_page == "initial"

        shell._on_step_selected("setup.boundary")
        assert shell.current_page == "regions"

    def test_import_is_the_first_task_of_the_workflow(self, shell: Shell, tmp_path) -> None:
        """A case is meshed *around* a surface, so importing one comes first."""
        workflow = [s.id for s in STEPS if s.parent == "workflow"]
        assert workflow[0] == "workflow.import"

        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("workflow.import")
        assert shell.current_page == "geometry"

    def test_a_group_header_is_not_a_destination(self, shell: Shell) -> None:
        """Clicking a header must not navigate: it names a part, not a page."""
        before = shell.current_document
        shell.outline._on_clicked(shell.outline._items["setup"], 0)
        assert shell.current_document == before

    def test_nodes_needing_a_case_are_blocked_until_there_is_one(self, shell: Shell) -> None:
        assert not shell.outline.is_actionable("setup.general")

    def test_a_blocked_node_stays_visible_and_says_why(self, shell: Shell) -> None:
        """§7.9 rule 3 — hiding it would conceal what the procedure even is."""
        assert shell.outline.text_of("solution.run")
        shell.outline.select("solution.run")
        assert shell.outline.hint_text

    def test_state_is_carried_in_words_not_only_appearance(self, shell: Shell) -> None:
        """NFR-A2 — greying out is invisible to a screen reader."""
        described = shell.outline.state_text_of("solution.run")
        assert "not yet" in described.lower()

    def test_every_state_has_a_distinct_glyph(self) -> None:
        assert len(set(STATE_GLYPHS.values())) == len(STATE_GLYPHS)

    def test_with_nothing_open_the_next_thing_is_to_open_something(self, shell: Shell) -> None:
        """Every node needs a case, so "nothing outstanding" would be a lie."""
        assert "Open a case" in shell.outline.next_text

    def test_with_a_case_it_says_what_to_do_next(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert "Generate the Volume Mesh" in shell.outline.next_text

    def test_the_filter_narrows_the_tree(self, shell: Shell) -> None:
        shell.outline.filter_by("boundar")
        visible = shell.outline.visible_rows
        assert "setup.boundary" in visible
        assert "solution.methods" not in visible

    def test_a_filtered_node_keeps_its_heading(self, shell: Shell) -> None:
        """A node floating without its group has lost what says where it belongs."""
        shell.outline.filter_by("boundar")
        assert "setup" in shell.outline.visible_rows

    def test_clearing_the_filter_restores_everything(self, shell: Shell) -> None:
        shell.outline.filter_by("boundar")
        shell.outline.filter_by("")
        assert shell.outline.visible_rows == shell.outline.rows

    def test_the_outline_can_be_hidden_from_the_keyboard(self, shell: Shell) -> None:
        """NFR-A1 — a splitter that needs dragging is not keyboard-operable."""
        shell.show()
        shell.toggle_outline()
        assert not shell.outline.isVisibleTo(shell)
        shell.toggle_outline()
        assert shell.outline.isVisibleTo(shell)


class TestTheOutlineFollowsTheCase:
    def test_opening_a_case_unblocks_the_setup_nodes(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert shell.outline.is_actionable("setup.general")

    def test_an_unmeshed_case_cannot_be_run(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert not shell.outline.is_actionable("solution.run")

    def test_a_case_the_run_would_mesh_can_be_run(self, shell: Shell, tmp_path) -> None:
        """The plan starts with blockMesh, so there is no mesh to wait for.

        This was unreachable: no polyMesh meant *Run* was blocked, blocked rows
        cannot be clicked — so the button that would have run blockMesh could
        not be got to for want of the mesh blockMesh would have made.
        """
        shell._session = FakeSession()
        shell.open_case(_cavity(tmp_path, meshable=True))
        assert shell.outline.is_actionable("solution.run")

    def test_calculate_is_disabled_until_it_would_work(self, shell: Shell, tmp_path) -> None:
        """The ribbon's state comes from the outline's model, so they agree."""
        shell.open_case(_cavity(tmp_path / "bare"))
        assert not shell.ribbon.is_enabled("calculate")

        shell._session = FakeSession()
        shell.open_case(_cavity(tmp_path / "meshable", meshable=True))
        assert shell.ribbon.is_enabled("calculate")

    def test_a_disabled_action_says_why(self, shell: Shell, tmp_path) -> None:
        """§7.9 rule 3 — "why can I not click this?" is answered on the button."""
        shell.open_case(_cavity(tmp_path))
        assert "mesh" in shell.ribbon.tooltip_of("calculate").lower()

    def test_post_processing_still_waits_for_a_real_mesh(self, shell: Shell, tmp_path) -> None:
        """A plan that would mesh says nothing about results that do not exist."""
        shell._session = FakeSession()
        shell.open_case(_cavity(tmp_path, meshable=True))
        assert not shell.outline.is_actionable("results.graphics")

    def test_writing_a_blockmeshdict_unblocks_the_run_without_reopening(
        self, shell: Shell, tmp_path
    ) -> None:
        """Generating meshing dictionaries changes what pressing Calculate does.

        The plan is therefore re-read on refresh rather than kept from the one
        built at open, which would still say the case cannot mesh itself.
        """
        case = _cavity(tmp_path)
        shell._session = FakeSession()
        shell.open_case(case)
        assert not shell.outline.is_actionable("solution.run")

        (case / "system" / "blockMeshDict").write_text(_BLOCK_MESH_DICT)
        shell.refresh_workflow()
        assert shell.outline.is_actionable("solution.run")

    def test_importing_geometry_ticks_that_node_green(self, shell: Shell, tmp_path) -> None:
        # Without this the row stayed grey until the case was reopened, so the
        # one task the user had just finished was the one the outline denied.
        case = _cavity(tmp_path)
        shell.open_case(case)
        assert shell.outline.colour_of("workflow.import") != LIGHT.ready.lower()

        source = tmp_path / "wing.stl"
        source.write_text(
            "solid s\nfacet normal 0 0 1\nouter loop\n"
            "vertex 0 0 0\nvertex 1 0 0\nvertex 1 1 0\n"
            "endloop\nendfacet\nendsolid s\n"
        )
        shell.editors.geometry.import_file(source)

        assert shell.outline.model.state_of(step_by_id("workflow.import")) is StepState.DONE
        assert shell.outline.colour_of("workflow.import") == LIGHT.ready.lower()
        assert "✓" in shell.outline.text_of("workflow.import")

    def test_a_node_with_a_blank_page_is_not_drawn(self, shell: Shell, tmp_path) -> None:
        """A row that promises a settings table and opens a void is a broken promise.

        ``Monitors`` reads ``controlDict``'s ``functions`` entry. A case that
        has the file but no such entry would give the node a heading over an
        empty table, so the row goes rather than opening blank.
        """
        shell.open_case(_cavity(tmp_path))
        assert "solution.monitors" not in shell.outline.visible_rows

    def test_a_node_whose_file_is_merely_absent_is_kept(self, shell: Shell, tmp_path) -> None:
        """ "No blockMeshDict in this case" is content: it says which file is wanted."""
        shell.open_case(_cavity(tmp_path))
        assert "workflow.sizing" in shell.outline.visible_rows

    def test_the_node_returns_when_its_settings_appear(self, shell: Shell, tmp_path) -> None:
        case = _cavity(tmp_path)
        (case / "system" / "controlDict").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
            "application icoFoam;\nfunctions { solverInfo { type solverInfo; } }\n"
        )
        shell.open_case(case)
        assert "solution.monitors" in shell.outline.visible_rows

    def test_a_node_with_its_own_page_is_kept(self, shell: Shell, tmp_path) -> None:
        """Boundary Conditions shows no *settings*, but it has a page and a document."""
        shell.open_case(_cavity(tmp_path))
        assert "setup.boundary" in shell.outline.visible_rows

    def test_the_whole_tree_is_shown_before_a_case_is_opened(self, shell: Shell) -> None:
        """The empty outline's job is to show the shape of the work ahead."""
        assert shell.outline.visible_rows == shell.outline.rows

    def test_a_meshed_case_offers_the_way_back(self, shell: Shell, tmp_path) -> None:
        """Fluent's *Switch to Meshing*, and the reason it exists."""
        case = _cavity(tmp_path)
        _mesh(case)
        shell.open_case(case)
        assert shell.outline.offers_return_to_mesh

    def test_switching_to_meshing_unlocks_it(self, shell: Shell, tmp_path) -> None:
        case = _cavity(tmp_path, meshable=True)
        _mesh(case)
        shell.open_case(case)
        assert not shell.outline.is_actionable("workflow.sizing")
        shell._on_return_to_mesh()
        assert shell.outline.is_actionable("workflow.sizing")

    def test_opening_a_case_moves_on_to_the_first_thing_to_do(self, shell: Shell, tmp_path) -> None:
        # It used to land on Run whatever the case was, which told a user with
        # no mesh to start a solver that cannot start.
        shell._session = FakeSession()
        shell.open_case(_cavity(tmp_path))
        assert shell.current_step == "workflow.import"
        assert shell.outline.current_step == "workflow.import"


class TestUpdate:
    """DEC-22 — the outline shows what is out of date, and one verb fixes it."""

    def _meshed(self, shell: Shell, tmp_path, *, run: bool = True):
        """A case with a mesh and, optionally, a result — both current."""
        import time

        case = _cavity(tmp_path, meshable=True)
        time.sleep(0.02)
        _mesh(case)
        if run:
            time.sleep(0.02)
            (case / "0.5").mkdir()
            (case / "0.5" / "U").write_text("result\n")
        shell._session = FakeSession()
        shell.open_case(case)
        return case

    def _age(self, case, relative: str) -> None:
        """Edit an input, so what was computed from it is now out of date."""
        import time

        time.sleep(0.02)
        target = case / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(target.read_text() + "\n// edited\n" if target.is_file() else "x\n")

    def test_an_empty_polymesh_directory_is_not_a_mesh(self, shell: Shell, tmp_path) -> None:
        """Nothing can be run against it and checkMesh would fail on it, so
        reporting the mesh step done would be a tick on work that did not
        happen."""
        case = _cavity(tmp_path, meshable=True)
        (case / "constant" / "polyMesh").mkdir(parents=True)
        shell._session = FakeSession()
        shell.open_case(case)
        assert shell.outline.model.state_of(step_by_id("workflow.volume")) is not StepState.DONE

    def test_a_current_case_shows_no_marks(self, shell: Shell, tmp_path) -> None:
        self._meshed(shell, tmp_path)
        assert shell.outline.model.state_of(step_by_id("workflow.volume")) is StepState.DONE
        assert shell.outline.model.state_of(step_by_id("solution.run")) is StepState.DONE

    def test_editing_a_mesh_input_marks_the_mesh_and_the_run(self, shell: Shell, tmp_path) -> None:
        case = self._meshed(shell, tmp_path)
        self._age(case, "system/blockMeshDict")
        shell.refresh_workflow()
        assert shell.outline.model.state_of(step_by_id("workflow.volume")) is StepState.STALE
        assert shell.outline.model.state_of(step_by_id("solution.run")) is StepState.STALE

    def test_the_mark_is_a_glyph_and_a_word_and_a_colour(self, shell: Shell, tmp_path) -> None:
        """NFR-A2 — three channels, so none of them is the only one."""
        case = self._meshed(shell, tmp_path)
        self._age(case, "system/blockMeshDict")
        shell.refresh_workflow()
        row = shell.outline.text_of("workflow.volume")
        assert STATE_GLYPHS[StepState.STALE] in row
        assert "out of date" in row
        assert shell.outline.colour_of("workflow.volume") == LIGHT.degraded.lower()

    def test_the_mark_names_the_file_that_caused_it(self, shell: Shell, tmp_path) -> None:
        """Workbench says a cell needs updating and not why."""
        case = self._meshed(shell, tmp_path)
        self._age(case, "system/blockMeshDict")
        shell.refresh_workflow()
        assert "blockMeshDict" in shell.outline._items["workflow.volume"].toolTip(1)

    def test_update_is_offered_only_when_it_would_do_something(
        self, shell: Shell, tmp_path
    ) -> None:
        case = self._meshed(shell, tmp_path)
        assert not shell.ribbon.is_enabled("update")
        assert "up to date" in shell.ribbon.tooltip_of("update").lower()

        self._age(case, "system/blockMeshDict")
        shell.refresh_workflow()
        assert shell.ribbon.is_enabled("update")

    def test_a_case_that_has_never_run_can_be_updated(self, shell: Shell, tmp_path) -> None:
        self._meshed(shell, tmp_path, run=False)
        assert shell.ribbon.is_enabled("update")

    def test_update_runs_only_what_is_stale(self, shell: Shell, tmp_path) -> None:
        """The mesh is current, so only the solve is re-run."""
        case = self._meshed(shell, tmp_path)
        self._age(case, "0/U")
        shell.refresh_workflow()
        shell.ribbon.trigger("update")
        assert shell.run_view.strip.state_of("blockMesh") is StageState.SKIPPED
        assert shell.run_view.strip.state_of("solve") is not StageState.SKIPPED

    def test_update_re_meshes_when_the_mesh_is_stale(self, shell: Shell, tmp_path) -> None:
        case = self._meshed(shell, tmp_path)
        self._age(case, "system/blockMeshDict")
        shell.refresh_workflow()
        shell.ribbon.trigger("update")
        assert shell.run_view.strip.state_of("blockMesh") is not StageState.SKIPPED

    def test_update_opens_the_run_page(self, shell: Shell, tmp_path) -> None:
        case = self._meshed(shell, tmp_path)
        self._age(case, "0/U")
        shell.refresh_workflow()
        shell.ribbon.trigger("update")
        assert shell.current_step == "solution.run"

    def test_nothing_to_do_is_said_rather_than_done(self, shell: Shell, tmp_path) -> None:
        """Launching a plan whose every stage is skipped would put a "succeeded
        in 0.0s" in front of a user who asked a question."""
        self._meshed(shell, tmp_path)
        shell._update_case()
        assert "up to date" in shell.run_view.status_text.lower()
        assert not shell.run_view.strip.stage_names or all(
            shell.run_view.strip.state_of(name) is not StageState.RUNNING
            for name in shell.run_view.strip.stage_names
        )

    def test_calculate_still_means_the_whole_plan(self, shell: Shell, tmp_path, qtbot) -> None:
        """One button must not quietly change what another button does.

        The narrower plan is given to *this run*, never swapped into the case's
        own — so the next press of Calculate still means blockMesh.
        """
        case = self._meshed(shell, tmp_path)
        self._age(case, "0/U")
        shell.refresh_workflow()

        with qtbot.waitSignal(shell.run_view.run_finished, timeout=10_000):
            shell.ribbon.trigger("update")
        assert shell.run_view.strip.state_of("blockMesh") is StageState.SKIPPED

        with qtbot.waitSignal(shell.run_view.run_finished, timeout=10_000):
            shell.run_view.start()
        assert shell.run_view.strip.state_of("blockMesh") is not StageState.SKIPPED

    def test_update_has_its_own_shortcut(self, shell: Shell, tmp_path) -> None:
        """F5 is the chord Workbench users already have for *Update Project*."""
        self._meshed(shell, tmp_path, run=False)
        assert "F5" in shell.ribbon.tooltip_of("update")


class TestTheTaskPage:
    """§7.4 — the settings for whatever the outline selected."""

    def test_the_property_table_has_the_three_columns(self, shell: Shell) -> None:
        assert shell.properties.column_titles == ["Parameter", "Value", "Unit"]

    def test_it_is_empty_until_a_node_is_chosen(self, shell: Shell) -> None:
        assert shell.properties.row_count == 0

    def test_choosing_a_node_fills_it_from_the_case(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("setup.general")
        assert shell.properties.row_count > 0

    def test_it_shows_the_unit_where_there_is_one(self, shell: Shell, tmp_path) -> None:
        """A dimension is part of the value's meaning in OpenFOAM."""
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("setup.general")
        rows = [r for g in shell.properties.groups for r in g.rows]
        assert any(r.unit == "s" for r in rows if r.path == "endTime")

    def test_it_names_the_file_the_settings_came_from(self, shell: Shell, tmp_path) -> None:
        """D4 — teach OpenFOAM, not the interface."""
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("setup.general")
        assert any(g.source == "system/controlDict" for g in shell.properties.groups)

    def test_two_nodes_on_one_file_show_different_settings(self, shell: Shell, tmp_path) -> None:
        """General and Calculation Activities both read controlDict.

        Showing the whole file under each would make the two nodes identical
        and teach the user that the outline is decoration.
        """
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("setup.general")
        general = {r.path for g in shell.properties.groups for r in g.rows}
        shell._on_step_selected("solution.activities")
        activities = {r.path for g in shell.properties.groups for r in g.rows}
        assert general and activities
        assert not (general & activities)


class TestTheMeshDocument:
    """DEC-23 — the generated mesh, coloured by patch, clickable to its patch."""

    def _meshed(self, shell: Shell, tmp_path):
        from test_polymesh import _cube

        case = _cavity(tmp_path, meshable=True)
        _cube(case)
        shell._session = FakeSession()
        shell.open_case(case)
        return case

    def test_geometry_and_mesh_are_separate_documents(self, shell: Shell) -> None:
        """One tab showing whichever exists would mean the picture beside the
        naming controls was sometimes a mesh."""
        assert "geometry" in shell.graphics.documents
        assert "mesh" in shell.graphics.documents
        assert shell.graphics.widget("geometry") is not shell.graphics.widget("mesh")

    def test_the_import_task_raises_the_geometry_document(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("workflow.import")
        assert shell.current_document == "geometry"

    def test_a_meshed_case_draws_its_boundary(self, shell: Shell, tmp_path) -> None:
        self._meshed(shell, tmp_path)
        assert shell._mesh_preview.triangle_count > 0
        assert shell._mesh_preview.faces_known

    def test_every_patch_is_coloured_and_named(self, shell: Shell, tmp_path) -> None:
        self._meshed(shell, tmp_path)
        assert sorted(shell._mesh_patches.values()) == ["inlet", "outlet", "walls"]

    def test_a_case_with_no_mesh_says_so(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        assert shell._mesh_preview.triangle_count == 0
        assert "No mesh yet" in shell._mesh_preview._message

    def test_every_reason_it_can_decline_has_a_sentence(self, shell: Shell) -> None:
        """A missing one would reach the user as a KeyError while drawing."""
        from foamwb.services.polymesh import Unavailable

        for reason in Unavailable:
            assert shell._labels[f"mesh_{reason.value}"].strip()

    def test_clicking_a_face_selects_its_patch(self, shell: Shell, tmp_path) -> None:
        """ "Which patch is that?" is the question the matrix cannot answer — a
        row called ``frontAndBack`` says nothing about where on the model it is."""
        self._meshed(shell, tmp_path)
        group = next(g for g, name in shell._mesh_patches.items() if name == "walls")
        shell._mesh_preview.select([group])
        assert shell.regions._selected_patch().name == "walls"

    def test_picking_does_not_move_the_user(self, shell: Shell, tmp_path) -> None:
        """They pointed at something to find out what it is; taking the model
        away from under them to answer would be a poor trade."""
        self._meshed(shell, tmp_path)
        shell._on_step_selected("results.graphics")
        before = (shell.current_document, shell.current_page)
        group = next(iter(shell._mesh_patches))
        shell._mesh_preview.select([group])
        assert (shell.current_document, shell.current_page) == before

    def test_the_mesh_is_re_read_only_when_it_changes(self, shell: Shell, tmp_path) -> None:
        """Re-reading on every refresh would be correct and would throw away the
        angle the user turned the model to — on every save."""
        self._meshed(shell, tmp_path)
        shell._mesh_preview._yaw = 2.5
        shell.refresh_workflow()
        assert shell._mesh_preview.angles[0] == 2.5

    def test_a_rebuilt_mesh_is_re_read(self, shell: Shell, tmp_path) -> None:
        import time

        case = self._meshed(shell, tmp_path)
        shell._mesh_preview._yaw = 2.5
        time.sleep(0.02)
        points = case / "constant" / "polyMesh" / "points"
        points.write_text(points.read_text())
        shell.refresh_workflow()
        assert shell._mesh_preview.angles[0] != 2.5

    def test_a_theme_change_re_derives_the_patch_colours(self, shell: Shell, tmp_path) -> None:
        """They come from the palette, so they must not stay on the old series."""
        self._meshed(shell, tmp_path)
        shell.set_theme(ThemeChoice.DARK)
        assert shell._mesh_preview._palette is DARK
        assert shell._mesh_preview.triangle_count > 0


class TestTheConsole:
    """§7.5, DEC-21 — one transcript, one findings list, under the graphics."""

    def test_it_has_a_console_and_a_messages_tab(self, shell: Shell) -> None:
        assert shell.console.current_tab == "console"
        shell.console.show_messages()
        assert shell.console.current_tab == "messages"

    def test_it_folds_to_its_title_bar(self, shell: Shell) -> None:
        shell.show()
        shell.console.set_collapsed(True)
        assert shell.console.collapsed
        # The header stays, so there is always something to press to get it back.
        assert shell.console.isVisible()

    def test_collapsing_is_carried_in_words(self, shell: Shell) -> None:
        """NFR-A2 — the ▾/▴ glyph is not the only statement of the state."""
        shell.console.set_collapsed(True)
        assert "Expand" in shell.console._toggle.accessibleName()

    def test_the_meshing_utilities_write_to_the_same_console(self, shell: Shell) -> None:
        """One transcript, not a second log pane inside a 380-pixel column.

        A user reads one stream of what the application did on their behalf, and
        a meshing utility's output is the same kind of thing as a solver's.
        """
        assert shell.editors.mesh.log is shell._console
        assert shell.run_view.log is shell._console
        assert shell.post.log is shell._console

    def test_findings_land_in_messages(self, shell: Shell, tmp_path) -> None:
        case = _cavity(tmp_path)
        (case / "0" / "U").write_bytes(b"not a dictionary {{{\n")
        shell.open_case(case)
        assert shell.messages.count > 0

    def test_with_no_case_it_says_so_rather_than_showing_an_empty_box(self, shell: Shell) -> None:
        """An empty bordered list reads as something that failed to load."""
        assert shell.messages.summary_text
        assert shell.messages.count == 0

    def test_activating_a_finding_opens_its_file(self, shell: Shell, tmp_path) -> None:
        case = _cavity(tmp_path)
        (case / "0" / "U").write_bytes(b"not a dictionary {{{\n")
        shell.open_case(case)
        shell.messages.activate(0)
        assert shell.current_document == "files"
        assert shell.editors.current_file is not None


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
        from PySide6.QtWidgets import QToolButton

        indicator = shell.footer.findChild(QToolButton, "runtimeIndicator")
        qtbot.mouseClick(indicator, Qt.MouseButton.LeftButton)
        assert shell.current_document == "setup"


class TestTheStartDocument:
    """FR-A1, §7.2 — recent cases first, actions second."""

    def test_every_action_target_exists(self, shell: Shell) -> None:
        for key, _primary in shell.hub.ACTIONS:
            assert shell.hub.action_button(key) is not None

    @pytest.mark.parametrize(
        ("action", "destination"),
        [("library", "library"), ("guide", "guide"), ("settings", "setup")],
    )
    def test_actions_reach_their_document_in_one_click(
        self, shell: Shell, qtbot, action: str, destination: str
    ) -> None:
        qtbot.mouseClick(shell.hub.action_button(action), Qt.MouseButton.LeftButton)
        assert shell.current_document == destination

    def test_no_action_button_is_inert(self, shell: Shell, qtbot) -> None:
        # FR-A1: every target reachable in one click. A button wired to nothing
        # would pass a smoke test while being useless.
        asked: list[str] = []
        reported: list[str] = []
        shell.set_dialogs(
            choose_directory=lambda title: asked.append(title),
            ask_text=lambda title, _prompt, _default: asked.append(title),
            report=lambda title, _body: reported.append(title),
        )
        interactive = {"open_case", "new_case", "case_folder"}

        for key, _primary in shell.hub.ACTIONS:
            shell.graphics.show_document("start")
            before = len(asked) + len(reported)
            qtbot.mouseClick(shell.hub.action_button(key), Qt.MouseButton.LeftButton)
            if key in interactive:
                assert len(asked) + len(reported) > before, f"{key} did nothing"
            else:
                assert shell.current_document != "start", f"{key} did nothing"

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

    def test_recent_cases_also_reach_the_file_menu(self, shell: Shell) -> None:
        """Fluent's File → Recent. The same list, so the two cannot disagree."""
        shell.set_recent_cases([RecentCase(Path("/cases/pitzDaily"))])
        assert [a.text() for a in shell.ribbon._recent.actions()] == ["/cases/pitzDaily"]

    def test_an_empty_recent_menu_says_so_rather_than_being_blank(self, shell: Shell) -> None:
        shell.set_recent_cases([])
        entries = shell.ribbon._recent.actions()
        assert len(entries) == 1
        assert not entries[0].isEnabled()

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
        assert shell.current_document == "setup"

    def test_footer_and_banner_cannot_disagree(self, shell: Shell) -> None:
        # One setter drives both, so a footer saying "ready" above a banner
        # saying "not installed" is unreachable.
        shell.set_runtime_status(BROKEN)
        assert shell.hub.banner_visible
        assert "broken" in shell.footer.runtime_text.lower()

        shell.set_runtime_status(READY)
        assert not shell.hub.banner_visible
        assert "ready" in shell.footer.runtime_text.lower()


class TestUnfinishedWork:
    """§7.9 rule 1 applies to unfinished software too."""

    def test_the_setup_document_says_what_is_coming(self, shell: Shell) -> None:
        widget = shell.graphics.widget("setup")
        text = " ".join(label.text() for label in widget.findChildren(QLabel))
        assert len(text.split()) > 8


class TestTheRibbon:
    """§7.1, DEC-21 — grouped actions, every one reachable from the keyboard."""

    def test_the_tabs_are_fluent_s(self, shell: Shell) -> None:
        assert shell.ribbon.tab_keys == ["domain", "physics", "solution", "results", "view"]

    def test_every_action_has_a_label(self, shell: Shell) -> None:
        for key in shell.ribbon.action_keys:
            if key == "guide":
                continue
            assert shell._labels[f"action.{key}"].strip()

    def test_every_shortcut_is_unique(self) -> None:
        """Two actions on one chord means one of them silently never fires."""
        from foamwb.ui.ribbon import FILE_SHORTCUTS

        shortcuts = [
            action.shortcut
            for tab in RIBBON_TABS
            for group in tab.groups
            for action in group.actions
            if action.shortcut
        ] + list(FILE_SHORTCUTS.values())
        assert len(shortcuts) == len(set(shortcuts))

    def test_a_shortcut_is_named_in_the_tooltip(self, shell: Shell, tmp_path) -> None:
        """NFR-A1's keyboard route is worthless if it cannot be discovered."""
        shell._session = FakeSession()
        shell.open_case(_cavity(tmp_path, meshable=True))
        assert "Ctrl+R" in shell.ribbon.tooltip_of("calculate")

    def test_the_shortcut_comes_back_when_an_action_is_re_enabled(
        self, shell: Shell, tmp_path
    ) -> None:
        """A disabled action's tooltip is its reason; re-enabling must restore
        the sentence *and* the shortcut, not a recomposed copy without it."""
        assert "mesh" in shell.ribbon.tooltip_of("calculate").lower()
        shell._session = FakeSession()
        shell.open_case(_cavity(tmp_path, meshable=True))
        assert "Ctrl+R" in shell.ribbon.tooltip_of("calculate")

    def test_the_file_menu_holds_the_one_shot_commands(self, shell: Shell) -> None:
        expected = [key for key in FILE_MENU if key not in (None, "recent")]
        assert shell.ribbon.menu_keys == expected

    def test_switching_tabs_changes_nothing_else(self, shell: Shell, tmp_path) -> None:
        """A ribbon tab is a set of tools, not a place. Selecting one must not
        move the user's work out from under them."""
        shell.open_case(_cavity(tmp_path))
        shell._on_step_selected("setup.general")
        shell.ribbon.show_tab("results")
        assert shell.current_step == "setup.general"
        assert shell.current_document == "start" or shell.current_document

    def test_a_blocked_action_refuses_rather_than_navigating(self, shell: Shell, tmp_path) -> None:
        """Pressing a disabled action by shortcut must not reach a blocked node."""
        before = shell.current_step
        shell._on_ribbon_action("calculate")
        assert shell.current_step == before


class TestThemes:
    """NFR-A4 — light and dark, following the OS setting."""

    @pytest.mark.parametrize("palette", [LIGHT, DARK])
    def test_shell_builds_under_either_palette(self, qtbot, palette) -> None:
        window = Shell(palette)
        qtbot.addWidget(window)
        assert window.current_document == "start"

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

    def test_the_ribbon_offers_the_same_choice(self, themed) -> None:
        window, _service = themed
        window.ribbon.trigger("theme_dark")
        assert window.theme is ThemeChoice.DARK

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
        # The style sheet does not reach item brushes, syntax highlighting, the
        # ribbon's icons or the plot canvas, so each of these keeps its own copy
        # and would otherwise stay on the previous theme.
        window, _service = themed
        window.set_theme(ThemeChoice.DARK)
        for widget in (
            window.footer,
            window.ribbon,
            window.outline,
            window.messages,
            window.run_view,
            window.editors,
            window.editors.form,
            window.editors.text,
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
    """FR-C1 — *New Case* creates a case rather than showing an empty panel."""

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

    def test_lands_on_the_task_that_takes_geometry(self, shell: Shell, tmp_path: Path) -> None:
        # A new case has no mesh and no fields; the next thing to do with it is
        # import a model, so it must not open on a page that hides that.
        self._wire(shell, tmp_path)
        shell.new_case_dialog()
        assert shell.current_step == "workflow.import"
        assert shell.current_page == "geometry"

    def test_the_file_menu_reaches_it(self, shell: Shell, tmp_path: Path) -> None:
        self._wire(shell, tmp_path)
        shell.ribbon.trigger("new_case")
        assert (tmp_path / "wing" / "system" / "controlDict").is_file()

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
    """The *File → Case Folder* action."""

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


class TestTheOutlineReadsAsOne:
    """§7.2 — the tree has to be legible as the structure of a case."""

    def test_every_node_lives_inside_a_group(self) -> None:
        # Headers and nodes sharing an indent level are told apart only by a
        # glyph, which is not a difference anyone reads.
        for step in STEPS:
            if not step.is_group:
                assert step.parent, f"{step.id} is a node with no group"

    def test_a_blocked_row_says_so_in_words_on_the_row(self, shell: Shell) -> None:
        """Not only in a tooltip.

        "Why can I not click this?" is the question the tree most needed to
        answer, and a tooltip answers it only for someone using a mouse who
        already suspected there was something to hover over.
        """
        assert "not yet" in shell.outline.text_of("solution.run")

    def test_an_available_row_is_not_cluttered_with_its_state(self, shell: Shell, tmp_path) -> None:
        # Saying "ready" on every ordinary row is noise, not information.
        shell.open_case(_cavity(tmp_path))
        assert "ready" not in shell.outline.text_of("setup.general")

    def test_progress_is_reported(self, shell: Shell, tmp_path) -> None:
        shell.open_case(_cavity(tmp_path))
        done, total = shell.outline.model.progress
        assert total == len([s for s in STEPS if s.required])
        assert f"{done} of {total}" in shell.outline.progress_text

    def test_progress_moves_when_a_node_completes(self, shell: Shell, tmp_path) -> None:
        case = _cavity(tmp_path)
        shell.open_case(case)
        before, _ = shell.outline.model.progress

        _mesh(case)
        shell.open_case(case)
        after, _ = shell.outline.model.progress
        assert after > before

    def test_clicking_a_group_folds_it_rather_than_doing_nothing(self, shell: Shell) -> None:
        """A header that swallows a click reads as broken."""
        nav = shell.outline
        item = nav._items["setup"]
        assert item.isExpanded()
        nav._on_clicked(item, 0)
        assert not item.isExpanded()
        nav._on_clicked(item, 0)
        assert item.isExpanded()
