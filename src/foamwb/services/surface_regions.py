"""Naming the faces of an imported surface, so the mesh comes out with patches.

**This is the step where a user's vocabulary reaches OpenFOAM.** Everything
downstream is keyed on patch names — the boundary-condition matrix (FR-P4), the
y+ audit, every ``boundaryField`` entry the user will ever edit — and until now
those names came from whatever the exporter happened to call the solids in the
file. A part exported as one anonymous body gave one patch called after the file
stem, and there was no way to say "this face is the inlet" short of editing the
STL by hand in a text editor.

**Why it writes a new file rather than editing the imported one.** Region names
live in an STL as ``solid`` blocks, and *binary STL cannot express them at all* —
the format has no field for a name, which is why
:func:`~foamwb.services.geometry.inspect_surface` reports no solids for a binary
file. So there is no edit that would work for the format most CAD packages
export. The named surface is therefore a derived file written alongside the
original, and the original is left exactly as it was imported: a user who names
six faces and then decides the whole import was wrong still has the file they
started with.

**Face ids are positions, not stored identities.** A face is "the group
:func:`~foamwb.services.preview.group_faces` puts this triangle in", so the ids
are only meaningful for a given file read in a given order. That is safe because
grouping is deterministic — same file, same triangles, same order, same ids —
and unsafe the moment the file changes underneath, which is why an assignment is
stored against the surface it was made on and discarded when that file is
replaced.

NG1 rules out drawing geometry, and this does not: nothing here creates or moves
a triangle. It labels the ones that arrived, which is annotation rather than
authoring — the same category as naming a patch in the boundary editor, done at
the only point in the workflow where the user can still see which face is which.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from foamwb.codes import ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.geometry import GeometryError
from foamwb.services.preview import GROUPING_BUDGET, Triangle, read_triangles

__all__ = [
    "DEFAULT_REGION",
    "FaceAssignment",
    "clean_region_name",
    "is_valid_region_name",
    "named_surface_path",
    "read_faces",
    "write_named_surface",
]

_log = get_logger("services.surface_regions")

#: What unassigned faces are called in the written surface.
#:
#: Everything must land in some region: a triangle in no ``solid`` block is a
#: triangle ``snappyHexMesh`` will not mesh, so a user who names one face of a
#: car and presses on would lose the rest of the car. Named rather than silent,
#: so the patch that appears in the mesh is one they can find in this file.
DEFAULT_REGION = "walls"

#: Suffix marking the file this module writes, so it is recognisable as derived.
_NAMED_SUFFIX = "_regions"

#: What OpenFOAM will accept as a patch name.
#:
#: Letters, digits and underscore, not starting with a digit. Stricter than the
#: dictionary grammar strictly requires, because a name with a space or a dot in
#: it parses here and then fails much later inside a ``boundaryField`` key, where
#: nothing points back at the moment it was typed.
_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_valid_region_name(name: str) -> bool:
    return bool(_VALID_NAME.match(name))


def clean_region_name(name: str) -> str:
    """Turn what a user typed into something OpenFOAM will take.

    Offered rather than imposed: the caller shows the result and lets the user
    accept it. Silently rewriting "front face" to ``front_face`` would leave them
    hunting for a patch under a name they never chose.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return ""
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


@dataclass
class FaceAssignment:
    """Which face of a surface carries which name.

    Sparse on purpose. A model with four thousand faces of which the user has
    named three is the ordinary case, and storing a name for every face would
    make the record mostly a restatement of :data:`DEFAULT_REGION`.
    """

    surface: Path
    names: dict[int, str] = field(default_factory=dict)

    def name_of(self, face: int) -> str:
        return self.names.get(face, DEFAULT_REGION)

    def assign(self, faces: list[int] | tuple[int, ...], name: str) -> None:
        """Give these faces a name, or clear it when the name is empty."""
        for face in faces:
            if name:
                self.names[face] = name
            else:
                self.names.pop(face, None)

    @property
    def regions(self) -> tuple[str, ...]:
        """Every distinct name, in the order the faces carrying them appear.

        Ordered rather than sorted, because the order faces were named in is the
        order the user thought about them, and a list that reshuffles when a name
        is added is a list nobody can keep their place in.
        """
        seen: list[str] = []
        for _face, name in sorted(self.names.items()):
            if name not in seen:
                seen.append(name)
        return tuple(seen)


def read_faces(surface: Path) -> tuple[tuple[Triangle, ...], tuple[int, ...], int]:
    """Every triangle of a surface, and which face each belongs to.

    Distinct from the preview's read, which thins for drawing: writing a named
    surface must place *every* triangle, so this asks for the whole file. The
    grouping budget is the ceiling, and past it the result is empty rather than
    partial — half a surface written out would be a mesh with holes in it.
    """
    sample = read_triangles(surface, budget=GROUPING_BUDGET)
    if not sample.faces_known:
        return (), (), 0
    return sample.triangles, sample.faces, sample.face_count


def named_surface_path(surface: Path) -> Path:
    """Where the named copy of this surface goes.

    Beside the original and derived from its name, so the pair is obvious in a
    directory listing and in ``snappyHexMeshDict``. Always ``.stl``: the named
    file is written by this module in ASCII, whatever the original was.
    """
    stem = surface.stem
    if stem.endswith(_NAMED_SUFFIX):
        return surface.with_suffix(".stl")
    return surface.with_name(f"{stem}{_NAMED_SUFFIX}.stl")


def _format(value: float) -> str:
    """A coordinate, short but not rounded into a different point.

    ``repr`` would give the shortest string that reads back identically, which is
    what byte-fidelity elsewhere in this codebase would want; here the file is
    one this application generates rather than one it round-trips, and six
    significant figures past the decimal is well inside any mesher's tolerance
    while keeping the file readable by a human checking it.
    """
    return f"{value:.6g}"


def write_named_surface(
    surface: Path,
    assignment: FaceAssignment,
    *,
    destination: Path | None = None,
) -> Path:
    """Write an ASCII STL whose ``solid`` blocks are the user's names.

    One block per name, triangles gathered under it. Written whole to a
    neighbouring temporary file and moved into place, so an interrupted write
    cannot leave a half-surface where ``snappyHexMesh`` will find it and mesh it.

    Raises :class:`~foamwb.services.geometry.GeometryError` when the surface
    cannot be grouped, rather than writing something that omits triangles.
    """
    triangles, faces, _count = read_faces(surface)
    if not triangles:
        raise GeometryError(
            f"{surface.name} could not be read into faces, so it cannot be named",
            ErrorCode.GEOMETRY_UNREADABLE,
            surface,
        )

    grouped: dict[str, list[Triangle]] = {}
    for triangle, face in zip(triangles, faces, strict=True):
        grouped.setdefault(assignment.name_of(face), []).append(triangle)

    target = destination or named_surface_path(surface)
    lines: list[str] = []
    for name, members in grouped.items():
        lines.append(f"solid {name}")
        for triangle in members:
            # The normal is written as zero rather than computed. OpenFOAM's
            # triSurface reader takes the winding as authoritative and recomputes
            # it, and a normal that disagreed with the winding would be a second
            # claim about the same fact for a reader to choose between.
            lines.append("  facet normal 0 0 0")
            lines.append("    outer loop")
            for corner in triangle:
                lines.append(
                    f"      vertex {_format(corner[0])} {_format(corner[1])} {_format(corner[2])}"
                )
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append(f"endsolid {name}")

    scratch = target.with_name(f".{target.name}.partial")
    scratch.write_text("\n".join(lines) + "\n", encoding="utf-8")
    scratch.replace(target)

    log_event(
        _log,
        Event.CASE_WRITE,
        case=str(surface.parent),
        action="name_regions",
        regions=len(grouped),
        triangles=len(triangles),
    )
    return target
