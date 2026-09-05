"""The outline model and the property mapping (§7.2, §7.4, DEC-21).

Both are Qt-free services, so what the Outline View *says* and what the task
page *shows* are decided here and merely rendered there. That is what lets the
shape of the interface be asserted without a window.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.services.freshness import Freshness
from foamwb.services.properties import (
    STEP_SOURCES,
    PropertyGroup,
    Source,
    groups_for_step,
    rows_from_document,
)
from foamwb.services.schema import load_schema
from foamwb.services.workflow import (
    STEPS,
    Phase,
    StepKind,
    StepState,
    WorkflowModel,
    step_by_id,
)

CONTROL_DICT = (
    "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
    "application     icoFoam;\n"
    "startTime       0;\n"
    "endTime         0.5;\n"
    "deltaT          0.005;\n"
    "writeControl    timeStep;\n"
    "writeInterval   20;\n"
    "someKeyWeDoNotKnow  42;\n"
)


def _case(tmp_path: Path, *, meshed: bool = False, results: bool = False) -> Path:
    case = tmp_path / "cavity"
    # Idempotent: a single test builds the same case for several models.
    (case / "system").mkdir(parents=True, exist_ok=True)
    (case / "constant").mkdir(exist_ok=True)
    (case / "0").mkdir(exist_ok=True)
    (case / "system" / "controlDict").write_text(CONTROL_DICT)
    if meshed:
        (case / "constant" / "polyMesh").mkdir(exist_ok=True)
    if results:
        (case / "0.5").mkdir(exist_ok=True)
    return case


class TestTheWorkflowIsAProcedure:
    def test_it_is_ordered(self) -> None:
        """The list is read downwards; its order is the procedure."""
        ids = [step.id for step in STEPS]
        assert ids.index("workflow.volume") < ids.index("solution.run")
        assert ids.index("setup.general") < ids.index("solution.run")
        assert ids.index("solution.run") < ids.index("results.graphics")

    def test_children_follow_their_group(self) -> None:
        ids = [step.id for step in STEPS]
        for step in STEPS:
            if step.parent:
                assert ids.index(step.parent) < ids.index(step.id)

    def test_every_group_has_children(self) -> None:
        model = WorkflowModel()
        for step in STEPS:
            if step.kind is StepKind.GROUP:
                assert model.children_of(step.id), f"{step.id} is an empty header"

    def test_every_step_id_is_unique(self) -> None:
        ids = [step.id for step in STEPS]
        assert len(ids) == len(set(ids))

    def test_lookup_by_id(self) -> None:
        assert step_by_id("solution.run") is not None
        assert step_by_id("nonsense") is None


class TestPhases:
    def test_no_case_is_its_own_phase(self) -> None:
        assert WorkflowModel().phase is Phase.NO_CASE

    def test_a_case_without_a_mesh_is_in_the_mesh_phase(self, tmp_path) -> None:
        assert WorkflowModel(case=_case(tmp_path)).phase is Phase.MESH

    def test_a_mesh_moves_the_case_on(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.phase is Phase.ANALYSIS


class TestWhatIsOffered:
    def test_nothing_needing_a_case_is_offered_without_one(self) -> None:
        model = WorkflowModel()
        assert model.state_of(step_by_id("setup.general")) is StepState.BLOCKED

    def test_execution_needs_a_mesh(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path))
        assert model.state_of(step_by_id("solution.run")) is StepState.BLOCKED

    def test_a_mesh_unblocks_execution(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("solution.run")) is StepState.AVAILABLE

    def test_a_plan_that_meshes_unblocks_execution_too(self, tmp_path) -> None:
        """The run's own first stage is a mesh, so there is nothing to wait for.

        The regression this exists for: a freshly opened blockMesh tutorial has
        no polyMesh, so *Run* was blocked — and since blocked rows cannot be
        clicked or stepped onto, the button that would have run blockMesh was
        unreachable for want of the mesh blockMesh would have made.
        """
        model = WorkflowModel(case=_case(tmp_path), plan_meshes=True)
        assert model.state_of(step_by_id("solution.run")) is StepState.AVAILABLE

    def test_a_plan_that_meshes_does_not_unblock_post_processing(self, tmp_path) -> None:
        """Nothing about opening Results creates the mesh they would show."""
        model = WorkflowModel(case=_case(tmp_path), plan_meshes=True)
        assert model.state_of(step_by_id("results.graphics")) is StepState.BLOCKED

    def test_execution_is_still_not_reported_done(self, tmp_path) -> None:
        """Unblocked is not finished: results are what prove a run happened."""
        model = WorkflowModel(case=_case(tmp_path), plan_meshes=True)
        assert model.state_of(step_by_id("solution.run")) is not StepState.DONE

    def test_the_reason_a_row_is_blocked_matches_its_state(self, tmp_path) -> None:
        """The panel names the mesh as the blocker; it must be blocked by it."""
        for model in (
            WorkflowModel(case=_case(tmp_path)),
            WorkflowModel(case=_case(tmp_path), plan_meshes=True),
            WorkflowModel(case=_case(tmp_path), has_mesh=True),
        ):
            for step in STEPS:
                if model.awaiting_mesh(step):
                    assert model.state_of(step) is StepState.BLOCKED

    def test_a_step_with_nothing_behind_it_is_not_drawn(self, tmp_path) -> None:
        """A row that opens a blank page is a promise the application breaks."""
        model = WorkflowModel(case=_case(tmp_path), empty_steps=frozenset({"setup.materials"}))
        assert not model.is_offered(step_by_id("setup.materials"))
        assert "materials" not in [s.id for s in model.offered_steps()]

    def test_hiding_is_not_the_same_as_blocking(self, tmp_path) -> None:
        """Blocked means "do the earlier step"; nothing the user does unhides this."""
        model = WorkflowModel(case=_case(tmp_path), empty_steps=frozenset({"setup.materials"}))
        assert model.state_of(step_by_id("setup.materials")) is not StepState.BLOCKED

    def test_a_hidden_step_leaves_its_group(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), empty_steps=frozenset({"setup.materials"}))
        assert "materials" not in [s.id for s in model.children_of("setup")]

    def test_nothing_is_hidden_by_default(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path))
        assert len(model.offered_steps()) == len(STEPS)

    def test_a_hidden_step_is_never_proposed_as_next(self, tmp_path) -> None:
        """Naming a step the panel does not draw would send the user nowhere."""
        model = WorkflowModel(case=_case(tmp_path), empty_steps=frozenset(s.id for s in STEPS))
        assert model.next_step is None
        assert model.resume_step is None

    def test_every_node_needs_a_case(self) -> None:
        """The outline describes *a case*, so nothing in it means anything
        without one — which is why the empty window says "open a case" rather
        than offering a tree of live rows."""
        model = WorkflowModel()
        for step in STEPS:
            if step.is_group:
                continue
            assert model.state_of(step) is StepState.BLOCKED, step.id


class TestDoneMeansEvidence:
    """A step is done because something exists, never because it was visited."""

    def test_meshing_is_evidenced_by_the_mesh(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("workflow.volume")) is StepState.DONE

    def test_editing_a_dictionary_is_never_reported_as_done(self, tmp_path) -> None:
        """Visiting the editor proves nothing about what was written."""
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True, has_results=True)
        assert model.state_of(step_by_id("setup.boundary")) is not StepState.DONE

    def test_a_finished_step_reads_done_not_locked(self, tmp_path) -> None:
        """Progress is the one thing the user should not lose to a phase change."""
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("workflow.volume")) is StepState.DONE

    def test_the_mesh_editors_lock_once_the_mesh_exists(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("workflow.sizing")) is StepState.LOCKED

    def test_locking_is_reversible(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        model.set_state("workflow.sizing", StepState.AVAILABLE)
        assert model.state_of(step_by_id("workflow.sizing")) is StepState.AVAILABLE
        model.set_state("workflow.sizing", None)
        assert model.state_of(step_by_id("workflow.sizing")) is StepState.LOCKED


class TestStaleMeansDoneAndThenUndone:
    """DEC-22 — Workbench's ⚡, and why it is not just a prettier tick.

    A tick on a result computed from a case the user has since edited is the
    most expensive lie this interface could tell, because it is the one a
    student would put in a report.
    """

    def _meshed(self, tmp_path, **freshness) -> WorkflowModel:
        return WorkflowModel(
            case=_case(tmp_path),
            has_mesh=True,
            has_results=True,
            freshness=Freshness(has_mesh=True, has_results=True, **freshness),
        )

    def test_a_current_case_reads_done(self, tmp_path) -> None:
        model = self._meshed(tmp_path)
        assert model.state_of(step_by_id("workflow.volume")) is StepState.DONE
        assert model.state_of(step_by_id("solution.run")) is StepState.DONE

    def test_a_changed_mesh_input_marks_the_mesh(self, tmp_path) -> None:
        model = self._meshed(tmp_path, mesh_stale_because="system/blockMeshDict")
        assert model.state_of(step_by_id("workflow.volume")) is StepState.STALE

    def test_a_changed_mesh_input_marks_the_run_too(self, tmp_path) -> None:
        """Workbench's downstream propagation: a result from a mesh that is
        about to be rebuilt is out of date whether or not the solver's own
        settings have changed."""
        model = self._meshed(tmp_path, mesh_stale_because="system/blockMeshDict")
        assert model.state_of(step_by_id("solution.run")) is StepState.STALE

    def test_a_changed_solver_input_does_not_mark_the_mesh(self, tmp_path) -> None:
        """Propagation runs downstream only. Editing fvSchemes does not
        invalidate a mesh, and saying it did would make the mark meaningless."""
        model = self._meshed(tmp_path, results_stale_because="system/fvSchemes")
        assert model.state_of(step_by_id("workflow.volume")) is StepState.DONE
        assert model.state_of(step_by_id("solution.run")) is StepState.STALE

    def test_the_reason_travels_with_the_state(self, tmp_path) -> None:
        model = self._meshed(tmp_path, mesh_stale_because="system/blockMeshDict")
        assert model.stale_because(step_by_id("workflow.volume")) == "system/blockMeshDict"

    def test_the_run_names_its_own_reason_when_it_has_one(self, tmp_path) -> None:
        model = self._meshed(tmp_path, results_stale_because="0/U")
        assert model.stale_because(step_by_id("solution.run")) == "0/U"

    def test_a_current_node_has_no_reason(self, tmp_path) -> None:
        assert self._meshed(tmp_path).stale_because(step_by_id("solution.run")) == ""

    def test_check_case_is_never_stale(self, tmp_path) -> None:
        """Its verdict is recomputed on every refresh rather than stored, so it
        cannot be out of date with what it describes. Marking it would be
        theatre."""
        model = WorkflowModel(
            case=_case(tmp_path),
            has_mesh=True,
            has_results=True,
            checks_passed=True,
            freshness=Freshness(
                has_mesh=True, has_results=True, mesh_stale_because="system/blockMeshDict"
            ),
        )
        assert model.state_of(step_by_id("solution.check")) is StepState.DONE

    def test_a_node_that_never_happened_is_not_stale(self, tmp_path) -> None:
        """Stale means done-and-then-undone. Nothing was done here."""
        model = WorkflowModel(
            case=_case(tmp_path),
            freshness=Freshness(mesh_stale_because="system/blockMeshDict"),
        )
        assert model.state_of(step_by_id("workflow.volume")) is not StepState.STALE

    def test_a_stale_node_no_longer_counts_as_progress(self, tmp_path) -> None:
        done_before, _ = self._meshed(tmp_path).progress
        done_after, _ = self._meshed(tmp_path, mesh_stale_because="system/blockMeshDict").progress
        assert done_after < done_before

    def test_a_stale_node_is_what_to_do_next(self, tmp_path) -> None:
        """A "what next?" that skipped past it would send the user to a later
        step whose inputs are about to be replaced."""
        model = self._meshed(tmp_path, mesh_stale_because="system/blockMeshDict")
        assert model.next_step.id == "workflow.volume"

    def test_every_state_is_distinct(self) -> None:
        assert len({state.value for state in StepState}) == len(StepState)


class TestWhatToDoNext:
    """The question P1 actually has, which the old destination rail never answered."""

    def test_with_nothing_open_there_is_no_next_node(self) -> None:
        """Every node needs a case, so the honest answer is "none of them".

        The words the user reads — "Open a case to begin" — belong to the
        outline, which is the thing that knows there is no case; the model does
        not invent a node that is not in the tree.
        """
        assert WorkflowModel().next_step is None

    def test_with_a_case_it_is_the_mesh(self, tmp_path) -> None:
        assert WorkflowModel(case=_case(tmp_path)).next_step.id == "workflow.volume"

    def test_with_a_mesh_it_is_to_check_the_case(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.next_step.id == "solution.check"

    def test_it_never_suggests_merely_browsing(self, tmp_path) -> None:
        """ "Browse your files" is noise dressed as guidance."""
        for model in (
            WorkflowModel(),
            WorkflowModel(case=_case(tmp_path)),
            WorkflowModel(case=_case(tmp_path), has_mesh=True),
        ):
            following = model.next_step
            assert following is None or following.required

    def test_it_never_suggests_browsing_the_files(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True, has_results=True)
        assert model.next_step is None or model.next_step.parent != "files"


class TestGeometryIsEvidenceToo:
    """A surface on disk is proof of the geometry step, in the same sense a
    polyMesh is proof of the mesh step."""

    def test_a_case_with_no_surface_is_not_done(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path))
        assert model.state_of(step_by_id("workflow.import")) is StepState.AVAILABLE

    def test_an_imported_surface_ticks_the_step(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_geometry=True)
        assert model.state_of(step_by_id("workflow.import")) is StepState.DONE


class TestWhereOpeningACaseLands:
    """Opening a case has to leave the user somewhere; the workflow decides."""

    def test_nothing_open_resumes_nowhere(self) -> None:
        assert WorkflowModel().resume_step is None

    def test_a_fresh_case_resumes_on_its_geometry(self, tmp_path) -> None:
        # Not the Run view, which is where it used to land — telling a user with
        # no mesh to run a solver that cannot start.
        assert WorkflowModel(case=_case(tmp_path)).resume_step.id == "workflow.import"

    def test_a_meshed_case_resumes_past_the_mesh(self, tmp_path) -> None:
        # The mesh phase is locked once a mesh exists, and resuming into a locked
        # phase would be a page whose prerequisites are behind the user.
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.resume_step.id not in {"workflow.import", "workflow.sizing"}

    def test_it_never_resumes_on_the_file_browser(self, tmp_path) -> None:
        """Landing a user in a list of dictionaries answers no question they
        have just asked by opening a case."""
        for model in (
            WorkflowModel(case=_case(tmp_path)),
            WorkflowModel(case=_case(tmp_path), has_mesh=True),
            WorkflowModel(case=_case(tmp_path), has_mesh=True, has_results=True),
        ):
            assert model.resume_step is None or model.resume_step.parent != "files"

    def test_it_never_resumes_on_something_unreachable(self, tmp_path) -> None:
        for model in (
            WorkflowModel(case=_case(tmp_path)),
            WorkflowModel(case=_case(tmp_path), has_mesh=True),
        ):
            step = model.resume_step
            assert step is None or model.state_of(step) is StepState.AVAILABLE


class TestPropertyRows:
    def test_a_step_maps_to_its_files(self, tmp_path) -> None:
        groups = groups_for_step(_case(tmp_path), "setup.general")
        assert [g.source for g in groups] == ["system/controlDict"]

    def test_rows_carry_the_path_they_write_back_to(self, tmp_path) -> None:
        """The label and the key are the same object, so they cannot drift."""
        groups = groups_for_step(_case(tmp_path), "setup.general")
        rows = {row.path: row for row in groups[0].rows}
        assert rows["endTime"].label == "End time"
        assert rows["endTime"].value == "0.5"

    def test_units_are_their_own_column(self, tmp_path) -> None:
        groups = groups_for_step(_case(tmp_path), "setup.general")
        rows = {row.path: row for row in groups[0].rows}
        assert rows["endTime"].unit == "s"
        assert rows["deltaT"].unit == "s"

    def test_a_dimensionless_entry_claims_no_unit(self, tmp_path) -> None:
        groups = groups_for_step(_case(tmp_path), "setup.general")
        rows = {row.path: row for row in groups[0].rows}
        assert rows["application"].unit == ""

    def test_unknown_entries_are_shown_and_marked(self, tmp_path) -> None:
        """A form that dropped them would let a user believe they had seen the
        whole file, and FR-P7 promises those entries survive untouched."""
        case = _case(tmp_path)
        (case / "system" / "fvSolution").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }\n"
            "SIMPLE { nNonOrthogonalCorrectors 0; }\nsomeKeyWeDoNotKnow 42;\n"
        )
        groups = groups_for_step(case, "solution.controls")
        unknown = [row for row in groups[0].rows if row.unknown]
        assert any(row.path == "someKeyWeDoNotKnow" for row in unknown)

    def test_unknown_entries_are_not_editable_here(self, tmp_path) -> None:
        case = _case(tmp_path)
        (case / "system" / "fvSolution").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }\n"
            "someKeyWeDoNotKnow 42;\n"
        )
        groups = groups_for_step(case, "solution.controls")
        unknown = next(r for r in groups[0].rows if r.path == "someKeyWeDoNotKnow")
        assert not unknown.editable

    def test_schema_order_comes_first(self, tmp_path) -> None:
        """Not alphabetical, not file order: the order settings are reasoned about."""
        groups = groups_for_step(_case(tmp_path), "setup.general")
        paths = [row.path for row in groups[0].rows]
        assert paths.index("application") < paths.index("endTime")


class TestOneFileServesSeveralNodes:
    """Fluent splits controlDict's concerns across three nodes (DEC-21).

    Showing the whole file under each would make them look identical and teach
    the user that the outline is decoration.
    """

    def test_general_holds_the_solver_and_the_time_span(self, tmp_path) -> None:
        rows = {r.path for g in groups_for_step(_case(tmp_path), "setup.general") for r in g.rows}
        assert {"application", "endTime", "deltaT"} <= rows

    def test_activities_holds_the_write_settings(self, tmp_path) -> None:
        rows = {
            r.path for g in groups_for_step(_case(tmp_path), "solution.activities") for r in g.rows
        }
        assert {"writeControl", "writeInterval"} <= rows

    def test_the_two_do_not_overlap(self, tmp_path) -> None:
        case = _case(tmp_path)
        general = {r.path for g in groups_for_step(case, "setup.general") for r in g.rows}
        activities = {r.path for g in groups_for_step(case, "solution.activities") for r in g.rows}
        assert general and activities
        assert not (general & activities)

    def test_an_entry_no_node_claims_is_simply_not_shown(self, tmp_path) -> None:
        """It is still in the file, still editable in the Text tab, and still
        byte-identical after a save (FR-P7) — it is just not this node's."""
        case = _case(tmp_path)
        for step_id in ("setup.general", "solution.activities", "solution.monitors"):
            rows = {r.path for g in groups_for_step(case, step_id) for r in g.rows}
            assert "someKeyWeDoNotKnow" not in rows

    def test_a_source_with_no_key_filter_shows_the_whole_file(self) -> None:
        assert Source("system/fvSchemes", "fvSchemes").owns("anything")

    def test_a_nested_path_follows_its_top_level_key(self) -> None:
        """``functions/solverInfo`` belongs to whichever node owns ``functions``."""
        source = Source("system/controlDict", "controlDict", ("functions",))
        assert source.owns("functions/solverInfo")
        assert not source.owns("endTime")


class TestLineageSpecificFilesComeFromTheManifest:
    """NFR-M3, DEC-15 — the file's *name* is data, never a literal in code."""

    def test_a_role_resolves_to_a_filename(self) -> None:
        resolved = Source("constant/@turbulence").resolve()
        assert resolved.startswith("constant/")
        assert "@" not in resolved

    def test_a_plain_path_is_left_alone(self) -> None:
        assert Source("system/controlDict").resolve() == "system/controlDict"

    def test_the_models_node_reads_the_turbulence_dictionary(self, tmp_path) -> None:
        case = _case(tmp_path)
        name = Source("constant/@turbulence").resolve().rsplit("/", 1)[-1]
        (case / "constant" / name).write_text(
            f"FoamFile {{ version 2.0; format ascii; class dictionary; object {name}; }}\n"
            "simulationType RAS;\n"
        )
        rows = {r.path for g in groups_for_step(case, "setup.models") for r in g.rows}
        assert "simulationType" in rows

    def test_a_missing_file_is_reported_as_missing_not_empty(self, tmp_path) -> None:
        """ "No settings" and "no file" are different problems."""
        case = _case(tmp_path)
        groups = groups_for_step(case, "solution.controls")
        assert groups and all(g.missing for g in groups)

    def test_an_unparseable_file_does_not_raise(self, tmp_path) -> None:
        case = _case(tmp_path)
        (case / "system" / "fvSchemes").write_text("{{{ not a dictionary")
        groups = groups_for_step(case, "solution.controls")
        assert isinstance(groups[0], PropertyGroup)

    def test_no_case_means_no_rows(self) -> None:
        assert groups_for_step(None, "setup.general") == ()

    def test_a_step_with_no_files_yields_nothing(self, tmp_path) -> None:
        assert groups_for_step(_case(tmp_path), "results.reports") == ()

    @pytest.mark.parametrize("step_id", sorted(STEP_SOURCES))
    def test_every_mapped_step_exists(self, step_id: str) -> None:
        assert step_by_id(step_id) is not None


class TestRowsFromDocument:
    def test_a_schema_with_no_document_entries_yields_nothing(self) -> None:
        from foamwb.services.foamdict import Document

        document = Document.parse_bytes(b"FoamFile { object controlDict; }\n")
        rows = rows_from_document(document, load_schema("controlDict"))
        assert all(row.unknown for row in rows)

    def test_unknown_rows_can_be_suppressed(self, tmp_path) -> None:
        from foamwb.services.foamdict import Document

        document = Document.parse_bytes(CONTROL_DICT.encode())
        rows = rows_from_document(document, load_schema("controlDict"), include_unknown=False)
        assert not any(row.unknown for row in rows)
