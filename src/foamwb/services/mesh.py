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

**``transformPoints`` is the one utility with no default action.** Every other
name in §6.3's list does something useful when run bare; ``transformPoints``
exits fatally, because "transform" is not an instruction until you say into what.
So a utility carries whether it :attr:`~Utility.needs_operation`, and one that
does is never planned without one — a button whose only outcome is a failure is
the same defect as offering ``snappyHexMesh`` to a case with no dictionary, and
it is caught here rather than in the panel so a future caller cannot reintroduce
it.

**One operation per run**, though the utility accepts several at once. It applies
them in *its own* fixed order — recentre, translate, rotate, scale — regardless
of the order given on the command line, so a form offering several at once would
be a form that silently reorders what the user asked for. Sequential runs are
also individually reversible, which a composite is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from foamwb.codes import Severity
from foamwb.services.run.plan import RunPlan, Stage

__all__ = [
    "UTILITIES",
    "Axis",
    "MeshQuality",
    "QualityMetric",
    "Transform",
    "TransformKind",
    "Utility",
    "Verdict",
    "available_utilities",
    "can_mesh",
    "chain_for",
    "mesh_plan",
    "parse_check_mesh",
    "utility_plan",
]


class Verdict(StrEnum):
    """FR-P9's three states."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class TransformKind(StrEnum):
    """The three ``transformPoints`` operations a form can ask for.

    The utility offers more — ``-rotate`` between two vectors, ``-yawPitchRoll``,
    ``-cylToCart`` — but those take an argument the user would have to already
    understand to fill in, and a field nobody can answer is worse than an absent
    one. These three cover what a mesh actually needs after import: wrong units,
    wrong origin, wrong orientation.
    """

    SCALE = "scale"
    TRANSLATE = "translate"
    ROTATE = "rotate"


class Axis(StrEnum):
    """The axis a rotation turns about, through the origin."""

    X = "x"
    Y = "y"
    Z = "z"


def _number(value: float) -> str:
    """Render a coordinate the way OpenFOAM will read it back.

    Ten significant figures rather than :func:`repr`, because ``0.1 + 0.2`` must
    not reach a dictionary as ``0.30000000000000004``, and rather than ``%g``'s
    default six, because a translation in millimetres over a metre-scale domain
    needs the digits.
    """
    return format(float(value), ".10g")


@dataclass(frozen=True, slots=True)
class Transform:
    """One ``transformPoints`` operation, as the flags that express it.

    Frozen and self-rendering so the argv a run uses is the argv a test asserts
    on. The vector is written as a single ``(x y z)`` token: it reaches the
    utility through :class:`~foamwb.services.runtime.RuntimeSession` as one
    element of an argv list, never through a shell, so the spaces inside it are
    not a quoting problem.
    """

    kind: TransformKind
    vector: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis: Axis = Axis.Z
    degrees: float = 0.0

    @classmethod
    def scale(cls, x: float, y: float, z: float) -> Transform:
        """Multiply every coordinate. ``0.001`` is the millimetre-to-metre case."""
        return cls(kind=TransformKind.SCALE, vector=(x, y, z))

    @classmethod
    def translate(cls, x: float, y: float, z: float) -> Transform:
        return cls(kind=TransformKind.TRANSLATE, vector=(x, y, z))

    @classmethod
    def rotate(cls, axis: Axis, degrees: float) -> Transform:
        return cls(kind=TransformKind.ROTATE, axis=axis, degrees=degrees)

    @property
    def is_identity(self) -> bool:
        """Whether running this would move nothing.

        Worth asking before running: ``transformPoints`` rewrites every point
        either way, and a mesh rewritten to the same values still invalidates
        everything downstream that was derived from it. Refusing is more honest
        than a run that reports success for having done nothing.
        """
        if self.kind is TransformKind.SCALE:
            return self.vector == (1.0, 1.0, 1.0)
        if self.kind is TransformKind.TRANSLATE:
            return self.vector == (0.0, 0.0, 0.0)
        return self.degrees % 360.0 == 0.0

    @property
    def is_degenerate(self) -> bool:
        """Whether this would flatten the mesh rather than transform it.

        A zero scale factor collapses every point onto a plane, and
        ``transformPoints`` will do it without complaint — the result is a mesh
        of zero-volume cells that fails much later, in ``checkMesh`` or in the
        solver, with nothing pointing back at the transform that caused it.
        """
        return self.kind is TransformKind.SCALE and 0.0 in self.vector

    def argv(self) -> tuple[str, ...]:
        """The flags this operation becomes."""
        if self.kind is TransformKind.ROTATE:
            return (f"-rotate-{self.axis.value}", _number(self.degrees))
        vector = " ".join(_number(component) for component in self.vector)
        return (f"-{self.kind.value}", f"({vector})")


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

    chain: bool = False
    """Whether this belongs in the one-press generation sequence.

    Narrower than :attr:`makes_mesh`, and deliberately so. ``renumberMesh`` and
    ``transformPoints`` change a mesh but are not steps in *making* one — they
    are things done to a mesh that already exists, and ``transformPoints`` needs
    an operation nobody can supply on the user's behalf. Putting them in the
    chain would mean a button labelled *Generate mesh* silently reordered and
    moved the user's geometry.
    """

    needs_operation: bool = False
    """Whether the utility is meaningless without an operation argument.

    Only ``transformPoints`` is: run bare it exits fatally, having parsed its
    arguments and found no instruction. A caller must supply one, which is what
    :func:`utility_plan` enforces.
    """

    fail_on: Severity | None = None


#: §6.3's list, in the order a user would work through them.
UTILITIES: tuple[Utility, ...] = (
    Utility(
        name="blockMesh",
        argv=("blockMesh",),
        needs=("system/blockMeshDict", "constant/polyMesh/blockMeshDict"),
        makes_mesh=True,
        chain=True,
    ),
    Utility(
        name="surfaceFeatureExtract",
        argv=("surfaceFeatureExtract",),
        needs=("system/surfaceFeatureExtractDict",),
        chain=True,
    ),
    Utility(
        name="snappyHexMesh",
        argv=("snappyHexMesh", "-overwrite"),
        needs=("system/snappyHexMeshDict",),
        makes_mesh=True,
        chain=True,
    ),
    Utility(
        name="checkMesh",
        argv=("checkMesh",),
        # Exit code 0 is not a verdict here (E-S02), so the parsed output decides.
        fail_on=Severity.ERROR,
        chain=True,
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
        needs_operation=True,
    ),
)


def _dictionaries_present(case: Path, utility: Utility) -> bool:
    """Whether this case has a dictionary the utility can run on.

    A utility that names no dictionary needs none — ``checkMesh`` reads the mesh
    itself — so an empty ``needs`` is satisfied rather than unsatisfiable.
    """
    return not utility.needs or any((case / need).is_file() for need in utility.needs)


def chain_for(case: Path) -> list[Utility]:
    """The generation sequence this case supports, in order.

    Composed from the same evidence a single button is offered on, so the chain
    and the individual buttons can never disagree about what this case can run.
    """
    return [
        utility for utility in UTILITIES if utility.chain and _dictionaries_present(case, utility)
    ]


def can_mesh(case: Path) -> bool:
    """Whether one press could take this case to a mesh.

    Asked before the button is offered rather than after it is pressed: a case
    with no ``blockMeshDict`` and no ``snappyHexMeshDict`` has nothing that makes
    a mesh, and offering *Generate mesh* on it would promise work the case
    cannot do (the ``checkMesh`` stage alone would fail on the mesh it went
    looking for).
    """
    return any(utility.makes_mesh for utility in chain_for(case))


def mesh_plan(case: Path) -> RunPlan:
    """Every utility needed to take this case from geometry to a checked mesh.

    One plan rather than four presses. The pieces were always a sequence —
    ``blockMesh`` then ``surfaceFeatureExtract`` then ``snappyHexMesh`` then
    ``checkMesh``, in that order, each waited on — and making the user drive it
    one utility at a time asked them to know an order the application already
    knows. Composed as a multi-stage :class:`RunPlan` so the sequence runs, is
    reported and can be stopped exactly the way a solver run is; ``fail_on``
    carries over per stage, so a mesh ``checkMesh`` rejects stops the chain
    rather than being reported as a success.

    Raises :class:`ValueError` when nothing in the chain makes a mesh, for the
    same reason :func:`utility_plan` refuses a bare ``transformPoints``: this is
    the only route to the run, so the failure belongs here rather than at the
    button.
    """
    utilities = chain_for(case)
    if not any(utility.makes_mesh for utility in utilities):
        raise ValueError(
            "This case has no blockMeshDict and no snappyHexMeshDict, "
            "so there is nothing that would generate a mesh."
        )
    return RunPlan(
        case=case,
        stages=tuple(
            Stage(utility.name, argv=utility.argv, fail_on=utility.fail_on) for utility in utilities
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
        if not _dictionaries_present(case, utility):
            continue
        if not utility.needs and not utility.makes_mesh and not meshed:
            continue  # checkMesh needs a mesh to check
        if utility.makes_mesh and not utility.needs and not meshed:
            continue  # renumberMesh and transformPoints operate on one
        offered.append(utility)
    return offered


def utility_plan(utility: Utility, case: Path, *, operation: Transform | None = None) -> RunPlan:
    """Wrap a utility as a one-stage plan, so it runs the way everything runs.

    Refuses to plan a utility that needs an operation without one. The failure
    belongs here and not at the button: this is the only route to a run, so a
    caller that forgets cannot produce the fatal-on-every-case invocation that
    made ``transformPoints`` unusable in the first place.
    """
    if utility.needs_operation and operation is None:
        raise ValueError(f"{utility.name} does nothing without an operation")
    argv = (*utility.argv, *operation.argv()) if operation is not None else utility.argv
    return RunPlan(
        case=case,
        stages=(Stage(utility.name, argv=argv, fail_on=utility.fail_on),),
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
