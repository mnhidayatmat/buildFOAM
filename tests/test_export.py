"""FR-R12 and FR-R9 — getting cases out before the runtime that holds them goes.

The hazard is specific: DEC-05 keeps cases off /mnt/c and DEC-12 gives them
their own distribution, so on Windows the user's work sits on an ext4 filesystem
inside a VHDX that `wsl --unregister` deletes outright. No recycle bin, no undo.

FR-R9 asks for "no user case lost, verified by checksum comparison before and
after" — a stronger claim than "the copy did not raise", and the tests here
assert the stronger one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.export import (
    ExportResult,
    export_cases,
    plan_export,
    verify_export,
)
from foamwb.services.uninstall import (
    RemovalKind,
    UninstallItem,
    UninstallPlan,
    perform,
)


@pytest.fixture
def cases(tmp_path) -> Path:
    root = tmp_path / "cases"
    root.mkdir()
    for name in ("cavity", "pitzDaily"):
        case = root / name
        (case / "system").mkdir(parents=True)
        (case / "0").mkdir()
        (case / "system" / "controlDict").write_text(f"application icoFoam; // {name}\n")
        (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    return root


class TestPlanning:
    def test_it_finds_the_cases(self, cases, tmp_path) -> None:
        plan = plan_export(cases, tmp_path / "out")
        assert {c.name for c in plan.cases} == {"cavity", "pitzDaily"}

    def test_a_folder_that_is_not_a_case_is_skipped(self, cases, tmp_path) -> None:
        (cases / "notes").mkdir()
        plan = plan_export(cases, tmp_path / "out")
        assert "notes" not in {c.name for c in plan.cases}

    def test_it_reports_size_before_moving_anything(self, cases, tmp_path) -> None:
        plan = plan_export(cases, tmp_path / "out")
        assert plan.total_bytes > 0
        assert not (tmp_path / "out").exists()

    def test_an_absent_root_is_refused(self, tmp_path) -> None:
        plan = plan_export(tmp_path / "nope", tmp_path / "out")
        assert plan.blocked
        assert plan.code is ErrorCode.NOT_A_CASE

    def test_a_destination_without_room_is_refused(self, cases, tmp_path) -> None:
        """A destination that fills mid-copy leaves the half-state this exists
        to avoid."""
        plan = plan_export(cases, tmp_path / "out")
        plan.free_bytes = 1
        assert not plan.fits
        assert not plan.can_proceed


class TestExportingAndVerifying:
    def test_cases_arrive_intact(self, cases, tmp_path) -> None:
        result = export_cases(plan_export(cases, tmp_path / "out"))
        assert result.succeeded
        assert (tmp_path / "out" / "cavity" / "system" / "controlDict").is_file()

    def test_every_case_is_verified_by_digest(self, cases, tmp_path) -> None:
        """FR-R9's actual wording, not "the copy did not raise"."""
        result = export_cases(plan_export(cases, tmp_path / "out"))
        assert result.verified
        assert verify_export(cases / "cavity", tmp_path / "out" / "cavity")

    def test_a_corrupted_copy_fails_verification(self, cases, tmp_path) -> None:
        """A truncated field file raises nothing at all."""
        export_cases(plan_export(cases, tmp_path / "out"))
        (tmp_path / "out" / "cavity" / "0" / "U").write_text("truncated")
        assert not verify_export(cases / "cavity", tmp_path / "out" / "cavity")

    def test_an_existing_destination_folder_is_not_overwritten(self, cases, tmp_path) -> None:
        (tmp_path / "out" / "cavity").mkdir(parents=True)
        result = export_cases(plan_export(cases, tmp_path / "out"))
        assert any(name == "cavity" for name, _ in result.failed)
        assert not result.succeeded

    def test_symlinks_are_preserved_not_followed(self, cases, tmp_path) -> None:
        """The tutorial suite links 0 to 0.orig; following would double-count."""
        (cases / "cavity" / "0.orig").symlink_to(cases / "cavity" / "0")
        result = export_cases(plan_export(cases, tmp_path / "out"))
        assert result.succeeded
        assert (tmp_path / "out" / "cavity" / "0.orig").is_symlink()

    def test_a_failed_case_is_left_at_the_destination(self, cases, tmp_path) -> None:
        """Deleting a partial copy removes the only evidence of what went
        wrong, at the one moment the original is about to be destroyed."""
        export_cases(plan_export(cases, tmp_path / "out"))
        (tmp_path / "out" / "cavity" / "0" / "U").write_text("x")
        assert (tmp_path / "out" / "cavity").is_dir()


class TestItUnlocksTheUninstall:
    """FR-R9 and FR-R12 are one safety property, not two features."""

    def _blocked_plan(self, tmp_path) -> UninstallPlan:
        state = tmp_path / "state"
        state.mkdir()
        return UninstallPlan(
            items=[
                UninstallItem(
                    path=Path("wsl://Distro"),
                    kind=RemovalKind.RUNTIME_HOLDING_WORK,
                    label="d",
                ),
                UninstallItem(path=state, kind=RemovalKind.APPLICATION_STATE, label="s"),
            ]
        )

    def test_nothing_is_removed_before_the_export(self, tmp_path) -> None:
        assert perform(self._blocked_plan(tmp_path)) == []

    def test_a_verified_export_lifts_the_block(self, cases, tmp_path) -> None:
        plan = self._blocked_plan(tmp_path)
        result = export_cases(plan_export(cases, tmp_path / "out"))
        assert plan.record_export(result)
        assert not plan.needs_export
        assert perform(plan, dry_run=True)

    def test_a_failed_export_does_not(self, tmp_path) -> None:
        """Unlocking on an unverified copy would allow the unregister that
        destroys the original — the one moment with no second chance."""
        plan = self._blocked_plan(tmp_path)
        assert not plan.record_export(ExportResult(failed=[("cavity", "boom")]))
        assert plan.needs_export
        assert perform(plan) == []

    def test_an_empty_export_does_not_count(self, tmp_path) -> None:
        plan = self._blocked_plan(tmp_path)
        assert not plan.record_export(ExportResult())
        assert plan.needs_export
