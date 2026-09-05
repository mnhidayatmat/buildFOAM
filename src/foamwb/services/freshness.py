"""Whether a case's outputs are older than the inputs they came from (DEC-22).

Ansys Workbench's Project Schematic marks a cell **⚡ Update Required** when
something upstream of it has changed since it was last computed, and propagates
that mark downstream. It is the single most useful thing that interface does,
because it answers a question a user cannot answer themselves: *given everything
I have edited, what is no longer true?* Without it a green tick means only "this
happened once", and the commonest way to get a wrong CFD answer is to trust a
result that was computed from a case you have since edited.

This module is the evidence for that mark. It compares modification times, not
contents:

**Times, not hashes.** A hash of every definition file is what
:meth:`CaseService.tree_hash` already computes, and it costs a full read of the
case — on a meshed case that is the whole of ``constant/polyMesh``. This runs on
every save (NFR-P7), so it stats files rather than reading them. The cost of the
weaker test is a false *fresh* when a file is rewritten with identical bytes,
which is the harmless direction: it under-reports rather than crying wolf.

**Two artefacts, not a general graph.** A case has exactly two things that are
computed from other things — the mesh and the results — so a dependency engine
would be machinery with two entries in it. Which *outline nodes* those two facts
mark is :mod:`foamwb.services.workflow`'s business, which is also why this module
knows nothing about nodes: the outline imports freshness, so freshness must not
import the outline.

**The reason travels with the fact.** Workbench tells you a cell needs updating
and not why. A user who has edited four files wants to know which one did it, so
every stale verdict names the file that made it stale.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from foamwb.services.case import is_definition_file
from foamwb.services.mesh import UTILITIES

__all__ = ["Freshness", "assess", "mesh_inputs"]

#: Where a generated mesh lands.
MESH_DIR = ("constant", "polyMesh")

#: Surfaces the meshing utilities read. Not a dictionary, so it is not in any
#: utility's ``needs``, but ``snappyHexMesh`` meshes *around* it — editing or
#: re-importing a surface is the most direct way there is to invalidate a mesh.
SURFACE_DIR = ("constant", "triSurface")

#: Time directories that are *inputs* rather than results. ``0`` is where the
#: solver starts, not something it wrote.
INITIAL_TIMES = frozenset({"0", "0.orig"})


@dataclass(frozen=True, slots=True)
class Freshness:
    """What exists, and what is older than what it came from."""

    has_mesh: bool = False
    has_results: bool = False

    mesh_written_at: float = 0.0
    """When the mesh was last written, as a timestamp, or 0.0 for no mesh.

    Exposed because "has the mesh changed since I drew it?" needs an exact
    answer: the Mesh document re-reads only when this moves, so an ordinary save
    does not throw away the angle the user turned the model to (DEC-23)."""

    results_written_at: float = 0.0

    mesh_stale_because: str = ""
    """Relative path of the newest input that postdates the mesh, or empty.

    A path rather than a flag, because "the mesh needs rebuilding" and
    "``system/blockMeshDict`` changed after the mesh was built" are the same
    fact and only one of them can be acted on.
    """

    results_stale_because: str = ""

    @property
    def mesh_is_stale(self) -> bool:
        return bool(self.mesh_stale_because)

    @property
    def results_are_stale(self) -> bool:
        return bool(self.results_stale_because)

    @property
    def anything_to_do(self) -> bool:
        """Whether *Update* would run anything at all."""
        return (
            not self.has_mesh
            or not self.has_results
            or self.mesh_is_stale
            or self.results_are_stale
        )


def mesh_inputs(case: Path) -> Iterator[Path]:
    """Every file a generated mesh is built from.

    Taken from the meshing utilities' own declared ``needs`` rather than listed
    again here, so a utility added to :data:`~foamwb.services.mesh.UTILITIES`
    brings its dictionary with it. A second list would drift, and the symptom
    would be a mesh that stayed green after the dictionary that built it was
    edited.

    Deliberately narrow. ``system/controlDict`` is not a mesh input, and marking
    the mesh stale because the end time changed would train the user to ignore
    the mark — which costs more than the occasional miss.
    """
    for utility in UTILITIES:
        if not utility.chain:
            continue
        for relative in utility.needs:
            candidate = case / relative
            if candidate.is_file():
                yield candidate

    surfaces = case.joinpath(*SURFACE_DIR)
    if surfaces.is_dir():
        yield from (p for p in surfaces.rglob("*") if p.is_file())


def _run_inputs(case: Path) -> Iterator[Path]:
    """Every file the solver reads: the whole case definition, mesh included.

    Broad on purpose, and the opposite call from :func:`mesh_inputs`. A solver
    reads its schemes, its solvers, its physical properties, its boundary
    conditions and its mesh, and there is no entry among them whose change
    leaves the answer untouched. Anything excluded here would be a silent
    promise that editing that file does not invalidate the result.
    """
    for path in case.rglob("*"):
        if path.is_file() and not path.is_symlink() and is_definition_file(case, path):
            yield path


def _result_dirs(case: Path) -> Iterator[Path]:
    """Written time directories — the solver's output, not its input."""
    for path in case.iterdir():
        if not path.is_dir() or path.name in INITIAL_TIMES:
            continue
        try:
            float(path.name)
        except ValueError:
            continue
        yield path


def _written_at(paths: Iterable[Path]) -> float | None:
    """The newest modification time among these, or ``None`` for none of them."""
    newest: float | None = None
    for path in paths:
        try:
            stamp = path.stat().st_mtime
        except OSError:  # pragma: no cover - a file that vanished mid-walk
            continue
        if newest is None or stamp > newest:
            newest = stamp
    return newest


def _newest_after(case: Path, paths: Iterable[Path], written_at: float) -> str:
    """The newest input that postdates ``written_at``, as a relative path.

    Strictly newer. A file written in the same second as the output it feeds is
    the ordinary case for a mesh whose dictionary was generated moments before
    it, and calling that stale would leave a mark nothing could clear.
    """
    found: tuple[float, Path] | None = None
    for path in paths:
        try:
            stamp = path.stat().st_mtime
        except OSError:  # pragma: no cover - a file that vanished mid-walk
            continue
        if stamp > written_at and (found is None or stamp > found[0]):
            found = (stamp, path)
    if found is None:
        return ""
    try:
        return found[1].relative_to(case).as_posix()
    except ValueError:  # pragma: no cover - every candidate is under the case
        return found[1].name


def assess(case: Path | None) -> Freshness:
    """Read the case and report what is out of date.

    Never raises. This decides a marker in a tree and an enabled state on a
    button; a case that cannot be walked has larger problems, and they are
    reported by the views that exist to report them rather than by an exception
    thrown while drawing the outline.
    """
    if case is None:
        return Freshness()

    try:
        mesh_files = [p for p in case.joinpath(*MESH_DIR).rglob("*") if p.is_file()]
    except OSError:  # pragma: no cover - unreadable case directory
        return Freshness()

    mesh_written = _written_at(mesh_files)
    has_mesh = mesh_written is not None

    try:
        result_files = [p for d in _result_dirs(case) for p in d.rglob("*") if p.is_file()]
    except OSError:  # pragma: no cover - unreadable case directory
        result_files = []
    results_written = _written_at(result_files)
    has_results = results_written is not None

    mesh_because = ""
    if has_mesh:
        mesh_because = _newest_after(case, mesh_inputs(case), mesh_written)

    results_because = ""
    if has_results:
        results_because = _newest_after(case, _run_inputs(case), results_written)

    return Freshness(
        has_mesh=has_mesh,
        has_results=has_results,
        mesh_written_at=mesh_written or 0.0,
        results_written_at=results_written or 0.0,
        mesh_stale_because=mesh_because,
        results_stale_because=results_because,
    )
