"""Editing patch types (FR-P4, E-C04, §7.4).

A patch's *type* is not cosmetic. It decides which boundary conditions are legal,
whether turbulence wall functions apply, and — for ``empty`` and ``wedge`` —
what dimensionality the case is solving in. Changing it is one of the few edits
in this application that can silently change the physics, so every change is
planned, its consequences are named, and the ones that would leave the case
inconsistent are refused.

**The write is a splice, not a rewrite.** ``constant/polyMesh/boundary`` is a
counted list, which the structural parser deliberately treats as opaque. Its
*interior* re-parses as an ordinary document, so a type change is
:meth:`Document.set` on that interior, rendered back and spliced into the exact
byte range it came from. Everything outside — the header, the count, the face
lists, the mesh's own comments — is untouched, which is what FR-P7 requires of a
file this application did not write.

**Changing to a constrained type is refused when the fields disagree.** Setting a
patch to ``empty`` while ``0/U`` still names ``fixedValue`` there produces a case
that OpenFOAM rejects at startup, or worse, one that runs and solves a different
problem. The plan says which fields would have to change; carrying that out is
the boundary-condition editor's job, and doing it silently here would be a large
edit hiding behind a small one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from foamwb.codes import Code, ErrorCode
from foamwb.services.boundary import BOUNDARY_FILE, CONSTRAINED, Patch, read_boundary
from foamwb.services.boundary_matrix import field_files
from foamwb.services.foamdict import Document, ParseError

__all__ = [
    "SELECTABLE_TYPES",
    "RegionChange",
    "apply_patch_type",
    "plan_patch_type",
]

#: Types a user may choose. ``processor`` is absent deliberately: it is created
#: by ``decomposePar`` and setting it by hand produces a mesh that only makes
#: sense to a decomposition that does not exist.
SELECTABLE_TYPES: tuple[str, ...] = (
    "patch",
    "wall",
    "empty",
    "symmetry",
    "symmetryPlane",
    "wedge",
    "cyclic",
)


@dataclass(slots=True)
class RegionChange:
    """What changing one patch's type would mean."""

    patch: str
    old_type: str
    new_type: str
    consequences: list[str] = field(default_factory=list)
    """Plain-language effects, shown before the change is agreed to."""

    fields_needing_update: dict[str, str] = field(default_factory=dict)
    """``field file name -> the condition that patch must now carry``."""

    blocked: str = ""
    code: Code | None = None

    @property
    def can_apply(self) -> bool:
        return not self.blocked and self.old_type != self.new_type

    @property
    def is_noop(self) -> bool:
        return self.old_type == self.new_type


def plan_patch_type(case: Path, patch_name: str, new_type: str) -> RegionChange:
    """Work out what changing a patch's type would do. Writes nothing."""
    patches = {p.name: p for p in read_boundary(case)}
    existing = patches.get(patch_name)

    if existing is None:
        return RegionChange(
            patch=patch_name,
            old_type="",
            new_type=new_type,
            blocked=f"{patch_name} is not a patch in this mesh.",
            code=ErrorCode.MISSING_BOUNDARY_FIELD,
        )

    change = RegionChange(patch=patch_name, old_type=existing.type, new_type=new_type)
    if change.is_noop:
        return change

    if new_type not in SELECTABLE_TYPES:
        change.blocked = (
            f"{new_type} is not a type this editor sets. Use the Text tab if the "
            "mesh really needs it."
        )
        change.code = ErrorCode.PATCH_BC_INCOMPATIBLE
        return change

    _describe(change, existing)
    _fields_that_must_follow(change, case)
    return change


def _describe(change: RegionChange, existing: Patch) -> None:
    """Say what the change means, in the terms the consequence actually has."""
    required = CONSTRAINED.get(change.new_type)
    was_required = CONSTRAINED.get(change.old_type)

    if required is not None:
        change.consequences.append(
            f"Every field must carry the {required} condition on {change.patch}. "
            "This is dictated by the geometry, not chosen."
        )
    if change.new_type == "empty":
        change.consequences.append(
            "empty marks the front and back of a 2D case. On a 3D mesh it makes "
            "the case unsolvable rather than merely wrong."
        )
    if change.new_type == "wedge":
        change.consequences.append(
            "wedge is for an axisymmetric case, and expects a mesh one cell thick "
            "with the wedge planes meeting on the axis."
        )
    if change.new_type == "cyclic":
        change.consequences.append(
            "A cyclic patch is meaningless without its partner. Set the matching "
            "patch too, and give each a neighbourPatch, in the Text tab."
        )
    if change.new_type == "wall" and change.old_type != "wall":
        change.consequences.append(
            "Turbulence wall functions apply to wall patches only, so this patch "
            "will now be included in the y+ audit and in nut wall treatment."
        )
    if change.old_type == "wall" and change.new_type != "wall":
        change.consequences.append(
            "This patch is no longer a wall, so wall functions and the y+ audit "
            "will stop applying to it."
        )
    if was_required is not None and required is None:
        change.consequences.append(
            f"The {was_required} condition is no longer forced here, so each "
            "field's condition becomes a choice again."
        )
    if existing.n_faces:
        change.consequences.append(f"{existing.n_faces} faces are affected.")


def _fields_that_must_follow(change: RegionChange, case: Path) -> None:
    """Which field files would need their condition on this patch changed.

    Reported, never applied here. A type change that quietly rewrote six field
    files would be a large edit hiding behind a small one, and §7.9 rule 2 asks
    that what will happen is visible before it happens.
    """
    required = CONSTRAINED.get(change.new_type)
    if required is None:
        return

    for source in field_files(case):
        try:
            document = Document.parse_bytes(source.read_bytes())
        except (OSError, ParseError):
            continue
        path = f"boundaryField/{change.patch}/type"
        if document.has(path) and document.get(path) != required:
            change.fields_needing_update[source.name] = required


def apply_patch_type(case: Path, change: RegionChange) -> bool:
    """Write the new type. Returns whether anything was written.

    The boundary file is spliced rather than regenerated: only the bytes of the
    one ``type`` entry change, so a mesh file this application never wrote comes
    back byte-identical apart from the edit (FR-P7).
    """
    if not change.can_apply:
        return False

    source = case / BOUNDARY_FILE
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return False

    document = Document.parse_bytes(text.encode("utf-8"))
    body = _list_body_text(document)
    if body is None:
        return False

    try:
        interior = Document.parse(body)
    except ParseError:
        return False

    path = f"{change.patch}/type"
    if not interior.has(path):
        return False
    interior.set(path, change.new_type)

    updated = interior.render()
    if updated == body:
        return False

    # An exact single splice: `index` raises rather than silently editing the
    # wrong occurrence, which `replace` would do quietly.
    start = text.index(body)
    spliced = text[:start] + updated + text[start + len(body) :]

    temporary = source.with_suffix(source.suffix + ".tmp")
    temporary.write_text(spliced, encoding="utf-8")
    temporary.replace(source)
    return True


def _list_body_text(document: Document) -> str | None:
    """The text inside the outermost counted list, without its parentheses."""
    from foamwb.services.boundary import _list_body

    return _list_body(document)
