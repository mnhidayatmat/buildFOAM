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

from foamwb.services.run import RunPlan, Severity, Stage, StageState


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
