"""RunPlan (§4.3).

The parallel-rendering tests are the mechanical guard behind DEC-06. v1.0 ships
sequential-only, so nothing in the *application* will exercise ``n_procs > 1``
until v1.1 — which is precisely why these assertions exist now. If someone
short-cuts the stage machinery into a serial pipeline, this file fails at M0
instead of the problem surfacing at M10 as a rewrite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.services.case import CaseService
from foamwb.services.freshness import Freshness
from foamwb.services.run import (
    RunPlan,
    Severity,
    Stage,
    StageState,
    build_update_plan,
    plan_generates_mesh,
)

#: Enough of one for `build_plan` to see a case it can mesh. What it *would*
#: mesh is beside the point here: the plan is composed from the file's presence,
#: never from its contents.
BLOCK_MESH_DICT = (
    "FoamFile { version 2.0; format ascii; class dictionary; object blockMeshDict; }\n"
    "convertToMeters 1;\n"
)


def solve_plan(n_procs: int = 1) -> RunPlan:
    """The §4.3 worked example, verbatim."""
    return RunPlan(
        case=Path("/cases/pitzDaily"),
        n_procs=n_procs,
        stages=(
            Stage("blockMesh", argv=("blockMesh",)),
            Stage("checkMesh", argv=("checkMesh",), fail_on=Severity.ERROR),
            Stage("decomposePar", argv=("decomposePar",), when=lambda p: p.n_procs > 1),
            Stage("solve", argv=("simpleFoam",), parallel=True, monitored=True),
            Stage("reconstructPar", argv=("reconstructPar",), when=lambda p: p.n_procs > 1),
        ),
    )


class TestSequential:
    def test_v1_0_default_is_one_processor(self) -> None:
        assert RunPlan(case=Path("/c")).n_procs == 1

    def test_decomposition_stages_are_inactive(self) -> None:
        names = [s.name for s in solve_plan().active_stages()]
        assert names == ["blockMesh", "checkMesh", "solve"]

    def test_solver_runs_bare_without_mpirun(self) -> None:
        rendered = solve_plan().render()
        assert ("simpleFoam",) in rendered
        assert not any("mpirun" in argv for argv in rendered)

    def test_inactive_stages_are_shown_as_skipped_not_hidden(self) -> None:
        # FR-S1: the plan the user reviewed is the plan they watch execute.
        states = solve_plan().stage_states()
        assert states["decomposePar"] is StageState.SKIPPED
        assert states["reconstructPar"] is StageState.SKIPPED
        assert states["solve"] is StageState.PENDING


class TestParallelMachinery:
    """DEC-06: the machinery must already be correct, though the UI hides it."""

    def test_decomposition_stages_activate(self) -> None:
        names = [s.name for s in solve_plan(4).active_stages()]
        assert names == [
            "blockMesh",
            "checkMesh",
            "decomposePar",
            "solve",
            "reconstructPar",
        ]

    def test_parallel_stage_is_wrapped_in_mpirun(self) -> None:
        solve = Stage("solve", argv=("simpleFoam",), parallel=True)
        assert solve.render(4) == ("mpirun", "-np", "4", "simpleFoam", "-parallel")

    def test_parallel_flag_follows_the_solver_not_mpirun(self) -> None:
        # OpenFOAM parses -parallel as the solver's argument, so its position is
        # load-bearing, not cosmetic.
        rendered = Stage("solve", argv=("interFoam",), parallel=True).render(2)
        assert rendered[-1] == "-parallel"
        assert rendered.index("interFoam") < rendered.index("-parallel")

    def test_serial_stages_are_never_wrapped(self) -> None:
        # decomposePar and reconstructPar run once, serially, either side of the
        # solve. Wrapping either in mpirun would corrupt the decomposition.
        for name in ("decomposePar", "reconstructPar", "blockMesh"):
            assert Stage(name, argv=(name,)).render(8) == (name,)

    def test_argv_with_extra_flags_survives_wrapping(self) -> None:
        stage = Stage("solve", argv=("simpleFoam", "-case", "/cases/x"), parallel=True)
        assert stage.render(3) == (
            "mpirun",
            "-np",
            "3",
            "simpleFoam",
            "-case",
            "/cases/x",
            "-parallel",
        )

    def test_is_parallel_reflects_processor_count(self) -> None:
        assert not solve_plan(1).is_parallel
        assert solve_plan(2).is_parallel


class TestValidation:
    def test_zero_processors_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            RunPlan(case=Path("/c"), n_procs=0)

    def test_negative_processors_rejected_at_stage_render(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            Stage("solve", argv=("simpleFoam",)).render(-1)

    def test_duplicate_stage_names_are_rejected(self) -> None:
        # Run history and the stage strip both key on the name.
        with pytest.raises(ValueError, match="unique"):
            RunPlan(
                case=Path("/c"),
                stages=(Stage("solve", argv=("a",)), Stage("solve", argv=("b",))),
            )

    def test_severity_is_a_threshold_not_an_exact_match(self) -> None:
        assert Severity.ERROR > Severity.WARNING > Severity.INFO
        assert Severity.FATAL > Severity.ERROR


class TestPlanGeneratesMesh:
    """What the workflow panel asks before blocking *Run* on a missing mesh."""

    def test_a_plan_beginning_with_blockmesh_makes_its_own_mesh(self) -> None:
        assert plan_generates_mesh(solve_plan())

    def test_a_plan_that_only_checks_the_mesh_does_not_make_one(self) -> None:
        plan = RunPlan(
            case=Path("/cases/wing"),
            stages=(
                Stage("checkMesh", argv=("checkMesh",), fail_on=Severity.ERROR),
                Stage("solve", argv=("simpleFoam",), parallel=True, monitored=True),
            ),
        )
        assert not plan_generates_mesh(plan)

    def test_the_answer_comes_from_the_plan_not_the_case(self, tmp_path: Path) -> None:
        """So it cannot disagree with what build_plan decided about the case."""
        from foamwb.services.case import CaseService
        from foamwb.services.newcase import create_case
        from foamwb.services.run import build_plan

        created = create_case(tmp_path, "wing")
        case = CaseService().open(created.path)
        assert not plan_generates_mesh(build_plan(case))

        (created.path / "system" / "blockMeshDict").write_text(BLOCK_MESH_DICT)
        assert plan_generates_mesh(build_plan(CaseService().open(created.path)))


CONTROL_DICT = (
    "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
    "application     icoFoam;\n"
)


@pytest.fixture
def meshable(tmp_path: Path):
    """A case whose plan is blockMesh → checkMesh → solve."""
    root = tmp_path / "cavity"
    (root / "system").mkdir(parents=True)
    (root / "constant").mkdir()
    (root / "0").mkdir()
    (root / "system" / "controlDict").write_text(CONTROL_DICT)
    (root / "system" / "blockMeshDict").write_text("scale 1;\n")
    return CaseService().open(root)


def _running(plan: RunPlan) -> list[str]:
    return [stage.name for stage in plan.active_stages()]


class TestTheUpdatePlan:
    """DEC-22 — one verb that runs whatever is out of date, in order.

    Workbench's *Update Project*, and the reason it exists: a user who edits
    ``blockMeshDict`` should not have to work out for themselves that this means
    meshing again *and then* solving again.
    """

    def test_a_case_with_nothing_done_runs_everything(self, meshable) -> None:
        assert _running(build_update_plan(meshable, Freshness())) == [
            "blockMesh",
            "checkMesh",
            "solve",
        ]

    def test_a_current_case_runs_nothing(self, meshable) -> None:
        fresh = Freshness(has_mesh=True, has_results=True)
        assert _running(build_update_plan(meshable, fresh)) == []

    def test_a_stale_mesh_is_rebuilt_and_re_solved(self, meshable) -> None:
        """Re-meshing invalidates every result, so the solve follows it."""
        stale = Freshness(
            has_mesh=True, has_results=True, mesh_stale_because="system/blockMeshDict"
        )
        assert _running(build_update_plan(meshable, stale)) == ["blockMesh", "checkMesh", "solve"]

    def test_a_stale_result_re_solves_without_re_meshing(self, meshable) -> None:
        """The point of the whole exercise: not rebuilding a mesh that is fine."""
        stale = Freshness(has_mesh=True, has_results=True, results_stale_because="0/U")
        assert _running(build_update_plan(meshable, stale)) == ["checkMesh", "solve"]

    def test_a_meshed_case_that_has_never_run_only_solves(self, meshable) -> None:
        assert _running(build_update_plan(meshable, Freshness(has_mesh=True))) == [
            "checkMesh",
            "solve",
        ]

    def test_a_skipped_stage_is_shown_rather_than_dropped(self, meshable) -> None:
        """FR-S1 — the plan the user reviewed is the plan they watch.

        "blockMesh: skipped" says the mesh is current; its absence says nothing.
        """
        stale = Freshness(has_mesh=True, has_results=True, results_stale_because="0/U")
        states = build_update_plan(meshable, stale).stage_states()
        assert states["blockMesh"] is StageState.SKIPPED
        assert states["solve"] is StageState.PENDING

    def test_the_full_plan_is_unaffected(self, meshable) -> None:
        """*Calculate* still means the whole thing; the two verbs are distinct."""
        from foamwb.services.run import build_plan

        fresh = Freshness(has_mesh=True, has_results=True)
        build_update_plan(meshable, fresh)
        assert _running(build_plan(meshable)) == ["blockMesh", "checkMesh", "solve"]

    def test_an_existing_condition_is_kept_rather_than_replaced(self, meshable) -> None:
        """``decomposePar`` already carries "only in parallel"; dropping that
        would put an MPI stage into a serial run."""
        plan = build_update_plan(meshable, Freshness(), n_procs=2)
        assert "decomposePar" in _running(plan)
        serial = build_update_plan(meshable, Freshness(), n_procs=1)
        assert "decomposePar" not in [s.name for s in serial.stages]

    def test_a_case_with_no_solver_still_refuses(self, tmp_path) -> None:
        root = tmp_path / "nameless"
        (root / "system").mkdir(parents=True)
        (root / "system" / "controlDict").write_text("FoamFile { object controlDict; }\n")
        with pytest.raises(ValueError):
            build_update_plan(CaseService().open(root), Freshness())
