"""Whole-case validation (FR-C3, §7.4's validation panel).

Collects findings from every source that has one — schema checks on the
dictionaries it models, and the boundary matrix — into a single list ordered so
that the thing to fix first appears first.

Kept separate from :class:`~foamwb.services.case.CaseService` because validation
composes services that both depend on it: the schema layer and the boundary
matrix each need a parsed case, and having the case open itself validate would
make that circular.

**Findings never block opening.** §7.4 puts the panel beside the editor precisely
so a user can see what is wrong *while* fixing it; a case that refused to open
until it was valid would be unfixable in the application (FR-C2, §7.9 rule 1).
"""

from __future__ import annotations

from pathlib import Path

from foamwb.codes import ErrorCode, Severity
from foamwb.services.boundary_matrix import BoundaryMatrix, read_matrix
from foamwb.services.case import Case, Finding
from foamwb.services.foamdict import Document, ParseError
from foamwb.services.schema import available_schemas, load_schema, validate_document

__all__ = ["Validation", "validate_case"]


class Validation:
    """Everything wrong with a case, and the matrix that produced some of it."""

    def __init__(self, findings: list[Finding], matrix: BoundaryMatrix) -> None:
        self._findings = findings
        self.matrix = matrix

    @property
    def findings(self) -> list[Finding]:
        """Ordered worst-first, then by file.

        Severity leads because a run blocked by an error is not helped by a list
        that opens with three cosmetic warnings.
        """
        return sorted(self._findings, key=lambda f: (-int(f.severity), str(f.file), f.line or 0))

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocks_run]

    @property
    def is_runnable(self) -> bool:
        return not self.blocking


def validate_case(case: Case) -> Validation:
    """Validate a case (FR-C3).

    Findings carry file, severity and — where the parser could supply one — a
    line, so the panel can be clicked through to the offending place rather than
    reporting that something, somewhere, is wrong.
    """
    findings: list[Finding] = list(case.findings)

    for name in available_schemas():
        schema = load_schema(name)
        if schema is None:  # pragma: no cover - available_schemas only lists real ones
            continue
        source = case.path / schema.file
        if not source.is_file():
            continue
        findings.extend(_check(schema_name=name, source=source))

    findings.extend(_missing_initial_fields(case))

    matrix = read_matrix(case)
    findings.extend(matrix.findings)
    return Validation(findings, matrix)


#: Solver-block keys that are settings for a field already listed, not fields of
#: their own. ``pFinal`` tunes the last PISO corrector for ``p``.
_FINAL_SUFFIX = "Final"

#: Characters that make a solver key a *pattern* rather than a name.
_PATTERN_CHARS = frozenset('(|)*[]?^$\\"')


def _missing_initial_fields(case: Case) -> list[Finding]:
    """Fields ``fvSolution`` solves for that have no file in ``0`` (E-C08).

    The gap this closes is the one that matters most: deleting ``0/p`` used to
    produce no finding at all, so the check reported "this case can run" about a
    case that stops before its first timestep. A check that misses the failure it
    exists to catch is worse than no check (§7.9 rule 6).

    **Only unambiguous names are checked.** Real solver blocks are full of
    patterns — ``(U|k|epsilon|omega|f|v2)`` is a catch-all that ``pitzDaily``
    only half satisfies, and requiring every alternative would report a healthy
    case as broken. Patterns are skipped, which makes this check modest and
    never wrong; a false alarm here would teach users to ignore the panel.
    """
    source = case.path / "system" / "fvSolution"
    if not source.is_file():
        return []

    try:
        document = Document.parse_bytes(source.read_bytes())
    except (OSError, ParseError):
        return []

    directory = next(
        (case.path / name for name in ("0", "0.orig") if (case.path / name).is_dir()), None
    )
    if directory is None:
        return []

    # A multi-region case keeps a solvers block per region, so the top-level
    # fvSolution has none at all — `multiRegionHeater` is the case in point, and
    # `keys` raises rather than returning empty for a path that is not there.
    if not document.has("solvers"):
        return []

    findings: list[Finding] = []
    for key in document.keys("solvers"):
        if _PATTERN_CHARS & set(key) or key.endswith(_FINAL_SUFFIX):
            continue
        if not (directory / key).is_file():
            findings.append(
                Finding(
                    code=ErrorCode.MISSING_INITIAL_FIELD,
                    severity=Severity.ERROR,
                    file=Path(directory.name) / key,
                    detail=(
                        f"system/fvSolution solves for {key}, but {directory.name}/{key} "
                        "does not exist. The solver stops before its first timestep."
                    ),
                )
            )
    return findings


def _check(*, schema_name: str, source: Path) -> list[Finding]:
    schema = load_schema(schema_name)
    assert schema is not None
    try:
        document = Document.parse_bytes(source.read_bytes())
    except ParseError:
        # Already reported by CaseService.open for controlDict, and a file that
        # cannot be parsed cannot be schema-checked. Reporting it twice would
        # pad the panel without adding a fact.
        return []
    return validate_document(schema, document, source)
