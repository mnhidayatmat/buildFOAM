"""M5 — the run experience: the stop control, the fence, and run history.

The behaviours asserted here were each measured against OpenFOAM v2512 before
being written down. Where a constant looks arbitrary — the trigger filename, the
``writeNow`` action, the acknowledgement string — the test says what the solver
actually did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeSession, ScriptedCommand
from foamwb.services import fence
from foamwb.services.case import CaseService
from foamwb.services.run.controller import (
    ABORT_ACKNOWLEDGED,
    RunController,
    RunOutcome,
    StopMode,
)
from foamwb.services.run.plan import StageState
from test_run_m2 import CONTROL_DICT, _plan


class TestTheFenceCarriesBothObjects:
    def test_one_functions_block_not_two(self) -> None:
        """``functions`` is a dictionary keyword; twice is a rejected case."""
        block = fence.run_block(("U", "p"))
        assert block.count("functions") == 1

    def test_it_contains_the_monitor_and_the_stop(self) -> None:
        block = fence.run_block(("U", "p"))
        assert "type            solverInfo;" in block
        assert "type            abort;" in block

    def test_the_abort_action_is_write_now(self) -> None:
        """The object's own default is ``nextWrite``.

        Left at the default, Stop & Write would mean "stop at the next scheduled
        write" — minutes away on a case writing every hundred steps, which reads
        as a stop button that does not work.
        """
        assert "action          writeNow;" in fence.abort_entry()

    def test_the_trigger_is_application_scoped(self) -> None:
        """It must not collide with a file the user keeps in their case."""
        assert fence.STOP_TRIGGER.startswith(".")
        assert "stop" in fence.STOP_TRIGGER

    def test_installing_is_still_reversible_byte_for_byte(self) -> None:
        """FR-C5 must survive the fence gaining a second object."""
        injected = fence.install(CONTROL_DICT, fence.run_block(("U", "p")))
        assert fence.remove(injected) == CONTROL_DICT

    def test_installing_twice_does_not_stack(self) -> None:
        once = fence.install(CONTROL_DICT, fence.run_block(("U",)))
        twice = fence.install(once, fence.run_block(("U",)))
        assert once == twice

    def test_an_empty_block_is_refused(self) -> None:
        with pytest.raises(ValueError):
            fence.functions_block()


class TestStopAndWrite:
    def test_it_writes_the_trigger_file(self, tmp_path) -> None:
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 1"])})
        controller = RunController(session)
        plan = _plan(tmp_path)

        delivered: list[bool] = []

        def on_line(stage: str, _line: str) -> None:
            if stage == "solve" and not delivered:
                delivered.append(controller.stop(StopMode.WRITE))

        controller = RunController(session, on_line=on_line)
        controller.execute(plan)
        assert delivered == [True]

    def test_it_does_not_signal_the_process(self, tmp_path) -> None:
        """DEC-14: a graceful stop must never quietly become SIGTERM.

        Escalating on the user's behalf is what produces the partial time
        directory the pause button was removed to avoid.
        """
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 1"])})
        controller = RunController(session)

        def on_line(stage: str, _line: str) -> None:
            if stage == "solve":
                controller.stop(StopMode.WRITE)

        controller = RunController(session, on_line=on_line)
        controller.execute(_plan(tmp_path))

        assert session.processes, "no process was started"
        assert not any(p.terminated for p in session.processes)
        assert not any(p.killed for p in session.processes)

    def test_a_stale_trigger_is_cleared_before_a_run(self, tmp_path) -> None:
        """Otherwise the next run stops on its first timestep."""
        plan = _plan(tmp_path)
        stale = plan.case / fence.STOP_TRIGGER
        stale.write_text("action=writeNow\n")

        RunController(FakeSession({})).execute(plan)
        assert not stale.exists()

    def test_an_unconsumed_trigger_is_removed(self, tmp_path) -> None:
        controller = RunController(FakeSession({}))
        controller.execute(_plan(tmp_path))
        controller.stop(StopMode.WRITE)
        assert (_plan(tmp_path).case / fence.STOP_TRIGGER).exists()
        controller.clear_stop_trigger()
        assert not (_plan(tmp_path).case / fence.STOP_TRIGGER).exists()


class TestAnAcknowledgedStopIsNotASuccess:
    def test_exit_zero_with_the_abort_notice_is_cancelled(self, tmp_path) -> None:
        """The finding that makes this necessary.

        A Stop & Write exits **0**. Judged on status alone it is identical to a
        run that reached its endTime, so the stage strip would report a run the
        user cut short as having finished.
        """
        session = FakeSession(
            {
                "icoFoam": ScriptedCommand(
                    lines=[
                        "Time = 1",
                        f"{ABORT_ACKNOWLEDGED} (timeIndex=7294): stop and write data",
                    ],
                    exit_code=0,
                )
            }
        )
        result = RunController(session).execute(_plan(tmp_path))
        solve = next(s for s in result.stages if s.name == "solve")
        assert solve.exit_code == 0
        assert solve.state is StageState.CANCELLED
        assert result.outcome is RunOutcome.STOPPED

    def test_a_plain_exit_zero_is_still_a_success(self, tmp_path) -> None:
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 1", "End"])})
        result = RunController(session).execute(_plan(tmp_path))
        assert result.outcome is RunOutcome.SUCCEEDED


class TestStoppingBetweenStages:
    def test_a_stop_during_meshing_does_not_launch_the_solver(self, tmp_path) -> None:
        """A stop asked for during blockMesh must be honoured before the solver.

        Without this the loop ran on, started the solver, and the pending trigger
        halted it on its first timestep — leaving a time directory at t≈0 that
        looks like a fault rather than an honoured request.
        """
        session = FakeSession({"blockMesh": ScriptedCommand(lines=["Creating block mesh"])})
        controller = RunController(session)

        def on_line(stage: str, _line: str) -> None:
            if stage == "blockMesh":
                controller.stop(StopMode.WRITE)

        controller = RunController(session, on_line=on_line)
        result = controller.execute(_plan(tmp_path))

        assert result.outcome is RunOutcome.STOPPED
        assert not session.ran("icoFoam")

    def test_it_leaves_no_trigger_behind(self, tmp_path) -> None:
        session = FakeSession({"blockMesh": ScriptedCommand(lines=["Creating block mesh"])})
        controller = RunController(session)

        def on_line(stage: str, _line: str) -> None:
            if stage == "blockMesh":
                controller.stop(StopMode.WRITE)

        controller = RunController(session, on_line=on_line)
        plan = _plan(tmp_path)
        controller.execute(plan)
        assert not (plan.case / fence.STOP_TRIGGER).exists()


class TestLiveDivergenceIsReported:
    def test_a_diverging_run_raises_a_diagnosis_while_running(self, tmp_path) -> None:
        session = FakeSession(
            {
                "icoFoam": ScriptedCommand(
                    lines=[
                        "Time = 1",
                        "GAMG:  Solving for p, Initial residual = nan, "
                        "Final residual = nan, No Iterations 1000",
                    ],
                    exit_code=1,
                )
            }
        )
        seen = []
        RunController(session, on_diagnosis=seen.append).execute(_plan(tmp_path))
        assert len(seen) == 1
        assert "diverged" in seen[0].message.lower()

    def test_the_failure_carries_the_same_finding(self, tmp_path) -> None:
        session = FakeSession(
            {
                "icoFoam": ScriptedCommand(
                    lines=[
                        "Time = 1",
                        "GAMG:  Solving for p, Initial residual = nan, "
                        "Final residual = nan, No Iterations 1000",
                    ],
                    exit_code=1,
                )
            }
        )
        result = RunController(session).execute(_plan(tmp_path))
        assert result.failed_stage.diagnosis is not None
        assert result.failed_stage.detail == result.failed_stage.diagnosis.message

    def test_a_healthy_run_raises_nothing(self, tmp_path) -> None:
        session = FakeSession(
            {
                "icoFoam": ScriptedCommand(
                    lines=[
                        "Time = 1",
                        "DICPCG:  Solving for p, Initial residual = 1e-6, "
                        "Final residual = 1e-8, No Iterations 3",
                        "End",
                    ]
                )
            }
        )
        seen = []
        RunController(session, on_diagnosis=seen.append).execute(_plan(tmp_path))
        assert seen == []


class TestMonitoringStillWorks:
    """The fence gained an object; FR-S3 and FR-C5 must be unaffected."""

    def test_enabling_monitoring_installs_both(self, tmp_path) -> None:
        case_path = _make_case(tmp_path)
        service = CaseService()
        case = service.open(case_path)
        assert service.enable_monitoring(case)

        text = (case_path / "system" / "controlDict").read_text()
        assert "solverInfo" in text
        assert "abort" in text
        assert fence.STOP_TRIGGER in text

    def test_disabling_restores_the_file_exactly(self, tmp_path) -> None:
        case_path = _make_case(tmp_path)
        original = (case_path / "system" / "controlDict").read_bytes()

        service = CaseService()
        case = service.open(case_path)
        service.enable_monitoring(case)
        service.disable_monitoring(case)

        assert (case_path / "system" / "controlDict").read_bytes() == original


def _make_case(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text(CONTROL_DICT)
    (case / "0" / "U").write_text(
        "FoamFile { version 2.0; format ascii; class volVectorField; object U; }\n"
        "internalField uniform (0 0 0);\n"
        "boundaryField { }\n"
    )
    (case / "0" / "p").write_text(
        "FoamFile { version 2.0; format ascii; class volScalarField; object p; }\n"
        "internalField uniform 0;\n"
        "boundaryField { }\n"
    )
    return case
