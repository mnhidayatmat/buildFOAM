"""The workflow model and the property mapping (§7.2, §7.4).

Both are Qt-free services, so what the navigation panel *says* and what the
property panel *shows* are decided here and merely rendered there. That is what
lets the shape of the interface be asserted without a window.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.services.properties import (
    STEP_SOURCES,
    PropertyGroup,
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
        assert ids.index("mesh.generate") < ids.index("execute")
        assert ids.index("conditions.basic") < ids.index("execute")
        assert ids.index("execute") < ids.index("results")

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
        assert step_by_id("execute") is not None
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
        assert model.state_of(step_by_id("conditions.basic")) is StepState.BLOCKED

    def test_execution_needs_a_mesh(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path))
        assert model.state_of(step_by_id("execute")) is StepState.BLOCKED

    def test_a_mesh_unblocks_execution(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("execute")) is StepState.AVAILABLE

    def test_the_library_needs_no_case(self) -> None:
        model = WorkflowModel()
        assert model.state_of(step_by_id("library")) is StepState.AVAILABLE


class TestDoneMeansEvidence:
    """A step is done because something exists, never because it was visited."""

    def test_opening_a_case_is_evidenced_by_the_case(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path))
        assert model.state_of(step_by_id("case.open")) is StepState.DONE

    def test_meshing_is_evidenced_by_the_mesh(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("mesh.generate")) is StepState.DONE

    def test_editing_a_dictionary_is_never_reported_as_done(self, tmp_path) -> None:
        """Visiting the editor proves nothing about what was written."""
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True, has_results=True)
        assert model.state_of(step_by_id("conditions.boundary")) is not StepState.DONE

    def test_a_finished_step_reads_done_not_locked(self, tmp_path) -> None:
        """Progress is the one thing the user should not lose to a phase change."""
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("mesh.generate")) is StepState.DONE

    def test_the_mesh_editors_lock_once_the_mesh_exists(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.state_of(step_by_id("mesh.settings")) is StepState.LOCKED

    def test_locking_is_reversible(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        model.set_state("mesh.settings", StepState.AVAILABLE)
        assert model.state_of(step_by_id("mesh.settings")) is StepState.AVAILABLE
        model.set_state("mesh.settings", None)
        assert model.state_of(step_by_id("mesh.settings")) is StepState.LOCKED


class TestWhatToDoNext:
    """The question P1 actually has, which the old destination rail never answered."""

    def test_with_nothing_open_it_is_to_open_something(self) -> None:
        assert WorkflowModel().next_step.id == "case.open"

    def test_with_a_case_it_is_the_mesh(self, tmp_path) -> None:
        assert WorkflowModel(case=_case(tmp_path)).next_step.id == "mesh.generate"

    def test_with_a_mesh_it_is_to_check_the_setup(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True)
        assert model.next_step.id == "verify"

    def test_it_never_suggests_merely_browsing(self, tmp_path) -> None:
        """ "Browse your files" is noise dressed as guidance."""
        for model in (
            WorkflowModel(),
            WorkflowModel(case=_case(tmp_path)),
            WorkflowModel(case=_case(tmp_path), has_mesh=True),
        ):
            following = model.next_step
            assert following is None or following.required

    def test_it_never_suggests_a_reference(self, tmp_path) -> None:
        model = WorkflowModel(case=_case(tmp_path), has_mesh=True, has_results=True)
        assert model.next_step is None or model.next_step.id not in {"library", "guide"}


class TestPropertyRows:
    def test_a_step_maps_to_its_files(self, tmp_path) -> None:
        groups = groups_for_step(_case(tmp_path), "conditions.basic")
        assert [g.source for g in groups] == ["system/controlDict"]

    def test_rows_carry_the_path_they_write_back_to(self, tmp_path) -> None:
        """The label and the key are the same object, so they cannot drift."""
        groups = groups_for_step(_case(tmp_path), "conditions.basic")
        rows = {row.path: row for row in groups[0].rows}
        assert rows["endTime"].label == "End time"
        assert rows["endTime"].value == "0.5"

    def test_units_are_their_own_column(self, tmp_path) -> None:
        groups = groups_for_step(_case(tmp_path), "conditions.basic")
        rows = {row.path: row for row in groups[0].rows}
        assert rows["endTime"].unit == "s"
        assert rows["deltaT"].unit == "s"

    def test_a_dimensionless_entry_claims_no_unit(self, tmp_path) -> None:
        groups = groups_for_step(_case(tmp_path), "conditions.basic")
        rows = {row.path: row for row in groups[0].rows}
        assert rows["application"].unit == ""

    def test_unknown_entries_are_shown_and_marked(self, tmp_path) -> None:
        """A form that dropped them would let a user believe they had seen the
        whole file, and FR-P7 promises those entries survive untouched."""
        groups = groups_for_step(_case(tmp_path), "conditions.basic")
        unknown = [row for row in groups[0].rows if row.unknown]
        assert any(row.path == "someKeyWeDoNotKnow" for row in unknown)

    def test_unknown_entries_are_not_editable_here(self, tmp_path) -> None:
        groups = groups_for_step(_case(tmp_path), "conditions.basic")
        unknown = next(r for r in groups[0].rows if r.path == "someKeyWeDoNotKnow")
        assert not unknown.editable

    def test_schema_order_comes_first(self, tmp_path) -> None:
        """Not alphabetical, not file order: the order settings are reasoned about."""
        groups = groups_for_step(_case(tmp_path), "conditions.basic")
        paths = [row.path for row in groups[0].rows]
        assert paths.index("application") < paths.index("endTime")
        assert paths[-1] == "someKeyWeDoNotKnow"

    def test_a_missing_file_is_reported_as_missing_not_empty(self, tmp_path) -> None:
        """ "No settings" and "no file" are different problems."""
        case = _case(tmp_path)
        groups = groups_for_step(case, "conditions.control")
        assert groups and all(g.missing for g in groups)

    def test_an_unparseable_file_does_not_raise(self, tmp_path) -> None:
        case = _case(tmp_path)
        (case / "system" / "fvSchemes").write_text("{{{ not a dictionary")
        groups = groups_for_step(case, "conditions.control")
        assert isinstance(groups[0], PropertyGroup)

    def test_no_case_means_no_rows(self) -> None:
        assert groups_for_step(None, "conditions.basic") == ()

    def test_a_step_with_no_files_yields_nothing(self, tmp_path) -> None:
        assert groups_for_step(_case(tmp_path), "guide") == ()

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
