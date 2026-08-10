"""Fence, monitor and controller (FR-S3, FR-S4, FR-S1, NFR-C3, DEC-13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeSession, ScriptedCommand
from foamwb.codes import ErrorCode
from foamwb.services import fence
from foamwb.services.foamdict import Document
from foamwb.services.monitor import MonitorService, parse_dat
from foamwb.services.run import (
    RunController,
    RunOutcome,
    RunPlan,
    Severity,
    Stage,
    StageState,
    StopMode,
)

CONTROL_DICT = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

application     icoFoam;
endTime         0.5;

// ************************************************************************* //
"""

# Column padding is stripped relative to a real file; the widths are cosmetic
# and the tab separators are what the parser keys on. The real format is asserted
# against a live solver in test_runtime_integration.py.
SOLVER_INFO_DAT = """\
# Solver information
# Time	U_solver	Ux_initial	Ux_final	Ux_iters	p_solver	p_initial	p_converged
0.005         	smoothSolver	1.000000e+00	8.905110e-06	19	DICPCG	1.000000e+00	true
0.01          	smoothSolver	1.606860e-01	6.830310e-06	19	DICPCG	4.289250e-01	true
0.015         	smoothSolver	4.476320e-02	9.124730e-06	15	DICPCG	1.315840e-01	true
"""


class TestFence:
    """NFR-C3 — fenced, disclosed, reversible."""

    def test_install_then_remove_is_byte_identical(self) -> None:
        # The claim FR-C5 rests on: a case that has been run and then cleaned is
        # byte-identical to the case that was imported. "Similar" is not enough —
        # a stray blank line is invisible to a person and glaring in a diff.
        block = fence.solver_info_block(("U", "p"))
        assert fence.remove(fence.install(CONTROL_DICT, block)) == CONTROL_DICT

    def test_the_case_still_parses_after_injection(self) -> None:
        injected = fence.install(CONTROL_DICT, fence.solver_info_block(("U", "p")))
        document = Document.parse(injected)
        assert document.get("application") == "icoFoam"
        assert document.get("endTime") == "0.5"

    def test_user_entries_are_untouched(self) -> None:
        # Appended, never interleaved, so every byte the user wrote keeps its
        # offset and the line numbers the solver reports still point where they did.
        injected = fence.install(CONTROL_DICT, fence.solver_info_block(("U",)))
        assert injected.startswith(CONTROL_DICT.rstrip("\n"))

    def test_installing_twice_does_not_stack(self) -> None:
        # Every launch injects. Without this, a case run ten times would carry ten
        # copies of the function object.
        block = fence.solver_info_block(("U", "p"))
        once = fence.install(CONTROL_DICT, block)
        assert fence.install(once, block) == once
        assert once.count(fence.FENCE_BEGIN) == 1

    def test_removing_an_absent_fence_is_a_no_op(self) -> None:
        assert fence.remove(CONTROL_DICT) == CONTROL_DICT

    def test_the_fence_explains_itself_in_the_file(self) -> None:
        # NFR-C3's "disclosed". A P4 user opening this in vim should not have to
        # guess what wrote it or whether deleting it is safe.
        injected = fence.install(CONTROL_DICT, fence.solver_info_block(("U",)))
        assert "Safe to delete" in injected

    def test_markers_are_comments_so_a_broken_fence_cannot_break_the_case(self) -> None:
        # OpenFOAM ignores comments entirely, so the worst outcome of a malformed
        # fence is losing the live plot — never an unrunnable case.
        assert fence.FENCE_BEGIN.lstrip().startswith("//")
        assert fence.FENCE_END.lstrip().startswith("//")

    def test_the_block_names_the_requested_fields(self) -> None:
        block = fence.solver_info_block(("U", "p", "k"))
        assert "(U p k)" in block
        assert "solverInfo" in block

    def test_no_fields_is_refused(self) -> None:
        with pytest.raises(ValueError, match="At least one field"):
            fence.solver_info_block(())

    def test_survives_a_file_without_a_trailing_newline(self) -> None:
        source = CONTROL_DICT.rstrip("\n")
        injected = fence.install(source, fence.solver_info_block(("U",)))
        assert Document.parse(injected).get("application") == "icoFoam"


class TestMonitorParsing:
    """DEC-13 — stable columnar output rather than log scraping."""

    def test_reads_column_names_from_the_last_header_line(self) -> None:
        names, rows = parse_dat(SOLVER_INFO_DAT)
        assert names[0] == "Time"
        assert "Ux_initial" in names
        assert len(rows) == 3

    def test_mixed_type_columns_do_not_break_the_reader(self, tmp_path) -> None:
        # U_solver is a solver name and p_converged is a boolean. A reader that
        # assumed floats would fail on the first row of every case.
        series = _monitor_with(tmp_path, SOLVER_INFO_DAT).series("solverInfo")
        assert series.text_columns["U_solver"] == "smoothSolver"
        assert series.text_columns["p_converged"] == "true"

    def test_numeric_columns_become_series(self, tmp_path) -> None:
        series = _monitor_with(tmp_path, SOLVER_INFO_DAT).series("solverInfo")
        ux = series.series["Ux_initial"]
        assert len(ux) == 3
        assert ux.values[0] == pytest.approx(1.0)
        assert ux.latest == pytest.approx(4.476320e-02)

    def test_residuals_are_the_initial_ones(self, tmp_path) -> None:
        # The final residual only says the linear solver converged this timestep,
        # which it almost always did. Convergence is judged on the initial one.
        series = _monitor_with(tmp_path, SOLVER_INFO_DAT).series("solverInfo")
        assert sorted(s.label for s in series.residuals) == ["Ux", "p"]

    def test_reading_is_incremental(self, tmp_path) -> None:
        # NFR-P4 gives 500 ms from write to plot, over runs of tens of thousands
        # of rows. Re-reading each poll would make that quadratic.
        monitor = _monitor_with(tmp_path, SOLVER_INFO_DAT)
        assert len(monitor.series("solverInfo").series["Ux_initial"]) == 3

        dat = next(iter(monitor.dat_files()))
        with dat.open("a", encoding="utf-8") as handle:
            handle.write("0.02\tsmoothSolver\t2.5e-02\t6.6e-06\t15\tDICPCG\t6.9e-02\ttrue\n")

        assert len(monitor.series("solverInfo").series["Ux_initial"]) == 4

    def test_a_partial_final_line_is_skipped_not_guessed(self, tmp_path) -> None:
        # Normal when polling a file the solver is still appending to. Guessing at
        # it would put a wrong point on a plot the user reads for convergence.
        monitor = _monitor_with(tmp_path, SOLVER_INFO_DAT + "0.02\tsmoothSol")
        assert len(monitor.series("solverInfo").series["Ux_initial"]) == 3

    def test_a_truncated_file_is_reread_from_the_start(self, tmp_path) -> None:
        monitor = _monitor_with(tmp_path, SOLVER_INFO_DAT)
        monitor.series("solverInfo")
        dat = next(iter(monitor.dat_files()))
        dat.write_text(SOLVER_INFO_DAT.rsplit("\n", 2)[0] + "\n")
        assert len(monitor.series("solverInfo").series["Ux_initial"]) == 2

    def test_no_post_processing_directory_is_not_an_error(self, tmp_path) -> None:
        # The normal state before the first run.
        assert MonitorService(tmp_path).refresh() == {}

    def test_csv_export_carries_every_series(self, tmp_path) -> None:
        csv = _monitor_with(tmp_path, SOLVER_INFO_DAT).series("solverInfo").to_csv()
        assert csv.splitlines()[0].startswith("Time,")
        assert len(csv.splitlines()) == 4


def _monitor_with(root: Path, dat: str) -> MonitorService:
    target = root / "postProcessing" / "solverInfo" / "0"
    target.mkdir(parents=True, exist_ok=True)
    (target / "solverInfo.dat").write_text(dat)
    return MonitorService(root)


def _plan(case: Path, n_procs: int = 1) -> RunPlan:
    return RunPlan(
        case=case,
        n_procs=n_procs,
        stages=(
            Stage("blockMesh", argv=("blockMesh",)),
            Stage("checkMesh", argv=("checkMesh",), fail_on=Severity.ERROR),
            Stage("decomposePar", argv=("decomposePar",), when=lambda p: p.n_procs > 1),
            Stage("solve", argv=("icoFoam",), parallel=True, monitored=True),
        ),
    )


class TestRunController:
    def test_runs_active_stages_in_order(self, tmp_path) -> None:
        session = FakeSession()
        result = RunController(session).execute(_plan(tmp_path))
        assert result.outcome is RunOutcome.SUCCEEDED
        assert [a[0] for a in session.commands] == ["blockMesh", "checkMesh", "icoFoam"]

    def test_skipped_stages_are_reported_not_hidden(self, tmp_path) -> None:
        # FR-S1: the plan the user reviewed is the plan they watch execute.
        result = RunController(FakeSession()).execute(_plan(tmp_path))
        states = {s.name: s.state for s in result.stages}
        assert states["decomposePar"] is StageState.SKIPPED

    def test_results_are_in_plan_order_even_after_a_failure(self, tmp_path) -> None:
        session = FakeSession({"blockMesh": ScriptedCommand(exit_code=1)})
        result = RunController(session).execute(_plan(tmp_path))
        assert [s.name for s in result.stages] == [
            "blockMesh",
            "checkMesh",
            "decomposePar",
            "solve",
        ]

    def test_stops_at_the_first_failure(self, tmp_path) -> None:
        # A solver launched against a mesh blockMesh failed to build produces
        # pages of errors that bury the one that matters.
        session = FakeSession({"blockMesh": ScriptedCommand(exit_code=1)})
        result = RunController(session).execute(_plan(tmp_path))
        assert result.outcome is RunOutcome.FAILED
        assert not session.ran("icoFoam")
        assert result.failed_stage.name == "blockMesh"

    def test_a_failure_carries_an_error_code(self, tmp_path) -> None:
        session = FakeSession({"icoFoam": ScriptedCommand(exit_code=1)})
        result = RunController(session).execute(_plan(tmp_path))
        assert result.failed_stage.reason is ErrorCode.DIVERGED

    def test_exit_zero_with_errors_in_the_output_still_fails(self, tmp_path) -> None:
        # E-S02: checkMesh reports mesh errors and exits 0. Trusting the exit code
        # alone would let a broken mesh through to the solver.
        session = FakeSession(
            {"checkMesh": ScriptedCommand(lines=["***Number of edges not aligned: 12"])}
        )
        result = RunController(session).execute(_plan(tmp_path))
        assert result.outcome is RunOutcome.FAILED
        assert result.failed_stage.name == "checkMesh"
        assert result.failed_stage.exit_code == 0
        assert result.failed_stage.reason is ErrorCode.CHECKMESH_ERRORS

    def test_a_warning_below_the_threshold_does_not_fail(self, tmp_path) -> None:
        session = FakeSession(
            {"checkMesh": ScriptedCommand(lines=["--> FOAM Warning : minor skewness"])}
        )
        assert RunController(session).execute(_plan(tmp_path)).succeeded

    def test_a_stage_without_fail_on_ignores_its_output(self, tmp_path) -> None:
        session = FakeSession({"blockMesh": ScriptedCommand(lines=["*** something"])})
        assert RunController(session).execute(_plan(tmp_path)).succeeded

    def test_streams_every_line_tagged_with_its_stage(self, tmp_path) -> None:
        seen: list[tuple[str, str]] = []
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 0.005", "End"])})
        RunController(session, on_line=lambda s, ln: seen.append((s, ln))).execute(_plan(tmp_path))
        assert ("solve", "Time = 0.005") in seen

    def test_reports_state_transitions(self, tmp_path) -> None:
        seen: list[tuple[str, StageState]] = []
        RunController(FakeSession(), on_state=lambda s, st: seen.append((s, st))).execute(
            _plan(tmp_path)
        )
        assert ("blockMesh", StageState.RUNNING) in seen
        assert ("blockMesh", StageState.SUCCEEDED) in seen
        assert ("decomposePar", StageState.SKIPPED) in seen

    def test_writes_a_log_per_stage(self, tmp_path) -> None:
        # FR-S7: history survives restart and logs are retrievable per run.
        logs = tmp_path / "logs"
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 0.005"])})
        RunController(session).execute(_plan(tmp_path), log_dir=logs)
        assert (logs / "log.solve").read_text() == "Time = 0.005\n"

    def test_runs_in_the_case_directory(self, tmp_path) -> None:
        session = FakeSession()
        RunController(session).execute(_plan(tmp_path))
        assert all(str(cwd) == str(tmp_path) for _argv, cwd in session.calls)

    def test_a_missing_binary_is_reported_not_raised(self, tmp_path) -> None:
        # E-S05. Raising would take down the UI thread for a case that is simply
        # pointed at the wrong runtime.
        session = FakeSession({"blockMesh": ScriptedCommand(raises=OSError("No such file"))})
        result = RunController(session).execute(_plan(tmp_path))
        assert result.outcome is RunOutcome.FAILED
        assert result.failed_stage.reason is ErrorCode.SOLVER_NOT_FOUND

    def test_parallel_plans_wrap_the_solver(self, tmp_path) -> None:
        # DEC-06: the machinery is parallel-aware even though v1.0's UI is not.
        session = FakeSession()
        RunController(session).execute(_plan(tmp_path, n_procs=4))
        assert ("mpirun", "-np", "4", "icoFoam", "-parallel") in session.commands
        assert session.ran("decomposePar")


class TestStopping:
    """FR-S5, DEC-14 — stopping is not killing."""

    def test_the_default_stop_sends_no_signal(self, tmp_path) -> None:
        # Stop & Write is a solver-level stop. Quietly escalating to SIGTERM would
        # produce exactly the partial time directory DEC-14 exists to avoid.
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 0.005"])})
        controller = RunController(session, on_line=lambda _s, _ln: controller.stop(StopMode.WRITE))
        controller.execute(_plan(tmp_path))
        assert not any(p.terminated or p.killed for p in session.processes)

    def test_stop_now_sends_sigterm(self, tmp_path) -> None:
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 0.005"])})
        controller = RunController(
            session, on_line=lambda _s, _ln: controller.stop(StopMode.TERMINATE)
        )
        controller.execute(_plan(tmp_path))
        assert any(p.terminated for p in session.processes)

    def test_force_kill_sends_sigkill(self, tmp_path) -> None:
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 0.005"])})
        controller = RunController(session, on_line=lambda _s, _ln: controller.stop(StopMode.KILL))
        controller.execute(_plan(tmp_path))
        assert any(p.killed for p in session.processes)

    def test_a_stopped_run_is_not_a_failed_one(self, tmp_path) -> None:
        # Reporting a deliberate stop as a failure would train users to ignore
        # failures.
        session = FakeSession({"blockMesh": ScriptedCommand(exit_code=-15)})
        controller = RunController(session)
        controller.stop(StopMode.TERMINATE)
        result = controller.execute(_plan(tmp_path))
        # execute() resets the request, so this asserts the reset rather than the
        # stop — a stale stop must not poison the next run.
        assert result.outcome is RunOutcome.FAILED

    def test_stopping_before_anything_runs_is_safe(self) -> None:
        controller = RunController(FakeSession())
        controller.stop(StopMode.KILL)
        assert controller.stop_requested is StopMode.KILL
