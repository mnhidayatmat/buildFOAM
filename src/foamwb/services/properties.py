"""Turning a case's dictionaries into property rows (§7.4).

Qt-free, so the mapping from *workflow step* to *what the property panel shows*
is testable headlessly and could equally drive a CLI (NFR-M1). The widget renders
these; it decides nothing about them.

**Every row carries the path it writes back to.** The panel shows "End time" and
saves ``endTime``; the two can never drift because they are the same object. This
is what lets FR-P7 hold through the panel: a value edited here goes through
:meth:`Document.set`, which touches one entry and leaves every other byte alone.

**Entries the schema does not describe are shown, marked, and not editable
here.** A form that quietly dropped them would let a user believe they had seen
their whole file. They are editable in the Text tab, where the full file is
visible and there is no pretence of understanding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from foamwb.services.foamdict import Document, ParseError
from foamwb.services.schema import Schema, load_schema

#: Not settings. ``FoamFile`` is the format header every dictionary carries —
#: showing it as a parameter would put the same four rows of file metadata at the
#: top of every panel, and none of them is something the user sets.
NOT_SETTINGS: frozenset[str] = frozenset({"FoamFile"})

__all__ = [
    "STEP_SOURCES",
    "PropertyGroup",
    "PropertyRow",
    "groups_for_step",
    "rows_from_document",
]


@dataclass(frozen=True, slots=True)
class PropertyRow:
    """One parameter, as the panel shows it."""

    path: str
    """The dictionary path this writes back to, e.g. ``ddtSchemes/default``."""

    label: str
    value: str = ""
    unit: str = ""
    description: str = ""
    depth: int = 0
    editable: bool = True
    unknown: bool = False
    """Present in the file but not described by any schema — shown and marked."""


@dataclass(frozen=True, slots=True)
class PropertyGroup:
    """A set of rows that came from one file."""

    title: str
    source: str = ""
    """The file, named so the user learns the mapping rather than the interface."""

    rows: tuple[PropertyRow, ...] = field(default_factory=tuple)
    missing: bool = False
    """The file the group describes is not in this case. Said plainly, because
    an empty group and an absent file mean different things to the user."""


#: Which files each workflow step is about. The step names are the ones a course
#: uses; the files are the ones OpenFOAM has. Keeping the mapping here — as data,
#: in one place — is what lets the navigation be renamed without hunting through
#: widgets for hard-coded filenames.
STEP_SOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    # step id -> ((relative path, schema name), ...)
    "conditions.basic": (("system/controlDict", "controlDict"),),
    "conditions.control": (
        ("system/fvSchemes", "fvSchemes"),
        ("system/fvSolution", "fvSolution"),
    ),
    "mesh.settings": (("system/blockMeshDict", "blockMeshDict"),),
    "conditions.output": (("system/controlDict", "controlDict"),),
}


def rows_from_document(
    document: Document,
    schema: Schema | None,
    *,
    include_unknown: bool = True,
) -> tuple[PropertyRow, ...]:
    """Build rows for one parsed dictionary.

    Schema order first, then anything else the file contains. Schema order is
    not alphabetical and not file order: it is the order the settings are
    usually reasoned about, which is the only one that helps someone learning.
    """
    rows: list[PropertyRow] = []
    described: set[str] = set()

    for entry in schema.fields if schema is not None else ():
        described.add(entry.key)
        if not document.has(entry.key):
            continue
        rows.append(
            PropertyRow(
                path=entry.key,
                label=entry.title,
                value=document.get(entry.key) or "",
                unit=entry.unit,
                description=entry.help,
                depth=entry.key.count("/"),
            )
        )

    if include_unknown:
        # Not a mapping: Document.keys() walks the dictionary and returns
        # paths like ddtSchemes/default. Dropping the call would iterate
        # something else entirely.
        for key in document.keys():  # noqa: SIM118
            if key in described or key.split("/", 1)[0] in NOT_SETTINGS:
                continue
            rows.append(
                PropertyRow(
                    path=key,
                    label=key.rsplit("/", 1)[-1],
                    value=document.get(key) or "",
                    depth=key.count("/"),
                    editable=False,
                    unknown=True,
                )
            )

    return tuple(rows)


def groups_for_step(case: Path | None, step_id: str) -> tuple[PropertyGroup, ...]:
    """What the property panel shows for a workflow step.

    An unreadable file produces a group that says so rather than an empty one:
    "this file could not be parsed" and "this file has no settings" are different
    problems and only one of them is the user's to fix.
    """
    if case is None:
        return ()

    sources = STEP_SOURCES.get(step_id, ())
    groups: list[PropertyGroup] = []

    for relative, schema_name in sources:
        path = case / relative
        title = relative.rsplit("/", 1)[-1]

        if not path.is_file():
            groups.append(PropertyGroup(title=title, source=relative, missing=True))
            continue

        try:
            document = Document.parse_bytes(path.read_bytes())
        except (OSError, ParseError):
            groups.append(PropertyGroup(title=title, source=relative, missing=True))
            continue

        schema = load_schema(schema_name) if schema_name else None
        groups.append(
            PropertyGroup(
                title=title,
                source=relative,
                rows=rows_from_document(document, schema),
            )
        )

    return tuple(groups)
