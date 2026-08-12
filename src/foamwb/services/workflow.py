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
    "REQUIRED_STEPS",
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

    reference: bool = False
    """A place to look something up, not a step in the procedure.

    The Library and the Guide were in the list beside Execute and Results, which
    reads as "step twelve is: consult the guide". They are still reachable from
    the same panel — this is not a demotion — but they are drawn below the
    procedure rather than inside it, so the numbered spine ends where the work
    ends."""

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
#: **Every step lives inside exactly one group.** The first version left six
#: entries — materials, verify, execute, results, vandv — at the top level, where
#: they sat at the same indentation as the group *headers* and were told apart
#: only by a four-pixel glyph. Structure and content were indistinguishable at a
#: glance, which is the single thing users reported as making the panel hard to
#: read. A strict two-level tree costs one extra header and removes the ambiguity
#: entirely.
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
    Step("conditions", kind=StepKind.GROUP),
    # Material properties belong with the physics rather than floating above it:
    # viscosity and the turbulence model are conditions of the problem in exactly
    # the sense the rest of this group is.
    Step("materials", parent="conditions", view="cases"),
    Step("conditions.type", parent="conditions", view="vv"),
    Step("conditions.basic", parent="conditions", view="cases"),
    Step("conditions.initial", parent="conditions", view="initial"),
    Step("conditions.boundary", parent="conditions", view="cases"),
    Step("conditions.control", parent="conditions", view="cases"),
    Step("conditions.output", parent="conditions", view="cases"),
    Step("solution", kind=StepKind.GROUP),
    Step("verify", parent="solution", view="verify", required=True),
    Step("execute", parent="solution", view="run", needs_mesh=True, required=True),
    Step("results", parent="solution", view="post", needs_mesh=True),
    Step("vandv", parent="solution", view="vv", needs_mesh=True),
    Step("reference", kind=StepKind.GROUP, needs_case=False, reference=True),
    Step("library", parent="reference", view="library", needs_case=False, reference=True),
    Step("guide", parent="reference", view="guide", needs_case=False, reference=True),
)

#: The numbered spine, in order. These are the steps a case cannot run without,
#: and the only ones that carry a number — which is what makes "required" and
#: "optional" visible without a legend to learn.
REQUIRED_STEPS: tuple[Step, ...] = tuple(step for step in STEPS if step.required)


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
    checks_passed: bool = False
    """Whether validation found nothing that would stop a run.

    Needed because *Check setup* is part of the spine and had no evidence of its
    own, so it could never be reported done. That was invisible while the panel
    only named the next step, and plainly wrong the moment it started counting:
    progress could not reach the total, and "Next: Check setup" persisted after
    the case had been meshed, run and post-processed."""

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
        # Passing the checks *is* the evidence. Not a claim the physics is right
        # — validation only reports self-contradiction — which is why the step
        # stays available afterwards rather than being locked away.
        "verify": lambda self: self.checks_passed,
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
            if not step.required or step.reference:
                continue
            if self.state_of(step) is StepState.AVAILABLE:
                return step
        return None

    def number_of(self, step: Step) -> int | None:
        """This step's position in the numbered spine, or ``None`` if optional.

        The number *is* the distinction between "you must do this" and "you may
        want this". Twenty-one identically marked rows read as twenty-one
        obligations; four numbered ones among them read as a procedure with
        optional detail hanging off it, which is what this actually is.
        """
        for position, candidate in enumerate(REQUIRED_STEPS, start=1):
            if candidate.id == step.id:
                return position
        return None

    @property
    def progress(self) -> tuple[int, int]:
        """How many required steps are done, out of how many.

        Answers "how far along am I?", which the panel could not previously
        answer at all — the only progress signal was a "Next:" line that names
        one step and says nothing about the shape of what is left.
        """
        done = sum(1 for step in REQUIRED_STEPS if self.state_of(step) is StepState.DONE)
        return done, len(REQUIRED_STEPS)

    def is_locked_phase(self, step: Step) -> bool:
        """Whether this step belongs to a phase the case has moved past.

        Locked, not hidden. scFLOW greys the geometry group out and offers
        *Return to Prepare Parts*; hiding it instead would leave a user who needs
        to change their mesh with no visible way back.
        """
        return step.phase is Phase.MESH and self.phase is Phase.ANALYSIS
