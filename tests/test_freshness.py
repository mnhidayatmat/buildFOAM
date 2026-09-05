"""Which outputs are older than their inputs (DEC-22).

Workbench's ⚡ is the most useful mark in that interface because it answers a
question a user cannot answer for themselves: *given everything I have edited,
what is no longer true?* These tests pin the two halves of that — what counts as
an input to each artefact, and that the propagation goes downstream and not up.

The times are real. ``time.sleep`` between writes rather than a patched clock,
because what is being tested is a comparison of filesystem mtimes and a fake one
would test the arithmetic instead of the thing that matters.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from foamwb.services.freshness import Freshness, assess, mesh_inputs

#: Long enough to separate two writes on every filesystem the application
#: supports, short enough not to be felt across the module.
_TICK = 0.02


def _touch(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def case(tmp_path: Path) -> Path:
    """A case with a mesh and a result, everything current."""
    root = tmp_path / "cavity"
    _touch(root / "system" / "controlDict", "application icoFoam;\n")
    _touch(root / "system" / "blockMeshDict", "scale 1;\n")
    _touch(root / "constant" / "transportProperties", "nu 1e-5;\n")
    _touch(root / "0" / "U", "internalField uniform (0 0 0);\n")
    time.sleep(_TICK)
    _touch(root / "constant" / "polyMesh" / "points", "0\n")
    time.sleep(_TICK)
    _touch(root / "0.5" / "U", "result\n")
    return root


class TestWhatExists:
    def test_no_case_is_not_an_error(self) -> None:
        assert assess(None) == Freshness()

    def test_an_empty_directory_has_neither(self, tmp_path: Path) -> None:
        result = assess(tmp_path)
        assert not result.has_mesh
        assert not result.has_results

    def test_a_mesh_is_found(self, case: Path) -> None:
        assert assess(case).has_mesh

    def test_results_are_found(self, case: Path) -> None:
        assert assess(case).has_results

    def test_the_initial_directory_is_not_a_result(self, tmp_path: Path) -> None:
        """``0`` is where the solver starts, not something it wrote."""
        root = tmp_path / "cavity"
        _touch(root / "system" / "controlDict")
        _touch(root / "0" / "U")
        _touch(root / "0.orig" / "U")
        assert not assess(root).has_results

    def test_a_directory_that_is_not_a_time_is_not_a_result(self, tmp_path: Path) -> None:
        root = tmp_path / "cavity"
        _touch(root / "system" / "controlDict")
        _touch(root / "postProcessing" / "solverInfo" / "0" / "solverInfo.dat")
        assert not assess(root).has_results


class TestNothingIsStaleWhenNothingChanged:
    def test_a_current_case_is_current(self, case: Path) -> None:
        result = assess(case)
        assert not result.mesh_is_stale
        assert not result.results_are_stale

    def test_a_case_with_no_mesh_has_no_stale_mesh(self, tmp_path: Path) -> None:
        """Missing and out-of-date are different problems with different remedies."""
        root = tmp_path / "cavity"
        _touch(root / "system" / "blockMeshDict")
        assert not assess(root).mesh_is_stale

    def test_a_case_with_no_results_has_no_stale_results(self, tmp_path: Path) -> None:
        root = tmp_path / "cavity"
        _touch(root / "system" / "controlDict")
        _touch(root / "constant" / "polyMesh" / "points")
        assert not assess(root).results_are_stale

    def test_reading_a_case_changes_nothing_about_it(self, case: Path) -> None:
        """§5.1 — opening someone else's case must not modify it."""
        before = {p: p.stat().st_mtime for p in case.rglob("*") if p.is_file()}
        assess(case)
        assert {p: p.stat().st_mtime for p in case.rglob("*") if p.is_file()} == before


class TestTheMeshGoesStale:
    def test_editing_the_block_mesh_dictionary(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "system" / "blockMeshDict", "scale 2;\n")
        assert assess(case).mesh_stale_because == "system/blockMeshDict"

    def test_importing_a_surface(self, case: Path) -> None:
        """snappyHexMesh meshes *around* the surface, so a new one invalidates it."""
        time.sleep(_TICK)
        _touch(case / "constant" / "triSurface" / "wing.stl", "solid s\nendsolid s\n")
        assert assess(case).mesh_stale_because == "constant/triSurface/wing.stl"

    def test_the_solver_s_own_settings_do_not_touch_it(self, case: Path) -> None:
        """A mesh is not stale because the end time changed.

        Marking it would train the user to ignore the mark, which costs more
        than the occasional miss.
        """
        time.sleep(_TICK)
        _touch(case / "system" / "controlDict", "application icoFoam;\nendTime 9;\n")
        assert not assess(case).mesh_is_stale

    def test_the_boundary_conditions_do_not_touch_it(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "0" / "U", "internalField uniform (1 0 0);\n")
        assert not assess(case).mesh_is_stale

    def test_the_inputs_come_from_the_utilities_that_read_them(self, case: Path) -> None:
        """Not a second list. A utility added to UTILITIES brings its dictionary."""
        _touch(case / "system" / "snappyHexMeshDict", "castellatedMesh true;\n")
        named = {p.relative_to(case).as_posix() for p in mesh_inputs(case)}
        assert "system/blockMeshDict" in named
        assert "system/snappyHexMeshDict" in named

    def test_a_dictionary_the_case_does_not_have_is_not_an_input(self, case: Path) -> None:
        named = {p.relative_to(case).as_posix() for p in mesh_inputs(case)}
        assert "system/snappyHexMeshDict" not in named


class TestResultsGoStale:
    def test_editing_a_boundary_condition(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "0" / "U", "internalField uniform (1 0 0);\n")
        assert assess(case).results_stale_because == "0/U"

    def test_editing_the_physical_properties(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "constant" / "transportProperties", "nu 2e-5;\n")
        assert assess(case).results_stale_because == "constant/transportProperties"

    def test_editing_the_solver_settings(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "system" / "fvSchemes", "ddtSchemes { default steadyState; }\n")
        assert assess(case).results_stale_because == "system/fvSchemes"

    def test_rebuilding_the_mesh(self, case: Path) -> None:
        """The mesh is an input to the solve, so a newer mesh dates the result."""
        time.sleep(_TICK)
        _touch(case / "constant" / "polyMesh" / "points", "1\n")
        assert assess(case).results_stale_because == "constant/polyMesh/points"

    def test_writing_more_results_does_not(self, case: Path) -> None:
        """The solver's own output is not one of its inputs."""
        time.sleep(_TICK)
        _touch(case / "1.0" / "U", "later\n")
        assert not assess(case).results_are_stale

    def test_post_processing_output_does_not(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "postProcessing" / "solverInfo" / "0" / "solverInfo.dat", "data\n")
        assert not assess(case).results_are_stale

    def test_our_own_metadata_does_not(self, case: Path) -> None:
        """Writing a run record must not mark the run it records as out of date."""
        from foamwb.branding import CASE_METADATA_DIR

        time.sleep(_TICK)
        _touch(case / CASE_METADATA_DIR / "case.json", "{}\n")
        assert not assess(case).results_are_stale


class TestTheReasonIsNamed:
    def test_it_is_the_file_and_not_merely_the_fact(self, case: Path) -> None:
        """A user who has edited four things needs to know which one did it."""
        time.sleep(_TICK)
        _touch(case / "system" / "fvSolution", "solvers {}\n")
        assert assess(case).results_stale_because == "system/fvSolution"

    def test_the_newest_change_is_the_one_named(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "system" / "fvSolution", "solvers {}\n")
        time.sleep(_TICK)
        _touch(case / "system" / "fvSchemes", "ddtSchemes {}\n")
        assert assess(case).results_stale_because == "system/fvSchemes"

    def test_a_relative_path_so_it_can_be_shown(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "0" / "p", "0\n")
        assert not Path(assess(case).results_stale_because).is_absolute()


class TestWhetherThereIsAnythingToDo:
    def test_a_finished_case_has_nothing_outstanding(self, case: Path) -> None:
        assert not assess(case).anything_to_do

    def test_an_unmeshed_case_has(self, tmp_path: Path) -> None:
        root = tmp_path / "cavity"
        _touch(root / "system" / "controlDict")
        assert assess(root).anything_to_do

    def test_an_unrun_case_has(self, tmp_path: Path) -> None:
        root = tmp_path / "cavity"
        _touch(root / "system" / "controlDict")
        _touch(root / "constant" / "polyMesh" / "points")
        assert assess(root).anything_to_do

    def test_a_stale_case_has(self, case: Path) -> None:
        time.sleep(_TICK)
        _touch(case / "system" / "blockMeshDict", "scale 3;\n")
        assert assess(case).anything_to_do
