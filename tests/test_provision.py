"""Provisioning (FR-R3, FR-R4, FR-R10, FR-R11, §7.3).

Every test injects a command runner. Nothing here installs Homebrew, taps a
repository or downloads a cask — a suite that did would be unusable in CI and
hostile to run locally, and it would test the network rather than the code.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.runtime import load_manifest
from foamwb.services.runtime.provision import (
    ProvisionAction,
    Provisioner,
    ProvisionOutcome,
    ProvisionPlan,
    Strategy,
)


class RecordingRunner:
    """A command runner that records instead of executing."""

    def __init__(self, responses: dict[str, tuple[int, str]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        self.calls.append(tuple(argv))
        # Matched against the joined command, like `ran` — a scripted response
        # keyed on "install --cask" has to see the flag and the subcommand
        # together, and matching token-by-token would silently never fire.
        command = " ".join(argv)
        for fragment, response in self.responses.items():
            if fragment in command:
                return response
        return 0, ""

    @property
    def commands(self) -> list[str]:
        return [" ".join(call) for call in self.calls]

    def ran(self, fragment: str) -> bool:
        return any(fragment in command for command in self.commands)


@pytest.fixture
def manifest():
    return load_manifest()


def _provisioner(manifest, runner=None, *, machine="arm64", brew=True, docker=False):
    provisioner = Provisioner(manifest, runner=runner or RecordingRunner(), machine=machine)
    provisioner.homebrew_path = lambda: "/opt/homebrew/bin/brew" if brew else None  # type: ignore[method-assign]
    provisioner.docker_path = lambda: "/usr/local/bin/docker" if docker else None  # type: ignore[method-assign]
    provisioner.free_disk_bytes = lambda path=None: 500_000_000_000  # type: ignore[method-assign]
    return provisioner


class TestPlanning:
    """§7.3 step 4 — nothing installs before the plan is accepted."""

    def test_planning_runs_no_commands(self, manifest) -> None:
        # The review screen must be safe to reach. A planner that probed by
        # running `brew install --dry-run` would violate its own promise.
        runner = RecordingRunner()
        _provisioner(manifest, runner).plan()
        assert runner.calls == []

    def test_an_existing_runtime_is_adopted_not_reinstalled(self, manifest) -> None:
        # FR-R1. Downloading 1.4 GB onto a machine that did not need it is the
        # fastest way to lose a user in the first five minutes.
        plan = _provisioner(manifest).plan(already_usable=True)
        assert plan.strategy is Strategy.ADOPT
        assert plan.download_bytes == 0
        assert not plan.installs_anything

    def test_homebrew_present_means_no_password_prompt(self, manifest) -> None:
        # FR-R11's first rule: if Homebrew is already there, use it and never
        # prompt.
        plan = _provisioner(manifest, brew=True).plan()
        assert plan.strategy is Strategy.HOMEBREW
        assert plan.authorisation_prompts == 0
        assert not any(step.action is ProvisionAction.INSTALL_HOMEBREW for step in plan.steps)

    def test_homebrew_absent_adds_one_authorised_step(self, manifest) -> None:
        plan = _provisioner(manifest, brew=False).plan()
        actions = [step.action for step in plan.steps]
        assert ProvisionAction.INSTALL_HOMEBREW in actions
        assert plan.authorisation_prompts == 1

    def test_never_more_than_one_authorisation_prompt(self, manifest) -> None:
        # FR-R3 caps elevation at one prompt for the whole provisioning run.
        for brew in (True, False):
            assert _provisioner(manifest, brew=brew).plan().authorisation_prompts <= 1

    def test_the_plan_states_its_cost(self, manifest) -> None:
        # §7.3 step 4 requires "how many bytes downloaded and occupied".
        plan = _provisioner(manifest).plan()
        assert plan.download_bytes > 0
        assert plan.disk_bytes > plan.download_bytes

    def test_the_plan_ends_by_verifying(self, manifest) -> None:
        # §7.3 step 8: the wizard is not done until a real simulation has run.
        # A plan that ended at "installed" would be claiming the wrong thing.
        plan = _provisioner(manifest).plan()
        assert plan.steps[-1].action is ProvisionAction.VERIFY

    def test_taps_before_installing(self, manifest) -> None:
        plan = _provisioner(manifest).plan()
        actions = [step.action for step in plan.steps]
        assert actions.index(ProvisionAction.ADD_TAP) < actions.index(ProvisionAction.INSTALL_CASK)

    def test_insufficient_disk_blocks_before_downloading(self, manifest) -> None:
        # E-R05 belongs on the system-check screen, not after 1.4 GB has landed.
        provisioner = _provisioner(manifest)
        provisioner.free_disk_bytes = lambda path=None: 1_000_000  # type: ignore[method-assign]
        plan = provisioner.plan()
        assert plan.blocked_by is ErrorCode.INSUFFICIENT_DISK

    def test_intel_hardware_is_routed_away_from_the_tap(self, manifest) -> None:
        # E-R08 / §3.3: the tap's Intel support ends at an older release, so
        # offering it on Intel would be offering a path that cannot work.
        plan = _provisioner(manifest, machine="x86_64", docker=True).plan()
        assert plan.strategy is Strategy.DOCKER
        assert plan.blocked_by is ErrorCode.MACOS_INTEL_UNSUPPORTED

    def test_intel_without_docker_is_unavailable_not_silently_broken(self, manifest) -> None:
        plan = _provisioner(manifest, machine="x86_64", docker=False).plan()
        assert plan.strategy is Strategy.UNAVAILABLE
        assert plan.blocked_by is not None

    def test_an_unknown_version_is_refused(self, manifest) -> None:
        from foamwb.services.runtime.manifest import ManifestError

        with pytest.raises(ManifestError):
            _provisioner(manifest).plan("v9999")


class TestExecution:
    def test_runs_the_steps_in_order(self, manifest) -> None:
        runner = RecordingRunner({"list --cask": (1, "not installed")})
        provisioner = _provisioner(manifest, runner)
        result = provisioner.provision(provisioner.plan())
        assert result.succeeded
        assert runner.ran("tap")
        assert runner.ran("install --cask")

    def test_reports_progress_before_each_step(self, manifest) -> None:
        # §7.9 rule 2: anything that downloads or takes over five seconds shows
        # progress. Reported *before* the step so a long download is not silent.
        seen: list[ProvisionAction] = []
        provisioner = _provisioner(manifest, RecordingRunner({"list --cask": (1, "")}))
        plan = provisioner.plan()
        provisioner.provision(plan, on_progress=lambda step: seen.append(step.action))
        assert seen == [step.action for step in plan.steps]

    def test_an_already_installed_cask_is_not_reinstalled(self, manifest) -> None:
        # NFR-R4: re-running the wizard after a failure converges to the same
        # state. A resumed run must not re-download 1.4 GB it already has.
        runner = RecordingRunner({"list --cask": (0, "openfoam")})
        provisioner = _provisioner(manifest, runner)
        assert provisioner.provision(provisioner.plan()).succeeded
        assert not runner.ran("install --cask")

    def test_a_brew_failure_carries_the_tools_own_output(self, manifest) -> None:
        # E-R06 shows the last lines of what brew said. A paraphrase would strip
        # exactly the detail that makes the failure diagnosable.
        runner = RecordingRunner(
            {"tap": (1, "Error: Failure while executing git clone\nfatal: unable to access")}
        )
        provisioner = _provisioner(manifest, runner)
        result = provisioner.provision(provisioner.plan())
        assert result.outcome is ProvisionOutcome.FAILED
        assert result.reason is ErrorCode.PACKAGE_MANAGER_FAILED
        assert "unable to access" in result.detail
        assert result.failed_step.action is ProvisionAction.ADD_TAP

    def test_stops_at_the_first_failure(self, manifest) -> None:
        runner = RecordingRunner({"tap": (1, "boom")})
        provisioner = _provisioner(manifest, runner)
        provisioner.provision(provisioner.plan())
        assert not runner.ran("install --cask")

    def test_completed_steps_are_reported_so_a_resume_can_skip_them(self, manifest) -> None:
        # Both scripted: `list --cask` must report the cask absent, or the
        # install step is correctly skipped and there is nothing to fail.
        runner = RecordingRunner({"list --cask": (1, ""), "install --cask": (1, "download failed")})
        provisioner = _provisioner(manifest, runner)
        result = provisioner.provision(provisioner.plan())
        assert [s.action for s in result.completed] == [ProvisionAction.ADD_TAP]

    def test_a_blocked_plan_runs_nothing(self, manifest) -> None:
        runner = RecordingRunner()
        provisioner = _provisioner(manifest, runner)
        result = provisioner.provision(
            ProvisionPlan(
                strategy=Strategy.HOMEBREW,
                version="v0000",
                blocked_by=ErrorCode.INSUFFICIENT_DISK,
            )
        )
        assert result.outcome is ProvisionOutcome.BLOCKED
        assert runner.calls == []


class TestHomebrewAuthorisation:
    """FR-R11 — a system password dialog, never a terminal."""

    def test_uses_the_native_authorisation_dialog(self, manifest) -> None:
        # A GUI wizard cannot answer a TTY sudo prompt. osascript's "with
        # administrator privileges" raises the macOS dialog instead, which is the
        # hole §3.3 identifies in the zero-terminal promise.
        runner = RecordingRunner({"list --cask": (1, "")})
        provisioner = _provisioner(manifest, runner, brew=False)
        # brew appears once Homebrew is installed; simulate that for later steps.
        provisioner.provision(provisioner.plan())
        assert runner.ran("osascript")
        assert runner.ran("with administrator privileges")

    def test_drives_the_installer_non_interactively(self, manifest) -> None:
        runner = RecordingRunner({"list --cask": (1, "")})
        provisioner = _provisioner(manifest, runner, brew=False)
        provisioner.provision(provisioner.plan())
        assert runner.ran("NONINTERACTIVE=1")

    def test_a_declined_dialog_is_a_decision_not_a_crash(self, manifest) -> None:
        # FR-R11: refusing routes to the Docker path rather than dead-ending, so
        # the refusal has to arrive as a specific code the wizard can branch on.
        runner = RecordingRunner({"osascript": (1, "User canceled. (-128)")})
        provisioner = _provisioner(manifest, runner, brew=False)
        result = provisioner.provision(provisioner.plan())
        assert result.outcome is ProvisionOutcome.FAILED
        assert result.reason is ErrorCode.NO_ADMIN_RIGHTS

    def test_an_installer_failure_is_distinguished_from_a_refusal(self, manifest) -> None:
        # They lead to different remedies: a refusal offers Docker, a failure
        # offers a retry and a diagnostics bundle.
        runner = RecordingRunner({"osascript": (1, "curl: (6) Could not resolve host")})
        provisioner = _provisioner(manifest, runner, brew=False)
        result = provisioner.provision(provisioner.plan())
        assert result.reason is ErrorCode.PACKAGE_MANAGER_FAILED


class TestDockerHonesty:
    """FR-R10 is planned but not yet executable; the plan must say so."""

    def test_the_docker_plan_is_marked_blocked(self, manifest) -> None:
        # A wizard that "succeeded" into a runtime nothing can talk to would be
        # worse than one that says plainly it cannot help yet.
        plan = _provisioner(manifest, machine="x86_64", docker=True).plan()
        assert plan.strategy is Strategy.DOCKER
        assert plan.blocked_by is not None

    def test_executing_it_refuses_rather_than_pretending(self, manifest) -> None:
        runner = RecordingRunner()
        provisioner = _provisioner(manifest, runner, machine="x86_64", docker=True)
        result = provisioner.provision(provisioner.plan())
        assert not result.succeeded
        assert runner.calls == []


class TestManagerIntegration:
    def test_plan_provision_adopts_what_is_already_working(self, manifest, tmp_path) -> None:
        from foamwb.services.runtime import RuntimeManager

        bundle = tmp_path / "OpenFOAM-v2512.app"
        launcher = bundle / "Contents" / "Resources" / "etc" / "openfoam"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\necho v2512\n")
        launcher.chmod(0o755)

        manager = RuntimeManager(application_dirs=(tmp_path,))
        assert manager.plan_provision("v2512").strategy is Strategy.ADOPT

    def test_a_failed_provision_never_reports_ready(self, manifest, tmp_path) -> None:
        # FR-R5 again: "the installer said OK" and "this machine can run CFD" are
        # different claims, and only the second one matters.
        from foamwb.services.runtime import RuntimeManager

        runner = RecordingRunner({"tap": (1, "boom")})
        provisioner = _provisioner(manifest, runner)
        manager = RuntimeManager(application_dirs=(tmp_path,), provisioner=provisioner)
        result, status = manager.provision(provisioner.plan())
        assert not result.succeeded
        assert not status.is_usable
        assert status.reason is not None
