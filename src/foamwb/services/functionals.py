"""Scalar functionals of a solution — the currency of the §12.3 numerical gate.

§12.3 states the constraint plainly: CFD field output is **not bit-reproducible**
across compiler version, MPI implementation, BLAS or CPU generation, so a
hash-equality gate would fail spuriously the moment the CI runner image changed.
The gate is therefore defined on *scalar functionals with explicit tolerances*,
against references captured on a pinned toolchain.

Two mechanisms, because §12.3 asks for two different kinds of number:

* **L2 norm of a field** is a pure reduction over cell values and needs no mesh
  metrics, so it is computed here by parsing the time directory with
  :class:`~foamwb.services.foamdict.Document`. That reuses the parser the whole
  product already depends on rather than adding a second, differently-buggy
  reader.
* **Volume-weighted quantities** need cell volumes, which live in the mesh. Those
  are computed by OpenFOAM's own ``volFieldValue`` function object and read back
  from ``postProcessing``. Reimplementing OpenFOAM's integration in Python to
  check OpenFOAM would be checking the wrong thing — the reference must come from
  the code under test's own arithmetic, not from a second opinion that could
  differ for reasons unrelated to a regression.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from foamwb.services.foamdict import Document, ParseError

__all__ = [
    "FieldStats",
    "field_l2_norm",
    "field_values",
    "read_volume_field_value",
]

#: `uniform <value>` — a field with one value everywhere, common in a `0/` directory.
_UNIFORM = re.compile(r"^uniform\s+(.*)$", re.DOTALL)

#: `nonuniform List<scalar> 400 ( ... )`
_NONUNIFORM = re.compile(r"^nonuniform\s+List<(\w+)>\s*(\d+)?\s*\((.*)\)\s*$", re.DOTALL)

_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


@dataclass(frozen=True, slots=True)
class FieldStats:
    """Reduction of one field at one time."""

    name: str
    time: str
    count: int
    l2_norm: float
    minimum: float
    maximum: float

    def close_to(self, other: FieldStats, *, relative: float) -> bool:
        """Whether two reductions agree within a relative tolerance.

        Compared relatively rather than absolutely because the fields the gate
        watches span many orders of magnitude — a pressure of 1e-6 and a velocity
        of 1e1 cannot share an absolute tolerance.
        """
        if self.count != other.count:
            return False
        return _relative_difference(self.l2_norm, other.l2_norm) <= relative


def _relative_difference(a: float, b: float) -> float:
    if a == b:
        return 0.0
    scale = max(abs(a), abs(b))
    return math.inf if scale == 0 else abs(a - b) / scale


def field_values(path: Path) -> list[float]:
    """Every component of a field's ``internalField``, flattened.

    Flattened because the functional is a norm over the whole field: a vector
    field's three components contribute exactly as three scalars would, which is
    what makes one code path serve ``p`` and ``U`` alike.

    A ``uniform`` field yields one entry per component — the cell count is
    unknown without the mesh, and inventing it would make two meshes of the same
    uniform field compare equal when they should not be compared at all.
    """
    try:
        document = Document.parse_bytes(path.read_bytes())
    except ParseError as exc:
        raise ValueError(f"{path}: {exc}") from exc

    raw = document.get("internalField")
    if raw is None:
        raise ValueError(f"{path}: no internalField entry")

    if match := _UNIFORM.match(raw):
        return [float(n) for n in _NUMBER.findall(match.group(1))]
    if match := _NONUNIFORM.match(raw):
        return [float(n) for n in _NUMBER.findall(match.group(3))]
    raise ValueError(f"{path}: internalField is neither uniform nor nonuniform")


def field_l2_norm(case: Path, time: str, field: str) -> FieldStats:
    """L2 norm of a field at a time directory (§12.3's ``cavity`` row)."""
    path = case / time / field
    values = field_values(path)
    if not values:
        raise ValueError(f"{path}: field is empty")
    return FieldStats(
        name=field,
        time=time,
        count=len(values),
        l2_norm=math.sqrt(sum(v * v for v in values)),
        minimum=min(values),
        maximum=max(values),
    )


def read_volume_field_value(case: Path, function_object: str) -> float:
    """Final value written by a ``volFieldValue`` function object.

    Scalar operations only. ``volIntegrate(U)`` writes a *vector* — three numbers
    in parentheses — and silently taking its first component would be a quiet
    wrong answer in a gate whose entire purpose is to catch quiet wrong answers.
    """
    directory = case / "postProcessing" / function_object
    files = sorted(directory.rglob("*.dat")) if directory.is_dir() else []
    if not files:
        raise ValueError(f"No output from function object {function_object!r} in {case}")

    rows = [
        line.split()
        for line in files[-1].read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not rows or len(rows[-1]) < 2:
        raise ValueError(f"{files[-1]}: no data rows")

    value = rows[-1][1]
    if value.startswith("("):
        raise ValueError(
            f"{function_object} produced a vector ({' '.join(rows[-1][1:])}); "
            "the gate compares scalars, so use a scalar operation"
        )
    return float(value)
