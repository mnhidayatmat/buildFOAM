"""RunController — executes a :class:`RunPlan` stage by stage (§4.2, FR-S1).

Qt-free, like every service. Progress reaches the UI through plain callbacks, so
the whole execution path is exercised headlessly by the test suite and by the
§12.3 golden-case harness, which runs the *same* code path a user's run takes.
Testing a different path than the one that ships would prove nothing about the
one that ships.

Three behaviours are requirements rather than conveniences:

* **The plan is visible before it runs** (FR-S1, §7.9 rule 2). It is data, built
  and returned before anything executes.
* **A stage can fail without exiting non-zero** (E-S02). ``checkMesh`` reports
  mesh errors and exits 0, so ``fail_on`` lets a stage be judged on parsed output
  as well as exit status. Trusting the exit code alone would let a broken mesh
  through to the solver, where it becomes a diverged run and a confusing error.
* **Stopping is not killing** (FR-S5, DEC-14). The default stop is graceful and
  belongs to the run, not to the process; SIGTERM mid-write leaves a partial time
  directory that breaks reconstruction and ParaView.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.run.plan import RunPlan, Severity, Stage, StageState
from foamwb.services.runtime.session import RuntimeSession

__all__ = ["RunController", "RunOutcome", "RunResult", "StageResult", "StopMode"]

_log = get_logger("run.controller")

#: Emitted for every line of solver output, tagged with the stage that produced
#: it. A single sink rather than one per stage, because the user reads one log.
LineCallback = Callable[[str, str], None]

#: Called when a stage changes state, so the stage strip (§7.5) can update.
StateCallback = Callable[[str, StageState], None]


class StopMode(StrEnum):
    """FR-S5's three-level stop.

    Named rather than boolean because the difference between them is the
    difference between a usable final time directory and a corrupt one, and a
    caller passing ``True`` would not have to think about which they meant.
    """

    WRITE = "write"
    """*Stop & Write* — the default. Asks the solver to write and exit cleanly."""

    TERMINATE = "terminate"
    """*Stop Now* — SIGTERM. May leave a partial time directory."""

    KILL = "kill"
    """*Force Kill* — SIGKILL. Leaves whatever was on disk."""


class RunOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(slots=True)
class StageResult:
    name: str
    state: StageState
    exit_code: int | None = None
    wall_seconds: float = 0.0
    reason: Code | None = None
    """A §9 code when the stage failed, so the UI has something to link and
    support has something to name."""

    detail: str = ""


@dataclass(slots=True)
class RunResult:
    outcome: RunOutcome
    stages: list[StageResult] = field(default_factory=list)
    wall_seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.outcome is RunOutcome.SUCCEEDED

    @property
    def failed_stage(self) -> StageResult | None:
        return next((s for s in self.stages if s.state is StageState.FAILED), None)


#: Parsed from a stage's output to decide `fail_on`. Deliberately small: this is
#: a severity classifier, not a diagnostic engine. Turning a specific failure
#: into a specific message (E-S01, E-S03) belongs with the run experience at M5.
_SEVERITY_MARKERS: tuple[tuple[str, Severity], ...] = (
    ("FOAM FATAL ERROR", Severity.FATAL),
    ("FOAM FATAL IO ERROR", Severity.FATAL),
    ("***", Severity.ERROR),
    ("--> FOAM Warning", Severity.WARNING),
)


def classify(line: str) -> Severity | None:
    """Severity of one output line, or ``None`` if it carries no verdict."""
    for marker, severity in _SEVERITY_MARKERS:
        if marker in line:
            return severity
    return None


class RunController:
    """Runs a plan against a session, reporting progress as it goes."""

    def __init__(
        self,
        session: RuntimeSession,
        *,
        on_line: LineCallback | None = None,
        on_state: StateCallback | None = None,
    ) -> None:
        self._session = session
        self._on_line = on_line
        self._on_state = on_state
        self._current = None
        self._stop_requested: StopMode | None = None

    # -- execution ---------------------------------------------------------

    def execute(self, plan: RunPlan, *, log_dir: Path | None = None) -> RunResult:
        """Run every active stage in order, stopping at the first failure.

        Stopping at the first failure rather than pressing on: a solver launched
        against a mesh ``blockMesh`` failed to build produces pages of errors that
        bury the one that matters, and the user then has to work backwards to the
        real cause.
        """
        started = time.monotonic()
        self._stop_requested = None
        results: list[StageResult] = []

        states = plan.stage_states()
        for name, state in states.items():
            if state is StageState.SKIPPED:
                results.append(StageResult(name=name, state=state))
                self._emit_state(name, state)

        log_event(
            _log,
            Event.RUN_BEGIN,
            case=str(plan.case),
            n_procs=plan.n_procs,
            stages=[s.name for s in plan.active_stages()],
        )

        outcome = RunOutcome.SUCCEEDED
        for stage in plan.active_stages():
            result = self._run_stage(stage, plan, log_dir)
            results.append(result)
            if result.state is StageState.CANCELLED:
                outcome = RunOutcome.STOPPED
                break
            if result.state is StageState.FAILED:
                outcome = RunOutcome.FAILED
                break

        # Stages after a failure never ran, but the stage strip shows the whole
        # plan (FR-S1, §7.5) — a strip that dropped them would leave the user
        # unable to see what the run would have done next. Reported as pending,
        # which is what they are.
        reported = {r.name for r in results}
        results.extend(
            StageResult(name=stage.name, state=StageState.PENDING)
            for stage in plan.stages
            if stage.name not in reported
        )

        elapsed = time.monotonic() - started
        log_event(_log, Event.RUN_END, outcome=outcome.value, wall_seconds=round(elapsed, 3))

        # Ordered as the plan is, not as execution finished, so the stage strip
        # reads left to right even when a middle stage failed.
        order = list(states)
        results.sort(key=lambda r: order.index(r.name))
        return RunResult(outcome=outcome, stages=results, wall_seconds=elapsed)

    def _run_stage(self, stage: Stage, plan: RunPlan, log_dir: Path | None) -> StageResult:
        started = time.monotonic()
        argv = stage.render(plan.n_procs)
        cwd = PurePosixPath(self._session.to_runtime_path(plan.case))

        self._emit_state(stage.name, StageState.RUNNING)
        log_event(_log, Event.RUN_STAGE_BEGIN, stage=stage.name, argv=list(argv))

        worst = Severity.INFO
        log_file = None
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = (log_dir / f"log.{stage.name}").open("w", encoding="utf-8")

        try:
            process = self._session.run(argv, cwd=cwd)
            self._current = process
            for line in process.lines():
                if log_file is not None:
                    log_file.write(line + "\n")
                if self._on_line is not None:
                    self._on_line(stage.name, line)
                severity = classify(line)
                if severity is not None and severity > worst:
                    worst = severity
            code = process.wait()
        except OSError as exc:
            self._emit_state(stage.name, StageState.FAILED)
            return StageResult(
                name=stage.name,
                state=StageState.FAILED,
                reason=ErrorCode.SOLVER_NOT_FOUND,
                detail=str(exc),
                wall_seconds=time.monotonic() - started,
            )
        finally:
            self._current = None
            if log_file is not None:
                log_file.close()

        elapsed = time.monotonic() - started

        if self._stop_requested is not None and code != 0:
            # A stopped run is not a failed one. Reporting a deliberate stop as a
            # failure would train users to ignore failures.
            state = StageState.CANCELLED
            result = StageResult(name=stage.name, state=state, exit_code=code, wall_seconds=elapsed)
        elif code != 0:
            result = StageResult(
                name=stage.name,
                state=StageState.FAILED,
                exit_code=code,
                wall_seconds=elapsed,
                reason=self._reason_for(stage, code),
                detail=f"{stage.name} exited with status {code}",
            )
        elif stage.fail_on is not None and worst >= stage.fail_on:
            # Exit code 0 but the output says otherwise — checkMesh's behaviour,
            # and the reason `fail_on` exists (E-S02).
            result = StageResult(
                name=stage.name,
                state=StageState.FAILED,
                exit_code=code,
                wall_seconds=elapsed,
                reason=ErrorCode.CHECKMESH_ERRORS,
                detail=f"{stage.name} reported {worst.name.lower()} in its output",
            )
        else:
            result = StageResult(
                name=stage.name,
                state=StageState.SUCCEEDED,
                exit_code=code,
                wall_seconds=elapsed,
            )

        self._emit_state(stage.name, result.state)
        log_event(
            _log,
            Event.RUN_STAGE_END,
            stage=stage.name,
            state=result.state.value,
            exit_code=code,
            wall_seconds=round(elapsed, 3),
        )
        return result

    @staticmethod
    def _reason_for(stage: Stage, code: int) -> Code:
        if stage.monitored:
            return ErrorCode.DIVERGED if code == 1 else ErrorCode.FLOATING_POINT_EXCEPTION
        return ErrorCode.MESH_FAILED

    # -- stopping ----------------------------------------------------------

    def stop(self, mode: StopMode = StopMode.WRITE) -> None:
        """Request a stop (FR-S5).

        :data:`StopMode.WRITE` is recorded here and carried out by the run
        experience at M5, which installs the ``abort`` function object and
        triggers it — a solver-level stop that yields a complete final time
        directory. This method never escalates to a signal on its own: quietly
        turning a graceful stop into SIGTERM would produce exactly the partial
        time directory DEC-14 removed the pause button to avoid.
        """
        self._stop_requested = mode
        log_event(_log, Event.RUN_STOP_REQUESTED, mode=mode.value)

        process = self._current
        if process is None:
            return
        if mode is StopMode.TERMINATE:
            process.terminate()
        elif mode is StopMode.KILL:
            process.kill()

    @property
    def stop_requested(self) -> StopMode | None:
        return self._stop_requested

    # -- helpers -----------------------------------------------------------

    def _emit_state(self, stage: str, state: StageState) -> None:
        if self._on_state is not None:
            self._on_state(stage, state)
