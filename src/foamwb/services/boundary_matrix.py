"""The patch x field boundary-condition matrix (FR-P4, FR-C3, E-C03, E-C04).

§1.2 names boundary-condition and patch mismatches "the single most common
beginner failure", and §7.4 answers it with a matrix: rows are the patches the
mesh declares, columns are the fields in ``0/``, and every cell shows the
condition in force. An empty cell is an error, not a blank.

The shape is the point. A student's failure is almost never "I wrote the wrong
type" — it is "I did not notice that `p` has no entry for the patch I added",
which a per-file editor hides and a grid makes obvious at a glance.

Two constraints are checked, and both are things OpenFOAM will otherwise report
as a cryptic runtime failure long after the mistake was made:

* **Missing entries** (E-C03). Every patch needs an entry in every field, unless
  a regex or ``.*`` default covers it.
* **Constrained patch types** (E-C04). An ``empty`` patch must carry the
  ``empty`` condition; the same holds for ``symmetry``, ``wedge`` and ``cyclic``.
  A 2D case whose front and back carry a real condition is silently solving a
  different problem, and nothing in the output says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from foamwb.codes import ErrorCode, Severity
from foamwb.services.boundary import Patch, read_boundary
from foamwb.services.case import Case, Finding
from foamwb.services.foamdict import Document, NodeKind, ParseError

__all__ = ["BoundaryMatrix", "Cell", "read_matrix"]

#: Files under ``0/`` that are not fields. ``include`` holds shared fragments
#: pulled in with ``#include``; the rest are editor and archive litter.
_NOT_FIELDS = frozenset({"include", "README", "README.md", ".DS_Store"})


@dataclass(frozen=True, slots=True)
class Cell:
    """One patch's boundary condition in one field."""

    patch: str
    field_name: str
    condition: str | None = None
    """The ``type`` in force, or ``None`` when nothing covers this patch."""

    matched_by: str | None = None
    """The key that supplied it — the patch name, or the regex that matched.

    Recorded because a value arriving through ``".*"`` is a different fact from
    one written for the patch: the user may not know the default is there, and it
    is the first thing to look at when a patch behaves unexpectedly.
    """

    @property
    def is_default(self) -> bool:
        return self.matched_by is not None and self.matched_by != self.patch

    @property
    def is_missing(self) -> bool:
        return self.condition is None


@dataclass(slots=True)
class BoundaryMatrix:
    """Every patch against every field, plus what is wrong with it."""

    patches: list[Patch] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    @property
    def is_meshed(self) -> bool:
        """Whether a mesh exists to build rows from.

        An unmeshed case is the ordinary state of a fresh import, not a fault:
        the view says the mesh is needed rather than reporting an error the user
        cannot act on.
        """
        return bool(self.patches)

    def cell(self, patch: str, field_name: str) -> Cell | None:
        return self.cells.get((patch, field_name))

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.blocks_run]

    def missing(self) -> list[Cell]:
        return [c for c in self.cells.values() if c.is_missing]


def field_files(case: Path) -> list[Path]:
    """Field files in the initial-condition directory, in name order.

    ``0.orig`` is read when there is no ``0``, so the matrix works on a freshly
    imported tutorial — the majority ship that way — rather than only after a run
    has been prepared.
    """
    for name in ("0", "0.orig"):
        directory = case / name
        if directory.is_dir():
            return sorted(
                entry
                for entry in directory.iterdir()
                if entry.is_file()
                and entry.name not in _NOT_FIELDS
                and not entry.name.startswith(".")
            )
    return []


def read_matrix(case: Case) -> BoundaryMatrix:
    """Build the matrix for a case, with its findings (FR-P4, FR-C3)."""
    patches = read_boundary(case.path)
    matrix = BoundaryMatrix(patches=patches)

    for source in field_files(case.path):
        try:
            document = Document.parse_bytes(source.read_bytes())
        except ParseError as exc:
            # The field still appears as a column: it exists, and hiding it would
            # make the matrix disagree with the file tree beside it. The finding
            # says why its cells are blank.
            matrix.fields.append(source.name)
            matrix.findings.append(
                Finding(
                    code=ErrorCode.PARSE_ERROR,
                    severity=Severity.ERROR,
                    file=source,
                    line=exc.line,
                    column=exc.column,
                    detail=exc.message,
                )
            )
            continue

        matrix.fields.append(source.name)
        _read_field(matrix, source, document, patches)

    return matrix


def _read_field(
    matrix: BoundaryMatrix, source: Path, document: Document, patches: list[Patch]
) -> None:
    entries = _boundary_entries(document)

    for patch in patches:
        key, condition = _lookup(entries, patch.name)
        matrix.cells[(patch.name, source.name)] = Cell(
            patch=patch.name,
            field_name=source.name,
            condition=condition,
            matched_by=key,
        )

        if condition is None:
            matrix.findings.append(
                Finding(
                    code=ErrorCode.MISSING_BOUNDARY_FIELD,
                    severity=Severity.ERROR,
                    file=source,
                    detail=(
                        f"Patch {patch.name!r} has no boundaryField entry in "
                        f"{source.name}, so the solver has nothing to apply there."
                    ),
                )
            )
            continue

        required = patch.required_condition
        if required is not None and condition != required:
            matrix.findings.append(
                Finding(
                    code=ErrorCode.PATCH_BC_INCOMPATIBLE,
                    severity=Severity.ERROR,
                    file=source,
                    detail=(
                        f"Patch {patch.name!r} is of type {patch.type!r}, which "
                        f"requires the {required!r} boundary condition, but "
                        f"{source.name} sets {condition!r}."
                    ),
                )
            )


def _boundary_entries(document: Document) -> list[tuple[str, str | None]]:
    """``(key, type)`` for each entry under ``boundaryField``, in file order.

    Order matters: OpenFOAM applies the *last* matching key, so a later ``".*"``
    overrides an earlier explicit patch entry. Resolving in the wrong order would
    show a value the solver does not use.
    """
    node = document.find("boundaryField")
    if node is None:
        return []
    return [
        (child.keyword, document.get(f"boundaryField/{child.keyword}/type"))
        for child in node.children
        if child.keyword is not None and child.kind is NodeKind.DICT
    ]


def _lookup(entries: list[tuple[str, str | None]], patch: str) -> tuple[str | None, str | None]:
    """Resolve a patch against the entries, honouring regex keys.

    OpenFOAM matches a key as a regular expression when it contains regex
    metacharacters, which is how ``".*"`` and ``"(inlet|outlet)"`` work. The last
    match wins, matching the solver.
    """
    found_key: str | None = None
    found_condition: str | None = None

    for key, condition in entries:
        if key == patch or (_is_pattern(key) and _matches(key, patch)):
            found_key, found_condition = key, condition
    return found_key, found_condition


_METACHARACTERS = re.compile(r"[.*+?\[\]()|^$\\]")


def _is_pattern(key: str) -> bool:
    return bool(_METACHARACTERS.search(key))


def _matches(pattern: str, patch: str) -> bool:
    try:
        return re.fullmatch(pattern, patch) is not None
    except re.error:
        # A key that looks like a pattern but is not a valid one is treated as a
        # literal, which is what a user who wrote it by hand meant.
        return False
