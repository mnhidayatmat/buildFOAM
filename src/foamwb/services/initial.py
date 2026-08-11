"""Initial conditions — the ``0`` directory (FR-P3, §7.4).

Each field file states three things this editor cares about: what the quantity
is, what units it is in, and what value the interior starts at. OpenFOAM writes
the units as an exponent vector, which is correct, complete and unreadable:
``[0 2 -2 0 0 0 0]`` is m²/s², and a user who has to decode that in their head
to check a pressure is being asked to do the machine's work.

So the vector is rendered, and rendered *from the file* rather than from a table
of field names. ``p`` is m²/s² in an incompressible case and m·kg/(s²·m) in a
compressible one; a lookup keyed on the name would confidently print the wrong
unit for half the tutorial suite.

**Only ``internalField`` is edited here.** The boundary values belong to the
boundary-condition matrix, which already understands patch constraints (E-C04).
Two editors writing the same file from different models is how they end up
disagreeing about it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from foamwb.services.boundary_matrix import field_files
from foamwb.services.foamdict import Document, ParseError

__all__ = [
    "DIMENSION_SYMBOLS",
    "InitialField",
    "format_dimensions",
    "read_initial_fields",
    "set_internal_field",
]

#: OpenFOAM's dimension vector, in order. The order is the file format's, not a
#: choice, and getting it wrong silently mislabels every field.
DIMENSION_SYMBOLS: tuple[str, ...] = ("kg", "m", "s", "K", "kmol", "A", "cd")

_SUPERSCRIPT = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
_UNIFORM = re.compile(r"^\s*uniform\s+(.*)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class InitialField:
    """One field's starting state."""

    name: str
    path: Path
    dimensions: str = ""
    internal_field: str = ""
    class_name: str = ""

    @property
    def unit(self) -> str:
        """The dimensions, rendered readably. Empty when the file gives none."""
        return format_dimensions(self.dimensions)

    @property
    def is_uniform(self) -> bool:
        return _UNIFORM.match(self.internal_field) is not None

    @property
    def value(self) -> str:
        """The value without the ``uniform`` keyword, for editing.

        A non-uniform field returns its whole expression unchanged: those are
        ``nonuniform List<vector>`` blocks of one entry per cell, and offering a
        text box for a million numbers would be a worse lie than showing none.
        """
        match = _UNIFORM.match(self.internal_field)
        return match.group(1).strip() if match else self.internal_field

    @property
    def is_vector(self) -> bool:
        return self.value.startswith("(")


def format_dimensions(raw: str) -> str:
    """``[0 2 -2 0 0 0 0]`` → ``m²/s²``.

    Returns an empty string rather than a guess when the vector is absent or
    malformed: a wrong unit beside a number is worse than no unit, because it
    invites the user to trust a value they should have checked.
    """
    if not raw:
        return ""
    inner = raw.strip().strip("[]").split()
    if len(inner) != len(DIMENSION_SYMBOLS):
        return ""

    try:
        exponents = [int(value) for value in inner]
    except ValueError:
        return ""

    if not any(exponents):
        return "-"

    numerator: list[str] = []
    denominator: list[str] = []
    for symbol, exponent in zip(DIMENSION_SYMBOLS, exponents, strict=True):
        if exponent == 0:
            continue
        target, power = (numerator, exponent) if exponent > 0 else (denominator, -exponent)
        target.append(symbol if power == 1 else f"{symbol}{str(power).translate(_SUPERSCRIPT)}")

    top = "·".join(numerator) if numerator else "1"
    if not denominator:
        return top
    return f"{top}/{'·'.join(denominator)}"


def read_initial_fields(case: Path) -> list[InitialField]:
    """Every field in the initial-condition directory, in name order.

    Files that will not parse are still listed, with empty values. Omitting them
    would tell the user their case has fewer fields than it does, and the fix —
    open it in the Text tab — needs the file to be visible first.
    """
    found: list[InitialField] = []
    for source in field_files(case):
        try:
            document = Document.parse_bytes(source.read_bytes())
        except (OSError, ParseError):
            found.append(InitialField(name=source.name, path=source))
            continue

        found.append(
            InitialField(
                name=source.name,
                path=source,
                dimensions=document.get("dimensions") or "",
                internal_field=document.get("internalField") or "",
                class_name=document.get("FoamFile/class") or "",
            )
        )
    return found


def set_internal_field(field: InitialField, value: str) -> bool:
    """Write a new uniform interior value. Returns whether anything changed.

    The ``uniform`` keyword is re-added here rather than asked of the user: it is
    part of the file format, not part of the physics, and a value typed without
    it would produce a parse error from the solver that named a line rather than
    a mistake.
    """
    text = value.strip()
    if not text:
        return False

    wanted = text if text.startswith(("uniform", "nonuniform")) else f"uniform {text}"
    if wanted == field.internal_field:
        return False

    try:
        document = Document.parse_bytes(field.path.read_bytes())
    except (OSError, ParseError):
        return False
    if not document.has("internalField"):
        return False

    document.set("internalField", wanted)
    temporary = field.path.with_suffix(field.path.suffix + ".tmp")
    temporary.write_bytes(document.render_bytes())
    temporary.replace(field.path)
    return True
