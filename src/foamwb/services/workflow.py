"""The outline: an ordered tree of what a case consists of (§7.2, DEC-21).

Modelled on the single-window Fluent's *Outline View*. The left-hand tree is not
a set of *places* but the structure of the case in the order it is set up:
**Workflow** (the meshing tasks), then **Setup**, **Solution** and **Results**.
You work down it. A student who does not yet know what a CFD case consists of is
told, by the shape of the window, what the parts are and which one comes next —
which is precisely §1's problem statement ("defeats a large fraction of
prospective users before they run anything").

The vocabulary is Fluent's where OpenFOAM has the same thing under a different
name — *Boundary Conditions*, *Methods*, *Controls*, *Initialization*, *Run
Calculation* — because P3 arrives knowing those words, and P1 will meet them in
every textbook. The file each node edits is named in the task page underneath,
so the user learns the mapping rather than having to know it first (D4).

**Nodes carry ids, never display text.** The labels live in the string catalogue
(NFR-A5) and this module is Qt-free (NFR-M1), so the same outline drives the UI,
a future CLI, and the tests without any of them agreeing a second time about what
the nodes are.

**Phases, and why they gate.** Fluent runs meshing and solving as two modes of
one window, with *Switch to Solution* between them. The equivalent here is the
mesh: physics can be edited at any time, but until ``constant/polyMesh`` exists
there is nothing to run, and offering *Calculate* would produce a failure the
user cannot interpret. The gate is stated in the tree rather than enforced by a
dead button (§7.9 rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from foamwb.services.freshness import Freshness

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
    """What activating a node does."""

    GROUP = "group"
    """A header. Selecting it expands its children and shows nothing itself."""

    PAGE = "page"
    """Opens a task page, a document in the graphics window, or both."""

    ACTION = "action"
    """Runs something — the *Generate the Volume Mesh* task of Fluent's workflow."""


class Phase(StrEnum):
    """Which part of the procedure the case is in.

    Deliberately coarse. Three phases a user can name beat seven they cannot.
    """

    NO_CASE = "no_case"
    """Nothing is open. Only the file nodes mean anything."""

    MESH = "mesh"
    """A case exists but has no mesh, so nothing can be run yet."""

    ANALYSIS = "analysis"
    """A mesh exists. Physics, execution and results are all reachable."""


class StepState(StrEnum):
    """How a node is offered."""

    DONE = "done"
    """Evidence on disk says this is complete. Not a claim that it is *right*."""

    STALE = "stale"
    """Done once, but from inputs that have since changed (DEC-22).

    Workbench's ⚡ *Update Required*. Distinct from ``DONE`` because a tick on a
    result computed from a case you have since edited is the most expensive lie
    this interface could tell, and distinct from ``AVAILABLE`` because the work
    *did* happen and the old output is still there to look at."""

    AVAILABLE = "available"
    BLOCKED = "blocked"
    """Reachable in principle, but something earlier is missing. The tree says
    which, rather than leaving a dead entry the user clicks at repeatedly."""

    LOCKED = "locked"
    """Belongs to a phase the case has moved past — Fluent's meshing mode once
    the user has switched to solution mode. Reversible, never hidden."""


@dataclass(frozen=True, slots=True)
class Step:
    """One node of the outline."""

    id: str
    kind: StepKind = StepKind.PAGE
    parent: str = ""
    """Group id, empty for a top-level entry."""

    page: str = ""
    """Which task page this node opens in the column beside the outline.

    Fluent's *Task Page*: the form for the selected node. Several nodes share
    the ``settings`` page and differ only in which file's rows it shows, so the
    page is named here beside the node rather than decided in the shell."""

    document: str = ""
    """Which document this node raises in the graphics window, if any.

    Where Fluent opens a dialog — *Boundary Conditions → Edit…* — this opens a
    tab in the graphics window instead, because the boundary matrix and the
    dictionary editors are wider than a task page and a modal would trap the
    user with the outline out of reach."""

    needs_case: bool = True
    needs_mesh: bool = False

    makes_mesh: bool = False
    """Whether this node's own work would produce the mesh it needs.

    Only *Run Calculation* is both: the run plan begins with ``blockMesh``
    whenever the case has a ``blockMeshDict``, so a solver run on a freshly
    opened tutorial meshes itself. Without this flag ``needs_mesh`` blocked
    exactly the cases the plan already handles — the button that would have
    built the mesh was unreachable for want of the mesh it would have built.
    Post-processing nodes are ``needs_mesh`` alone, because nothing they do
    creates one.
    """

    required: bool = False
    """Whether this is part of the *spine* of the procedure.

    Most entries are editors: legitimate to visit at any time, in any order, and
    never "overdue". Only a few must actually happen for a case to run, and only
    those can answer "what next?" — a prompt that said *browse your files* to a
    user with an unmeshed case would be noise dressed as guidance."""

    phase: Phase | None = None
    """The phase this node belongs to, if it is gated by one."""

    @property
    def is_group(self) -> bool:
        return self.kind is StepKind.GROUP

    @property
    def is_property_page(self) -> bool:
        """Whether this node's whole content is the settings table.

        The nodes this is true of have nothing else to show, so an empty table
        is an empty *node*. Nodes that name a page of their own — geometry, the
        boundary matrix, initial conditions — have content regardless of what
        the property mapping knows about them, and must never be judged by it.
        """
        return self.page == "settings" and not self.document


#: The outline, in order. Fluent's Outline View in *shape* — Workflow, Setup,
#: Solution, Results, each a group with indented children — naming the things
#: OpenFOAM actually has.
#:
#: The Workflow group is Fluent Meshing's *Watertight Geometry Workflow*, reduced
#: to the tasks this application can perform: import a surface, describe which
#: side of it the fluid is on, set the sizing, name the boundaries, generate the
#: volume mesh. Fluent's surface-mesh and boundary-layer tasks have no
#: counterpart in a ``blockMesh``/``snappyHexMesh`` chain and are not pretended.
#:
#: Fluent's *Cell Zone Conditions*, *Report Definitions*, *Mesh Interfaces* and
#: *Named Expressions* are omitted rather than offered empty: each would open on
#: a file most cases do not have, and a node that opens a void is the dead end
#: §7.9 rule 1 forbids. They can be added as the property mapping learns the
#: files they describe.
#:
#: **Every node lives inside exactly one group.** Headers and nodes at the same
#: indentation are told apart only by a glyph, which is the single thing users
#: reported as making the earlier panel hard to read.
STEPS: tuple[Step, ...] = (
    Step("workflow", kind=StepKind.GROUP, phase=Phase.MESH),
    # Geometry before sizing, because that is the order the work happens in: a
    # case is meshed *around* an imported surface, so a user sent to the mesh
    # controls first is being shown the settings for a mesh of nothing.
    # The imported surface and the generated mesh are different things and get
    # different documents (DEC-23). One tab showing whichever happened to exist
    # would mean the picture beside the naming controls was sometimes a mesh.
    Step(
        "workflow.import",
        parent="workflow",
        page="geometry",
        document="geometry",
        phase=Phase.MESH,
    ),
    Step(
        "workflow.describe",
        parent="workflow",
        page="describe",
        document="geometry",
        phase=Phase.MESH,
    ),
    Step("workflow.sizing", parent="workflow", page="settings", phase=Phase.MESH),
    Step("workflow.boundaries", parent="workflow", page="regions", phase=Phase.MESH),
    Step(
        "workflow.volume",
        parent="workflow",
        kind=StepKind.ACTION,
        page="mesh",
        document="mesh",
        phase=Phase.MESH,
        required=True,
    ),
    Step("setup", kind=StepKind.GROUP),
    Step("setup.general", parent="setup", page="settings"),
    Step("setup.models", parent="setup", page="settings"),
    Step("setup.materials", parent="setup", page="settings"),
    Step("setup.boundary", parent="setup", page="regions", document="boundary"),
    Step("setup.reference", parent="setup", page="reference", document="vv"),
    Step("solution", kind=StepKind.GROUP),
    Step("solution.methods", parent="solution", page="settings"),
    Step("solution.controls", parent="solution", page="settings"),
    Step("solution.monitors", parent="solution", page="settings"),
    Step("solution.initialization", parent="solution", page="initial"),
    Step("solution.activities", parent="solution", page="settings"),
    Step("solution.check", parent="solution", page="check", document="verify", required=True),
    Step(
        "solution.run",
        parent="solution",
        page="run",
        document="residuals",
        needs_mesh=True,
        makes_mesh=True,
        required=True,
    ),
    Step("results", kind=StepKind.GROUP),
    Step("results.graphics", parent="results", page="post", document="mesh", needs_mesh=True),
    Step("results.plots", parent="results", page="post", document="residuals", needs_mesh=True),
    Step("results.reports", parent="results", page="post", document="vv", needs_mesh=True),
    Step("files", kind=StepKind.GROUP),
    Step("files.case", parent="files", page="files", document="files"),
)

#: The spine, in order. These are the nodes a case cannot run without, and the
#: only ones that count towards progress.
REQUIRED_STEPS: tuple[Step, ...] = tuple(step for step in STEPS if step.required)


def step_by_id(step_id: str) -> Step | None:
    return next((step for step in STEPS if step.id == step_id), None)


@dataclass
class WorkflowModel:
    """The outline's state for one case.

    Evidence-based throughout: a node is *done* because something exists on
    disk, never because the user visited the page. Marking a node complete on
    visit would tell a user their boundary conditions are set when they opened
    the editor and closed it again — the exact false reassurance §7.9 rule 6
    forbids.
    """

    case: Path | None = None
    has_geometry: bool = False
    """Whether a surface has been imported into ``constant/triSurface``.

    Evidence for the import task in exactly the sense the rest of this class
    means it: the file is there, so the task is done. Not a claim the surface is
    the right one, or in the right units — nothing on disk knows that."""

    has_mesh: bool = False

    plan_meshes: bool = False
    """Whether this case's run plan would generate the mesh before solving.

    Not evidence of anything on disk, unlike its neighbours here: it is a fact
    about what pressing *Calculate* would do, which is what decides whether a
    missing mesh is a blocker or merely the plan's first stage. Supplied by the
    caller from :func:`~foamwb.services.run.plan_generates_mesh` so the two agree
    by construction rather than by both reading the case directory."""

    has_results: bool = False
    checks_passed: bool = False
    """Whether validation found nothing that would stop a run.

    Needed because *Check Case* is part of the spine and had no evidence of its
    own, so it could never be reported done — and progress could never reach
    the total."""

    freshness: Freshness = field(default_factory=Freshness)
    """Which outputs are older than their inputs (DEC-22).

    Supplied by the caller for the same reason ``has_mesh`` is: this class
    decides how a node is *offered*, and the filesystem is read once, by the
    shell, and handed to everything that needs an answer from it."""

    empty_steps: frozenset[str] = frozenset()
    """Nodes with nothing behind them, which the outline does not draw.

    A row that opens a blank page is worse than no row: it is a promise the
    application makes and then does not keep, and the user has no way to tell it
    apart from a page that failed to load. Hidden rather than disabled, because
    "blocked" already means something here: a prerequisite is missing and doing
    the earlier step will unblock it. Nothing the user can do makes a hidden
    node appear; only shipping the mapping does — and as soon as that ships the
    node comes back on its own, because this is computed from what the mapping
    actually returns rather than from a list of exceptions.
    """

    solver: str = ""
    _overrides: dict[str, StepState] = field(default_factory=dict)

    @property
    def phase(self) -> Phase:
        if self.case is None:
            return Phase.NO_CASE
        return Phase.ANALYSIS if self.has_mesh else Phase.MESH

    #: Nodes whose completion is visible on disk, and what proves it. Anything
    #: not listed here is never reported DONE, because there is no evidence for
    #: it — an editor that was opened proves nothing about what was written.
    _EVIDENCE: ClassVar[dict] = {
        "workflow.import": lambda self: self.has_geometry,
        "workflow.volume": lambda self: self.has_mesh,
        # Passing the checks *is* the evidence. Not a claim the physics is right
        # — validation only reports self-contradiction — which is why the node
        # stays available afterwards rather than being locked away.
        "solution.check": lambda self: self.checks_passed,
        "solution.run": lambda self: self.has_results,
    }

    def awaiting_mesh(self, step: Step) -> bool:
        """Whether this node is waiting on a mesh nothing is going to produce.

        The distinction the plain ``needs_mesh and not has_mesh`` test could not
        make: *Run Calculation* on an unmeshed blockMesh case is not waiting on
        anything, it *is* the thing that meshes it. Also the reason a row gives
        for being blocked, so the explanation and the state cannot drift apart.
        """
        if not step.needs_mesh or self.has_mesh:
            return False
        return not (step.makes_mesh and self.plan_meshes)

    def state_of(self, step: Step) -> StepState:
        """How this node should be offered, given what is on disk."""
        if (forced := self._overrides.get(step.id)) is not None:
            return forced

        if step.needs_case and self.case is None:
            return StepState.BLOCKED
        if self.awaiting_mesh(step):
            return StepState.BLOCKED
        # Evidence first: a completed task reads "done" even once its phase has
        # been left behind. Fluent's workflow keeps its ticks after the switch
        # to solution mode, and reporting finished work as merely locked would
        # lose the one piece of progress the user cares about.
        proof = self._EVIDENCE.get(step.id)
        if proof is not None and proof(self):
            return StepState.STALE if self.is_stale(step) else StepState.DONE
        if self.is_locked_phase(step):
            return StepState.LOCKED
        return StepState.AVAILABLE

    #: Which node each stale artefact marks, and what it is derived from. The
    #: second entry is Workbench's downstream propagation, stated rather than
    #: computed: a result produced from a mesh that is now out of date is out of
    #: date whether or not anything the *solver* reads has changed since.
    _STALENESS: ClassVar[dict[str, tuple[str, ...]]] = {
        "workflow.volume": ("mesh_stale_because",),
        "solution.run": ("results_stale_because", "mesh_stale_because"),
    }

    def is_stale(self, step: Step) -> bool:
        """Whether this node's output was computed from inputs that have changed.

        *Check Case* is deliberately absent from the table: its verdict is
        recomputed from the case on every refresh rather than stored, so it can
        never be out of date with what it describes. Marking it would be
        theatre.
        """
        return bool(self.stale_because(step))

    def stale_because(self, step: Step) -> str:
        """The file that made this node stale, or empty. Named, so the user can act."""
        for attribute in self._STALENESS.get(step.id, ()):
            if reason := getattr(self.freshness, attribute):
                return reason
        return ""

    def set_state(self, step_id: str, state: StepState | None) -> None:
        """Override a node's state — used for evidence the model cannot see.

        ``None`` removes the override rather than setting a state, so a caller
        can undo without having to know what the computed value would be.
        """
        if state is None:
            self._overrides.pop(step_id, None)
        else:
            self._overrides[step_id] = state

    def is_offered(self, step: Step) -> bool:
        """Whether this node is drawn at all. See :attr:`empty_steps`."""
        return step.id not in self.empty_steps

    def offered_steps(self) -> tuple[Step, ...]:
        """Every node the outline draws, in order."""
        return tuple(step for step in STEPS if self.is_offered(step))

    def children_of(self, group_id: str) -> tuple[Step, ...]:
        return tuple(step for step in STEPS if step.parent == group_id and self.is_offered(step))

    @property
    def resume_step(self) -> Step | None:
        """Where the work continues once a case has just been opened.

        Opening a case has to leave the user somewhere, and the honest answer is
        the first thing they can actually do next. Taken in outline order, so a
        fresh case resumes on its geometry and a meshed one on the setup that
        follows it — a case is never opened onto a page whose prerequisites do
        not exist yet.

        The file browser is skipped because browsing is not a step. Distinct
        from :attr:`next_step`, which answers "what is outstanding in the
        spine?" and so may name a node several groups ahead.
        """
        if self.case is None:
            return None
        for step in self.offered_steps():
            if step.is_group or step.parent == "files":
                continue
            if self.state_of(step) is StepState.AVAILABLE:
                return step
        return None

    @property
    def next_step(self) -> Step | None:
        """The first required thing the user can actually do.

        Drives the "what now?" affordance. Groups are skipped — a header is not
        an action — and so is everything optional.
        """
        for step in self.offered_steps():
            if not step.required:
                continue
            # STALE counts as outstanding: the work happened, and then something
            # it depended on changed, so it has to happen again. A "what next?"
            # that skipped past it would send the user to a later step whose
            # inputs are about to be replaced.
            if self.state_of(step) in {StepState.AVAILABLE, StepState.STALE}:
                return step
        return None

    @property
    def progress(self) -> tuple[int, int]:
        """How many required nodes are done, out of how many.

        Answers "how far along am I?", which a tree of names cannot on its own.
        """
        done = sum(1 for step in REQUIRED_STEPS if self.state_of(step) is StepState.DONE)
        return done, len(REQUIRED_STEPS)

    def is_locked_phase(self, step: Step) -> bool:
        """Whether this node belongs to a phase the case has moved past.

        Locked, not hidden. Fluent greys the meshing workflow out once the user
        has switched to solution mode and offers *Switch to Meshing*; hiding it
        instead would leave a user who needs to change their mesh with no
        visible way back.
        """
        return step.phase is Phase.MESH and self.phase is Phase.ANALYSIS
