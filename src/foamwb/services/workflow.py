"""The ordered setup workflow (§7.2, D1, P1).

Modelled on scFLOW's Navigation panel, which is the strongest idea in that
interface: the left-hand list is not a set of *places* but an ordered *procedure*.
You work down it. A student who does not yet know what a CFD case consists of is
told, by the shape of the window, what the steps are and which one comes next —
which is precisely §1's problem statement ("defeats a large fraction of
prospective users before they run anything").

The previous navigation was a destination rail: Hub, Cases, Setup, Run, Post.
Those are correct groupings for someone who already knows the workflow and wrong
for someone learning it. The rail answered "where do I go?"; this answers "what
do I do next?", which is the question P1 actually has.

**Steps carry ids, never display text.** The labels live in the string catalogue
(NFR-A5) and this module is Qt-free (NFR-M1), so the same workflow drives the UI,
a future CLI, and the tests without any of them agreeing a second time about what
the steps are.

**Phases, and why they gate.** scFLOW greys out the geometry group once the
analysis model is built, and swaps *Build Analysis Model* for *Return to Prepare
Parts*. The equivalent here is the mesh: physics can be edited at any time, but
until ``constant/polyMesh`` exists there is nothing to run, and offering Execute
would produce a failure the user cannot interpret. The gate is stated in the list
rather than enforced by a dead button (§7.9 rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

__all__ = [
    "STEPS",
    "Phase",
    "Step",
    "StepKind",
    "StepState",
    "WorkflowModel",
    "step_by_id",
]


class StepKind(StrEnum):
    """What activating a step does."""

    GROUP = "group"
    """A header. Selecting it expands its children and shows nothing itself."""

    PAGE = "page"
    """Opens an editor or a view in the main panel."""

    ACTION = "action"
    """Runs something — the equivalent of scFLOW's *Build Analysis Model*."""


class Phase(StrEnum):
    """Which part of the procedure the case is in.

    Deliberately coarse. Three phases a user can name beat seven they cannot.
    """

    NO_CASE = "no_case"
    """Nothing is open. Only the case steps mean anything."""

    MESH = "mesh"
    """A case exists but has no mesh, so nothing can be run yet."""

    ANALYSIS = "analysis"
    """A mesh exists. Physics, execution and results are all reachable."""


class StepState(StrEnum):
    """How a step is offered."""

    DONE = "done"
    """Evidence on disk says this is complete. Not a claim that it is *right*."""

    AVAILABLE = "available"
    BLOCKED = "blocked"
    """Reachable in principle, but something earlier is missing. The list says
    which, rather than leaving a dead entry the user clicks at repeatedly."""

    LOCKED = "locked"
    """Belongs to a phase the case has moved past, like scFLOW's greyed-out
    geometry group. Reversible, never hidden."""


@dataclass(frozen=True, slots=True)
class Step:
    """One entry in the navigation list."""

    id: str
    kind: StepKind = StepKind.PAGE
    parent: str = ""
    """Group id, empty for a top-level entry."""

    view: str = ""
    """Which existing view this opens, where it maps onto one."""

    needs_case: bool = True
    needs_mesh: bool = False
    required: bool = False
    """Whether this is part of the *spine* of the procedure.

    Most entries are editors: legitimate to visit at any time, in any order, and
    never "overdue". Only a few must actually happen for a case to run, and only
    those can answer "what next?" — a prompt that said *browse your files* to a
    user with an unmeshed case would be noise dressed as guidance."""

    phase: Phase | None = None
    """The phase this step belongs to, if it is gated by one."""

    @property
    def is_group(self) -> bool:
        return self.kind is StepKind.GROUP


#: The workflow, in order. Mirrors scFLOW's Navigation panel in *shape* — groups
#: with indented children, geometry before physics, an explicit Execute at the
#: end — while naming the things OpenFOAM actually has.
#:
#: scFLOW's "Part Material" is a library of solids for conjugate heat transfer;
#: the equivalent here is the transport and turbulence properties, which is what
#: an incompressible OpenFOAM case calls its material model. Its "Register
#: Region" is our boundary patches. Its "Octree/Mesh Parameter" collapse into one
#: mesh-settings page, because blockMesh and snappyHexMesh do not share an octree
#: abstraction and pretending they do would be a lie about the tool underneath.
STEPS: tuple[Step, ...] = (
    Step("case", kind=StepKind.GROUP, needs_case=False),
    Step("case.open", parent="case", view="hub", needs_case=False, required=True),
    Step("case.files", parent="case", view="cases"),
    Step("mesh", kind=StepKind.GROUP, phase=Phase.MESH),
    Step("mesh.settings", parent="mesh", view="cases", phase=Phase.MESH),
    Step("mesh.regions", parent="mesh", view="regions", phase=Phase.MESH),
    Step(
        "mesh.generate",
        parent="mesh",
        kind=StepKind.ACTION,
        phase=Phase.MESH,
        required=True,
    ),
    Step("materials", view="cases"),
    Step("conditions", kind=StepKind.GROUP),
    Step("conditions.type", parent="conditions", view="vv"),
    Step("conditions.basic", parent="conditions", view="cases"),
    Step("conditions.initial", parent="conditions", view="initial"),
    Step("conditions.boundary", parent="conditions", view="cases"),
    Step("conditions.control", parent="conditions", view="cases"),
    Step("conditions.output", parent="conditions", view="cases"),
    Step("verify", kind=StepKind.ACTION, required=True),
    Step("execute", view="run", needs_mesh=True, required=True),
    Step("results", view="post", needs_mesh=True),
    Step("vandv", view="vv", needs_mesh=True),
    Step("library", view="library", needs_case=False),
    Step("guide", view="guide", needs_case=False),
)


def step_by_id(step_id: str) -> Step | None:
    return next((step for step in STEPS if step.id == step_id), None)


@dataclass
class WorkflowModel:
    """The workflow's state for one case.

    Evidence-based throughout: a step is *done* because something exists on disk,
    never because the user visited the page. Marking a step complete on visit
    would tell a user their boundary conditions are set when they opened the
    editor and closed it again — the exact false reassurance §7.9 rule 6 forbids.
    """

    case: Path | None = None
    has_mesh: bool = False
    has_results: bool = False
    solver: str = ""
    _overrides: dict[str, StepState] = field(default_factory=dict)

    @property
    def phase(self) -> Phase:
        if self.case is None:
            return Phase.NO_CASE
        return Phase.ANALYSIS if self.has_mesh else Phase.MESH

    #: Steps whose completion is visible on disk, and what proves it. Anything
    #: not listed here is never reported DONE, because there is no evidence for
    #: it — an editor that was opened proves nothing about what was written.
    _EVIDENCE: ClassVar[dict] = {
        "case.open": lambda self: self.case is not None,
        "mesh.generate": lambda self: self.has_mesh,
        "execute": lambda self: self.has_results,
    }

    def state_of(self, step: Step) -> StepState:
        """How this step should be offered, given what is on disk."""
        if (forced := self._overrides.get(step.id)) is not None:
            return forced

        if step.needs_case and self.case is None:
            return StepState.BLOCKED
        if step.needs_mesh and not self.has_mesh:
            return StepState.BLOCKED
        # Evidence first: a completed step reads "done" even once its phase has
        # been left behind. scFLOW greys out the geometry group but still shows
        # that the model was built, and reporting finished work as merely locked
        # would lose the one piece of progress the user cares about.
        proof = self._EVIDENCE.get(step.id)
        if proof is not None and proof(self):
            return StepState.DONE
        if self.is_locked_phase(step):
            return StepState.LOCKED
        return StepState.AVAILABLE

    def set_state(self, step_id: str, state: StepState | None) -> None:
        """Override a step's state — used for evidence the model cannot see.

        ``None`` removes the override rather than setting a state, so a caller
        can undo without having to know what the computed value would be.
        """
        if state is None:
            self._overrides.pop(step_id, None)
        else:
            self._overrides[step_id] = state

    def children_of(self, group_id: str) -> tuple[Step, ...]:
        return tuple(step for step in STEPS if step.parent == group_id)

    @property
    def next_step(self) -> Step | None:
        """The first thing the user can actually do.

        Drives the "what now?" affordance. Groups are skipped — a header is not
        an action — and so are the always-available destinations at the end,
        which are references rather than steps in the procedure.
        """
        for step in STEPS:
            if not step.required:
                continue
            if self.state_of(step) is StepState.AVAILABLE:
                return step
        return None

    def is_locked_phase(self, step: Step) -> bool:
        """Whether this step belongs to a phase the case has moved past.

        Locked, not hidden. scFLOW greys the geometry group out and offers
        *Return to Prepare Parts*; hiding it instead would leave a user who needs
        to change their mesh with no visible way back.
        """
        return step.phase is Phase.MESH and self.phase is Phase.ANALYSIS
