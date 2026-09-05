"""Turning an imported surface into something that can be drawn (FR-P3).

**This is not a viewer, and the distinction matters.** NG1 says the product does
not *draw* geometry, meaning it has no CAD authoring; NG3 says it does not
replace ParaView. What is here is neither: a shaded outline of the file that was
just imported, so a user can see whether it is the thing they meant. There are no
fields, no results and no colour maps.

**It picks as well as paints, and that is still not authoring.** Faces can be
clicked and named, because the names of an STL's regions are what the generated
mesh's patches are called and there was otherwise no way to set them short of
editing the file by hand. Nothing here creates or moves a triangle; it labels the
ones that arrived. :mod:`foamwb.services.surface_regions` is where a label
becomes a file.

**It exists because a bounding box is a poor way to recognise a shape.**
:mod:`foamwb.services.geometry` already reports ``2400 × 900 × 1500`` precisely
so a user notices their car is in millimetres. That works for units and not for
anything else: it cannot tell them they exported the wrong body, that the
surface came out inside out, or that half the assembly is missing. A picture
answers all three in the time it takes to look at it.

**The projection lives here rather than in the widget** so it can be tested
without a display, and so the same code could back a thumbnail in a future case
list. The widget receives finished polygons and paints them.

**Triangles are read to a budget, not in full.** A detailed assembly runs to
millions of facets; painting those per frame would stall the GUI thread, which
NFR-P3 forbids in the one place a user is most likely to drag something. Reading
stops at the budget and says how many it took, because a preview drawn from a
tenth of a model must not claim to be the model.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_FEATURE_ANGLE",
    "GROUPING_BUDGET",
    "Facet",
    "Sample",
    "group_faces",
    "pick",
    "project",
    "read_triangles",
]

#: How many triangles the preview will read before it stops.
#:
#: Chosen so a full redraw stays inside a frame on the reference machine while
#: still resolving the shape of a typical imported body. Beyond this the extra
#: facets are smaller than a pixel and cost only time.
DEFAULT_BUDGET = 24_000

#: How many triangles may be *grouped into faces* before the attempt is given up.
#:
#: Much larger than the drawing budget, and necessarily so: grouping is about
#: which triangles touch each other, and thinned triangles do not touch. Sampling
#: one facet in ten leaves almost no two sharing an edge, so every triangle would
#: come out as its own face — not a coarser answer but a wrong one. Grouping
#: therefore reads the file in full or not at all, and this is where "not at all"
#: begins. Above it :attr:`Sample.faces_known` is false and the interface says so
#: rather than offering a picture whose pieces are meaningless.
GROUPING_BUDGET = 200_000

#: How far two touching triangles may differ, in degrees, and still be one face.
#:
#: 40° keeps a cube at six faces and a cylinder at a barrel plus two caps, which
#: is what a user means by "that face". OpenFOAM's own ``surfaceFeatureExtract``
#: defaults to 30° for the complementary question — which edges are features —
#: so this sits in the same family of judgement rather than inventing one.
DEFAULT_FEATURE_ANGLE = 40.0

_BINARY_HEADER = 84
_BINARY_TRIANGLE = 50

Vector = tuple[float, float, float]
Triangle = tuple[Vector, Vector, Vector]


@dataclass(frozen=True, slots=True)
class Facet:
    """One triangle, projected and shaded, ready to be filled."""

    points: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    shade: float
    """0 for a face turned away from the light, 1 for one facing it square on."""

    depth: float
    """Distance from the viewer, for painting back to front."""

    face: int = 0
    """Which face group this triangle belongs to.

    The identity a click resolves to. Carried on the projected facet rather than
    looked up by index afterwards, because projection sorts by depth and the
    caller would have to undo that sort to find its way back."""


@dataclass(frozen=True, slots=True)
class Sample:
    """What was read from a surface file, and what it was read from.

    Read once and projected many times: turning the model must not re-read
    megabytes off disk on every mouse move.
    """

    triangles: tuple[Triangle, ...]
    total: int
    """Triangles the file holds, so a thinned preview can say it is thinned."""

    faces: tuple[int, ...] = ()
    """Face group per triangle, parallel to :attr:`triangles`.

    Empty when grouping was not attempted, which is not the same as a model with
    one face — see :attr:`faces_known`."""

    face_count: int = 0
    faces_known: bool = False
    """Whether the faces are a real answer about this model.

    False for a file past :data:`GROUPING_BUDGET`, where reading every triangle
    to find which ones touch would cost more than the feature is worth. Stated
    rather than defaulted to one face, because "this model has a single face" and
    "nobody looked" are different things to tell a user who is trying to click
    one."""

    @property
    def is_partial(self) -> bool:
        return len(self.triangles) < self.total


def _rotate(point: Vector, yaw: float, pitch: float) -> Vector:
    """Turn a point about the vertical axis, then tip it towards the viewer."""
    x, y, z = point
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    x, y = x * cos_y - y * sin_y, x * sin_y + y * cos_y
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)
    y, z = y * cos_p - z * sin_p, y * sin_p + z * cos_p
    return x, y, z


def _normal(triangle: Triangle) -> Vector:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length == 0.0:
        # A degenerate facet has no direction to be lit from. Facing the viewer
        # is the choice that makes it invisible rather than a black speck.
        return 0.0, 0.0, 1.0
    return nx / length, ny / length, nz / length


def _weld_tolerance(triangles: tuple[Triangle, ...] | list[Triangle]) -> float:
    """How close two corners must be to count as the same point.

    Relative to the model rather than absolute: the same part exported in metres
    and in millimetres must weld identically, and a fixed epsilon would join
    everything in one and nothing in the other. Exporters also round differently
    on either side of a shared edge, so comparing the floats exactly leaves a
    surface with no adjacency at all.
    """
    xs = [corner[0] for tri in triangles for corner in tri]
    ys = [corner[1] for tri in triangles for corner in tri]
    zs = [corner[2] for tri in triangles for corner in tri]
    diagonal = math.sqrt(
        (max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2
    )
    # A degenerate model — every corner in one place — has no scale to be
    # relative to. Any positive tolerance welds it to a point, which is the
    # truth about it.
    return (diagonal or 1.0) * 1e-6


def group_faces(
    triangles: tuple[Triangle, ...] | list[Triangle],
    *,
    feature_angle: float = DEFAULT_FEATURE_ANGLE,
) -> tuple[tuple[int, ...], int]:
    """Cluster triangles into the faces a user would point at.

    Two triangles join when they **share an edge** and their normals differ by
    less than ``feature_angle``. Both halves are needed: the angle alone would
    merge the two opposite walls of a duct, which are parallel and nowhere near
    each other, and adjacency alone would merge an entire closed body into one.

    The comparison is on the *absolute* dot product, so a surface whose facets
    wind inconsistently — which imported STLs very often do, and which
    :func:`project` already compensates for when lighting them — is not split
    into stripes along the seams where the winding flips.

    Returns a face id per triangle and how many faces there are. Ids are
    allocated in the order the faces are first met, so the numbering is stable
    for a given file rather than depending on dictionary iteration.
    """
    count = len(triangles)
    if count == 0:
        return (), 0

    tolerance = _weld_tolerance(triangles)
    normals = [_normal(tri) for tri in triangles]
    limit = math.cos(math.radians(feature_angle))

    parent = list(range(count))

    def find(node: int) -> int:
        # Iterative, with path compression. Recursion would hit Python's limit on
        # a long thin strip of triangles, which is an ordinary shape.
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            # Towards the lower index, so first-appearance order survives.
            if left_root < right_root:
                parent[right_root] = left_root
            else:
                parent[left_root] = right_root

    def key(corner: Vector) -> tuple[int, int, int]:
        return (
            round(corner[0] / tolerance),
            round(corner[1] / tolerance),
            round(corner[2] / tolerance),
        )

    seen: dict[tuple[tuple[int, int, int], tuple[int, int, int]], int] = {}
    for index, triangle in enumerate(triangles):
        corners = [key(corner) for corner in triangle]
        for first, second in ((0, 1), (1, 2), (2, 0)):
            edge = (corners[first], corners[second])
            if edge[0] > edge[1]:
                edge = (edge[1], edge[0])
            neighbour = seen.get(edge)
            if neighbour is None:
                seen[edge] = index
                continue
            left, right = normals[index], normals[neighbour]
            alignment = abs(sum(a * b for a, b in zip(left, right, strict=True)))
            if alignment >= limit:
                union(index, neighbour)

    labels: dict[int, int] = {}
    faces = []
    for index in range(count):
        root = find(index)
        if root not in labels:
            labels[root] = len(labels)
        faces.append(labels[root])
    return tuple(faces), len(labels)


def _contains(facet: Facet, x: float, y: float) -> bool:
    """Whether a screen point falls inside a projected triangle.

    Sign-of-cross-product on all three edges. Consistent signs mean inside; a
    zero is a point exactly on an edge, which counts as inside so that the seam
    between two triangles of the same face is not a line that cannot be clicked.
    """
    (ax, ay), (bx, by), (cx, cy) = facet.points
    first = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
    second = (cx - bx) * (y - by) - (cy - by) * (x - bx)
    third = (ax - cx) * (y - cy) - (ay - cy) * (x - cx)
    return not ((first < 0 or second < 0 or third < 0) and (first > 0 or second > 0 or third > 0))


def pick(facets: tuple[Facet, ...], x: float, y: float) -> int | None:
    """Which face is under this screen point, or ``None`` for empty space.

    Scans from the front backwards, which is the reverse of the order
    :func:`project` returns and paints in. Taking the first hit rather than the
    last is the whole of the depth test: the facet drawn on top of the pile is
    the one the user is looking at, and it is the one they mean.
    """
    for facet in reversed(facets):
        if _contains(facet, x, y):
            return facet.face
    return None


def project(
    triangles: tuple[Triangle, ...] | list[Triangle],
    *,
    width: float,
    height: float,
    yaw: float = 0.6,
    pitch: float = -1.1,
    margin: float = 0.12,
    faces: tuple[int, ...] = (),
) -> tuple[Facet, ...]:
    """Flatten a surface into shaded polygons that fill the given box.

    Orthographic rather than perspective: this is a part being inspected, not a
    scene being entered, and parallel edges staying parallel is what makes a
    wrong aspect ratio visible at a glance.

    The fit is computed from the *rotated* geometry, so turning the model never
    moves it out of frame — a preview the user has to re-centre after every drag
    is one they stop turning.
    """
    if not triangles or width <= 0 or height <= 0:
        return ()

    turned = [tuple(_rotate(corner, yaw, pitch) for corner in tri) for tri in triangles]

    xs = [corner[0] for tri in turned for corner in tri]
    zs = [corner[2] for tri in turned for corner in tri]
    span_x = max(xs) - min(xs)
    span_z = max(zs) - min(zs)
    # A flat plate seen edge-on has zero extent one way. Falling back to the
    # other axis draws a line, which is the truth about it.
    scale = min(
        (width * (1 - 2 * margin)) / span_x if span_x else float("inf"),
        (height * (1 - 2 * margin)) / span_z if span_z else float("inf"),
    )
    if scale == float("inf"):
        return ()

    mid_x = (max(xs) + min(xs)) / 2
    mid_z = (max(zs) + min(zs)) / 2

    def to_screen(corner: Vector) -> tuple[float, float]:
        # Screen y grows downward and the model's z grows upward, so the sign
        # flips here rather than leaving every caller to remember it.
        return (
            width / 2 + (corner[0] - mid_x) * scale,
            height / 2 - (corner[2] - mid_z) * scale,
        )

    # Lit from over the viewer's shoulder, which is the convention that makes a
    # shape read as solid without a second light to reason about.
    light = (0.3, -0.8, 0.5)
    light_length = math.sqrt(sum(component * component for component in light))
    light = tuple(component / light_length for component in light)

    facets = []
    for index, rotated in enumerate(turned):
        nx, ny, nz = _normal(rotated)
        # abs, so a surface whose facets wind inconsistently — which imported
        # STLs very often do — is still lit rather than showing black holes.
        intensity = abs(nx * light[0] + ny * light[1] + nz * light[2])
        facets.append(
            Facet(
                points=tuple(to_screen(corner) for corner in rotated),
                shade=0.25 + 0.75 * intensity,
                depth=sum(corner[1] for corner in rotated) / 3.0,
                face=faces[index] if index < len(faces) else 0,
            )
        )

    # Painter's algorithm: no depth buffer, so the far ones go down first. It is
    # wrong for interpenetrating facets and right for everything a single
    # imported body contains, at a fraction of the cost of sorting per pixel.
    facets.sort(key=lambda facet: facet.depth)
    return tuple(facets)


def read_triangles(
    path: Path,
    *,
    budget: int = DEFAULT_BUDGET,
    grouping_budget: int = GROUPING_BUDGET,
    feature_angle: float = DEFAULT_FEATURE_ANGLE,
) -> Sample:
    """Read a surface file, group it into faces, and thin it for drawing.

    In that order, and the order is the point. Grouping asks which triangles
    touch, so it has to see all of them; thinning throws most of them away.
    Grouping the thinned set would find almost no shared edges and report every
    remaining triangle as its own face — a confident wrong answer rather than a
    coarse right one.

    Returns an empty sample rather than raising for a file that cannot be read:
    by the time anything is previewed the file has already been validated by
    :func:`~foamwb.services.geometry.inspect_surface`, and a picture failing to
    appear must never be a louder event than the import itself was.
    """
    try:
        if path.suffix.lower() == ".obj":
            triangles, total, complete = _read_obj(path, budget, grouping_budget)
        elif _is_binary_stl(path):
            triangles, total, complete = _read_binary_stl(path, budget, grouping_budget)
        else:
            triangles, total, complete = _read_ascii_stl(path, budget, grouping_budget)
    except (OSError, ValueError, struct.error):
        return Sample(triangles=(), total=0)

    if not complete:
        return Sample(triangles=tuple(triangles), total=total)

    faces, face_count = group_faces(triangles, feature_angle=feature_angle)
    # Thinned only now, and the face ids are thinned with it, so a facet on
    # screen still knows which face of the *whole* model it came from.
    step = _stride(len(triangles), budget)
    if step > 1:
        triangles = triangles[::step]
        faces = faces[::step]
    return Sample(
        triangles=tuple(triangles),
        total=total,
        faces=tuple(faces),
        face_count=face_count,
        faces_known=True,
    )


def _is_binary_stl(path: Path) -> bool:
    size = path.stat().st_size
    if size < _BINARY_HEADER:
        return False
    with path.open("rb") as handle:
        handle.seek(80)
        raw = handle.read(4)
    if len(raw) != 4:
        return False
    (count,) = struct.unpack("<I", raw)
    return size == _BINARY_HEADER + count * _BINARY_TRIANGLE


def _stride(total: int, budget: int) -> int:
    """Take every nth facet rather than the first n.

    The first n triangles of an STL are one corner of the model — exporters
    write in surface order, so a truncated read draws a fragment and calls it
    the shape. Sampling evenly across the file draws the whole thing coarsely,
    which is what a preview is for.
    """
    return max(1, math.ceil(total / budget)) if total > budget else 1


def _read_binary_stl(
    path: Path, budget: int, grouping_budget: int
) -> tuple[list[Triangle], int, bool]:
    with path.open("rb") as handle:
        handle.seek(80)
        (total,) = struct.unpack("<I", handle.read(4))
        # The count is in the header, so a binary file can be turned down before
        # it is read rather than after — which is the whole reason the grouping
        # budget can be this generous without risking the memory of a huge one.
        complete = total <= grouping_budget
        step = 1 if complete else _stride(total, budget)
        triangles: list[Triangle] = []
        for index in range(total):
            block = handle.read(_BINARY_TRIANGLE)
            if len(block) < _BINARY_TRIANGLE:
                break
            if index % step:
                continue
            values = struct.unpack("<12f", block[:48])
            triangles.append(
                (
                    (values[3], values[4], values[5]),
                    (values[6], values[7], values[8]),
                    (values[9], values[10], values[11]),
                )
            )
    return triangles, total, complete


def _read_ascii_stl(
    path: Path, budget: int, grouping_budget: int
) -> tuple[list[Triangle], int, bool]:
    corners: list[Vector] = []
    triangles: list[Triangle] = []
    total = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith("vertex"):
                continue
            parts = stripped.split()
            if len(parts) < 4:
                continue
            corners.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if len(corners) == 3:
                total += 1
                triangles.append((corners[0], corners[1], corners[2]))
                corners = []
    # ASCII files are read in full — the count is not known until the end — and
    # thinned afterwards, which costs memory on a large file but keeps the
    # sampling even. Binary is the format large models actually arrive in.
    if total <= grouping_budget:
        return triangles, total, True
    step = _stride(total, budget)
    if step > 1:
        triangles = triangles[::step]
    return triangles, total, False


def _read_obj(path: Path, budget: int, grouping_budget: int) -> tuple[list[Triangle], int, bool]:
    vertices: list[Vector] = []
    faces: list[tuple[int, ...]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v" and len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif parts[0] == "f" and len(parts) >= 4:
                # "f 1/2/3" — the vertex index is the part before the first
                # slash; texture and normal indices are not geometry.
                indices = []
                for token in parts[1:]:
                    try:
                        indices.append(int(token.split("/")[0]))
                    except ValueError:
                        indices = []
                        break
                if len(indices) >= 3:
                    faces.append(tuple(indices))

    triangles: list[Triangle] = []
    for face in faces:
        # A quad or an n-gon is fanned from its first corner. Correct for the
        # convex faces exporters emit, and a preview is not the place to fight
        # about the concave ones.
        for offset in range(1, len(face) - 1):
            try:
                corners = tuple(
                    vertices[index - 1 if index > 0 else len(vertices) + index]
                    for index in (face[0], face[offset], face[offset + 1])
                )
            except IndexError:
                continue
            triangles.append(corners)  # type: ignore[arg-type]

    total = len(triangles)
    if total <= grouping_budget:
        return triangles, total, True
    step = _stride(total, budget)
    if step > 1:
        triangles = triangles[::step]
    return triangles, total, False
