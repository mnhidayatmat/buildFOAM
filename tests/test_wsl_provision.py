"""M3 — WSL provisioning and the reboot (FR-R3, E-R01 to E-R05, §7.3).

FR-R3 makes two promises that pull against each other: **at most one elevation
prompt**, and **survive the reboot**. Both are properties of the *plan*, so both
are asserted here by counting rather than believed.

What is not established here is that ``wsl --install`` behaves as documented.
This file tests the decision-making — which steps, in which order, at what
privilege, and what survives a restart — on a machine with no Windows.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from foamwb.branding import WSL_DISTRO_NAME
from foamwb.codes import ErrorCode
from foamwb.services.runtime.provision import Strategy
from foamwb.services.runtime.resume import MAX_AGE, ResumeState, ResumeStore
from foamwb.services.runtime.wslprovision import (
    WslAction,
    WslPreconditions,
    reboot_falls_after,
    remaining_after,
    wsl_plan,
)

VERSION = "v2512"


def _actions(plan) -> list[str]:
    return [str(step.action) for step in plan.steps]


class TestTheCleanMachinePlan:
    def test_it_covers_features_distro_and_openfoam(self) -> None:
        plan = wsl_plan(VERSION, WslPreconditions())
        assert _actions(plan) == [
            WslAction.ENABLE_FEATURES,
            WslAction.IMPORT_DISTRO,
            WslAction.APT_INSTALL,
            WslAction.VERIFY,
        ]

    def test_it_says_what_will_be_downloaded_before_anything_is(self) -> None:
        """§7.3 step 4: nothing installs before this screen is accepted."""
        plan = wsl_plan(VERSION, WslPreconditions())
        assert plan.download_bytes > 0
        assert plan.disk_bytes > plan.download_bytes

    def test_it_ends_with_a_verification(self) -> None:
        """§7.3 step 8: "the installer said OK" is not the claim users care about."""
        assert _actions(wsl_plan(VERSION, WslPreconditions()))[-1] == WslAction.VERIFY

    def test_the_distro_is_ours_not_the_users(self) -> None:
        """DEC-12 — installing into someone's existing Ubuntu is a change they
        did not ask for and cannot easily undo."""
        plan = wsl_plan(VERSION, WslPreconditions())
        step = next(s for s in plan.steps if s.action == WslAction.IMPORT_DISTRO)
        assert step.target == WSL_DISTRO_NAME


class TestAtMostOneElevation:
    """FR-R3's cap, asserted by counting rather than assumed."""

    def test_a_clean_machine_asks_once(self) -> None:
        assert wsl_plan(VERSION, WslPreconditions()).authorisation_prompts == 1

    def test_the_elevated_step_comes_first(self) -> None:
        """Ordered by privilege, not convenience.

        Elevating late would mean the reboot lands in the middle of the
        unprivileged work and the user is prompted again on the way back.
        """
        plan = wsl_plan(VERSION, WslPreconditions())
        assert plan.steps[0].needs_authorisation
        assert not any(step.needs_authorisation for step in plan.steps[1:])

    def test_importing_and_apt_need_no_elevation(self) -> None:
        """apt runs as root *inside* the distro, which raises no UAC prompt."""
        plan = wsl_plan(VERSION, WslPreconditions(wsl_present=True, features_enabled=True))
        assert plan.authorisation_prompts == 0

    def test_a_machine_with_wsl_already_asks_for_nothing(self) -> None:
        plan = wsl_plan(
            VERSION,
            WslPreconditions(wsl_present=True, features_enabled=True, distro_present=True),
        )
        assert plan.authorisation_prompts == 0
        assert _actions(plan) == [WslAction.APT_INSTALL, WslAction.VERIFY]


class TestTheReboot:
    def test_a_clean_machine_is_warned_before_starting(self) -> None:
        """ "This will restart your computer once" is needed while deciding."""
        assert reboot_falls_after(wsl_plan(VERSION, WslPreconditions())) is not None

    def test_no_reboot_when_the_features_are_already_on(self) -> None:
        plan = wsl_plan(VERSION, WslPreconditions(wsl_present=True, features_enabled=True))
        assert reboot_falls_after(plan) is None

    def test_the_resumed_half_needs_no_elevation(self) -> None:
        """The whole point of ordering by privilege."""
        plan = wsl_plan(VERSION, WslPreconditions())
        resumed = remaining_after(plan, (str(WslAction.ENABLE_FEATURES),))
        assert resumed.authorisation_prompts == 0

    def test_the_resumed_half_drops_what_is_done(self) -> None:
        plan = wsl_plan(VERSION, WslPreconditions())
        resumed = remaining_after(plan, (str(WslAction.ENABLE_FEATURES),))
        assert _actions(resumed) == [
            WslAction.IMPORT_DISTRO,
            WslAction.APT_INSTALL,
            WslAction.VERIFY,
        ]

    def test_the_resumed_half_reports_only_its_own_download(self) -> None:
        """Restating the whole job would misdescribe what is left to do."""
        plan = wsl_plan(VERSION, WslPreconditions())
        resumed = remaining_after(plan, (str(WslAction.IMPORT_DISTRO),))
        assert resumed.download_bytes < plan.download_bytes


class TestBlockedPlans:
    """§7.3 step 2 — every failure produces a §9 code with remediation."""

    def test_virtualization_disabled(self) -> None:
        plan = wsl_plan(VERSION, WslPreconditions(virtualization_enabled=False))
        assert plan.blocked_by is ErrorCode.VIRTUALIZATION_DISABLED

    def test_no_admin_rights(self) -> None:
        plan = wsl_plan(VERSION, WslPreconditions(has_admin=False))
        assert plan.blocked_by is ErrorCode.NO_ADMIN_RIGHTS

    def test_insufficient_disk(self) -> None:
        plan = wsl_plan(VERSION, WslPreconditions(free_disk_bytes=1))
        assert plan.blocked_by is ErrorCode.INSUFFICIENT_DISK

    def test_no_network(self) -> None:
        plan = wsl_plan(VERSION, WslPreconditions(network_reachable=False))
        assert plan.blocked_by is ErrorCode.DOWNLOAD_BLOCKED

    def test_virtualization_outranks_the_others(self) -> None:
        """A firmware setting no amount of disk makes up for.

        Reporting disk first would send the user to free space and only then
        tell them their BIOS is wrong — two trips for one problem.
        """
        plan = wsl_plan(
            VERSION,
            WslPreconditions(
                virtualization_enabled=False, free_disk_bytes=1, network_reachable=False
            ),
        )
        assert plan.blocked_by is ErrorCode.VIRTUALIZATION_DISABLED

    def test_a_blocked_plan_still_shows_its_steps(self) -> None:
        """An empty list with no reason tells the user nothing (§7.9)."""
        plan = wsl_plan(VERSION, WslPreconditions(virtualization_enabled=False))
        assert plan.steps


class TestAdoption:
    def test_an_existing_openfoam_is_adopted_rather_than_reinstalled(self) -> None:
        """FR-R1: on a machine that already has it, no download is offered."""
        plan = wsl_plan(VERSION, WslPreconditions(openfoam_present=True))
        assert plan.strategy is Strategy.ADOPT
        assert plan.download_bytes == 0
        assert plan.authorisation_prompts == 0


class TestResumingAcrossAReboot:
    def test_a_saved_record_survives_a_new_process(self, tmp_path) -> None:
        path = tmp_path / "resume.json"
        ResumeStore(path).save(
            ResumeState(
                version=VERSION,
                distro=WSL_DISTRO_NAME,
                completed=(str(WslAction.ENABLE_FEATURES),),
                awaiting_reboot=True,
            )
        )
        # A different store object, as after a restart.
        recovered = ResumeStore(path).load(version=VERSION, distro=WSL_DISTRO_NAME)
        assert recovered is not None
        assert recovered.completed == (str(WslAction.ENABLE_FEATURES),)
        assert recovered.awaiting_reboot

    def test_the_whole_cycle_completes_with_one_prompt(self, tmp_path) -> None:
        """FR-R3's acceptance test, as far as it can be checked without Windows."""
        plan = wsl_plan(VERSION, WslPreconditions())
        assert plan.authorisation_prompts == 1

        store = ResumeStore(tmp_path / "resume.json")
        store.save(
            ResumeState(
                version=VERSION,
                distro=WSL_DISTRO_NAME,
                completed=(str(WslAction.ENABLE_FEATURES),),
                awaiting_reboot=True,
            )
        )
        after = ResumeStore(tmp_path / "resume.json").load(version=VERSION, distro=WSL_DISTRO_NAME)
        rest = remaining_after(plan, after.completed)

        assert plan.authorisation_prompts + rest.authorisation_prompts == 1

    def test_a_record_for_another_version_is_not_obeyed(self, tmp_path) -> None:
        path = tmp_path / "resume.json"
        ResumeStore(path).save(ResumeState(version=VERSION, distro=WSL_DISTRO_NAME))
        assert ResumeStore(path).load(version="v2506", distro=WSL_DISTRO_NAME) is None

    def test_a_record_for_another_version_is_kept_not_deleted(self, tmp_path) -> None:
        """The user may switch back; deleting would lose work."""
        path = tmp_path / "resume.json"
        ResumeStore(path).save(ResumeState(version=VERSION, distro=WSL_DISTRO_NAME))
        ResumeStore(path).load(version="v2506", distro=WSL_DISTRO_NAME)
        assert path.is_file()

    def test_a_stale_record_is_discarded(self, tmp_path) -> None:
        path = tmp_path / "resume.json"
        old = datetime.now(UTC) - MAX_AGE - timedelta(days=1)
        ResumeStore(path).save(
            ResumeState(
                version=VERSION,
                distro=WSL_DISTRO_NAME,
                created=old.isoformat(timespec="seconds"),
            )
        )
        assert ResumeStore(path).load() is None
        assert not path.exists()

    def test_a_record_with_no_timestamp_is_stale(self) -> None:
        """Treating it as fresh means a hand-edited file is trusted forever."""
        assert ResumeState(version=VERSION, distro="x", created="").is_stale

    def test_a_corrupt_record_is_discarded_rather_than_half_trusted(self, tmp_path) -> None:
        """It would otherwise parse as "nothing completed" and re-elevate."""
        path = tmp_path / "resume.json"
        path.write_text("{ truncated")
        assert ResumeStore(path).load() is None
        assert not path.exists()

    def test_a_non_object_record_is_discarded(self, tmp_path) -> None:
        path = tmp_path / "resume.json"
        path.write_text("[]")
        assert ResumeStore(path).load() is None

    def test_the_record_is_written_atomically(self, tmp_path) -> None:
        """No temporary file is left where a later read could find it."""
        path = tmp_path / "resume.json"
        ResumeStore(path).save(ResumeState(version=VERSION, distro=WSL_DISTRO_NAME))
        assert [p.name for p in tmp_path.iterdir()] == ["resume.json"]

    def test_saving_stamps_a_record_that_has_no_time(self, tmp_path) -> None:
        path = tmp_path / "resume.json"
        ResumeStore(path).save(ResumeState(version=VERSION, distro=WSL_DISTRO_NAME))
        assert json.loads(path.read_text())["created"]

    def test_clearing_is_safe_when_there_is_nothing(self, tmp_path) -> None:
        ResumeStore(tmp_path / "absent.json").clear()

    def test_completing_a_step_is_recorded_without_mutating(self) -> None:
        first = ResumeState(version=VERSION, distro="x")
        second = first.with_completed("a")
        assert first.completed == ()
        assert second.completed == ("a",)

    def test_completing_the_same_step_twice_changes_nothing(self) -> None:
        state = ResumeState(version=VERSION, distro="x").with_completed("a")
        assert state.with_completed("a").completed == ("a",)


class TestNoPendingProvisionOnAFreshMachine:
    def test_an_absent_record_is_simply_absent(self, tmp_path) -> None:
        assert not ResumeStore(tmp_path / "nothing.json").has_pending

    @pytest.mark.parametrize("bad", ["", "   ", "null"])
    def test_unusable_content_never_raises(self, tmp_path, bad: str) -> None:
        path = tmp_path / "resume.json"
        path.write_text(bad)
        assert ResumeStore(path).load() is None
