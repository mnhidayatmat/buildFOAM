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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services import fence
from foamwb.services.case import Case
from foamwb.services.run.diagnosis import Diagnosis, DivergenceWatcher, diagnose
from foamwb.services.run.plan import RunPlan, Severity, Stage, StageState
from foamwb.services.runtime.session import RuntimeSession

__all__ = [
    "ABORT_ACKNOWLEDGED",
    "RunController",
    "RunOutcome",
    "RunResult",
    "StageResult",
    "StopMode",
    "build_plan",
]

#: What the ``abort`` function object prints when it acts on the trigger file.
#: Matched rather than inferred: a *Stop & Write* exits **0**, indistinguishable
#: by status from a run that reached its ``endTime``, and reporting an early stop
#: as a completed run would be a lie the stage strip tells silently.
ABORT_ACKNOWLEDGED = "USER REQUESTED ABORT"

#: How many trailing log lines are kept for post-mortem diagnosis. A long run's
#: log is far too large to hold, and every failure signal — the nan, the fatal
#: banner, the stack trace — appears at the end.
_TAIL_LINES = 4000

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

    diagnosis: Diagnosis | None = None
    """The log-derived explanation (FR-S6), when the log offered one.

    ``None`` when nothing in the output explained the failure, which the run
    experience shows as the raw log rather than as an invented cause."""


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


def build_plan(case: Case, *, n_procs: int = 1) -> RunPlan:
    """Compose the default plan for a case (§4.2's ``plan(case, options)``).

    Stages are included on evidence rather than by template: ``blockMesh`` only
    when there is a ``blockMeshDict`` to run it on, ``setFields`` only when the
    case defines one. A plan that named stages the case cannot support would fail
    at the first one and teach the user nothing about their case.

    ``checkMesh`` always runs and always gates the solver. It costs seconds and
    catches the mesh errors that would otherwise surface as a diverged run twenty
    minutes later, which is a much worse way to learn the same fact (E-S02).

    Raises :class:`ValueError` when ``controlDict`` names no application: without
    a solver there is nothing to plan, and guessing one would run the wrong
    physics silently.
    """
    if not case.application:
        raise ValueError(
            f"{case.name} does not name an application in system/controlDict, "
            "so there is no solver to run."
        )

    stages: list[Stage] = []
    system = case.path / "system"

    if (system / "blockMeshDict").is_file() or (
        case.path / "constant" / "polyMesh" / "blockMeshDict"
    ).is_file():
        stages.append(Stage("blockMesh", argv=("blockMesh",)))

    stages.append(Stage("checkMesh", argv=("checkMesh",), fail_on=Severity.ERROR))

    if (system / "setFieldsDict").is_file():
        # Initial conditions for multiphase cases. After the mesh exists, since it
        # sets values on cells.
        stages.append(Stage("setFields", argv=("setFields",)))

    if n_procs > 1:
        stages.append(Stage("decomposePar", argv=("decomposePar",), when=lambda p: p.n_procs > 1))

    stages.append(Stage("solve", argv=(case.application,), parallel=True, monitored=True))

    if n_procs > 1:
        stages.append(
            Stage(
                "reconstructPar",
                argv=("reconstructPar",),
                when=lambda p: p.n_procs > 1,
            )
        )

    return RunPlan(case=case.path, stages=tuple(stages), n_procs=n_procs)


class RunController:
    """Runs a plan against a session, reporting progress as it goes."""

    def __init__(
        self,
        session: RuntimeSession,
        *,
        on_line: LineCallback | None = None,
        on_state: StateCallback | None = None,
        on_diagnosis: Callable[[Diagnosis], None] | None = None,
    ) -> None:
        self._session = session
        self._on_line = on_line
        self._on_state = on_state
        self._on_diagnosis = on_diagnosis
        self._current = None
        self._stop_requested: StopMode | None = None
        self._case: Path | None = None

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
        self._case = plan.case
        # A trigger the previous run's solver never consumed would stop this one
        # on its first timestep, which would look like a solver fault.
        self.clear_stop_trigger()
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
            if self._stop_requested is not None:
                # The stop arrived while an earlier stage was running. Without
                # this the loop would carry on and launch the solver *after* the
                # user asked to stop — and the pending trigger would then halt it
                # on its first timestep, leaving a time directory at t≈0 that
                # looks like a solver fault rather than an honoured request.
                outcome = RunOutcome.STOPPED
                self.clear_stop_trigger()
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

        tail: deque[str] = deque(maxlen=_TAIL_LINES)
        watcher = DivergenceWatcher() if stage.monitored else None
        acknowledged = False

        try:
            process = self._session.run(argv, cwd=cwd)
            self._current = process
            for line in process.lines():
                if log_file is not None:
                    log_file.write(line + "\n")
                if self._on_line is not None:
                    self._on_line(stage.name, line)
                tail.append(line)
                if ABORT_ACKNOWLEDGED in line:
                    acknowledged = True
                if watcher is not None and (found := watcher.feed(line)) is not None:
                    # Reported while the run is still going, which is the only
                    # point at which the user can still save the machine time.
                    log_event(_log, Event.RUN_DIVERGED, stage=stage.name, code=found.code.id)
                    if self._on_diagnosis is not None:
                        self._on_diagnosis(found)
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

        if acknowledged or (self._stop_requested is not None and code != 0):
            # A stopped run is not a failed one. Reporting a deliberate stop as a
            # failure would train users to ignore failures.
            #
            # `acknowledged` is tested first and independently of the exit code
            # because *Stop & Write* succeeds: the solver writes its final time
            # directory and exits 0. Judged on status alone it is indistinguishable
            # from a run that reached its endTime, and the stage strip would claim
            # the run completed when the user had cut it short.
            state = StageState.CANCELLED
            result = StageResult(name=stage.name, state=state, exit_code=code, wall_seconds=elapsed)
        elif code != 0:
            found = diagnose("\n".join(tail), code) if stage.monitored else None
            result = StageResult(
                name=stage.name,
                state=StageState.FAILED,
                exit_code=code,
                wall_seconds=elapsed,
                reason=found.code if found is not None else self._reason_for(stage, code),
                detail=(
                    found.message
                    if found is not None
                    else f"{stage.name} exited with status {code}"
                ),
                diagnosis=found,
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
        """Fallback when the log explains nothing (:func:`diagnose` returned None).

        Deliberately vague for a solver stage, and that is the point. The exit
        code cannot tell a divergence from a typo — a mistyped ``endTime``, a
        missing ``0/p`` and a run diverged to ``nan`` all exit **1** — so the
        earlier ``code == 1 → DIVERGED`` rule reported a spelling mistake as a
        numerical instability. Naming the wrong cause confidently is worse than
        admitting the log did not say (§7.9 rule 6).
        """
        if stage.monitored:
            return ErrorCode.SOLVER_FAILED
        return ErrorCode.MESH_FAILED

    # -- stopping ----------------------------------------------------------

    def stop(self, mode: StopMode = StopMode.WRITE) -> bool:
        """Request a stop (FR-S5). Returns whether the request was delivered.

        :data:`StopMode.WRITE` writes the ``abort`` function object's trigger
        file. The solver notices it at the end of the current timestep, writes a
        **complete** time directory and exits cleanly — verified against
        ``icoFoam``, which stopped at t = 36.475, a time that is not on the write
        interval and so could only have come from ``writeNow``.

        This method never escalates to a signal on its own: quietly turning a
        graceful stop into SIGTERM would produce exactly the partial time
        directory DEC-14 removed the pause button to avoid. The user escalates,
        by choosing a stronger mode.
        """
        self._stop_requested = mode
        log_event(_log, Event.RUN_STOP_REQUESTED, mode=mode.value)

        process = self._current
        if mode is StopMode.WRITE:
            return self._request_write_stop()
        if process is None:
            return False
        if mode is StopMode.TERMINATE:
            process.terminate()
        elif mode is StopMode.KILL:
            process.kill()
        return True

    def _request_write_stop(self) -> bool:
        """Create the trigger file the ``abort`` function object watches.

        The file's *content* carries ``action=writeNow`` as well, even though the
        installed object already specifies it. That costs one line and makes the
        stop work against a case whose fence was written by an older version, or
        removed and hand-restored by a user — the fallback FR-S5 asks for, at no
        added complexity.
        """
        if self._case is None:
            return False
        trigger = self._case / fence.STOP_TRIGGER
        try:
            trigger.write_text("action=writeNow\n", encoding="utf-8")
        except OSError:
            return False
        return True

    def clear_stop_trigger(self) -> None:
        """Remove a trigger file the solver never consumed.

        The function object deletes the file itself once it has acted on it, so
        one left behind means the request was never seen — a stage that had
        already finished, or a case whose fence is missing. Leaving it would stop
        the *next* run the instant it started, which would look like a bug in the
        solver rather than a leftover from a previous stop.
        """
        if self._case is None:
            return
        (self._case / fence.STOP_TRIGGER).unlink(missing_ok=True)

    @property
    def stop_requested(self) -> StopMode | None:
        return self._stop_requested

    # -- helpers -----------------------------------------------------------

    def _emit_state(self, stage: str, state: StageState) -> None:
        if self._on_state is not None:
            self._on_state(stage, state)
