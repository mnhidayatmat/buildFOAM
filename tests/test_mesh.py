"""Meshing utilities and the quality summary (FR-P5, FR-P9, E-S02)."""

from __future__ import annotations

import pytest

from foamwb.codes import Severity
from foamwb.services.mesh import (
    UTILITIES,
    Axis,
    Transform,
    Verdict,
    available_utilities,
    can_mesh,
    mesh_plan,
    parse_check_mesh,
    utility_plan,
)

TRANSFORM_POINTS = next(u for u in UTILITIES if u.name == "transformPoints")

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

    def test_transform_points_is_never_planned_without_an_operation(self, tmp_path) -> None:
        # Run bare it parses its arguments, finds no instruction and exits
        # fatally — on every case, so the button could only ever fail.
        assert TRANSFORM_POINTS.needs_operation
        with pytest.raises(ValueError):
            utility_plan(TRANSFORM_POINTS, tmp_path)

    def test_an_operation_reaches_the_argv(self, tmp_path) -> None:
        plan = utility_plan(
            TRANSFORM_POINTS, tmp_path, operation=Transform.scale(0.001, 0.001, 0.001)
        )
        assert plan.render() == (("transformPoints", "-scale", "(0.001 0.001 0.001)"),)

    def test_the_vector_stays_one_argument(self, tmp_path) -> None:
        # It has spaces in it and never goes near a shell, so it must arrive as
        # a single token rather than three.
        plan = utility_plan(TRANSFORM_POINTS, tmp_path, operation=Transform.translate(1, 2, 3))
        assert plan.render()[0][-1] == "(1 2 3)"

    def test_utilities_that_need_nothing_are_unaffected(self, tmp_path) -> None:
        block_mesh = next(u for u in UTILITIES if u.name == "blockMesh")
        assert utility_plan(block_mesh, tmp_path).render() == (("blockMesh",),)

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


class TestGeneratingInOnePress:
    """The whole sequence as one plan, rather than four presses in order."""

    def _dicts(self, tmp_path, *names: str):
        (tmp_path / "system").mkdir(exist_ok=True)
        for name in names:
            (tmp_path / "system" / name).write_text("x")
        return tmp_path

    def test_the_chain_runs_in_the_order_the_work_happens(self, tmp_path) -> None:
        case = self._dicts(
            tmp_path, "blockMeshDict", "surfaceFeatureExtractDict", "snappyHexMeshDict"
        )
        assert [s.name for s in mesh_plan(case).stages] == [
            "blockMesh",
            "surfaceFeatureExtract",
            "snappyHexMesh",
            "checkMesh",
        ]

    def test_the_chain_is_what_the_case_has_not_a_template(self, tmp_path) -> None:
        """A case with no surface has no feature extraction to do."""
        case = self._dicts(tmp_path, "blockMeshDict")
        assert [s.name for s in mesh_plan(case).stages] == ["blockMesh", "checkMesh"]

    def test_mesh_operations_are_never_in_the_chain(self, tmp_path) -> None:
        """`transformPoints` moves a mesh and needs an operation nobody supplied.

        Including it would mean a button labelled *Generate mesh* silently
        transformed the user's geometry — and `utility_plan` refuses to plan it
        bare precisely because running it that way is fatal.
        """
        case = self._dicts(tmp_path, "blockMeshDict", "snappyHexMeshDict")
        names = [s.name for s in mesh_plan(case).stages]
        assert "transformPoints" not in names
        assert "renumberMesh" not in names

    def test_check_mesh_still_gates_the_result(self, tmp_path) -> None:
        """E-S02: exit code 0 is not a verdict, so the threshold carries over."""
        case = self._dicts(tmp_path, "blockMeshDict")
        check = next(s for s in mesh_plan(case).stages if s.name == "checkMesh")
        assert check.fail_on is Severity.ERROR

    def test_a_case_with_nothing_to_mesh_is_not_planned(self, tmp_path) -> None:
        (tmp_path / "system").mkdir()
        assert not can_mesh(tmp_path)
        with pytest.raises(ValueError, match="nothing that would generate a mesh"):
            mesh_plan(tmp_path)

    def test_check_mesh_alone_is_not_a_mesh_plan(self, tmp_path) -> None:
        """checkMesh needs no dictionary, so it alone must not look meshable."""
        case = self._dicts(tmp_path, "surfaceFeatureExtractDict")
        assert not can_mesh(case)

    def test_either_mesher_makes_the_case_meshable(self, tmp_path) -> None:
        assert can_mesh(self._dicts(tmp_path, "blockMeshDict"))
        assert can_mesh(self._dicts(tmp_path, "snappyHexMeshDict"))

    def test_every_stage_that_needs_a_dictionary_has_one(self, tmp_path) -> None:
        """The chain and the buttons read the same evidence, so they cannot disagree."""
        case = self._dicts(tmp_path, "blockMeshDict", "snappyHexMeshDict")
        offered = {u.name for u in available_utilities(case, meshed=False)}
        needs_a_dictionary = {u.name for u in UTILITIES if u.needs}
        planned = {s.name for s in mesh_plan(case).stages}
        assert planned & needs_a_dictionary <= offered

    def test_the_chain_checks_a_mesh_it_has_not_made_yet(self, tmp_path) -> None:
        """checkMesh is in the chain on an unmeshed case, and is right to be.

        The button is not offered there — checkMesh alone on a case with no mesh
        fails on the mesh it goes looking for. In the chain it runs *after* the
        stages that create one, which is the whole difference a sequence makes.
        """
        case = self._dicts(tmp_path, "blockMeshDict")
        assert "checkMesh" not in [u.name for u in available_utilities(case, meshed=False)]
        assert mesh_plan(case).stages[-1].name == "checkMesh"


class TestTransform:
    """The operation `transformPoints` cannot run without."""

    def test_scale_renders_the_flag_the_utility_documents(self) -> None:
        assert Transform.scale(0.001, 0.001, 0.001).argv() == ("-scale", "(0.001 0.001 0.001)")

    def test_translate_renders_a_vector(self) -> None:
        assert Transform.translate(0, 0, -1.5).argv() == ("-translate", "(0 0 -1.5)")

    def test_rotation_names_its_axis_in_the_flag(self) -> None:
        assert Transform.rotate(Axis.Y, 90).argv() == ("-rotate-y", "90")

    def test_coordinates_do_not_arrive_as_float_noise(self) -> None:
        # 0.1 + 0.2 must not reach a mesh as 0.30000000000000004.
        assert Transform.translate(0.1 + 0.2, 0, 0).argv()[1] == "(0.3 0 0)"

    def test_a_small_factor_keeps_its_digits(self) -> None:
        # %g's default six significant figures would be enough here, but a
        # translation in millimetres across a large domain needs more.
        assert Transform.translate(1234.56789, 0, 0).argv()[1] == "(1234.56789 0 0)"

    def test_a_scale_of_one_moves_nothing(self) -> None:
        assert Transform.scale(1, 1, 1).is_identity

    def test_a_translation_of_zero_moves_nothing(self) -> None:
        assert Transform.translate(0, 0, 0).is_identity

    def test_a_full_turn_moves_nothing(self) -> None:
        assert Transform.rotate(Axis.Z, 360).is_identity
        assert not Transform.rotate(Axis.Z, 359).is_identity

    def test_a_real_transform_is_not_an_identity(self) -> None:
        assert not Transform.scale(0.001, 0.001, 0.001).is_identity
        assert not Transform.translate(0, 0, 1).is_identity

    def test_a_zero_scale_is_recognised_as_destruction(self) -> None:
        # transformPoints would flatten the mesh without complaint, and the
        # zero-volume cells fail much later with nothing pointing back here.
        assert Transform.scale(1, 0, 1).is_degenerate

    def test_a_zero_translation_is_not_destruction(self) -> None:
        assert not Transform.translate(0, 0, 0).is_degenerate


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
