"""Harness for the §12.3 golden-case regression — the numerical gate.

§12.3's reproducibility caveat drives the whole design: CFD field output is not
bit-reproducible across compiler, MPI, BLAS or CPU generation, so the gate is
defined on **scalar functionals with explicit tolerances** against references
captured on a **pinned toolchain**.

That splits the rows into two kinds, and keeping them apart is what makes the
gate both meaningful and runnable:

**Toolchain-dependent** rows compare against stored reference numbers, and are
only valid on the toolchain those numbers came from. Elsewhere they are skipped
with the mismatch named — a comparison across toolchains is not a weaker test,
it is an invalid one, and letting it fail would train people to ignore red.

**Toolchain-independent** rows compare two runs on *this* machine and are valid
anywhere OpenFOAM exists. §12.3 singles out the last of these as "the one that
actually protects users: it proves the *editor* changed nothing numerical,
independently of whether the solver is reproducible." Those run everywhere.

The harness drives the same ``RunController`` and ``RunPlan`` a user's run goes
through. Testing a different path than the one that ships would prove nothing
about the one that ships.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from foamwb.services import fence
from foamwb.services.case import CaseService
from foamwb.services.functionals import field_l2_norm, read_volume_field_value
from foamwb.services.run import RunController, RunOutcome, RunPlan, Stage
from foamwb.services.runtime import Installation, RuntimeManager

__all__ = [
    "GOLDEN_CASES",
    "GoldenCase",
    "Measurement",
    "measure",
    "toolchain_fingerprint",
]

#: Function objects appended to a golden case so OpenFOAM computes the
#: volume-weighted functionals with its own mesh metrics (§12.3). Installed in
#: the same fence the application uses, so the harness exercises that too.
_VOLUME_FUNCTIONALS = """\
functions
{{
    {name}
    {{
        type            volFieldValue;
        libs            (fieldFunctionObjects);
        fields          ({field});
        operation       {operation};
        regionType      all;
        writeFields     false;
        writeControl    onEnd;
        log             false;
    }}
}}"""


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One row of §12.3's table."""

    name: str
    tutorial: str
    stages: tuple[tuple[str, tuple[str, ...]], ...]

    l2_fields: tuple[str, ...] = ()
    """Fields whose L2 norm is compared. Needs no mesh metrics."""

    volume_field: str | None = None
    volume_operation: str = "volAverage"
    """A volume-weighted scalar, computed by OpenFOAM itself."""

    relative_tolerance: float = 1e-8
    """§12.3's tolerance for this row."""

    def plan(self, case: Path) -> RunPlan:
        return RunPlan(
            case=case,
            stages=tuple(Stage(name, argv=argv) for name, argv in self.stages),
        )


#: §12.3's table. `cavity` and `damBreak` are the two the PRD names with a 1e-8
#: relative tolerance; `pitzDaily`'s residual-based row needs the convergence
#: bookkeeping that arrives with the run experience at M5.
GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        name="cavity",
        tutorial="incompressible/icoFoam/cavity/cavity",
        stages=(("blockMesh", ("blockMesh",)), ("solve", ("icoFoam",))),
        l2_fields=("U", "p"),
        volume_field="p",
        volume_operation="volAverage",
        relative_tolerance=1e-8,
    ),
    GoldenCase(
        name="damBreak",
        tutorial="multiphase/interFoam/laminar/damBreak/damBreak",
        stages=(
            ("blockMesh", ("blockMesh",)),
            ("setFields", ("setFields",)),
            ("solve", ("interFoam",)),
        ),
        l2_fields=("alpha.water",),
        volume_field="alpha.water",
        # A conserved quantity, so a strong check: the integral must not drift.
        volume_operation="volIntegrate",
        relative_tolerance=1e-8,
    ),
)


@dataclass(slots=True)
class Measurement:
    """Scalar functionals from one run."""

    case: str
    final_time: str
    l2_norms: dict[str, float] = field(default_factory=dict)
    cell_counts: dict[str, int] = field(default_factory=dict)
    volume_value: float | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "case": self.case,
            "final_time": self.final_time,
            "l2_norms": self.l2_norms,
            "cell_counts": self.cell_counts,
            "volume_value": self.volume_value,
        }

    @classmethod
    def from_json(cls, raw: dict) -> Measurement:
        return cls(
            case=raw["case"],
            final_time=raw["final_time"],
            l2_norms=dict(raw.get("l2_norms", {})),
            cell_counts={k: int(v) for k, v in raw.get("cell_counts", {}).items()},
            volume_value=raw.get("volume_value"),
        )


def toolchain_fingerprint(openfoam_version: str) -> dict[str, str]:
    """What the reference values are only valid against (§12.3).

    Part of the reference, not metadata about it: comparing numbers captured on
    one toolchain against a run on another is the spurious failure §12.3 designs
    the gate to avoid.
    """
    return {
        "openfoam": openfoam_version,
        "platform": platform.system(),
        "machine": platform.machine(),
    }


def prepare(golden: GoldenCase, tutorials: Path, destination: Path) -> Path:
    """Copy a tutorial and install the functional-computing function objects."""
    source = tutorials / golden.tutorial
    if not source.is_dir():
        raise FileNotFoundError(f"Tutorial not found: {source}")

    case = destination / golden.name
    if case.exists():
        shutil.rmtree(case)
    shutil.copytree(source, case)

    # Most tutorials ship 0.orig and no 0, exactly as their Allrun expects. The
    # harness performs the same restoration the application does, so the gate
    # exercises the real path rather than a specially prepared one.
    service = CaseService()
    service.restore_initial_conditions(service.open(case))

    if golden.volume_field:
        control = case / "system" / "controlDict"
        block = _VOLUME_FUNCTIONALS.format(
            name="goldenFunctional",
            field=golden.volume_field,
            operation=golden.volume_operation,
        )
        control.write_text(fence.install(control.read_text(), block))
    return case


def run(golden: GoldenCase, case: Path, manager: RuntimeManager, install: Installation) -> None:
    """Execute the case through the shipping code path."""
    session = manager.session_for(install)
    try:
        result = RunController(session).execute(golden.plan(case))
    finally:
        session.close()
    if result.outcome is not RunOutcome.SUCCEEDED:
        failed = result.failed_stage
        raise AssertionError(
            f"{golden.name} did not run: {failed.name if failed else '?'} "
            f"{failed.detail if failed else ''}"
        )


def measure(golden: GoldenCase, case: Path) -> Measurement:
    """Reduce a completed run to its scalar functionals."""
    times = sorted(
        (float(p.name), p.name) for p in case.iterdir() if p.is_dir() and _is_time(p.name)
    )
    if not times:
        raise AssertionError(f"{golden.name} wrote no time directories")
    final = times[-1][1]

    measurement = Measurement(case=golden.name, final_time=final)
    for name in golden.l2_fields:
        stats = field_l2_norm(case, final, name)
        measurement.l2_norms[name] = stats.l2_norm
        measurement.cell_counts[name] = stats.count
    if golden.volume_field:
        measurement.volume_value = read_volume_field_value(case, "goldenFunctional")
    return measurement


def _is_time(name: str) -> bool:
    try:
        float(name)
    except ValueError:
        return False
    return True


def relative_difference(a: float, b: float) -> float:
    if a == b:
        return 0.0
    scale = max(abs(a), abs(b))
    return float("inf") if scale == 0 else abs(a - b) / scale
