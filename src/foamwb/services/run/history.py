"""Run history bookkeeping shared by every route that starts a run (FR-S7).

The Run page and the agent interface (``foamwb.mcp``) both start runs, and a
run must land in ``.<app>/`` identically whichever of them started it: the same
``r-NNNN`` numbering, the same log directory, the same record. Two copies of
this logic would eventually disagree — one would renumber from ``r-0001`` and
overwrite the other's logs, which is exactly the evidence a user comparing two
runs needs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from foamwb.branding import CASE_METADATA_DIR
from foamwb.services.case import RunRecord
from foamwb.services.run.controller import RunResult

__all__ = ["latest_written_time", "log_dir_for", "next_run_id", "run_record"]


def log_dir_for(case: Path, run_id: str) -> Path:
    """Where a run's stage logs are written."""
    return case / CASE_METADATA_DIR / "logs" / run_id


def next_run_id(case: Path | None) -> str:
    """The next unused ``r-NNNN``, read from the directory rather than a counter.

    Reading the directory means a restarted application continues the numbering
    instead of overwriting r-0001 again.
    """
    if case is None:
        return "r-0001"
    logs = case / CASE_METADATA_DIR / "logs"
    used = {p.name for p in logs.glob("r-*")} if logs.is_dir() else set()
    index = 1
    while f"r-{index:04d}" in used:
        index += 1
    return f"r-{index:04d}"


def latest_written_time(case: Path | None) -> str | None:
    """The last time directory the run wrote, which is what a user looks for.

    Named from the directory rather than from ``endTime``: a stopped or diverged
    run has an ``endTime`` it never reached, and reporting it would describe a
    result the case does not contain.
    """
    if case is None or not case.is_dir():
        return None
    times = []
    for path in case.iterdir():
        if not path.is_dir():
            continue
        try:
            times.append((float(path.name), path.name))
        except ValueError:
            continue
    return max(times)[1] if times else None


def run_record(
    case: Path,
    run_id: str,
    *,
    started: datetime,
    finished: datetime,
    result: RunResult,
    n_procs: int,
) -> RunRecord:
    """The history entry for a finished run."""
    failed = result.failed_stage
    return RunRecord(
        id=run_id,
        started=started.isoformat(timespec="seconds"),
        finished=finished.isoformat(timespec="seconds"),
        exit_code=failed.exit_code if failed else 0,
        plan=tuple(s.name for s in result.stages),
        n_procs=n_procs,
        wall_seconds=round(result.wall_seconds, 3),
        final_time=latest_written_time(case),
        converged=result.succeeded,
        log_dir=run_id,
    )
