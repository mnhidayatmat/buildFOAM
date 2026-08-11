"""The dictionary schema layer (§5.4, FR-P1, FR-C3).

"Form editors are driven by declarative schema files, not hand-written widgets.
Adding support for a new OpenFOAM version is therefore predominantly a data
change, not a code change."

That promise only holds if nothing version- or dictionary-specific leaks into
Python, which is what ``tools/check_version_literals.py`` enforces. This module
is the reader: it knows about *kinds* of field — enum, scalar, bool — and nothing
at all about ``controlDict``.

**A schema says what the form can edit, never what a file may contain.** §5.4 is
explicit that any key present in the file but absent from the schema is preserved
untouched and shown in the raw-text tab (FR-P6). So validation reports on the
keys it knows and is silent about the rest: a case using a solver-specific entry
this build has never heard of is a normal case, not a broken one, and a validator
that flagged it would be training users to ignore it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from foamwb.codes import ErrorCode, Severity
from foamwb.services.case import Finding
from foamwb.services.foamdict import Document, PathError

__all__ = ["Field", "FieldKind", "Schema", "load_schema", "validate_document"]

#: OpenFOAM's boolean spellings. It writes ``yes``/``no``; ``true``/``false`` and
#: ``on``/``off`` are accepted aliases that appear in real cases.
_TRUE = frozenset({"yes", "true", "on", "1"})
_FALSE = frozenset({"no", "false", "off", "0"})


class SchemaError(ValueError):
    """A schema file that cannot be used."""


class FieldKind(StrEnum):
    """What a field holds, and therefore how it is edited and checked."""

    WORD = "word"
    """A bare identifier — a solver name, a boundary-condition type."""

    TEXT = "text"
    """A free value that may contain spaces.

    Needed because a discretisation scheme is a *phrase*: ``Gauss linear
    corrected``, ``bounded Gauss linearUpwind grad(U)``. Rejecting spaces here —
    as :data:`WORD` does — would make every fvSchemes entry unwritable, and
    enumerating the combinations is not possible: the operand appears in the
    value, so the set is open."""

    ENUM = "enum"
    """One of a fixed set. Rendered as a list, so an invalid value is unreachable
    from the form rather than merely rejected after typing."""

    SCALAR = "scalar"
    INTEGER = "integer"
    BOOL = "bool"


@dataclass(frozen=True, slots=True)
class Field:
    """One editable entry."""

    key: str
    kind: FieldKind
    label: str = ""
    help: str = ""
    required: bool = False
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    depends: tuple[tuple[str, str], ...] = ()
    """``(key, value)`` pairs that must all hold for this field to apply.

    ``endTime`` matters only when ``stopAt`` is ``endTime``; ``maxCo`` only when
    ``adjustTimeStep`` is on. Without this, a form would demand values the case
    will never read and report their absence as an error.
    """

    @property
    def title(self) -> str:
        return self.label or self.key

    def applies_to(self, document: Document) -> bool:
        """Whether this field is in play, given the rest of the document."""
        for key, expected in self.depends:
            actual = document.get(key)
            if actual is None:
                return False
            if _as_bool(expected) is not None:
                if _as_bool(actual) != _as_bool(expected):
                    return False
            elif actual != expected:
                return False
        return True

    def check(self, raw: str) -> str | None:
        """Return why ``raw`` is unacceptable, or ``None`` if it is fine.

        A message rather than a boolean, because the form shows it: "must be
        greater than 0" tells the user what to do, while a red border does not.
        """
        value = raw.strip()
        if not value:
            return "cannot be empty"

        match self.kind:
            case FieldKind.ENUM:
                if self.values and value not in self.values:
                    return f"must be one of: {', '.join(self.values)}"
            case FieldKind.BOOL:
                if _as_bool(value) is None:
                    return "must be yes or no"
            case FieldKind.INTEGER:
                try:
                    number = int(value)
                except ValueError:
                    return "must be a whole number"
                return self._check_range(number)
            case FieldKind.SCALAR:
                try:
                    number = float(value)
                except ValueError:
                    return "must be a number"
                return self._check_range(number)
            case FieldKind.WORD:
                if any(character.isspace() for character in value):
                    return "must be a single word"
            case FieldKind.TEXT:
                # Non-empty is the only universal rule; anything more would be
                # guessing at a grammar OpenFOAM itself keeps open.
                pass
        return None

    def _check_range(self, number: float) -> str | None:
        if self.minimum is not None:
            if self.exclusive_minimum and number <= self.minimum:
                return f"must be greater than {_trim(self.minimum)}"
            if not self.exclusive_minimum and number < self.minimum:
                return f"must be at least {_trim(self.minimum)}"
        if self.maximum is not None and number > self.maximum:
            return f"must be at most {_trim(self.maximum)}"
        return None


@dataclass(frozen=True, slots=True)
class Schema:
    """The editable fields of one dictionary."""

    name: str
    file: Path
    title: str
    fields: tuple[Field, ...]

    def field(self, key: str) -> Field | None:
        return next((f for f in self.fields if f.key == key), None)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields)

    @property
    def covered_groups(self) -> frozenset[str]:
        """Top-level names the schema reaches into.

        A field key may be a path — ``ddtSchemes/default``, ``SIMPLE/nCorrectors``
        — because fvSchemes and fvSolution keep their settings one level down.
        The group is what a *top-level* key must be compared against, or every
        such dictionary would report its own groups as unknown.
        """
        return frozenset(key.split("/", 1)[0] for key in self.keys)

    def unknown_keys(self, document: Document) -> list[str]:
        """Top-level keys the form does not reach (§5.4, FR-P6).

        Surfaced rather than hidden: the user should be able to see that the raw
        tab holds something the form does not, instead of discovering it when an
        edit they expected to make is not offered.

        A group the schema reaches *into* is not listed, even though the form
        cannot edit all of it. ``divSchemes`` is the case in point: its
        ``default`` is editable while its per-operator entries are not, and
        calling the whole group unknown would be as misleading as saying nothing.
        """
        known = self.covered_groups | {"FoamFile"}
        present = document.keys()  # a Document method, not a mapping
        return [key for key in present if key not in known]

    def partial_groups(self, document: Document) -> list[str]:
        """Groups the form reaches into but does not fully cover.

        Named separately from :meth:`unknown_keys` because the advice differs:
        an unknown key is entirely in the text tab, while a partial group has
        some settings here and the rest there.
        """
        partial = []
        for group in sorted(self.covered_groups):
            node = document.find(group)
            if node is None:
                continue
            covered = {key.split("/", 1)[1] for key in self.keys if key.startswith(f"{group}/")}
            try:
                present = set(document.keys(group))
            except PathError:  # pragma: no cover - find() already returned a node
                continue
            if present - covered:
                partial.append(group)
        return partial


def _parse_field(raw: dict[str, Any]) -> Field:
    try:
        kind = FieldKind(raw["type"])
    except (KeyError, ValueError) as exc:
        raise SchemaError(f"Field {raw.get('key')!r} has no usable type") from exc
    if "key" not in raw:
        raise SchemaError("A field is missing its key")

    return Field(
        key=raw["key"],
        kind=kind,
        label=raw.get("label", ""),
        help=raw.get("help", ""),
        required=bool(raw.get("required", False)),
        values=tuple(raw.get("values", ())),
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
        exclusive_minimum=bool(raw.get("exclusive_minimum", False)),
        depends=tuple(raw.get("depends", {}).items()),
    )


def parse_schema(name: str, text: str) -> Schema:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"Schema {name!r} is not valid JSON: {exc}") from exc
    if raw.get("schema") != 1:
        raise SchemaError(f"Schema {name!r} has unsupported version {raw.get('schema')!r}")

    return Schema(
        name=name,
        file=Path(raw["file"]),
        title=raw.get("title", name),
        fields=tuple(_parse_field(f) for f in raw.get("fields", ())),
    )


@cache
def load_schema(name: str) -> Schema | None:
    """Load a bundled schema by dictionary name, or ``None`` if there is none.

    Absence is ordinary: most dictionaries have no schema yet and are edited in
    the raw-text tab, which FR-P6 provides for *every* dictionary. Returning
    ``None`` rather than raising keeps "no form for this file" an expected state.
    """
    source = resources.files("foamwb.data.schemas").joinpath(f"{name}.json")
    if not source.is_file():
        return None
    return parse_schema(name, source.read_text(encoding="utf-8"))


@cache
def available_schemas() -> tuple[str, ...]:
    return tuple(
        sorted(
            entry.name.removesuffix(".json")
            for entry in resources.files("foamwb.data.schemas").iterdir()
            if entry.name.endswith(".json")
        )
    )


def validate_document(schema: Schema, document: Document, source: Path) -> list[Finding]:
    """Check a parsed dictionary against its schema (FR-C3).

    Only schema-covered keys are reported. Everything else is somebody's valid
    OpenFOAM entry that this build does not model, and §5.4 requires it preserved
    rather than complained about.
    """
    findings: list[Finding] = []

    for field in schema.fields:
        if not field.applies_to(document):
            continue

        raw = document.get(field.key)
        if raw is None:
            if field.required:
                findings.append(
                    Finding(
                        code=ErrorCode.PARSE_ERROR,
                        severity=Severity.ERROR,
                        file=source,
                        detail=f"{field.title} ({field.key}) is required but not set.",
                    )
                )
            continue

        problem = field.check(raw)
        if problem is not None:
            findings.append(
                Finding(
                    code=ErrorCode.PARSE_ERROR,
                    severity=Severity.ERROR,
                    file=source,
                    detail=f"{field.title} ({field.key}) {problem}; found {raw!r}.",
                )
            )
    return findings


def _as_bool(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return None


def _trim(number: float) -> str:
    return f"{number:g}"
