"""The ``RunPlan`` abstraction (§4.3) — the reason v1.1 is cheap.

Every execution — meshing, solving, post-utility — is an ordered list of stages,
each an argv plus a working directory and a success predicate. Sequential and
parallel differ only in the plan's *contents*, never in the code that runs it.

**DEC-06 is the point of this module.** v1.0 exposes sequential runs only, but
the stage machinery is parallel-aware from M0 with ``n_procs`` fixed at 1.
Hard-coding a serial pipeline is explicitly forbidden, because unpicking one
later is the difference between a UI change and a rewrite. The guard is
mechanical: ``test_plan.py`` renders plans at ``n_procs > 1`` and asserts the
``mpirun`` form, so a serial short-cut fails CI at M0 rather than surfacing at
M10.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from foamwb.codes import Severity

__all__ = ["RunPlan", "Severity", "Stage", "StageState"]


class StageState(StrEnum):
    """Lifecycle of one stage, as rendered by the Run view's stage strip (§7.5)."""

    PENDING = "pending"
    SKIPPED = "skipped"
    """``when`` evaluated false — e.g. ``decomposePar`` in a serial plan. Shown as
    skipped rather than hidden, so the plan the user reviewed before launch is the
    plan they watch execute (FR-S1)."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Stage:
    """One command in a plan."""

    name: str
    """Display name for the stage strip, e.g. ``blockMesh``."""

    argv: tuple[str, ...]
    """Command tokens, without any MPI wrapper — :meth:`render` adds that."""

    cwd: PurePosixPath | None = None
    """Runtime-side working directory. ``None`` means the case root."""

    fail_on: Severity | None = None
    """Threshold at which parsed output fails the stage regardless of exit code.

    ``checkMesh`` is why this exists: it exits 0 while reporting mesh errors, so
    exit status alone would let a broken mesh through to the solver (E-S02).
    """

    when: Callable[[RunPlan], bool] | None = None
    """Predicate deciding whether the stage runs, evaluated against the whole plan.

    Takes the plan rather than just ``n_procs`` so that later conditions —
    "only if the mesh changed", "only if a turbulence model is set" — need no
    signature change.
    """

    parallel: bool = False
    """Whether this stage is MPI-decomposable.

    ``decomposePar`` and ``reconstructPar`` are **not** parallel stages: they run
    once, serially, either side of the solve.
    """

    monitored: bool = False
    """Whether MonitorService should watch this stage's output for time series."""

    def render(self, n_procs: int) -> tuple[str, ...]:
        """Return the argv actually executed at the given processor count.

        ``mpirun -np N <argv> -parallel`` when the stage is parallel and
        ``n_procs > 1``; the bare argv otherwise. The ``-parallel`` flag goes
        after the solver name because OpenFOAM parses it as the *solver's*
        argument, not ``mpirun``'s.
        """
        if n_procs < 1:
            raise ValueError(f"n_procs must be at least 1, got {n_procs}")
        if not self.parallel or n_procs == 1:
            return self.argv
        return ("mpirun", "-np", str(n_procs), *self.argv, "-parallel")


@dataclass(frozen=True, slots=True)
class RunPlan:
    """An ordered, reviewable list of stages for one execution.

    Shown to the user in full before launch (FR-S1) — "no hidden work" (§7.9
    rule 2) means the plan is a contract, not an implementation detail.
    """

    case: Path
    """Host-side path to the case root."""

    stages: tuple[Stage, ...] = field(default_factory=tuple)

    n_procs: int = 1
    """Processor count. **v1.0 fixes this at 1**; the UI exposes it in v1.1
    (FR-S9). The machinery below is already correct for larger values."""

    def __post_init__(self) -> None:
        if self.n_procs < 1:
            raise ValueError(f"n_procs must be at least 1, got {self.n_procs}")
        names = [s.name for s in self.stages]
        if len(names) != len(set(names)):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(
                f"Stage names must be unique within a plan; duplicated: {duplicates}. "
                "Run history and the stage strip both key on the name."
            )

    @property
    def is_parallel(self) -> bool:
        return self.n_procs > 1

    def active_stages(self) -> tuple[Stage, ...]:
        """Stages whose ``when`` predicate passes for this plan."""
        return tuple(s for s in self.stages if s.when is None or s.when(self))

    def render(self) -> tuple[tuple[str, ...], ...]:
        """Every active stage's argv, in order, as actually executed."""
        return tuple(s.render(self.n_procs) for s in self.active_stages())

    def stage_states(self) -> dict[str, StageState]:
        """Initial state for each stage, before execution begins.

        Inactive stages start :data:`StageState.SKIPPED` so the stage strip shows
        the shape of the run up front.
        """
        active = {s.name for s in self.active_stages()}
        return {
            s.name: StageState.PENDING if s.name in active else StageState.SKIPPED
            for s in self.stages
        }
