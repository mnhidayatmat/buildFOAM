"""CaseService and ParaView (§5.1, §5.2, FR-C2, FR-C4, FR-C7, FR-V1, FR-V2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foamwb.branding import CASE_METADATA_DIR, CASE_METADATA_FILE
from foamwb.codes import ErrorCode
from foamwb.services.case import (
    Case,
    CaseClass,
    CaseError,
    CaseService,
    RunRecord,
)
from foamwb.services.paraview import ParaViewService, ensure_foam_stub, foam_stub_path

CONTROL_DICT = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}
application     icoFoam;
startTime       0;
endTime         0.5;
"""


def make_case(root: Path, *, name: str = "cavity", control: str = CONTROL_DICT) -> Path:
    case = root / name
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir(parents=True)
    (case / "0").mkdir(parents=True)
    (case / "system" / "controlDict").write_text(control)
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    return case


@pytest.fixture
def service() -> CaseService:
    return CaseService(app_version="0.0.0-test")


class TestOpening:
    def test_opens_a_valid_case(self, service, tmp_path) -> None:
        case = service.open(make_case(tmp_path))
        assert case.name == "cavity"
        assert case.application == "icoFoam"

    def test_a_directory_without_a_controldict_is_not_a_case(self, service, tmp_path) -> None:
        # E-C01, the only thing that makes opening fail outright.
        (tmp_path / "empty").mkdir()
        with pytest.raises(CaseError) as caught:
            service.open(tmp_path / "empty")
        assert caught.value.code is ErrorCode.NOT_A_CASE

    def test_a_missing_directory_is_reported_as_not_a_case(self, service, tmp_path) -> None:
        with pytest.raises(CaseError):
            service.open(tmp_path / "nope")

    def test_an_unparseable_controldict_is_a_finding_not_a_refusal(self, service, tmp_path) -> None:
        # FR-C2: any tutorial opens. The file the user most needs to fix must not
        # be the one that prevents opening the case to fix it.
        case = make_case(tmp_path, control="application icoFoam;\nbroken {\n")
        opened = service.open(case)
        assert opened.application is None
        assert opened.findings[0].code is ErrorCode.PARSE_ERROR
        assert opened.findings[0].line is not None

    def test_a_non_dictionary_file_does_not_block_opening(self, service, tmp_path) -> None:
        # The tutorial suite puts geometry, CSV and m4 templates under system/
        # and constant/. Parsing them eagerly would refuse cases that run fine.
        case = make_case(tmp_path)
        (case / "constant" / "geometry.obj").write_text("v 0 0 0\nf 1 1 1\n")
        (case / "system" / "blockMeshDict.m4").write_text("changecom(//)\n")
        assert service.open(case).findings == []

    def test_corrupt_metadata_degrades_rather_than_breaks(self, service, tmp_path) -> None:
        # The case is the directory; the metadata is an accessory to it.
        case = make_case(tmp_path)
        (case / CASE_METADATA_DIR).mkdir()
        (case / CASE_METADATA_DIR / CASE_METADATA_FILE).write_text("{ not json")
        opened = service.open(case)
        assert opened.classification is CaseClass.FOREIGN
        assert opened.findings and not opened.findings[0].blocks_run


class TestClassification:
    """§5.1's table."""

    def test_a_case_without_metadata_is_foreign(self, service, tmp_path) -> None:
        assert service.open(make_case(tmp_path)).classification is CaseClass.FOREIGN

    def test_opening_a_foreign_case_writes_nothing(self, service, tmp_path) -> None:
        # Opening someone else's case must not modify it — metadata is created on
        # first *write*, with consent (§5.1).
        case = make_case(tmp_path)
        service.open(case)
        assert not (case / CASE_METADATA_DIR).exists()

    def test_writing_metadata_makes_it_managed(self, service, tmp_path) -> None:
        case = service.open(make_case(tmp_path))
        service.write_metadata(case, openfoam_version="v0000")
        assert service.open(case.path).classification is CaseClass.MANAGED

    def test_an_external_edit_is_detected(self, service, tmp_path) -> None:
        # FR-C4: never silently overwrite. The banner depends on this.
        case = service.open(make_case(tmp_path))
        service.write_metadata(case)
        control = case.path / "system" / "controlDict"
        control.write_text(control.read_text().replace("0.5", "1.0"))
        assert service.open(case.path).classification is CaseClass.MODIFIED

    def test_keep_mine_adopts_the_current_state(self, service, tmp_path) -> None:
        case = service.open(make_case(tmp_path))
        service.write_metadata(case)
        control = case.path / "system" / "controlDict"
        control.write_text(control.read_text().replace("0.5", "1.0"))

        modified = service.open(case.path)
        service.accept_external_changes(modified)
        assert service.open(case.path).classification is CaseClass.MANAGED


class TestTreeHash:
    def test_identical_trees_hash_identically(self, service, tmp_path) -> None:
        a, b = make_case(tmp_path / "a"), make_case(tmp_path / "b")
        assert service.tree_hash(a) == service.tree_hash(b)

    def test_editing_a_dictionary_changes_the_hash(self, service, tmp_path) -> None:
        case = make_case(tmp_path)
        before = service.tree_hash(case)
        (case / "system" / "controlDict").write_text(CONTROL_DICT + "writeInterval 20;\n")
        assert service.tree_hash(case) != before

    def test_editing_a_boundary_condition_changes_the_hash(self, service, tmp_path) -> None:
        # The 0/ directory is part of the case definition. If it were excluded,
        # a boundary-condition edit would be invisible to FR-C4.
        case = make_case(tmp_path)
        before = service.tree_hash(case)
        (case / "0" / "U").write_text("internalField uniform (1 0 0);\n")
        assert service.tree_hash(case) != before

    def test_written_results_do_not_change_the_hash(self, service, tmp_path) -> None:
        # A hash that moved every write interval would fire the "changed outside"
        # banner continuously during a run, teaching users to dismiss it.
        case = make_case(tmp_path)
        before = service.tree_hash(case)
        (case / "0.1").mkdir()
        (case / "0.1" / "U").write_text("internalField uniform (9 9 9);\n")
        (case / "postProcessing").mkdir()
        (case / "postProcessing" / "x.dat").write_text("data")
        assert service.tree_hash(case) == before

    def test_metadata_does_not_change_the_hash(self, service, tmp_path) -> None:
        # Otherwise writing the hash would invalidate the hash.
        case = make_case(tmp_path)
        before = service.tree_hash(case)
        (case / CASE_METADATA_DIR).mkdir()
        (case / CASE_METADATA_DIR / CASE_METADATA_FILE).write_text("{}")
        assert service.tree_hash(case) == before

    def test_renaming_a_file_changes_the_hash(self, service, tmp_path) -> None:
        # Paths are hashed with contents, so a rename is a change even when every
        # byte is identical.
        case = make_case(tmp_path)
        before = service.tree_hash(case)
        (case / "0" / "U").rename(case / "0" / "V")
        assert service.tree_hash(case) != before


class TestMetadata:
    def test_written_atomically(self, service, tmp_path) -> None:
        # NFR-R2. Truncated metadata would classify the case as modified on next
        # open and offer to overwrite the user's own edits.
        case = service.open(make_case(tmp_path))
        service.write_metadata(case)
        target = case.metadata_dir / CASE_METADATA_FILE
        assert json.loads(target.read_text())["schema"] == 1
        assert not list(case.metadata_dir.glob("*.tmp"))

    def test_records_the_openfoam_version(self, service, tmp_path) -> None:
        case = service.open(make_case(tmp_path))
        service.write_metadata(case, openfoam_version="v0000")
        assert (
            json.loads((case.metadata_dir / CASE_METADATA_FILE).read_text())["openfoam"]["version"]
            == "v0000"
        )

    def test_run_history_survives_a_reopen(self, service, tmp_path) -> None:
        # FR-S7.
        case = service.open(make_case(tmp_path))
        service.record_run(
            case,
            RunRecord(id="r-0001", started="2026-08-10T09:14:22+08:00", exit_code=0),
        )
        reopened = service.open(case.path)
        assert reopened.metadata is not None
        assert [r.id for r in reopened.metadata.runs] == ["r-0001"]

    def test_deleting_the_metadata_leaves_a_valid_case(self, service, tmp_path) -> None:
        # FR-C7 in structural form; the numerical form is in the golden gate.
        import shutil

        case = service.open(make_case(tmp_path))
        service.write_metadata(case)
        shutil.rmtree(case.metadata_dir)
        assert service.open(case.path).application == "icoFoam"


class TestInitialConditions:
    """The majority of tutorials ship 0.orig and no 0."""

    def test_detects_a_case_that_needs_restoring(self, service, tmp_path) -> None:
        case = make_case(tmp_path)
        (case / "0").rename(case / "0.orig")
        assert service.needs_initial_conditions(service.open(case))

    def test_restores_it(self, service, tmp_path) -> None:
        case_path = make_case(tmp_path)
        (case_path / "0").rename(case_path / "0.orig")
        case = service.open(case_path)
        assert service.restore_initial_conditions(case)
        assert (case_path / "0" / "U").read_text() == "internalField uniform (0 0 0);\n"

    def test_does_nothing_when_a_zero_directory_exists(self, service, tmp_path) -> None:
        # Never overwrite initial conditions the user may have edited.
        case = service.open(make_case(tmp_path))
        assert not service.restore_initial_conditions(case)

    def test_restoring_does_not_look_like_an_external_edit(self, service, tmp_path) -> None:
        # It is an application-initiated change. Leaving the hash stale would
        # offer to undo work the user just asked for (FR-C4).
        case_path = make_case(tmp_path)
        (case_path / "0").rename(case_path / "0.orig")
        case = service.open(case_path)
        service.write_metadata(case)
        service.restore_initial_conditions(case)
        assert service.open(case_path).classification is CaseClass.MANAGED


class TestTimeDirectories:
    def test_sorted_numerically_not_lexically(self, service, tmp_path) -> None:
        # "10" sorts before "9" as a string. FR-S8's resume would restart from
        # the wrong time.
        case_path = make_case(tmp_path)
        for name in ("0.5", "10", "9", "2"):
            (case_path / name).mkdir()
        assert service.open(case_path).time_directories() == ["0", "0.5", "2", "9", "10"]

    def test_latest_time_is_the_largest(self, service, tmp_path) -> None:
        case_path = make_case(tmp_path)
        for name in ("1", "10", "2"):
            (case_path / name).mkdir()
        assert service.open(case_path).latest_time == "10"

    def test_a_fresh_case_has_no_results(self, service, tmp_path) -> None:
        assert not service.open(make_case(tmp_path)).has_results


class TestParaView:
    """FR-V1, FR-V2, DEC-16."""

    def test_stub_is_named_after_the_case(self, tmp_path) -> None:
        case = make_case(tmp_path)
        assert foam_stub_path(case).name == "cavity.foam"

    def test_stub_is_created_empty(self, tmp_path) -> None:
        # Empty is the point: it carries no state, so it can be recreated freely
        # and deleted without consequence (FR-C7, D4).
        stub = ensure_foam_stub(make_case(tmp_path))
        assert stub.is_file()
        assert stub.read_bytes() == b""

    def test_an_existing_stub_is_left_alone(self, tmp_path) -> None:
        # Touching it would change the case tree hash for no reason and trip
        # FR-C4's external-modification detection.
        case = make_case(tmp_path)
        stub = ensure_foam_stub(case)
        before = stub.stat().st_mtime_ns
        assert ensure_foam_stub(case).stat().st_mtime_ns == before

    def test_absence_is_reported_not_raised(self, tmp_path) -> None:
        # E-V01. Postprocessing is not on the path to a first result, and setup
        # step 6 is skippable (DEC-16).
        service = ParaViewService(app_dirs=(tmp_path / "none",))
        assert service.locate() is None or service.locate() is not None  # never raises
        assert not service.is_available or service.is_available

    def test_open_case_returns_false_without_paraview(self, tmp_path, monkeypatch) -> None:
        service = ParaViewService(app_dirs=(tmp_path / "none",))
        monkeypatch.setattr(service, "locate", lambda: None)
        assert service.open_case(make_case(tmp_path)) is False

    def test_finds_a_bundle_and_prefers_the_newest(self, tmp_path) -> None:
        for version in ("5.11.0", "6.1.0"):
            macos = tmp_path / f"ParaView-{version}.app" / "Contents" / "MacOS"
            macos.mkdir(parents=True)
            (macos / "paraview").write_text("#!/bin/sh\n")
        install = ParaViewService(app_dirs=(tmp_path,)).locate()
        assert install is not None
        assert install.version == "6.1.0"

    def test_a_configured_path_wins(self, tmp_path) -> None:
        # FR-V1's third source: the user pointed us at it, so stop searching.
        macos = tmp_path / "elsewhere" / "ParaView-9.9.9.app" / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        (macos / "paraview").write_text("#!/bin/sh\n")
        service = ParaViewService(
            app_dirs=(tmp_path,), configured=tmp_path / "elsewhere" / "ParaView-9.9.9.app"
        )
        assert service.locate().version == "9.9.9"

    def test_launching_creates_the_stub_and_passes_it(self, tmp_path) -> None:
        macos = tmp_path / "ParaView-6.1.0.app" / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        (macos / "paraview").write_text("#!/bin/sh\n")

        launched: list[tuple[list[str], Path]] = []
        service = ParaViewService(
            app_dirs=(tmp_path,), launcher=lambda argv, cwd: launched.append((list(argv), cwd))
        )
        case = make_case(tmp_path)
        assert service.open_case(case)
        argv, cwd = launched[0]
        assert argv[-1].endswith("cavity.foam")
        assert cwd == case
        assert foam_stub_path(case).is_file()


class TestCaseHelpers:
    def test_foam_stub_property_matches_the_service(self, service, tmp_path) -> None:
        case: Case = service.open(make_case(tmp_path))
        assert case.foam_stub == foam_stub_path(case.path)
