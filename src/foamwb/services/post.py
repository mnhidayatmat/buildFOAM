"""Standard post-processing utilities (FR-V5).

``postProcess -func``, ``foamToVTK`` and ``sample`` run through the same
:class:`RuntimeSession` as the solver, for the same reason everything else does:
a case path with a space or a ``$`` in it stays one argument, and the WSL bridge
gets these for free at M3 rather than needing a second implementation.

**The function names are data, not a hard-coded list.** ``postProcess -func`` is
open-ended — OpenFOAM ships dozens and a user may have their own — so this module
offers a small curated set with plain-language descriptions and accepts anything
else typed in. A closed list would make the useful ones unreachable and would
need editing every release.

Utilities write into ``postProcessing/``, which :mod:`foamwb.services.case`
already excludes from the case tree hash. Running one therefore does not make a
managed case look externally modified (FR-C4) — worth stating, because the
opposite would produce a spurious "this case changed outside the application"
banner every time a user sampled a line.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.runtime.session import RuntimeSession

__all__ = ["FUNCTIONS", "PostFunction", "PostResult", "PostService", "output_roots"]

_log = get_logger("services.post")


@dataclass(frozen=True, slots=True)
class PostFunction:
    """One offered operation, named as a user would describe it."""

    key: str
    """What goes after ``-func``, or the utility name for a non-postProcess entry."""

    label: str
    summary: str
    utility: str = "postProcess"
    needs_argument: bool = False
    """Whether ``key`` is a template the user must complete, e.g. a patch name."""

    def argv(self, *, argument: str = "", time: str = "") -> tuple[str, ...]:
        """The command line, as a token list. Never a shell string."""
        if self.utility != "postProcess":
            tokens = [self.utility]
        else:
            if self.needs_argument and not argument:
                raise ValueError(f"{self.label} needs a value")
            spec = self.key.format(argument) if self.needs_argument else self.key
            tokens = ["postProcess", "-func", spec]

        if time:
            tokens += ["-time", time]
        return tuple(tokens)


#: The curated set. Deliberately short: §7.6 offers the operations a taught
#: course actually uses, and a menu of forty function objects is a reference
#: manual rather than a user interface.
FUNCTIONS: tuple[PostFunction, ...] = (
    PostFunction(
        key="mag(U)",
        label="Velocity magnitude",
        summary="Adds |U| as a field, which is what most contour plots want.",
    ),
    PostFunction(
        key="vorticity",
        label="Vorticity",
        summary="Curl of the velocity field — shows rotation and shed structures.",
    ),
    PostFunction(
        key="Q",
        label="Q-criterion",
        summary="The usual vortex-identification field for iso-surfaces.",
    ),
    PostFunction(
        key="wallShearStress",
        label="Wall shear stress",
        summary="Shear on every wall patch. Needed for drag and skin friction.",
    ),
    PostFunction(
        key="yPlus",
        label="y+",
        summary="Writes y+ per wall patch — the input to the V&V audit.",
    ),
    PostFunction(
        key="patchAverage(name={0},field=p)",
        label="Average over a patch",
        summary="Area-weighted mean of a field on one patch.",
        needs_argument=True,
    ),
    PostFunction(
        key="foamToVTK",
        label="Export to VTK",
        summary="Writes VTK files for ParaView or another reader to open.",
        utility="foamToVTK",
    ),
)


def output_roots(case: Path) -> tuple[Path, ...]:
    """Every place these utilities write. Measured, not assumed.

    Three different destinations, which a single ``postProcessing/`` assumption
    gets wrong for most of the set:

    * **time directories** — ``mag(U)``, ``vorticity`` and ``Q`` add a *field*
      to each time they process;
    * **postProcessing/** — sampling and patch functions, and ``yPlus``;
    * **VTK/** — ``foamToVTK``.

    Watching only the middle one reported "produced nothing" for three functions
    that had just written a field into every time directory in the case.
    """
    roots = [case / "postProcessing", case / "VTK"]
    roots += [path for path in case.iterdir() if path.is_dir() and _is_time(path.name)]
    return tuple(roots)


def _is_time(name: str) -> bool:
    try:
        float(name)
    except ValueError:
        return False
    return True


@dataclass(slots=True)
class PostResult:
    function: PostFunction
    exit_code: int
    lines: list[str]
    written: list[Path]

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

    @property
    def produced_nothing(self) -> bool:
        """Exit 0 with no output files.

        A real outcome rather than a failure: ``yPlus`` on a case with no wall
        patches succeeds and writes nothing, and reporting that as an error
        would be wrong. The caller says so plainly instead.
        """
        return self.succeeded and not self.written


class PostService:
    """Runs post utilities against a case (FR-V5)."""

    def __init__(self, session: RuntimeSession) -> None:
        self._session = session

    def run(
        self,
        case: Path,
        function: PostFunction,
        *,
        argument: str = "",
        time: str = "",
        on_line: Callable[[str], None] | None = None,
    ) -> PostResult:
        """Run one utility, streaming its output as it arrives.

        Streamed rather than captured and returned at the end: ``foamToVTK`` on a
        large transient case runs for minutes, and a UI with no output until it
        finishes is indistinguishable from one that has hung.
        """
        argv = function.argv(argument=argument, time=time)
        before = _snapshot(case)

        log_event(_log, Event.COMMAND_BEGIN, component="post", argv=list(argv))
        process = self._session.run(argv, cwd=PurePosixPath(self._session.to_runtime_path(case)))

        collected: list[str] = []
        for line in process.lines():
            collected.append(line)
            if on_line is not None:
                on_line(line)
        code = process.wait()

        written = sorted(_snapshot(case) - before)
        log_event(_log, Event.COMMAND_END, component="post", exit_code=code, files=len(written))
        return PostResult(function=function, exit_code=code, lines=collected, written=written)

    @staticmethod
    def available(names: Sequence[str] = ()) -> tuple[PostFunction, ...]:
        """The offered set, optionally narrowed to given keys."""
        if not names:
            return FUNCTIONS
        wanted = set(names)
        return tuple(f for f in FUNCTIONS if f.key in wanted or f.utility in wanted)


def _snapshot(case: Path) -> set[Path]:
    """Every output file currently in the case, for diffing what a run produced.

    Compared by *set difference* rather than by timestamp: a utility rerun over
    the same time directory rewrites files in place, and a modification-time
    comparison would report the whole tree as new every time.
    """
    found: set[Path] = set()
    if not case.is_dir():
        return found
    for root in output_roots(case):
        if root.is_dir():
            found.update(path for path in root.rglob("*") if path.is_file())
    return found
