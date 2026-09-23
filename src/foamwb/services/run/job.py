"""A run executing on its own thread, observable by polling (FR-S1, FR-S2).

The Run page executes plans through ``ui/run_worker.py``, which reports by Qt
signal. A caller with no event loop — the agent interface in ``foamwb.mcp``, or
a future CLI — cannot receive a signal, so it needs the same execution exposed
the other way round: start it, then *ask* how it is going.

Nothing here re-implements a run. The job wraps the same
:class:`RunController` the Run page and the §12.3 golden-case gate use, installs
the same monitoring fence, and records the same history entry through
:mod:`foamwb.services.run.history`. A run started by an agent is therefore
indistinguishable in the case from one started by a person, which is what lets
the GUI pick up a case an agent has been working on.

Output is kept as a bounded tail rather than accumulated: a solver writing
NFR-P3's 5 000 lines/s for an hour would otherwise hold the whole log in
memory. The full log is on disk in the run's log directory regardless.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.case import CaseService
from foamwb.services.run.controller import RunController, RunResult, StopMode
from foamwb.services.run.diagnosis import Diagnosis
from foamwb.services.run.history import log_dir_for, next_run_id, run_record
from foamwb.services.run.plan import RunPlan, StageState
from foamwb.services.runtime.session import RuntimeSession

__all__ = ["TAIL_LINES", "JobState", "RunJob"]

_log = get_logger("services.run.job")

#: Lines of output kept in memory for :meth:`RunJob.tail`.
TAIL_LINES = 2000


@dataclass(frozen=True, slots=True)
class JobState:
    """A consistent snapshot of a job, taken under its lock."""

    run_id: str
    case: Path
    running: bool
    stages: dict[str, StageState]
    current_stage: str | None
    result: RunResult | None
    error: str | None
    diagnosis: Diagnosis | None
    started: datetime
    finished: datetime | None
    lines_seen: int
    log_dir: Path


@dataclass(slots=True)
class _Progress:
    stages: dict[str, StageState] = field(default_factory=dict)
    current_stage: str | None = None
    result: RunResult | None = None
    error: str | None = None
    diagnosis: Diagnosis | None = None
    finished: datetime | None = None
    lines_seen: int = 0


class RunJob:
    """One plan, executed on a daemon thread."""

    def __init__(
        self,
        session: RuntimeSession,
        plan: RunPlan,
        *,
        cases: CaseService | None = None,
        monitor: bool = True,
    ) -> None:
        self._session = session
        self._plan = plan
        self._cases = cases or CaseService()
        self._monitor = monitor
        self._lock = threading.Lock()
        self._tail: deque[str] = deque(maxlen=TAIL_LINES)
        self._progress = _Progress(stages=dict(plan.stage_states()))
        self._controller = RunController(
            session,
            on_line=self._on_line,
            on_state=self._on_state,
            on_diagnosis=self._on_diagnosis,
        )
        self._thread: threading.Thread | None = None
        self.run_id = next_run_id(plan.case)
        self.started = datetime.now(UTC)
        self.log_dir = log_dir_for(plan.case, self.run_id)

    @property
    def case(self) -> Path:
        return self._plan.case

    @property
    def plan(self) -> RunPlan:
        return self._plan

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Begin executing. Returns at once; poll :meth:`snapshot`."""
        if self._thread is not None:
            raise RuntimeError("A job runs once; build a new one to run again.")

        # FR-S3: monitoring is installed at launch, not at open — starting a run
        # is the consent, exactly as pressing Run is on the Run page. A failure
        # here costs the live residuals and nothing else (DEC-13), so it must
        # never stop the run.
        if self._monitor:
            try:
                self._cases.enable_monitoring(self._cases.open(self.case))
            except (OSError, ValueError) as exc:
                log_event(_log, Event.ERROR_RAISED, where="enable_monitoring", error=str(exc))

        # Reserved before the thread starts, so a second job started straight
        # after this one cannot be handed the same run id.
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._execute, name=f"run-{self.run_id}", daemon=True
        )
        self._thread.start()

    def stop(self, mode: StopMode = StopMode.WRITE) -> bool:
        """Request a stop (FR-S5). Graceful unless the caller asks otherwise."""
        return self._controller.stop(mode)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the job ends or ``timeout`` passes. Returns whether it ended."""
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- observation -------------------------------------------------------

    def snapshot(self) -> JobState:
        with self._lock:
            progress = self._progress
            return JobState(
                run_id=self.run_id,
                case=self.case,
                running=self.is_running,
                stages=dict(progress.stages),
                current_stage=progress.current_stage,
                result=progress.result,
                error=progress.error,
                diagnosis=progress.diagnosis,
                started=self.started,
                finished=progress.finished,
                lines_seen=progress.lines_seen,
                log_dir=self.log_dir,
            )

    def tail(self, lines: int = 50) -> list[str]:
        """The last ``lines`` lines of output, oldest first."""
        if lines <= 0:
            return []
        with self._lock:
            return list(self._tail)[-lines:]

    # -- execution ---------------------------------------------------------

    def _execute(self) -> None:
        try:
            result = self._controller.execute(self._plan, log_dir=self.log_dir)
        except Exception as exc:
            # A failure of the machinery, not of the case — the controller turns
            # every case failure into a RunResult. Reported rather than raised:
            # a daemon thread's exception reaches nobody.
            log_event(_log, Event.ERROR_RAISED, where="run.job", error=str(exc))
            with self._lock:
                self._progress.error = str(exc)
                self._progress.finished = datetime.now(UTC)
            return

        finished = datetime.now(UTC)
        with self._lock:
            self._progress.result = result
            self._progress.finished = finished
            self._progress.current_stage = None
        self._record(result, finished)

    def _record(self, result: RunResult, finished: datetime) -> None:
        """Append the run to the case history (FR-S7), never failing the run."""
        try:
            self._cases.record_run(
                self._cases.open(self.case),
                run_record(
                    self.case,
                    self.run_id,
                    started=self.started,
                    finished=finished,
                    result=result,
                    n_procs=self._plan.n_procs,
                ),
            )
        except (OSError, ValueError) as exc:
            log_event(_log, Event.ERROR_RAISED, where="record_run", error=str(exc))

    def _on_line(self, _stage: str, line: str) -> None:
        with self._lock:
            self._tail.append(line)
            self._progress.lines_seen += 1

    def _on_state(self, stage: str, state: StageState) -> None:
        with self._lock:
            self._progress.stages[stage] = state
            if state is StageState.RUNNING:
                self._progress.current_stage = stage

    def _on_diagnosis(self, diagnosis: Diagnosis) -> None:
        with self._lock:
            self._progress.diagnosis = diagnosis
