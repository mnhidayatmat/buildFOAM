"""M5's exit criterion (§11).

    "``stopAt writeNow`` produces a loadable time directory in 100% of corpus
    cases."

Three decisions about how that is tested.

**Real tutorial cases, not the vendored corpus.** The corpus under ``tests/``
is a *dictionary* corpus for §12.2's round-trip gate: many of its files are
``#include`` fragments with no ``FoamFile`` header, and none of them is a
runnable case. Asserting a run claim against it would be asserting nothing.

**Loadable is judged by OpenFOAM, not by us.** A directory that merely contains
files with plausible names would pass a structural check while still being
truncated mid-write. ``postProcess -time <t>`` makes the solver's own I/O layer
read every field back, which is the property a user actually needs: their result
opens again.

**The stop must be mid-run.** A case that reaches ``endTime`` on its own writes a
complete final directory no matter what the stop control does, so it would pass
this test while proving nothing. Each case here is given an ``endTime`` far
beyond what it will reach, and is interrupted.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from conftest import require_runtime_or_skip
from foamwb.services.case import CaseService
from foamwb.services.run.controller import RunController, StopMode, build_plan
from foamwb.services.run.plan import StageState
from foamwb.services.runtime.manager import RuntimeManager

pytestmark = pytest.mark.requires_runtime

#: Transient solvers, so there is a run long enough to interrupt. Chosen across
#: two solver families so the assertion is not about one solver's I/O path.
CASES: tuple[tuple[str, str], ...] = (
    ("incompressible/icoFoam/cavity/cavity", "icoFoam"),
    ("incompressible/pimpleFoam/RAS/TJunction", "pimpleFoam"),
    ("multiphase/interFoam/laminar/damBreak/damBreak", "interFoam"),
)


@pytest.fixture(scope="module")
def runtime():
    manager = RuntimeManager()
    installations = manager.discover()
    if not installations:
        require_runtime_or_skip("no OpenFOAM installation found")
    status = manager.verify(installations[0])
    if not status.is_usable:
        require_runtime_or_skip(f"OpenFOAM present but not usable: {status.detail}")
    return manager, installations[0]


@pytest.fixture(scope="module")
def tutorials(runtime) -> Path:
    manager, installation = runtime
    found = manager.tutorials_dir(installation)
    if found is None or not found.is_dir():
        require_runtime_or_skip("tutorial suite not reachable")
    return found


def _runnable_or_skip(source: Path, relative: str) -> Path:
    """Skip tutorials that are templates rather than cases.

    Several tutorials ship a ``setups.orig`` and an ``Allrun`` that assembles a
    case from it, so the directory has no ``system/controlDict`` of its own —
    ``planarPoiseuille`` is one. Treating that as a failure would report a
    missing feature where there is only a differently shaped tutorial.
    """
    if not (source / "system" / "controlDict").is_file():
        pytest.skip(f"{relative} is a template, not a runnable case")
    return source


def _prepare(source: Path, destination: Path) -> Path:
    """Copy a case and push its endTime out of reach."""
    import shutil

    shutil.copytree(source, destination)
    control = destination / "system" / "controlDict"
    text = control.read_text()
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("endTime") and ";" in line:
            lines.append("endTime         100000;")
        else:
            lines.append(line)
    control.write_text("\n".join(lines) + "\n")
    return destination


def _stopped_run(manager, installation, case_path: Path, delay: float = 5.0):
    """Run the case and ask for Stop & Write once it is properly under way."""
    service = CaseService()
    case = service.open(case_path)
    # 351 tutorials ship their initial conditions as 0.orig and are unrunnable
    # without this — damBreak among them, which fails on a missing 0/p_rgh.
    service.restore_initial_conditions(case)
    service.enable_monitoring(case)

    delivered: list[bool] = []
    solving = threading.Event()

    def watch(stage: str, line: str) -> None:
        # Stop once the solver has actually advanced a timestep. A fixed delay
        # would race the meshing stages: damBreak reaches its solver in 1.6 s and
        # cavity in under one, so "wait five seconds" tests a different moment on
        # every case and on every machine.
        if stage == "solve" and line.startswith("Time = "):
            solving.set()

    controller = RunController(manager.session_for(installation), on_line=watch)
    plan = build_plan(case)

    def request_stop() -> None:
        if solving.wait(timeout=delay + 60):
            time.sleep(0.5)
            delivered.append(controller.stop(StopMode.WRITE))

    thread = threading.Thread(target=request_stop, daemon=True)
    thread.start()
    result = controller.execute(plan, log_dir=case_path / "logs")
    thread.join(timeout=30)
    return result, delivered


def _latest_time(case_path: Path) -> str | None:
    times = []
    for path in case_path.iterdir():
        if not path.is_dir():
            continue
        try:
            times.append((float(path.name), path.name))
        except ValueError:
            continue
    return max(times)[1] if times else None


@pytest.mark.parametrize("relative,solver", CASES, ids=[c[0].split("/")[-1] for c in CASES])
class TestStopAndWriteProducesALoadableResult:
    def test_the_run_stops_without_reaching_end_time(
        self, runtime, tutorials, tmp_path, relative, solver
    ) -> None:
        manager, installation = runtime
        source = _runnable_or_skip(tutorials / relative, relative)

        case_path = _prepare(source, tmp_path / "case")
        result, delivered = _stopped_run(manager, installation, case_path)

        assert delivered == [True], "the trigger file could not be written"
        solve = next(s for s in result.stages if s.name == "solve")
        assert solve.state is StageState.CANCELLED, (
            "a Stop & Write exits 0; judged on status alone the strip would claim the run completed"
        )

    def test_the_final_time_directory_is_loadable(
        self, runtime, tutorials, tmp_path, relative, solver
    ) -> None:
        """The criterion itself, judged by OpenFOAM reading the result back."""
        manager, installation = runtime
        source = _runnable_or_skip(tutorials / relative, relative)

        case_path = _prepare(source, tmp_path / "case")
        _stopped_run(manager, installation, case_path)

        latest = _latest_time(case_path)
        assert latest not in (None, "0"), "the stop produced no new time directory"

        session = manager.session_for(installation)
        process = session.run(
            ("postProcess", "-func", "mag(U)", "-time", latest),
            cwd=session.to_runtime_path(case_path),
        )
        output = list(process.lines())
        code = process.wait()
        assert code == 0, "OpenFOAM could not read the written time back:\n" + "\n".join(
            output[-15:]
        )

    def test_the_trigger_file_is_consumed(
        self, runtime, tutorials, tmp_path, relative, solver
    ) -> None:
        """The function object deletes it, which is the acknowledgement.

        One left behind would stop the *next* run on its first timestep, which
        would present as a solver fault rather than as our leftover.
        """
        from foamwb.services import fence

        manager, installation = runtime
        source = _runnable_or_skip(tutorials / relative, relative)

        case_path = _prepare(source, tmp_path / "case")
        _stopped_run(manager, installation, case_path)
        assert not (case_path / fence.STOP_TRIGGER).exists()


class TestTheStopIsWriteNowNotNextWrite:
    """The distinction the ``abort`` object's default gets wrong.

    Its documented default action is ``nextWrite``. On a case writing every
    hundred steps that means "stop in some minutes", which would look like a
    stop button that does not work.
    """

    def test_the_final_write_is_off_the_write_interval(self, runtime, tutorials, tmp_path) -> None:
        manager, installation = runtime
        source = tutorials / "incompressible" / "icoFoam" / "cavity" / "cavity"
        if not source.is_dir():
            pytest.skip("cavity not in this tutorial suite")

        case_path = _prepare(source, tmp_path / "case")
        _stopped_run(manager, installation, case_path, delay=6.0)

        latest = _latest_time(case_path)
        assert latest is not None

        # cavity writes every 20 steps of deltaT 0.005, i.e. every 0.1 s. A stop
        # at writeNow lands wherever the solver happened to be; nextWrite would
        # always land on a multiple of the interval.
        remainder = round(float(latest) % 0.1, 6)
        assert remainder not in (0.0, 0.1), (
            f"final time {latest} sits exactly on the write interval, which is "
            "what nextWrite would produce"
        )
