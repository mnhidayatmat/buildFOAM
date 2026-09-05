"""The generated mesh's boundary, as something that can be drawn (DEC-23).

The Mesh document showed the *imported surface* — the STL a case is meshed
around. That answers "is this the thing I meant to import?" and nothing about
what ``blockMesh`` or ``snappyHexMesh`` then produced, which is the question a
user has immediately afterwards and had to open ParaView to answer.

**Boundary faces only, and that is the whole design.** A volume mesh is cells;
its boundary is a surface, and a surface is what the existing projection already
draws. Reading only the boundary is also what makes this affordable: the faces of
a mesh are dominated by internal ones, which nobody can see, and OpenFOAM stores
the boundary faces contiguously at the end of ``faces`` — so the patches'
``startFace`` entries say exactly which part of the file to keep.

**Still not a viewer** (NG1, NG3). No fields, no results, no colour maps, no
clipping. The faces are coloured by the patch they belong to, because "which
patch is that?" is the question the boundary-condition matrix cannot answer — a
row called ``frontAndBack`` tells a student nothing about where on their model it
is, and pointing at it is the only explanation that works.

**It refuses rather than stalls.** A mesh past the size caps below is reported
unavailable with a reason, and the view says so and offers ParaView. Reading a
600 MB ``points`` file to draw a preview would breach NFR-P3 in the one place a
user is most likely to be dragging something, and "too large to preview here" is
an honest answer where a frozen window is not.

The reader produces the same :class:`~foamwb.services.preview.Sample` an STL
does, so everything downstream — projection, picking, the widget — is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from foamwb.services.boundary import Patch, read_boundary
from foamwb.services.preview import DEFAULT_BUDGET, Sample, Triangle

__all__ = [
    "FACES_FILE",
    "MAX_SOURCE_BYTES",
    "POINTS_FILE",
    "MeshSurface",
    "Unavailable",
    "read_mesh_surface",
]

#: Relative to the case root.
POINTS_FILE = Path("constant") / "polyMesh" / "points"
FACES_FILE = Path("constant") / "polyMesh" / "faces"

#: The largest ``points`` or ``faces`` file this will read, in bytes.
#:
#: Sized so a mesh of a few million cells still previews and a research-scale one
#: is refused in milliseconds rather than after a minute of parsing. The refusal
#: is the feature: NG3 says ParaView is what opens large results, and a preview
#: that locked the window for a minute would be worse than one that declines.
MAX_SOURCE_BYTES = 96 * 1024 * 1024

#: One face per match: the vertex count, then the indices inside its brackets.
#: Applied to the region of the file that holds the boundary faces, so the
#: internal faces are never turned into Python objects at all.
_FACE = re.compile(rb"(\d+)\s*\(([^)]*)\)")

#: ``(x y z)`` — the only form ``points`` is written in.
_POINT = re.compile(rb"\(([^)]*)\)")


class Unavailable(StrEnum):
    """Why there is no mesh to draw. A state, not an error (§7.9 rule 1)."""

    NO_MESH = "no_mesh"
    """The case has not been meshed yet — the ordinary state of a new case."""

    TOO_LARGE = "too_large"
    """Past :data:`MAX_SOURCE_BYTES`. ParaView is the answer, and the view says so."""

    UNREADABLE = "unreadable"
    """Present but not in a form this reads — a binary mesh, or a truncated file."""


@dataclass(frozen=True, slots=True)
class MeshSurface:
    """The boundary of a generated mesh, ready to project."""

    sample: Sample
    patches: tuple[Patch, ...] = ()
    """The patches, indexed by the face group ids in :attr:`Sample.faces`.

    Carried whole rather than as names, because the widget colours by patch and
    the matrix selects by patch, and both want the type as well as the name."""

    faces_read: int = 0
    faces_total: int = 0
    """Boundary faces drawn, and boundary faces the mesh has.

    Different when the mesh is past the drawing budget. Stated rather than
    hidden, for the same reason the STL preview says it is thinned: a picture
    drawn from a tenth of a mesh must not claim to be the mesh."""

    patch_of: dict[int, str] = field(default_factory=dict)
    """Face group id to patch name, which is what the widget labels with."""

    @property
    def is_partial(self) -> bool:
        return self.faces_read < self.faces_total


def _slice_after_count(data: bytes) -> bytes:
    """The interior of the counted list, past its own opening bracket.

    Two landmarks, in order. The header is an ordinary dictionary and the
    payload follows it, so its closing ``}`` comes first — searching for a
    bracket instead would find one inside ``arch "LSB;label=32..."`` or the
    comment banner. Then the list's own ``(`` is stepped over, because leaving
    it in makes the first regex match run from it to the first inner ``)`` and
    swallow the opening bracket of the first entry with it.
    """
    header = data.find(b"}")
    body = data[header + 1 :] if header >= 0 else data
    opening = body.find(b"(")
    return body[opening + 1 :] if opening >= 0 else body


def _read_points(path: Path) -> list[tuple[float, float, float]]:
    """Every vertex, in file order. Indices in ``faces`` are offsets into this."""
    body = _slice_after_count(path.read_bytes())
    points: list[tuple[float, float, float]] = []
    for match in _POINT.finditer(body):
        parts = match.group(1).split()
        if len(parts) != 3:
            continue
        points.append((float(parts[0]), float(parts[1]), float(parts[2])))
    return points


def _read_boundary_faces(path: Path, first: int, wanted: int) -> tuple[list[tuple[int, ...]], int]:
    """The faces from index ``first``, and the index the list started at.

    Faces before ``first`` are internal: they are between two cells, so nothing
    can see them, and matching them into Python tuples would be most of the work
    of reading the file for a result that is thrown away. The regex is stepped
    past them instead.
    """
    body = _slice_after_count(path.read_bytes())
    faces: list[tuple[int, ...]] = []
    for index, match in enumerate(_FACE.finditer(body)):
        if index < first:
            continue
        if len(faces) >= wanted:
            break
        faces.append(tuple(int(v) for v in match.group(2).split()))
    return faces, first


def _stride(total: int, budget: int) -> int:
    """Take every nth face, so a large mesh thins evenly rather than truncating.

    Truncating would draw one end of the model and leave the rest missing, which
    reads as a broken mesh rather than as a thinned picture.
    """
    return max(1, -(-total // budget)) if budget > 0 else 1


def read_mesh_surface(
    case: Path | None, *, budget: int = DEFAULT_BUDGET
) -> MeshSurface | Unavailable:
    """Read a meshed case's boundary faces, grouped by patch.

    Never raises. Every failure is one of :class:`Unavailable`, because this
    draws a picture: a case whose mesh cannot be read has larger problems and
    they are reported by the views that exist to report them.
    """
    if case is None:
        return Unavailable.NO_MESH

    points_path, faces_path = case / POINTS_FILE, case / FACES_FILE
    if not points_path.is_file() or not faces_path.is_file():
        return Unavailable.NO_MESH

    try:
        if max(points_path.stat().st_size, faces_path.stat().st_size) > MAX_SOURCE_BYTES:
            return Unavailable.TOO_LARGE
    except OSError:  # pragma: no cover - a file that vanished between the checks
        return Unavailable.NO_MESH

    patches = [p for p in read_boundary(case) if p.n_faces > 0]
    if not patches:
        return Unavailable.UNREADABLE

    first = min(p.start_face for p in patches)
    total = sum(p.n_faces for p in patches)

    try:
        points = _read_points(points_path)
        faces, offset = _read_boundary_faces(faces_path, first, total)
    except (OSError, ValueError):
        return Unavailable.UNREADABLE

    if not points or not faces:
        return Unavailable.UNREADABLE

    # Thinned **within each patch**, not across the flat list. A stride applied
    # to the whole boundary would take its faces in proportion to their number,
    # and a patch of thirty faces beside one of twenty-four thousand can lose
    # every face it has — leaving a patch that is named in the matrix, named in
    # the legend, and nowhere on the model. Per patch, every patch keeps at
    # least one face whatever the budget.
    step = _stride(total, budget)
    triangles: list[Triangle] = []
    groups: list[int] = []
    drawn = 0

    for group, patch in enumerate(patches):
        begin = patch.start_face - offset
        for position in range(begin, begin + patch.n_faces, step):
            if not 0 <= position < len(faces):
                continue
            face = faces[position]
            if len(face) < 3:
                continue
            try:
                corners = [points[v] for v in face]
            except IndexError:
                # A face naming a vertex the points file does not have is a
                # truncated or mismatched mesh. Skipped rather than fatal: the
                # rest of the boundary is still worth looking at.
                continue
            drawn += 1
            # Fan triangulation. Mesh faces are quads or triangles almost
            # always, and a fan is correct for any convex polygon — which a
            # finite-volume face has to be.
            for corner in range(1, len(corners) - 1):
                triangles.append((corners[0], corners[corner], corners[corner + 1]))
                groups.append(group)

    if not triangles:
        return Unavailable.UNREADABLE

    sample = Sample(
        triangles=tuple(triangles),
        total=len(triangles),
        faces=tuple(groups),
        face_count=len(patches),
        faces_known=True,
    )
    return MeshSurface(
        sample=sample,
        patches=tuple(patches),
        faces_read=drawn,
        faces_total=total,
        patch_of={group: patch.name for group, patch in enumerate(patches)},
    )
