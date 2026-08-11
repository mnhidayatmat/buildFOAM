"""Meshing utilities and the quality summary (FR-P5, FR-P9, E-S02)."""

from __future__ import annotations

import pytest

from foamwb.codes import Severity
from foamwb.services.mesh import (
    UTILITIES,
    Verdict,
    available_utilities,
    parse_check_mesh,
    utility_plan,
)

CHECK_MESH_OK = """\
Mesh stats
    points:           2226
    cells:            12225
Checking geometry...
    Max aspect ratio = 8.1407 OK.
    Mesh non-orthogonality Max: 5.95045 average: 1.63034
    Max skewness = 0.260575 OK.
Mesh OK.
End
"""

CHECK_MESH_BAD = """\
Mesh stats
    cells:            400
Checking geometry...
    Max aspect ratio = 2500 OK.
 ***Number of edges not aligned with or perpendicular to non-empty directions: 12
    Mesh non-orthogonality Max: 82.4 average: 20.1
    Max skewness = 14.2 FAILED.
Failed 2 mesh checks.
End
"""


class TestUtilities:
    def test_the_prd_list_is_covered(self) -> None:
        # §6.3 names these six by name.
        assert {u.name for u in UTILITIES} == {
            "blockMesh",
            "snappyHexMesh",
            "checkMesh",
            "surfaceFeatureExtract",
            "renumberMesh",
            "transformPoints",
        }

    def test_checkmesh_is_judged_on_output_not_exit_code(self) -> None:
        # E-S02: it exits 0 while reporting mesh errors, and trusting that would
        # let a broken mesh reach the solver.
        check = next(u for u in UTILITIES if u.name == "checkMesh")
        assert check.fail_on is Severity.ERROR

    def test_a_utility_is_a_one_stage_plan(self, tmp_path) -> None:
        # It runs through the same controller as a solver; a second execution
        # path would be a second set of bugs.
        plan = utility_plan(UTILITIES[0], tmp_path)
        assert len(plan.stages) == 1
        assert plan.render() == (("blockMesh",),)

    def test_only_utilities_the_case_can_run_are_offered(self, tmp_path) -> None:
        # A snappyHexMesh button on a case with no snappyHexMeshDict offers a
        # failure the user could not have avoided.
        (tmp_path / "system").mkdir()
        (tmp_path / "system" / "blockMeshDict").write_text("x")
        assert [u.name for u in available_utilities(tmp_path, meshed=False)] == ["blockMesh"]

    def test_mesh_consumers_appear_once_a_mesh_exists(self, tmp_path) -> None:
        (tmp_path / "system").mkdir()
        (tmp_path / "system" / "blockMeshDict").write_text("x")
        names = [u.name for u in available_utilities(tmp_path, meshed=True)]
        assert "checkMesh" in names
        assert "renumberMesh" in names

    def test_snappy_is_offered_when_its_dictionary_exists(self, tmp_path) -> None:
        (tmp_path / "system").mkdir()
        (tmp_path / "system" / "snappyHexMeshDict").write_text("x")
        assert "snappyHexMesh" in [u.name for u in available_utilities(tmp_path, meshed=True)]

    def test_snappy_overwrites_rather_than_writing_time_directories(self) -> None:
        # Without -overwrite it writes each refinement step as a time directory,
        # which the case view would then show as results.
        snappy = next(u for u in UTILITIES if u.name == "snappyHexMesh")
        assert "-overwrite" in snappy.argv


class TestCheckMeshParsing:
    """FR-P9 — the figures, not the prose."""

    def test_reads_the_quality_figures(self) -> None:
        quality = parse_check_mesh(CHECK_MESH_OK)
        assert quality.metric("non-orthogonality").value == pytest.approx(5.95045)
        assert quality.metric("skewness").value == pytest.approx(0.260575)
        assert quality.metric("aspect ratio").value == pytest.approx(8.1407)
        assert quality.cells == 12225

    def test_a_good_mesh_passes(self) -> None:
        quality = parse_check_mesh(CHECK_MESH_OK)
        assert quality.mesh_ok is True
        assert quality.verdict is Verdict.PASS

    def test_failed_checks_are_captured(self) -> None:
        quality = parse_check_mesh(CHECK_MESH_BAD)
        assert quality.failed_checks
        assert "edges not aligned" in quality.failed_checks[0]
        assert quality.verdict is Verdict.FAIL

    def test_figures_beyond_the_thresholds_are_flagged(self) -> None:
        quality = parse_check_mesh(CHECK_MESH_BAD)
        assert quality.metric("non-orthogonality").verdict is not Verdict.PASS
        assert quality.metric("skewness").verdict is not Verdict.PASS

    def test_thresholds_are_configurable(self) -> None:
        # Meshes for different physics tolerate different things; a fixed number
        # would either nag or mislead.
        strict = parse_check_mesh(CHECK_MESH_OK, {"skewness": (0.1, 0.2)})
        assert strict.metric("skewness").verdict is Verdict.FAIL

    def test_truncated_output_does_not_claim_a_verdict(self) -> None:
        # A utility that died before finishing said nothing about the mesh.
        assert parse_check_mesh("Checking geometry...\n").mesh_ok is None

    def test_empty_output_is_survivable(self) -> None:
        quality = parse_check_mesh("")
        assert quality.metrics == []
        assert quality.verdict is Verdict.PASS
