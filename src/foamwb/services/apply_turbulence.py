"""Applying a turbulence choice to a case (FR-VVT9, FR-VVT4, FR-P7).

"Changing the model rewrites only the turbulence dictionary and the affected
``boundaryField`` entries, preserving everything else byte-for-byte."

Every write goes through :meth:`Document.set`, so that guarantee is the same one
the form editors rest on rather than a second promise made separately.

**A change of family is refused, and that is the right answer rather than a
limitation.** Moving from RAS to LES is not a model swap: it needs a transient
``controlDict``, different schemes, a mesh fine enough to resolve the structures,
and usually a different solver. Writing ``LESModel`` into a steady case would
produce something that runs and is meaningless — the exact failure mode §6.9
exists to prevent. The refusal names what else would have to change, so the user
can decide, rather than silently doing a tenth of the job.

The dictionary's *name* comes from the runtime manifest (NFR-M3, DEC-15): the ESI
and Foundation lineages call this file different things, and hard-coding either
is what would make Foundation support a fork rather than a data change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from foamwb.services.advisor import Model, WallTreatment
from foamwb.services.boundary import Patch, PatchType, read_boundary
from foamwb.services.boundary_matrix import field_files
from foamwb.services.case import Case, CaseService
from foamwb.services.foamdict import Document, ParseError

__all__ = ["ApplyPlan", "ApplyResult", "apply_turbulence", "plan_apply"]

#: The eddy-viscosity field, which every model writes wall conditions for even
#: though no model transports it.
_NUT = "nut"


@dataclass(slots=True)
class ApplyPlan:
    """What applying a choice would change, before anything is written.

    Separate from the writing for the same reason §7.3 separates the provisioning
    plan from the install: a user should be able to see the consequence of a
    choice — which files, which patches — before agreeing to it.
    """

    model: Model
    treatment: WallTreatment
    dictionary: Path | None = None
    current_model: str | None = None
    model_changes: dict[str, str] = field(default_factory=dict)
    """``path -> value`` inside the turbulence dictionary."""

    condition_changes: dict[Path, dict[str, str]] = field(default_factory=dict)
    """``field file -> {boundaryField path: condition}``."""

    blocked: str = ""
    """Why this cannot be applied, empty if it can."""

    @property
    def can_apply(self) -> bool:
        return not self.blocked and bool(self.model_changes or self.condition_changes)

    @property
    def touched_files(self) -> list[Path]:
        files = list(self.condition_changes)
        if self.model_changes and self.dictionary is not None:
            files.insert(0, self.dictionary)
        return files

    @property
    def patch_count(self) -> int:
        return len({path.name for path in self.condition_changes})


@dataclass(slots=True)
class ApplyResult:
    written: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changed_anything(self) -> bool:
        return bool(self.written)


def turbulence_dictionary(case: Case, dictionary_name: str) -> Path | None:
    """Locate the case's turbulence dictionary by the manifest's name for it."""
    candidate = case.path / "constant" / dictionary_name
    return candidate if candidate.is_file() else None


def plan_apply(
    case: Case,
    model: Model,
    treatment: WallTreatment,
    *,
    dictionary_name: str,
) -> ApplyPlan:
    """Work out what applying this choice would change. Writes nothing."""
    plan = ApplyPlan(model=model, treatment=treatment)

    if treatment.key not in model.wall:
        # FR-VVT4: unreachable through the UI, but a caller could still ask.
        plan.blocked = (
            f"{model.name} cannot be used with {treatment.label.lower()}. "
            f"It supports: {', '.join(model.wall)}."
        )
        return plan

    source = turbulence_dictionary(case, dictionary_name)
    if source is None:
        plan.blocked = (
            f"This case has no constant/{dictionary_name}, so there is no "
            "turbulence model to change."
        )
        return plan
    plan.dictionary = source

    try:
        document = Document.parse_bytes(source.read_bytes())
    except ParseError as exc:
        plan.blocked = f"{dictionary_name} could not be read: {exc}"
        return plan

    current_block = document.get("simulationType")
    plan.current_model = document.get(f"{current_block}/{model.model_key}") or document.get(
        f"{current_block}/RASModel"
    )

    if current_block and current_block != model.block:
        plan.blocked = (
            f"This case is set up as {current_block}, and {model.name} is a "
            f"{model.block} model. Switching is not a model swap: it needs a "
            "transient controlDict, different schemes and a mesh able to resolve "
            "the structures. Change those first, in the Text tab, then come back."
        )
        return plan

    model_path = f"{model.block}/{model.model_key}"
    if document.get(model_path) != model.name:
        plan.model_changes[model_path] = model.name

    _plan_conditions(plan, case, model, treatment)
    return plan


def _plan_conditions(plan: ApplyPlan, case: Case, model: Model, treatment: WallTreatment) -> None:
    """Which wall boundary conditions the treatment implies (FR-VVT4).

    Only *wall* patches. An inlet's turbulence condition is a physical boundary
    the user set, not something the wall treatment gets to decide, and rewriting
    it would change the problem rather than the modelling of it.
    """
    walls = [p for p in read_boundary(case.path) if p.type == PatchType.WALL]
    if not walls:
        return

    wanted = {*model.fields, _NUT}
    for source in field_files(case.path):
        if source.name not in wanted:
            continue
        condition = treatment.condition_for(source.name)
        if condition is None:
            continue
        try:
            document = Document.parse_bytes(source.read_bytes())
        except ParseError:
            continue

        changes: dict[str, str] = {}
        for patch in walls:
            path = f"boundaryField/{patch.name}/type"
            if document.has(path) and document.get(path) != condition:
                changes[path] = condition
        if changes:
            plan.condition_changes[source] = changes


def apply_turbulence(
    case: Case, plan: ApplyPlan, *, service: CaseService | None = None
) -> ApplyResult:
    """Carry out a plan (FR-VVT9).

    Each change is a :meth:`Document.set`, so a file's diff is one line per
    entry actually changed and every other byte survives (FR-P7). Entries that
    already hold the wanted value are not written at all, so applying the same
    choice twice is a no-op rather than a rewrite.
    """
    service = service or CaseService()
    result = ApplyResult()

    if plan.blocked:
        result.skipped.append(plan.blocked)
        return result

    if plan.model_changes and plan.dictionary is not None:
        document = Document.parse_bytes(plan.dictionary.read_bytes())
        for path, value in plan.model_changes.items():
            document.set(path, value)
        service.write_dictionary(case, plan.dictionary, document.render_bytes())
        result.written.append(plan.dictionary)

    for source, changes in plan.condition_changes.items():
        document = Document.parse_bytes(source.read_bytes())
        for path, value in changes.items():
            document.set(path, value)
        service.write_dictionary(case, source, document.render_bytes())
        result.written.append(source)

    return result


def current_choice(case: Case, *, dictionary_name: str) -> tuple[str | None, str | None]:
    """The model a case currently uses, and the block it sits in.

    Read rather than assumed, so the advisor can account for the case's existing
    choice (FR-VVT1's "or explains why an alternative is defensible") instead of
    ranking in a vacuum.
    """
    source = case.path / "constant" / dictionary_name
    if not source.is_file():
        return None, None
    try:
        document = Document.parse_bytes(source.read_bytes())
    except ParseError:
        return None, None

    block = document.get("simulationType")
    if not block:
        return None, None
    for key in ("RASModel", "LESModel"):
        if (name := document.get(f"{block}/{key}")) is not None:
            return name, block
    return None, block


def wall_patches(case: Case) -> list[Patch]:
    """Wall patches, which are the ones a wall treatment applies to."""
    return [p for p in read_boundary(case.path) if p.type == PatchType.WALL]
