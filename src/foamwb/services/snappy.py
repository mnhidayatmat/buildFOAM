"""Generating a background mesh and a meshing dictionary from geometry (FR-P3).

FR-P3 asks for ``snappyHexMeshDict`` to be *configured and run* with STL import,
with surface refinement levels editable. Importing the surface is only the first
half: ``snappyHexMesh`` refines an existing hexahedral mesh down onto a surface,
so without a background mesh to refine there is nothing for it to do. A case with
geometry and neither dictionary offers no meshing utility at all, which is where
the import path used to stop.

So this writes both, from one description of the domain.

**The domain is derived from the geometry, because nothing else can derive it.**
The user has just imported a surface whose size they may not even know — that is
the point of reporting its bounding box — and asking them for eight corner
coordinates before they have seen a mesh is asking the wrong question first. The
box is computed and then shown, which is the order that lets them correct it.

**``locationInMesh`` is the entry that decides whether this works at all.** It
names a point in the region to *keep*, and it is the single most common reason a
``snappyHexMesh`` run produces an empty mesh or one containing the inside of the
solid instead of the fluid around it. There is no way to infer it from the
surface alone — the same STL is a wing in external flow and a duct in internal
flow, and the correct point is in opposite places — so :class:`FlowRegion` asks
that one question and everything else follows from the answer.

**Layer addition is off.** ``addLayers`` is the fragile third of snappyHexMesh:
it fails on exactly the meshes a beginner produces, and it fails *after* the long
part of the run. A mesh without layers is a valid mesh with a poorer near-wall
resolution, which the y+ audit in §6.9 already reports on. Turning it on is a
later decision made against a mesh that exists.

**Nothing is ever overwritten silently.** :func:`plan_mesh` reports which targets
already exist and :func:`write_dictionaries` refuses unless told, because a case
that shipped its own tuned ``snappyHexMeshDict`` must not lose it to a button
labelled *Generate*.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.foamwrite import dictionary
from foamwb.services.geometry import Surface, existing_surfaces

__all__ = [
    "BLOCK_MESH_DICT",
    "SNAPPY_DICT",
    "FlowRegion",
    "MeshPlan",
    "MeshSettings",
    "SnappyError",
    "plan_mesh",
    "write_dictionaries",
]

_log = get_logger("snappy")

#: Where the generated dictionaries go, case-relative.
BLOCK_MESH_DICT = Path("system") / "blockMeshDict"
SNAPPY_DICT = Path("system") / "snappyHexMeshDict"


class FlowRegion(StrEnum):
    """Which side of the surface the fluid is on.

    The one question that cannot be answered from the geometry. An STL of a pipe
    is the same file whether the flow is through it or around it, and the two
    need ``locationInMesh`` in opposite places.
    """

    EXTERNAL = "external"
    """Flow around the body. The domain is a box enclosing it, and the fluid is
    everything outside the surface."""

    INTERNAL = "internal"
    """Flow through the body. The surface *is* the boundary of the fluid, so the
    domain is the geometry's own extent and the fluid is inside it."""


@dataclass(frozen=True, slots=True)
class MeshSettings:
    """What the user can change about the generated mesh (FR-P3)."""

    region: FlowRegion = FlowRegion.EXTERNAL

    refinement_min: int = 2
    refinement_max: int = 3
    """Refinement levels on the surface, as ``snappyHexMesh``'s ``(min max)``.

    Each level halves the cell size, so the difference between 2 and 4 is a
    factor of four in each direction — which is why this is exposed rather than
    fixed. The default pair is the one the tutorials use for a first mesh."""

    background_cells: int = 40
    """Cells along the domain's longest axis.

    Everything else follows from keeping the background cells cubic, which is
    what ``snappyHexMesh`` wants: it refines by bisection, so a background cell
    with a 4:1 aspect ratio produces refined cells with the same 4:1 ratio all
    the way down."""

    padding: float = 2.0
    """How much larger than the body the domain is, for external flow only.

    A multiple of the body's own extent in each direction. Too small and the
    boundaries influence the answer; too large and the cell count is spent on
    empty space far from anything."""

    location_in_mesh: tuple[float, float, float] | None = None
    """An explicit point in the fluid, overriding the one derived from
    :attr:`region`. Present because the derived point is a good guess and a
    guess is exactly the thing a user must be able to correct."""

    def normalised(self) -> MeshSettings:
        """The same settings with impossible values brought into range.

        Clamped rather than rejected: these arrive from spin boxes, and a
        refinement maximum below the minimum is a half-finished edit rather than
        a mistake worth an error dialog.
        """
        low = max(0, self.refinement_min)
        return replace(
            self,
            # Coerced, because the value arrives from a combo box and Qt returns
            # user data as a plain ``str`` — a ``StrEnum`` goes in and "external"
            # comes back out. Every ``is`` comparison against FlowRegion then
            # reads False, which silently selected the *internal* branch and put
            # locationInMesh inside the body: the exact inside-out mesh the guide
            # warns about, produced by choosing the option that says "external".
            region=FlowRegion(self.region),
            refinement_min=low,
            refinement_max=max(low, self.refinement_max),
            background_cells=max(4, self.background_cells),
            padding=max(1.0, self.padding),
        )


@dataclass(frozen=True, slots=True)
class MeshPlan:
    """What would be written, and what it would cost."""

    low: tuple[float, float, float]
    high: tuple[float, float, float]
    cells: tuple[int, int, int]
    location_in_mesh: tuple[float, float, float]
    surfaces: tuple[Surface, ...]
    settings: MeshSettings
    existing: tuple[Path, ...] = ()
    """Targets that already hold a file. Empty means nothing would be lost."""

    @property
    def targets(self) -> tuple[Path, ...]:
        return (BLOCK_MESH_DICT, SNAPPY_DICT)

    @property
    def background_cell_count(self) -> int:
        """Cells in the background mesh, before any refinement.

        Worth showing: it is the number the user can act on, and a background
        mesh of ten million cells is a mistake that is cheap to see and
        expensive to discover by waiting."""
        return self.cells[0] * self.cells[1] * self.cells[2]

    @property
    def can_write(self) -> bool:
        return not self.existing


class SnappyError(ValueError):
    """Mesh generation that cannot proceed, carrying its §9 code."""

    def __init__(self, message: str, code: Code, path: Path) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.path = path


def _extent(surfaces: tuple[Surface, ...]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The box enclosing every surface that reported one."""
    boxes = [s.bounds for s in surfaces if s.bounds is not None]
    if not boxes:
        raise SnappyError(
            "the geometry has no readable extent",
            ErrorCode.GEOMETRY_UNREADABLE,
            Path(),
        )
    low = tuple(min(box[0][axis] for box in boxes) for axis in range(3))
    high = tuple(max(box[1][axis] for box in boxes) for axis in range(3))
    return low, high


def plan_mesh(case: Path, settings: MeshSettings | None = None) -> MeshPlan:
    """Work out the domain and the cell counts, without writing anything.

    Separated from writing for the reason every plan/apply pair in this codebase
    is: the user is shown the domain, the cell count and what would be
    overwritten *before* anything happens to their case.
    """
    settings = (settings or MeshSettings()).normalised()
    surfaces = tuple(s for s in existing_surfaces(case) if s.triangles > 0)
    if not surfaces:
        raise SnappyError(
            "there is no geometry to mesh around",
            ErrorCode.NO_GEOMETRY_TO_MESH,
            case,
        )

    low, high = _extent(surfaces)
    size = [high[axis] - low[axis] for axis in range(3)]

    if settings.region is FlowRegion.EXTERNAL:
        # Grown about the body's centre, so the body stays in the middle of the
        # domain rather than against whichever face happened to be nearest.
        margin = [(settings.padding - 1.0) * extent / 2 for extent in size]
        low = tuple(low[axis] - margin[axis] for axis in range(3))
        high = tuple(high[axis] + margin[axis] for axis in range(3))
    else:
        # The surface *is* the boundary, so the background box only has to
        # enclose it. A small margin keeps the box off the surface itself, which
        # snappyHexMesh needs in order to have cells to cut.
        margin = [max(extent * 0.02, _epsilon(size)) for extent in size]
        low = tuple(low[axis] - margin[axis] for axis in range(3))
        high = tuple(high[axis] + margin[axis] for axis in range(3))

    size = [high[axis] - low[axis] for axis in range(3)]
    cells = _cell_counts(size, settings.background_cells)
    location = settings.location_in_mesh or _location_in_mesh(low, high, settings.region)

    return MeshPlan(
        low=low,
        high=high,
        cells=cells,
        location_in_mesh=location,
        surfaces=surfaces,
        settings=settings,
        existing=tuple(
            target for target in (BLOCK_MESH_DICT, SNAPPY_DICT) if (case / target).is_file()
        ),
    )


def _epsilon(size: list[float]) -> float:
    """A length small against the model but not against floating point."""
    largest = max((extent for extent in size if extent > 0), default=1.0)
    return largest * 1e-3


def _cell_counts(size: list[float], along_longest: int) -> tuple[int, int, int]:
    """Cell counts that keep the background cells as cubic as they can be.

    ``snappyHexMesh`` refines by bisecting cells, so it cannot correct a
    background aspect ratio — a 4:1 background cell produces 4:1 cells at every
    refinement level, and those are what ``checkMesh`` then complains about.
    """
    longest = max(size) or 1.0
    edge = longest / along_longest
    # At least one cell per axis: a surface that is exactly flat in z has zero
    # extent there, and a zero cell count is not a mesh blockMesh will accept.
    return tuple(max(1, round(extent / edge)) for extent in size)


def _location_in_mesh(
    low: tuple[float, ...],
    high: tuple[float, ...],
    region: FlowRegion,
) -> tuple[float, float, float]:
    """A point in the fluid, chosen from which side the fluid is on.

    External flow keeps the region *outside* the body, so the point goes near a
    corner of the domain, which the padding guarantees is empty. Internal flow
    keeps the region inside, so the point goes at the centre — which is right for
    a duct and wrong for a strongly curved one, and is exactly why it can be
    overridden.
    """
    if region is FlowRegion.EXTERNAL:
        # Offset from the corner rather than on it: a point on a boundary face
        # is ambiguous, and snappyHexMesh refuses it.
        return tuple(low[axis] + 0.02 * (high[axis] - low[axis]) for axis in range(3))
    return tuple((low[axis] + high[axis]) / 2 for axis in range(3))


def _n(value: float) -> str:
    """A coordinate, written so it round-trips through OpenFOAM's parser."""
    return repr(round(float(value), 10))


def render_block_mesh(plan: MeshPlan) -> bytes:
    """The background mesh: one hex block, six named boundary patches.

    The faces are named rather than lumped into one patch, because after meshing
    they are the patches the user assigns boundary conditions to — and ``xMin``
    means something they can act on where ``background`` does not.
    """
    low, high = plan.low, plan.high
    corners = (
        (low[0], low[1], low[2]),
        (high[0], low[1], low[2]),
        (high[0], high[1], low[2]),
        (low[0], high[1], low[2]),
        (low[0], low[1], high[2]),
        (high[0], low[1], high[2]),
        (high[0], high[1], high[2]),
        (low[0], high[1], high[2]),
    )
    vertices = "\n".join(f"    ({_n(x)} {_n(y)} {_n(z)})" for x, y, z in corners)
    nx, ny, nz = plan.cells

    body = f"""\
scale   1;

vertices
(
{vertices}
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges
(
);

boundary
(
    xMin
    {{
        type patch;
        faces ( (0 4 7 3) );
    }}
    xMax
    {{
        type patch;
        faces ( (1 2 6 5) );
    }}
    yMin
    {{
        type patch;
        faces ( (0 1 5 4) );
    }}
    yMax
    {{
        type patch;
        faces ( (3 7 6 2) );
    }}
    zMin
    {{
        type patch;
        faces ( (0 3 2 1) );
    }}
    zMax
    {{
        type patch;
        faces ( (4 5 6 7) );
    }}
);

mergePatchPairs
(
);
"""
    return dictionary("blockMeshDict", body)


def _surface_name(surface: Surface) -> str:
    """The name a surface is known by inside the dictionary.

    The file stem, so the patch ``snappyHexMesh`` creates is called after the
    file the user imported — which is the only name they have for it.
    """
    return surface.path.stem


def render_snappy(plan: MeshPlan) -> bytes:
    """The meshing dictionary, referring to the surfaces already in the case."""
    settings = plan.settings
    geometry = "\n".join(
        f"""    {surface.name}
    {{
        type triSurfaceMesh;
        name {_surface_name(surface)};
    }}"""
        for surface in plan.surfaces
    )
    refinement = "\n".join(
        f"""        {_surface_name(surface)}
        {{
            level ({settings.refinement_min} {settings.refinement_max});
        }}"""
        for surface in plan.surfaces
    )
    x, y, z = plan.location_in_mesh

    body = f"""\
castellatedMesh true;
snap            true;
// Layer addition is the part that fails late and on exactly the meshes a
// first attempt produces. Turn it on against a mesh that already works.
addLayers       false;

geometry
{{
{geometry}
}}

castellatedMeshControls
{{
    maxLocalCells   1000000;
    maxGlobalCells  2000000;
    minRefinementCells 10;
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels 3;

    features
    (
    );

    refinementSurfaces
    {{
{refinement}
    }}

    resolveFeatureAngle 30;

    refinementRegions
    {{
    }}

    // The point in the region to KEEP. If the mesh comes out empty, or contains
    // the inside of the solid instead of the fluid around it, this is the entry
    // to change.
    locationInMesh ({_n(x)} {_n(y)} {_n(z)});

    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch    3;
    tolerance       2.0;
    nSolveIter      30;
    nRelaxIter      5;
    nFeatureSnapIter 10;
    implicitFeatureSnap false;
    explicitFeatureSnap true;
    multiRegionFeatureSnap false;
}}

addLayersControls
{{
    relativeSizes   true;
    layers
    {{
    }}
    expansionRatio  1.2;
    finalLayerThickness 0.3;
    minThickness    0.1;
    nGrow           0;
    featureAngle    60;
    nRelaxIter      3;
    nSmoothSurfaceNormals 1;
    nSmoothNormals  3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter      50;
}}

meshQualityControls
{{
    maxNonOrtho     65;
    maxBoundarySkewness 20;
    maxInternalSkewness 4;
    maxConcave      80;
    minVol          1e-13;
    minTetQuality   1e-30;
    minArea         -1;
    minTwist        0.02;
    minDeterminant  0.001;
    minFaceWeight   0.02;
    minVolRatio     0.01;
    minTriangleTwist -1;
    nSmoothScale    4;
    errorReduction  0.75;
}}

mergeTolerance 1e-6;
"""
    return dictionary("snappyHexMeshDict", body)


def write_dictionaries(
    case: Path, plan: MeshPlan, *, replace_existing: bool = False
) -> tuple[Path, ...]:
    """Write both dictionaries. Returns the paths written, case-relative.

    Refuses when either target exists unless ``replace_existing`` is set. A case
    that shipped a tuned ``snappyHexMeshDict`` must not lose it to a button
    labelled *Generate*, and the caller is the only layer that can ask.
    """
    if plan.existing and not replace_existing:
        raise SnappyError(
            "the meshing dictionaries are already there",
            ErrorCode.MESH_DICT_EXISTS,
            case / plan.existing[0],
        )

    (case / "system").mkdir(parents=True, exist_ok=True)
    for target, data in (
        (BLOCK_MESH_DICT, render_block_mesh(plan)),
        (SNAPPY_DICT, render_snappy(plan)),
    ):
        (case / target).write_bytes(data)

    log_event(
        _log,
        Event.CASE_WRITE,
        case=str(case),
        action="write_mesh_dicts",
        cells=plan.background_cell_count,
    )
    return plan.targets
