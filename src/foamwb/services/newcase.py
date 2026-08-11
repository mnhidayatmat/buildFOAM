"""Creating an empty case to import geometry into (FR-C1).

The Hub offers *New Case* and the Library offers a tutorial to copy, and they
answer different questions. The Library is for "show me a case that works"; this
is for "I have a model of my own and nowhere to put it". A user in the second
position given only the first has to install a tutorial they do not want and
delete its contents, which is how people end up with a case that still has
someone else's boundary conditions in it.

**Minimal, but valid on its own terms.** What is written is exactly what makes
the folder a case: ``system/controlDict`` naming a solver, plus the two
dictionaries every solver reads. It deliberately does not write ``0`` fields.
Which fields a case needs is decided by its solver *and* by the patches its mesh
turns out to have, and neither is known before the geometry is imported and
meshed — inventing them here would produce a case whose initial conditions
describe a mesh that does not exist yet.

So the case opens with work visibly outstanding, which is honest: the workflow
panel shows meshing as the next step, which is what it is.

**Nothing is overwritten, ever.** Creating into a directory that already holds a
case would silently destroy it, and there is no undo for that. An occupied
destination is refused with its own code and the user picks another name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from foamwb.branding import APP_DISPLAY_NAME
from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event

__all__ = [
    "DEFAULT_APPLICATION",
    "NewCaseError",
    "create_case",
    "is_valid_name",
]

_log = get_logger("newcase")

#: The solver a new case names until the user changes it.
#:
#: Steady, incompressible, turbulent — the most common starting point for the
#: external-flow problems that arrive as a CAD model, which is the case this
#: whole path exists to serve. Named in ``controlDict`` rather than left blank
#: because a case with no ``application`` cannot be planned or run, and the Run
#: view would have to explain an empty field the user never filled in.
DEFAULT_APPLICATION = "simpleFoam"

#: Characters a case name may not contain.
#:
#: OpenFOAM passes case paths through shell-adjacent tooling and its own
#: dictionary readers, and a name with a space or a quote in it survives this
#: application — which never builds shell strings — only to fail inside a
#: utility script. The restriction is stated up front rather than discovered.
_FORBIDDEN = set('<>:"/\\|?*')


class NewCaseError(ValueError):
    """A case that could not be created, carrying its §9 code."""

    def __init__(self, message: str, code: Code, path: Path) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class NewCase:
    """Where a case was created and what was put in it."""

    path: Path
    application: str
    written: tuple[Path, ...]
    """Every file created, relative to the case root — so the caller can say what
    it did rather than claiming a folder appeared by itself."""


def is_valid_name(name: str) -> bool:
    """Whether ``name`` is usable as a case directory name."""
    stripped = name.strip()
    if not stripped or stripped in {".", ".."}:
        return False
    if stripped != name:
        # Leading or trailing whitespace survives on POSIX and is silently
        # dropped by Windows, so the same name would refer to two different
        # directories depending on the machine.
        return False
    return not (set(name) & _FORBIDDEN)


#: A file-format header, not a release. The ``version`` here is the dictionary
#: format's own — 2.0 for every OpenFOAM release in living memory — which is why
#: it is a literal rather than something read from the runtime manifest.
_HEADER = """\
/*--------------------------------*- C++ -*----------------------------------*\\
| Written by {product}. This is an ordinary OpenFOAM case:                     |
| nothing here depends on the application that created it.                     |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      {object};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

"""

_CONTROL_DICT = """\
application     {application};
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         1000;
deltaT          1;
writeControl    timeStep;
writeInterval   100;
purgeWrite      0;
writeFormat     ascii;
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
"""

#: Schemes for a steady, incompressible run. Chosen to be stable rather than
#: accurate: a first-order upwind divergence scheme converges on a bad mesh,
#: which is the mesh a new case has, and the user can raise the order once it
#: runs at all.
_FV_SCHEMES = """\
ddtSchemes
{
    default         steadyState;
}

gradSchemes
{
    default         Gauss linear;
}

divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss upwind;
    div(phi,k)      bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}

wallDist
{
    method          meshWave;
}
"""

_FV_SOLUTION = """\
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.1;
        smoother        GaussSeidel;
    }

    "(U|k|omega|epsilon)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-05;
        relTol          0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent      yes;

    residualControl
    {
        p               1e-4;
        U               1e-4;
        "(k|omega|epsilon)" 1e-4;
    }
}

relaxationFactors
{
    equations
    {
        U               0.9;
        ".*"            0.9;
    }
}
"""


def _dictionary(object_name: str, body: str) -> bytes:
    return (_HEADER.format(product=APP_DISPLAY_NAME, object=object_name) + body).encode("utf-8")


def create_case(
    parent: Path,
    name: str,
    *,
    application: str = DEFAULT_APPLICATION,
) -> NewCase:
    """Create an empty case named ``name`` inside ``parent``.

    Raises :class:`NewCaseError` rather than writing over anything. The three
    refusals are all recoverable by the user changing one thing: the name, the
    destination, or what is already at the destination.
    """
    if not is_valid_name(name):
        raise NewCaseError(
            f"{name!r} cannot be used as a folder name",
            ErrorCode.NEW_CASE_NAME_INVALID,
            parent,
        )

    case = parent / name
    if case.exists() and any(case.iterdir()):
        raise NewCaseError(
            f"{name} already exists and is not empty",
            ErrorCode.NEW_CASE_EXISTS,
            case,
        )

    files = {
        Path("system") / "controlDict": _dictionary(
            "controlDict", _CONTROL_DICT.format(application=application)
        ),
        Path("system") / "fvSchemes": _dictionary("fvSchemes", _FV_SCHEMES),
        Path("system") / "fvSolution": _dictionary("fvSolution", _FV_SOLUTION),
    }

    try:
        for directory in ("system", "constant", "0"):
            (case / directory).mkdir(parents=True, exist_ok=True)
        for relative, data in files.items():
            (case / relative).write_bytes(data)
    except OSError as exc:
        raise NewCaseError(
            f"{name} could not be created: {exc.strerror or exc}",
            ErrorCode.NEW_CASE_NOT_WRITABLE,
            case,
        ) from exc

    log_event(_log, Event.CASE_WRITE, case=str(case), action="create")
    return NewCase(path=case, application=application, written=tuple(files))
