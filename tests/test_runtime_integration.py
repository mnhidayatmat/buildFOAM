"""End-to-end against a real OpenFOAM installation (§12.5 integration).

The unit tests use a scripted session, which proves the logic but proves nothing
about the runtime: that the launcher takes an argv the way we think, that the
canary's output parses, that ``solverInfo`` writes the columns the monitor
expects. Those assumptions are exactly the ones that were wrong before this code
was written against a real install — ``foamVersion`` is not a binary, the tap
ships a cask rather than a formula, and the payload is a disk image.

Skipped when no OpenFOAM is present, so the suite stays green on a CI runner
without one. It becomes a required job at M2's close, when CI gains a Linux
runner with OpenFOAM installed for the §12.3 golden-case regression.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import require_runtime_or_skip
from foamwb.branding import CASE_METADATA_DIR
from foamwb.services import fence
from foamwb.services.monitor import MonitorService
from foamwb.services.run import (
    RunController,
    RunOutcome,
    RunPlan,
    Severity,
    Stage,
    StageState,
    StopMode,
)
from foamwb.services.runtime import RuntimeManager, RuntimeState

pytestmark = pytest.mark.requires_runtime


@pytest.fixture(scope="session")
def runtime():
    manager = RuntimeManager()
    installations = manager.discover()
    if not installations:
        require_runtime_or_skip("no OpenFOAM installation found")
    status = manager.verify(installations[0])
    if not status.is_usable:
        require_runtime_or_skip(f"OpenFOAM present but not usable: {status.detail}")
    return manager, installations[0], status


@pytest.fixture(scope="session")
def tutorials(runtime) -> Path:
    # Asked of the runtime rather than guessed: $FOAM_TUTORIALS is a mounted disk
    # image on macOS, a package directory on Debian and a distribution path under
    # WSL, and the environment already knows which.
    manager, installation, _status = runtime
    found = manager.tutorials_dir(installation)
    if found is None:
        require_runtime_or_skip(f"tutorial suite not reachable from {installation.entry_point}")
    return found


@pytest.fixture
def cavity(tutorials, tmp_path) -> Path:
    source = tutorials / "incompressible" / "icoFoam" / "cavity" / "cavity"
    if not source.is_dir():
        require_runtime_or_skip("cavity tutorial not found")
    destination = tmp_path / "cavity"
    shutil.copytree(source, destination)
    return destination


class TestDetection:
    """FR-R1 and FR-R5 against the real thing."""

    def test_reports_ready_with_a_version(self, runtime) -> None:
        _manager, _installation, status = runtime
        assert status.state is RuntimeState.READY
        assert status.openfoam_version
        assert status.reason is None

    def test_the_version_is_one_the_manifest_knows(self, runtime) -> None:
        manager, _installation, status = runtime
        assert manager.manifest.supports(status.openfoam_version)

    def test_the_canary_names_the_installed_version(self, runtime) -> None:
        # The canary reads WM_PROJECT_VERSION rather than the bundle name, so a
        # renamed bundle cannot make it report a version it does not contain.
        _manager, installation, status = runtime
        if installation.version:
            assert status.openfoam_version == installation.version


class TestSession:
    def test_runs_a_command_in_the_openfoam_environment(self, runtime) -> None:
        manager, installation, _status = runtime
        session = manager.session_for(installation)
        code, output = session.run_to_completion(["bash", "-c", "echo $WM_PROJECT_DIR"], timeout=60)
        session.close()
        assert code == 0
        assert output.strip()

    def test_paths_with_spaces_and_unicode_survive(self, runtime, tmp_path) -> None:
        # NFR-C4. argv is a token list, never a shell string, so a directory named
        # like a real student's folder is an argument rather than three of them.
        manager, installation, _status = runtime
        awkward = tmp_path / "my cases" / "föö bär"
        awkward.mkdir(parents=True)
        session = manager.session_for(installation)
        code, output = session.run_to_completion(["bash", "-c", "pwd"], cwd=awkward, timeout=60)
        session.close()
        assert code == 0
        assert "föö bär" in output


class TestFirstRealRun:
    """M2's headline: open cavity, mesh it, solve it, plot residuals."""

    def test_the_full_pipeline(self, runtime, cavity) -> None:
        manager, installation, _status = runtime
        session = manager.session_for(installation)

        control = cavity / "system" / "controlDict"
        original = control.read_text()
        control.write_text(fence.install(original, fence.solver_info_block(("U", "p"))))

        plan = RunPlan(
            case=cavity,
            stages=(
                Stage("blockMesh", argv=("blockMesh",)),
                Stage("checkMesh", argv=("checkMesh",), fail_on=Severity.ERROR),
                Stage("solve", argv=("icoFoam",), monitored=True),
            ),
        )

        streamed: list[str] = []
        controller = RunController(session, on_line=lambda _s, line: streamed.append(line))
        result = controller.execute(plan, log_dir=cavity / CASE_METADATA_DIR / "logs" / "r-0001")
        session.close()

        assert result.outcome is RunOutcome.SUCCEEDED, result.failed_stage
        assert all(s.state is StageState.SUCCEEDED for s in result.stages)
        assert len(streamed) > 100, "solver output should stream, not arrive at the end"

        # Residuals came from the injected function object, not from the log.
        series = MonitorService(cavity).series("solverInfo")
        assert series is not None
        residuals = {s.label: s for s in series.residuals}
        assert {"Ux", "Uy", "p"} <= set(residuals)

        # cavity is a converging laminar case, so every residual must fall by
        # orders of magnitude from its peak. Compared against the peak rather than
        # the first sample: the lid drives x-velocity only, so Uy_initial is
        # exactly 0.0 at the first timestep and rises before it decays. Anchoring
        # on the first value would assert that a physically correct run had failed.
        for label, s in residuals.items():
            assert max(s.values) > s.values[-1] * 100, f"{label} did not converge"
            assert s.values[-1] < 1e-4, f"{label} ended at {s.values[-1]:.2e}"

        # FR-C5: cleaning the fence restores the file byte-for-byte.
        control.write_text(fence.remove(control.read_text()))
        assert control.read_text() == original

    def test_a_log_is_written_per_stage(self, runtime, cavity) -> None:
        # FR-S7: logs retrievable per run, surviving restart.
        manager, installation, _status = runtime
        session = manager.session_for(installation)
        logs = cavity / CASE_METADATA_DIR / "logs" / "r-0001"
        plan = RunPlan(case=cavity, stages=(Stage("blockMesh", argv=("blockMesh",)),))
        RunController(session).execute(plan, log_dir=logs)
        session.close()
        assert (logs / "log.blockMesh").read_text().strip().endswith("End")

    def test_the_case_still_runs_from_a_bare_shell_after_injection(self, runtime, cavity) -> None:
        # FR-C7 / D4 in its strongest form: everything written must remain a valid
        # OpenFOAM case that a P4 user can run without this application.
        manager, installation, _status = runtime
        session = manager.session_for(installation)
        control = cavity / "system" / "controlDict"
        control.write_text(fence.install(control.read_text(), fence.solver_info_block(("U", "p"))))
        code, _ = session.run_to_completion(["blockMesh"], cwd=cavity, timeout=300)
        assert code == 0
        code, output = session.run_to_completion(["icoFoam"], cwd=cavity, timeout=300)
        session.close()
        assert code == 0, output[-500:]


class TestProcessControl:
    """FR-S10, NFR-R6 — no orphaned processes."""

    def test_force_kill_stops_a_long_running_command(self, runtime) -> None:
        manager, installation, _status = runtime
        session = manager.session_for(installation)
        process = session.run(["bash", "-c", "sleep 30"])
        process.kill()
        assert process.wait(timeout=30) != 0
        session.close()

    def test_close_reaps_everything_still_running(self, runtime) -> None:
        # Force-quitting the application must leave nothing behind.
        manager, installation, _status = runtime
        session = manager.session_for(installation)
        process = session.run(["bash", "-c", "sleep 30"])
        session.close()
        assert process.wait(timeout=30) != 0

    def test_stop_now_terminates_a_running_stage(self, runtime, cavity) -> None:
        manager, installation, _status = runtime
        session = manager.session_for(installation)
        plan = RunPlan(case=cavity, stages=(Stage("sleep", argv=("bash", "-c", "sleep 30")),))
        controller = RunController(session)

        import threading

        threading.Timer(1.0, lambda: controller.stop(StopMode.TERMINATE)).start()
        result = controller.execute(plan)
        session.close()
        assert result.outcome is not RunOutcome.SUCCEEDED
