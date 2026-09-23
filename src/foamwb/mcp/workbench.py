"""What an agent's session holds between calls (DEC-24).

Three things, each a boundary:

* **Where it may work.** An agent is given a set of root directories when the
  server starts, and every path it names must resolve inside one of them. A
  tool that takes a path from a language model is a tool that will one day be
  handed ``C:\\Windows``; the check is here, once, rather than in each tool.
* **Which runtime it runs against.** Found the way the window finds it —
  detect, then adopt the best installation — so an agent never runs a
  different OpenFOAM from the one the footer names.
* **What it has running.** Runs outlive the call that started them, so they are
  held here by id and polled.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from pathlib import Path

from foamwb.codes import ErrorCode
from foamwb.mcp.protocol import ToolError
from foamwb.services.case import Case, CaseError, CaseService
from foamwb.services.run.job import RunJob
from foamwb.services.runtime import RuntimeManager, RuntimeSession, RuntimeStatus

__all__ = ["Workbench"]


class Workbench:
    """State shared by the tools of one server process."""

    def __init__(
        self,
        roots: Iterable[Path],
        *,
        cases: CaseService | None = None,
        manager_factory: Callable[[], RuntimeManager] = RuntimeManager,
        session: RuntimeSession | None = None,
    ) -> None:
        self.roots = tuple(Path(root).expanduser().resolve() for root in roots)
        if not self.roots:
            raise ValueError("The agent interface needs at least one permitted directory.")
        self.cases = cases or CaseService()
        self._manager_factory = manager_factory
        self._session = session
        self._status: RuntimeStatus | None = None
        self._jobs: dict[str, RunJob] = {}
        self._lock = threading.Lock()

    # -- paths -------------------------------------------------------------

    def resolve(self, raw: str, *, must_exist: bool = True) -> Path:
        """An agent-supplied path, made absolute and confined to the roots.

        Relative paths are taken against the first root, which is where an
        agent told "make a case called duct" expects it to go.
        """
        if not isinstance(raw, str) or not raw.strip():
            raise ToolError("A path is required.")
        candidate = Path(raw.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = self.roots[0] / candidate
        # resolve() follows symlinks, so a link inside a root that points out
        # of it is judged by where it leads, not where it sits.
        resolved = candidate.resolve()
        if not any(resolved == root or resolved.is_relative_to(root) for root in self.roots):
            allowed = ", ".join(str(root) for root in self.roots)
            raise ToolError(
                f"{resolved} is outside the directories this server may use ({allowed}). "
                "Restart the server with --root to permit another directory."
            )
        if must_exist and not resolved.exists():
            raise ToolError(f"{resolved} does not exist.")
        return resolved

    def open_case(self, raw: str) -> Case:
        path = self.resolve(raw)
        try:
            return self.cases.open(path)
        except CaseError as exc:
            raise ToolError(str(exc), code=exc.code.id, guide=exc.code.guide_anchor) from exc

    def case_file(self, case: Case, relative: str, *, must_exist: bool = True) -> Path:
        """A file inside ``case``, named relative to the case root."""
        if not isinstance(relative, str) or not relative.strip():
            raise ToolError("A file path relative to the case is required.")
        target = (case.path / relative.strip()).resolve()
        if not target.is_relative_to(case.path):
            raise ToolError(f"{relative} is outside the case {case.name}.")
        if must_exist and not target.is_file():
            raise ToolError(f"{case.name} has no file {relative}.")
        return target

    # -- runtime -----------------------------------------------------------

    def runtime_status(self, *, refresh: bool = False) -> RuntimeStatus:
        """Detect the runtime, once per process unless asked again."""
        if self._status is None or refresh:
            manager = self._manager_factory()
            self._status = manager.detect()
            if self._status.is_usable and self._session is None:
                installations = manager.discover()
                if installations:
                    self._session = manager.session_for(installations[0])
        return self._status

    def session(self) -> RuntimeSession:
        """The session to run against, or a ToolError saying why there is none."""
        if self._session is not None:
            return self._session
        status = self.runtime_status(refresh=True)
        if self._session is None:
            code = status.reason or ErrorCode.NOT_PROVISIONED
            raise ToolError(
                "No usable OpenFOAM runtime was found, so nothing can be run. "
                "Open the application once to provision one.",
                code=code.id,
                guide=code.guide_anchor,
            )
        return self._session

    @property
    def openfoam_version(self) -> str | None:
        return self._status.openfoam_version if self._status else None

    # -- runs --------------------------------------------------------------

    def add_job(self, job: RunJob) -> None:
        with self._lock:
            for other in self._jobs.values():
                if other.is_running and other.case == job.case:
                    raise ToolError(
                        f"{job.case.name} already has run {other.run_id} in progress. "
                        "Wait for it or stop it first."
                    )
            job.start()
            self._jobs[job.run_id + "@" + str(job.case)] = job

    def job(self, run_id: str, case: Path | None = None) -> RunJob:
        with self._lock:
            matches = [
                job
                for job in self._jobs.values()
                if job.run_id == run_id and (case is None or job.case == case)
            ]
        if not matches:
            raise ToolError(
                f"No run {run_id} was started by this server. Use list_runs to see its runs."
            )
        if len(matches) > 1:
            raise ToolError(f"{run_id} names runs in several cases; pass the case as well.")
        return matches[0]

    def jobs(self) -> list[RunJob]:
        with self._lock:
            return list(self._jobs.values())

    def shutdown(self) -> None:
        """Stop every run this server started (FR-S10, NFR-R6).

        The client closing the pipe is the agent's equivalent of the window
        closing, and must leave no solver behind. Graceful first, so a run that
        can write its last time directory does.
        """
        from foamwb.services.run import StopMode

        running = [job for job in self.jobs() if job.is_running]
        for job in running:
            job.stop(StopMode.WRITE)
        for job in running:
            if not job.wait(30):
                job.stop(StopMode.KILL)
                job.wait(10)
        if self._session is not None:
            self._session.close()
