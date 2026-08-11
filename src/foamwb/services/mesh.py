"""Meshing utilities and the ``checkMesh`` quality summary (FR-P5, FR-P9, E-S02).

A utility is a :class:`~foamwb.services.run.RunPlan` with one stage, so it runs
through the same controller, streams through the same log pane and is stopped by
the same control as a solver. Nothing here re-implements execution: a second path
would be a second set of bugs, and it is the path that gets less use that breaks
quietly.

**``checkMesh`` exits 0 while reporting mesh errors.** That is E-S02's whole
point and the reason ``fail_on`` exists: trusting the exit code would let a
broken mesh through to the solver, where it becomes a diverged run twenty minutes
later and a much worse way to learn the same fact.

FR-P9 asks for the quality figures "as a pass/warn/fail panel, not raw text".
Thresholds are data, and they are the *conventional* ones rather than anything
this project invented — non-orthogonality above 70 and skewness above 4 are what
OpenFOAM's own checks warn about. They are configurable because meshes for
different physics tolerate different things, and a fixed threshold would either
nag or mislead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from foamwb.codes import Severity
from foamwb.services.run import RunPlan, Stage

__all__ = [
    "UTILITIES",
    "MeshQuality",
    "QualityMetric",
    "Utility",
    "Verdict",
    "available_utilities",
    "parse_check_mesh",
    "utility_plan",
]


class Verdict(StrEnum):
    """FR-P9's three states."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Utility:
    """One meshing utility offered by the preprocessor (FR-P5)."""

    name: str
    argv: tuple[str, ...]
    needs: tuple[str, ...] = ()
    """Case-relative files this utility requires.

    Checked before the utility is offered, so a case with no
    ``snappyHexMeshDict`` does not present a button whose only outcome is a
    failure the user could not have avoided.
    """

    makes_mesh: bool = False
    """Whether running it changes the mesh, and therefore invalidates a boundary
    matrix built from the old one."""

    fail_on: Severity | None = None


#: §6.3's list, in the order a user would work through them.
UTILITIES: tuple[Utility, ...] = (
    Utility(
        name="blockMesh",
        argv=("blockMesh",),
        needs=("system/blockMeshDict", "constant/polyMesh/blockMeshDict"),
        makes_mesh=True,
    ),
    Utility(
        name="surfaceFeatureExtract",
        argv=("surfaceFeatureExtract",),
        needs=("system/surfaceFeatureExtractDict",),
    ),
    Utility(
        name="snappyHexMesh",
        argv=("snappyHexMesh", "-overwrite"),
        needs=("system/snappyHexMeshDict",),
        makes_mesh=True,
    ),
    Utility(
        name="checkMesh",
        argv=("checkMesh",),
        # Exit code 0 is not a verdict here (E-S02), so the parsed output decides.
        fail_on=Severity.ERROR,
    ),
    Utility(
        name="renumberMesh",
        argv=("renumberMesh", "-overwrite"),
        makes_mesh=True,
    ),
    Utility(
        name="transformPoints",
        argv=("transformPoints",),
        makes_mesh=True,
    ),
)


def available_utilities(case: Path, *, meshed: bool) -> list[Utility]:
    """Utilities that can actually run on this case, in order.

    A utility whose dictionary is absent is omitted rather than shown disabled:
    ``snappyHexMesh`` on a case with no ``snappyHexMeshDict`` is not a thing the
    user can fix from that button, and offering it invites a failure they could
    not have avoided.

    Utilities that operate *on* a mesh are omitted until one exists, for the same
    reason.
    """
    offered: list[Utility] = []
    for utility in UTILITIES:
        if utility.needs and not any((case / need).is_file() for need in utility.needs):
            continue
        if not utility.needs and not utility.makes_mesh and not meshed:
            continue  # checkMesh needs a mesh to check
        if utility.makes_mesh and not utility.needs and not meshed:
            continue  # renumberMesh and transformPoints operate on one
        offered.append(utility)
    return offered


def utility_plan(utility: Utility, case: Path) -> RunPlan:
    """Wrap a utility as a one-stage plan, so it runs the way everything runs."""
    return RunPlan(
        case=case,
        stages=(Stage(utility.name, argv=utility.argv, fail_on=utility.fail_on),),
    )


@dataclass(frozen=True, slots=True)
class QualityMetric:
    """One mesh-quality figure, with its verdict (FR-P9)."""

    name: str
    value: float
    verdict: Verdict
    threshold: float | None = None
    detail: str = ""


@dataclass(slots=True)
class MeshQuality:
    """What ``checkMesh`` reported, read as figures rather than prose."""

    metrics: list[QualityMetric] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    cells: int | None = None
    mesh_ok: bool | None = None
    """``checkMesh``'s own verdict, or ``None`` if it never stated one — which
    happens when the utility died before finishing."""

    @property
    def verdict(self) -> Verdict:
        """The worst thing found.

        ``checkMesh``'s own "Mesh OK" is not sufficient on its own: it reports OK
        alongside figures that will make a solver struggle, and FR-P9 exists so a
        user sees those rather than a green word.
        """
        if self.failed_checks or self.mesh_ok is False:
            return Verdict.FAIL
        if any(m.verdict is Verdict.WARN for m in self.metrics):
            return Verdict.WARN
        if any(m.verdict is Verdict.FAIL for m in self.metrics):
            return Verdict.FAIL
        return Verdict.PASS

    def metric(self, name: str) -> QualityMetric | None:
        return next((m for m in self.metrics if m.name == name), None)


#: Conventional limits, not invented ones: these are what OpenFOAM's own mesh
#: checks and the usual practice warn about. Overridable, because meshes for
#: different physics tolerate different things and a fixed number would either
#: nag or mislead.
DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "non-orthogonality": (65.0, 70.0),
    "skewness": (4.0, 10.0),
    "aspect ratio": (100.0, 1000.0),
}

_NUMBER = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("non-orthogonality", re.compile(rf"non-orthogonality Max:\s*{_NUMBER}", re.I)),
    ("skewness", re.compile(rf"Max skewness\s*=\s*{_NUMBER}", re.I)),
    ("aspect ratio", re.compile(rf"Max aspect ratio\s*=\s*{_NUMBER}", re.I)),
)

_CELLS = re.compile(r"^\s*cells:\s*(\d+)", re.I | re.M)
_FAILED = re.compile(r"^\s*\*\*\*(.+)$", re.M)


def parse_check_mesh(
    output: str, thresholds: dict[str, tuple[float, float]] | None = None
) -> MeshQuality:
    """Turn ``checkMesh`` output into figures and a verdict (FR-P9).

    Parsed rather than shown raw because the numbers are what matter and they are
    buried in eighty lines of prose. The raw output is still streamed to the log,
    so nothing is hidden — this is a summary, not a replacement.
    """
    limits = thresholds or DEFAULT_THRESHOLDS
    quality = MeshQuality()

    for name, pattern in _PATTERNS:
        match = pattern.search(output)
        if match is None:
            continue
        value = float(match.group(1))
        warn, fail = limits.get(name, (float("inf"), float("inf")))
        verdict = Verdict.FAIL if value > fail else Verdict.WARN if value > warn else Verdict.PASS
        quality.metrics.append(
            QualityMetric(name=name, value=value, verdict=verdict, threshold=warn)
        )

    if (cells := _CELLS.search(output)) is not None:
        quality.cells = int(cells.group(1))

    quality.failed_checks = [line.strip() for line in _FAILED.findall(output)]

    if "Mesh OK" in output:
        quality.mesh_ok = True
    elif "Failed" in output and "mesh checks" in output:
        quality.mesh_ok = False

    return quality
