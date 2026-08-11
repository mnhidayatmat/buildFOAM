"""The gaps the readiness review found, now closed (FR-A5, FR-C6, FR-C8, NFR-P2).

Each of these was a v1.0 requirement with no implementation. They are grouped
because they share a provenance, not a subsystem.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from foamwb.branding import WSL_DISTRO_NAME
from foamwb.codes import ErrorCode
from foamwb.services.duplicate import DuplicateError, duplicate_case, plan_duplicate
from foamwb.services.storage import StorageKind, classify_path
from foamwb.services.update import UpdateOutcome, UpdateService, UpdateStage


@pytest.fixture
def case(tmp_path) -> Path:
    root = tmp_path / "cavity"
    (root / "system").mkdir(parents=True)
    (root / "constant").mkdir()
    (root / "0").mkdir()
    (root / "system" / "controlDict").write_text("application icoFoam;\nendTime 0.5;\n")
    (root / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    return root


class TestUpdateRollback:
    """FR-A5 — a failed update restores the prior version and reports it."""

    def _service(self, tmp_path) -> UpdateService:
        return UpdateService(tmp_path / "update.json")

    def test_a_confirmed_launch_commits(self, tmp_path) -> None:
        svc = self._service(tmp_path)
        record = svc.begin(from_version="1.0.0", to_version="1.0.1")
        svc.advance(record, UpdateStage.ACTIVATED, previous_path=str(tmp_path / "prev"))
        assert svc.confirm_launch().stage is UpdateStage.COMMITTED
        assert not svc.read().needs_rollback

    def test_an_activated_update_that_never_started_needs_undoing(self, tmp_path) -> None:
        """The decisive failure is only visible from a *later* process."""
        svc = self._service(tmp_path)
        record = svc.begin(from_version="1.0.0", to_version="1.0.1")
        svc.advance(record, UpdateStage.ACTIVATED, previous_path=str(tmp_path / "prev"))

        later = UpdateService(tmp_path / "update.json")
        assert later.read().needs_rollback

    def test_rollback_restores_the_previous_version(self, tmp_path) -> None:
        install = tmp_path / "app"
        install.mkdir()
        (install / "broken").write_text("new")
        previous = tmp_path / "app.previous"
        previous.mkdir()
        (previous / "working").write_text("old")

        svc = self._service(tmp_path)
        record = svc.begin(from_version="1.0.0", to_version="1.0.1")
        svc.advance(record, UpdateStage.ACTIVATED, previous_path=str(previous))

        assert svc.roll_back(svc.read(), install_root=install) is UpdateOutcome.ROLLED_BACK
        assert (install / "working").is_file()
        assert not (install / "broken").exists()

    def test_rollback_is_a_rename_not_a_download(self, tmp_path) -> None:
        """The machine whose update failed is often the machine whose network
        caused it."""
        install = tmp_path / "app"
        install.mkdir()
        previous = tmp_path / "app.previous"
        previous.mkdir()
        (previous / "v1").write_text("x")

        svc = self._service(tmp_path)
        record = svc.begin(from_version="1", to_version="2")
        svc.advance(record, UpdateStage.ACTIVATED, previous_path=str(previous))
        svc.roll_back(svc.read(), install_root=install)
        assert not previous.exists()

    def test_no_previous_version_is_the_loudest_failure(self, tmp_path) -> None:
        install = tmp_path / "app"
        install.mkdir()
        svc = self._service(tmp_path)
        record = svc.begin(from_version="1", to_version="2")
        svc.advance(record, UpdateStage.ACTIVATED, previous_path=str(tmp_path / "gone"))

        assert svc.roll_back(svc.read(), install_root=install) is UpdateOutcome.FAILED
        assert svc.read().detail

    def test_a_rolled_back_update_still_reports_a_code(self, tmp_path) -> None:
        """Silence would leave the user believing the update happened."""
        assert UpdateService.code_for(UpdateOutcome.ROLLED_BACK) is ErrorCode.UPDATE_FAILED
        assert UpdateService.code_for(UpdateOutcome.SUCCEEDED) is None

    def test_stages_before_activation_need_no_rollback(self, tmp_path) -> None:
        svc = self._service(tmp_path)
        record = svc.begin(from_version="1", to_version="2")
        for stage in (UpdateStage.DOWNLOADED, UpdateStage.VERIFIED, UpdateStage.STAGED):
            svc.advance(record, stage)
            assert not svc.read().needs_rollback

    def test_an_unreadable_record_is_idle_not_an_error(self, tmp_path) -> None:
        """An application that refuses to start because its updater is confused
        is a worse failure than the one being guarded against."""
        path = tmp_path / "update.json"
        path.write_text("{ truncated")
        assert UpdateService(path).read().stage is UpdateStage.IDLE

    def test_a_stage_from_a_future_version_is_not_acted_on(self, tmp_path) -> None:
        path = tmp_path / "update.json"
        path.write_text('{"stage": "teleported", "previous_path": "/x"}')
        record = UpdateService(path).read()
        assert record.stage is UpdateStage.IDLE
        assert not record.needs_rollback


class TestSlowStorage:
    """FR-C8 — detected before the run, when the warning is still worth having."""

    @pytest.mark.parametrize(
        ("path", "kind"),
        [
            ("/Users/x/cases/cavity", StorageKind.LOCAL),
            ("/home/u/cases/cavity", StorageKind.LOCAL),
            (r"\\fileserver\share\cavity", StorageKind.NETWORK),
            ("/Users/x/Dropbox/cases/cavity", StorageKind.SYNCED),
            ("/Users/x/OneDrive/uni/cavity", StorageKind.SYNCED),
            ("/mnt/c/Users/x/cavity", StorageKind.CROSS_OS),
        ],
    )
    def test_paths_are_classified(self, path: str, kind: StorageKind) -> None:
        assert classify_path(Path(path)).kind is kind

    def test_the_distro_share_is_not_slow(self) -> None:
        """DEC-05 puts cases inside the distro deliberately; warning about the
        recommended location would be exactly wrong."""
        verdict = classify_path(Path(rf"\\wsl.localhost\{WSL_DISTRO_NAME}\home\u\cavity"))
        assert not verdict.is_slow

    def test_a_similarly_named_local_folder_is_not_flagged(self) -> None:
        """Matched on a path component, so `my-dropbox-notes` is left alone."""
        assert not classify_path(Path("/Users/x/my-dropbox-notes/cavity")).is_slow

    def test_a_slow_path_carries_its_code_and_a_reason(self) -> None:
        verdict = classify_path(Path("/mnt/c/Users/x/cavity"))
        assert verdict.code is ErrorCode.SLOW_PATH
        assert len(verdict.reason) > 40

    def test_it_is_a_warning_not_a_refusal(self) -> None:
        """A shared drive may be the only place a student can write."""
        verdict = classify_path(Path(r"\\server\share\c"))
        assert verdict.is_slow
        assert hasattr(verdict, "reason")


class TestDuplicatingACase:
    """FR-C6 — copy a case, rewriting no absolute paths."""

    def test_the_definition_is_copied(self, case, tmp_path) -> None:
        plan = plan_duplicate(case, tmp_path / "copy")
        out = duplicate_case(plan)
        assert (out / "system" / "controlDict").is_file()
        assert (out / "0" / "U").is_file()

    def test_files_are_byte_identical(self, case, tmp_path) -> None:
        import filecmp

        out = duplicate_case(plan_duplicate(case, tmp_path / "copy"))
        assert filecmp.cmp(
            case / "system" / "controlDict",
            out / "system" / "controlDict",
            shallow=False,
        )

    def test_absolute_paths_are_not_rewritten(self, case, tmp_path) -> None:
        """Rewriting them would change what the case computes."""
        (case / "system" / "withPath").write_text('include "/opt/shared/x.dict";\n')
        out = duplicate_case(plan_duplicate(case, tmp_path / "copy"))
        assert '"/opt/shared/x.dict"' in (out / "system" / "withPath").read_text()

    def test_absolute_paths_are_reported(self, case, tmp_path) -> None:
        """Only the user knows whether a path should follow the copy."""
        (case / "system" / "withPath").write_text('include "/opt/shared/x.dict";\n')
        plan = plan_duplicate(case, tmp_path / "copy")
        assert any("withPath" in ref for ref in plan.absolute_references)

    def test_results_are_left_behind_by_default(self, case, tmp_path) -> None:
        (case / "0.5").mkdir()
        (case / "0.5" / "U").write_text("x")
        plan = plan_duplicate(case, tmp_path / "copy")
        assert plan.excluded_results == 1
        out = duplicate_case(plan)
        assert not (out / "0.5").exists()

    def test_results_can_be_asked_for(self, case, tmp_path) -> None:
        (case / "0.5").mkdir()
        (case / "0.5" / "U").write_text("x")
        out = duplicate_case(plan_duplicate(case, tmp_path / "copy", include_results=True))
        assert (out / "0.5" / "U").is_file()

    def test_our_metadata_is_never_copied(self, case, tmp_path) -> None:
        """A duplicate has not been run and must not claim a history."""
        from foamwb.branding import CASE_METADATA_DIR

        (case / CASE_METADATA_DIR).mkdir()
        (case / CASE_METADATA_DIR / "case.json").write_text("{}")
        out = duplicate_case(plan_duplicate(case, tmp_path / "copy"))
        assert not (out / CASE_METADATA_DIR).exists()

    def test_an_existing_destination_is_refused(self, case, tmp_path) -> None:
        (tmp_path / "copy").mkdir()
        with pytest.raises(DuplicateError) as caught:
            plan_duplicate(case, tmp_path / "copy")
        assert caught.value.code is ErrorCode.DESTINATION_EXISTS

    def test_a_non_case_is_refused(self, tmp_path) -> None:
        (tmp_path / "notacase").mkdir()
        with pytest.raises(DuplicateError):
            plan_duplicate(tmp_path / "notacase", tmp_path / "copy")

    def test_an_interrupted_copy_leaves_no_half_case(self, case, tmp_path) -> None:
        """A partial directory that looks openable is worse than none."""
        plan = plan_duplicate(case, tmp_path / "copy")
        plan.files.append(case / "does-not-exist")
        with pytest.raises(DuplicateError):
            duplicate_case(plan)
        assert not (tmp_path / "copy").exists()
        assert not list(tmp_path.glob(".*partial"))


class TestPerformanceStaysTrue:
    """NFR-P2 — measured during the readiness review; regression-tested here."""

    def test_case_open_and_validate_is_well_inside_budget(self, tmp_path) -> None:
        from foamwb.services.case import CaseService
        from foamwb.services.validation import validate_case

        root = tmp_path / "big"
        (root / "system").mkdir(parents=True)
        (root / "constant").mkdir()
        (root / "0").mkdir()
        (root / "system" / "controlDict").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
            "application icoFoam;\nstartFrom startTime;\nstartTime 0;\nstopAt endTime;\n"
            "endTime 0.5;\ndeltaT 0.005;\nwriteControl timeStep;\nwriteInterval 20;\n"
        )
        for index in range(200):
            (root / "0" / f"field{index}").write_text(
                "dimensions [0 1 -1 0 0 0 0];\ninternalField uniform 0;\nboundaryField {}\n"
            )

        service = CaseService()
        started = time.perf_counter()
        validate_case(service.open(root))
        elapsed = time.perf_counter() - started

        # NFR-P2 budgets 2 s. Measured at ~26 ms on the development machine; a
        # tenth of the budget still leaves a 20x margin and will not flake on a
        # loaded CI box.
        assert elapsed < 0.2, f"took {elapsed * 1000:.0f} ms against a 2000 ms budget"
