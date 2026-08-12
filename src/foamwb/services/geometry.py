"""Bringing a geometry file into a case as a meshable surface (FR-P3, NG1).

``snappyHexMesh`` meshes *around* a triangulated surface held in
``constant/triSurface``. Getting a model into that directory, in a form the
mesher can read, is the whole job here — NG1 is explicit that this product does
not draw geometry, only import it.

**What the mesher can actually read decides the shape of this module.** OpenFOAM
reads STL and OBJ. Everything else divides into formats a geometry kernel can
tessellate for us (STEP, IGES, BREP — see :mod:`foamwb.services.cad`) and
formats nothing available can open, which are native CAD documents like
``.sldprt`` or ``.catpart``. Those three cases are genuinely different and each
gets its own §9 code, because "import failed" tells a user nothing about whether
the answer is to install a converter, to re-export from their CAD package, or
that the file was never geometry in the first place.

**An imported surface is inspected, not trusted.** A file with the ``.stl``
suffix may be an HTML error page a browser saved, an ASCII file truncated
mid-facet, or a valid surface whose units are millimetres when the case is in
metres. The first two are refused here; the third cannot be — no file states its
units — so the bounding box is reported instead, because a user who sees
``2400 × 900 × 1500`` knows immediately that their car is in millimetres.

**Nothing here is fenced, and that is deliberate.** NFR-C3's fence exists for the
case where the application edits a file the *user* wrote, which is why
``controlDict`` gets comment markers. An imported surface is a new file that
exists because the user asked for it, in a directory whose whole purpose is to
hold it; deleting it is already the complete reversal, and there is no
surrounding content of the user's to keep separate. Binary STL could not carry a
comment fence in any case.
"""

from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.cad import CadConverter, needs_conversion

__all__ = [
    "TRISURFACE_DIR",
    "GeometryError",
    "Surface",
    "SurfaceFormat",
    "classify",
    "existing_surfaces",
    "import_geometry",
    "inspect_surface",
]

_log = get_logger("geometry")

#: Where OpenFOAM expects a case's surfaces to live, relative to the case root.
TRISURFACE_DIR = Path("constant") / "triSurface"

#: The binary STL layout: an 80-byte header, a uint32 triangle count, then 50
#: bytes per triangle. Named because the file-size identity built from these is
#: the only reliable way to tell binary from ASCII.
_BINARY_HEADER = 84
_BINARY_TRIANGLE = 50


class SurfaceFormat(StrEnum):
    """What a file is, in terms of what has to happen to it."""

    STL = "stl"
    OBJ = "obj"
    """Read by OpenFOAM directly; importing is a copy."""

    CAD = "cad"
    """An exchange format a kernel can tessellate for us."""

    UNSUPPORTED = "unsupported"
    """Nothing available can open it. Usually a native CAD document."""


#: Suffixes OpenFOAM's surface handling reads without help.
_NATIVE = {".stl": SurfaceFormat.STL, ".obj": SurfaceFormat.OBJ}


class GeometryError(ValueError):
    """An import that cannot proceed, carrying its §9 code (FR-G2)."""

    def __init__(self, message: str, code: Code, path: Path) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class Surface:
    """A surface file and what could be established about it."""

    path: Path
    surface_format: SurfaceFormat
    triangles: int = 0
    is_binary: bool = False
    solids: tuple[str, ...] = ()
    """Named regions inside the file.

    Worth carrying because ``snappyHexMesh`` refines per region: a single STL
    holding ``inlet``, ``outlet`` and ``body`` can be given three different
    refinement levels, and a user who does not know the names cannot ask for
    that."""

    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    """Minimum and maximum corner, or ``None`` when the file held no vertices."""

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size(self) -> tuple[float, float, float] | None:
        """Extent along each axis, in whatever units the file used."""
        if self.bounds is None:
            return None
        low, high = self.bounds
        return (high[0] - low[0], high[1] - low[1], high[2] - low[2])


def classify(path: Path) -> SurfaceFormat:
    """What kind of file this is, by suffix.

    By suffix rather than by content because the answer decides which *reader* to
    try, and every reader here needs to know the format before it can open the
    file. Content is checked immediately afterwards by :func:`inspect_surface`,
    which is what catches a file whose suffix was a lie.
    """
    suffix = path.suffix.lower()
    if suffix in _NATIVE:
        return _NATIVE[suffix]
    if needs_conversion(path):
        return SurfaceFormat.CAD
    return SurfaceFormat.UNSUPPORTED


def inspect_surface(path: Path) -> Surface:
    """Read a native surface and report what is in it.

    Raises :class:`GeometryError` if the file is not a surface at all. This is
    the check that stops a truncated download or a saved error page from
    reaching ``snappyHexMesh``, which reports such a file as a meshing failure
    several minutes into a run.
    """
    if not path.is_file():
        raise GeometryError(f"{path.name} does not exist", ErrorCode.GEOMETRY_UNREADABLE, path)
    if path.stat().st_size == 0:
        raise GeometryError(f"{path.name} is empty", ErrorCode.GEOMETRY_UNREADABLE, path)

    surface_format = classify(path)
    if surface_format is SurfaceFormat.OBJ:
        return _inspect_obj(path)
    if surface_format is SurfaceFormat.STL:
        return _inspect_stl(path)
    raise GeometryError(f"{path.name} is not a surface file", ErrorCode.GEOMETRY_UNSUPPORTED, path)


def _is_binary_stl(path: Path) -> bool:
    """Decide by arithmetic, not by the leading keyword.

    A binary STL's 80-byte header is arbitrary text, and exporters exist that
    begin it with the word ``solid`` — so the usual "does it start with solid"
    test reports a binary file as ASCII and every subsequent read produces
    nonsense. The triangle count at offset 80 has to account for the file's
    exact length, which no ASCII file does by coincidence.
    """
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


def _inspect_stl(path: Path) -> Surface:
    return _inspect_binary_stl(path) if _is_binary_stl(path) else _inspect_ascii_stl(path)


def _inspect_binary_stl(path: Path) -> Surface:
    with path.open("rb") as handle:
        handle.seek(80)
        (count,) = struct.unpack("<I", handle.read(4))
        tracker = _Bounds()
        for _ in range(count):
            block = handle.read(_BINARY_TRIANGLE)
            if len(block) < _BINARY_TRIANGLE:
                raise GeometryError(
                    f"{path.name} ends part-way through a facet",
                    ErrorCode.GEOMETRY_UNREADABLE,
                    path,
                )
            # 12 floats: a normal we ignore, then the three corners.
            values = struct.unpack("<12f", block[:48])
            for index in (3, 6, 9):
                tracker.add(values[index], values[index + 1], values[index + 2])
    # Binary STL has no region names; the format simply cannot express them.
    return Surface(
        path=path,
        surface_format=SurfaceFormat.STL,
        triangles=count,
        is_binary=True,
        bounds=tracker.result(),
    )


def _inspect_ascii_stl(path: Path) -> Surface:
    triangles = 0
    solids: list[str] = []
    tracker = _Bounds()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith("facet"):
                triangles += 1
            elif stripped.startswith("solid"):
                name = stripped[5:].strip()
                if name:
                    solids.append(name)
            elif stripped.startswith("vertex"):
                tracker.add_text(stripped.split()[1:4], path)

    if triangles == 0:
        # A file claiming to be STL with no facet in it is not a surface. Most
        # often it is an HTML error page a browser saved under the right name.
        raise GeometryError(
            f"{path.name} contains no triangles", ErrorCode.GEOMETRY_UNREADABLE, path
        )
    return Surface(
        path=path,
        surface_format=SurfaceFormat.STL,
        triangles=triangles,
        is_binary=False,
        solids=tuple(solids),
        bounds=tracker.result(),
    )


def _inspect_obj(path: Path) -> Surface:
    faces = 0
    groups: list[str] = []
    tracker = _Bounds()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "f":
                faces += 1
            elif parts[0] == "v" and len(parts) >= 4:
                tracker.add_text(parts[1:4], path)
            elif parts[0] in {"g", "o"} and len(parts) >= 2:
                groups.append(parts[1])

    if faces == 0:
        raise GeometryError(f"{path.name} contains no faces", ErrorCode.GEOMETRY_UNREADABLE, path)
    return Surface(
        path=path,
        surface_format=SurfaceFormat.OBJ,
        triangles=faces,
        solids=tuple(groups),
        bounds=tracker.result(),
    )


class _Bounds:
    """Accumulates a bounding box without holding the vertices.

    Streaming because a detailed surface runs to millions of triangles, and
    keeping them to compute two corners would cost hundreds of megabytes to
    answer a question that needs six numbers.
    """

    __slots__ = ("_high", "_low")

    def __init__(self) -> None:
        self._low: list[float] | None = None
        self._high: list[float] | None = None

    def add(self, x: float, y: float, z: float) -> None:
        point = [x, y, z]
        if self._low is None or self._high is None:
            self._low, self._high = list(point), list(point)
            return
        for axis in range(3):
            self._low[axis] = min(self._low[axis], point[axis])
            self._high[axis] = max(self._high[axis], point[axis])

    def add_text(self, parts: list[str], path: Path) -> None:
        try:
            x, y, z = (float(value) for value in parts)
        except ValueError as exc:
            raise GeometryError(
                f"{path.name} has a vertex that is not a number",
                ErrorCode.GEOMETRY_UNREADABLE,
                path,
            ) from exc
        self.add(x, y, z)

    def result(self):
        if self._low is None or self._high is None:
            return None
        return (tuple(self._low), tuple(self._high))


def existing_surfaces(case: Path) -> list[Surface]:
    """Every surface already in the case, in name order.

    A file that cannot be read is *listed* rather than omitted, with zero
    triangles: it is in the directory, ``snappyHexMesh`` will try to read it, and
    hiding it would leave the user unable to find the thing that is about to
    break their mesh.
    """
    directory = case / TRISURFACE_DIR
    if not directory.is_dir():
        return []

    found: list[Surface] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or classify(path) not in {SurfaceFormat.STL, SurfaceFormat.OBJ}:
            continue
        try:
            found.append(inspect_surface(path))
        except GeometryError:
            found.append(Surface(path=path, surface_format=classify(path)))
    return found


def _free_name(directory: Path, stem: str, suffix: str) -> Path:
    """A target that does not overwrite something already imported.

    Disambiguated rather than refused. Importing a second revision of the same
    part is a normal thing to do, and an error saying "that name is taken" would
    leave the user renaming files in a file manager to get past it.
    """
    candidate = directory / f"{stem}{suffix}"
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def import_geometry(
    case: Path,
    source: Path,
    *,
    converter: CadConverter | None = None,
    max_element: float | None = None,
) -> Surface:
    """Bring ``source`` into ``case`` as a meshable surface, and describe it.

    STL and OBJ are copied. CAD exchange formats are tessellated first, and the
    STL that comes out is what lands in the case — so what ``snappyHexMesh``
    reads is always something this application has already inspected.

    Every failure carries a §9 code, because the remedies are different: E-C10
    means re-export from the CAD package, E-C11 means install a converter, E-C12
    means the model itself defeated the kernel.
    """
    if not source.is_file():
        raise GeometryError(f"{source.name} does not exist", ErrorCode.GEOMETRY_UNREADABLE, source)

    kind = classify(source)
    if kind is SurfaceFormat.UNSUPPORTED:
        raise GeometryError(
            f"{source.suffix or source.name} is not a format OpenFOAM can mesh",
            ErrorCode.GEOMETRY_UNSUPPORTED,
            source,
        )

    directory = case / TRISURFACE_DIR
    directory.mkdir(parents=True, exist_ok=True)

    if kind is SurfaceFormat.CAD:
        target = _convert(source, directory, converter, max_element)
    else:
        # Inspected before it is copied, so a file that turns out not to be a
        # surface never reaches the case at all — there is nothing to undo.
        inspect_surface(source)
        target = _free_name(directory, source.stem, source.suffix.lower())
        shutil.copy2(source, target)

    surface = inspect_surface(target)
    log_event(
        _log,
        Event.CASE_WRITE,
        case=str(case),
        action="import_geometry",
        triangles=surface.triangles,
    )
    return surface


def _convert(
    source: Path,
    directory: Path,
    converter: CadConverter | None,
    max_element: float | None,
) -> Path:
    """Tessellate CAD into the case, or say precisely why it could not be."""
    converter = converter or CadConverter()
    tool = converter.locate()
    if tool is None:
        raise GeometryError(
            f"{source.name} needs a CAD converter, and none is installed",
            ErrorCode.CAD_CONVERTER_MISSING,
            source,
        )

    target = _free_name(directory, source.stem, ".stl")
    result = converter.convert(source, target, tool=tool, max_element=max_element)
    if not result.ok:
        # A partial surface must not be left behind: it would be listed as an
        # importable surface and meshed against, and it is not the model.
        target.unlink(missing_ok=True)
        detail = result.detail or "the converter reported no reason"
        raise GeometryError(
            f"{source.name} could not be converted: {detail}",
            ErrorCode.CAD_CONVERSION_FAILED,
            source,
        )
    return target
