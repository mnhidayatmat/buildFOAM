"""Naming the faces of an imported surface (FR-P3).

The written file is the contract: what lands in ``constant/triSurface`` is what
``snappyHexMesh`` reads, and every triangle of the original has to be in it under
some name. A surface that lost triangles on the way through would mesh into a
body with holes, and nothing downstream would say why.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.services.geometry import GeometryError, inspect_surface
from foamwb.services.surface_regions import (
    DEFAULT_REGION,
    FaceAssignment,
    clean_region_name,
    is_valid_region_name,
    named_surface_path,
    read_faces,
    write_named_surface,
)
from test_preview import cube_triangles, write_ascii


@pytest.fixture
def cube(tmp_path: Path) -> Path:
    return write_ascii(tmp_path / "cube.stl", cube_triangles())


class TestNames:
    def test_a_plain_name_is_left_alone(self) -> None:
        assert clean_region_name("inlet") == "inlet"
        assert is_valid_region_name("inlet")

    def test_spaces_become_underscores(self) -> None:
        assert clean_region_name("front face") == "front_face"

    def test_a_leading_digit_is_not_a_patch_name(self) -> None:
        # It parses as a number where OpenFOAM expects a word.
        assert not is_valid_region_name("2nd_inlet")
        assert is_valid_region_name(clean_region_name("2nd_inlet"))

    def test_punctuation_that_would_fail_much_later_is_removed(self) -> None:
        """A dot survives the dictionary grammar and dies inside boundaryField."""
        assert is_valid_region_name(clean_region_name("wing.upper"))

    def test_a_name_of_nothing_but_punctuation_is_refused(self) -> None:
        # Returned empty rather than invented, so the caller can say why.
        assert clean_region_name("!!!") == ""

    def test_runs_of_separators_collapse(self) -> None:
        assert clean_region_name("  front   face  ") == "front_face"


class TestAssignment:
    def test_unnamed_faces_carry_the_default(self, cube: Path) -> None:
        assignment = FaceAssignment(surface=cube)
        assert assignment.name_of(3) == DEFAULT_REGION

    def test_naming_is_sparse(self, cube: Path) -> None:
        """Most faces of a real model are never named individually."""
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0], "inlet")
        assert assignment.names == {0: "inlet"}

    def test_a_name_can_be_taken_back(self, cube: Path) -> None:
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0], "inlet")
        assignment.assign([0], "")
        assert assignment.name_of(0) == DEFAULT_REGION

    def test_several_faces_share_one_name(self, cube: Path) -> None:
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0, 2, 4], "walls")
        assert assignment.regions == ("walls",)

    def test_regions_are_listed_once_each(self, cube: Path) -> None:
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0], "inlet")
        assignment.assign([1], "outlet")
        assignment.assign([2], "inlet")
        assert assignment.regions == ("inlet", "outlet")


class TestWriting:
    def test_the_faces_become_solids(self, cube: Path) -> None:
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0], "inlet")
        assignment.assign([1], "outlet")
        written = write_named_surface(cube, assignment)
        assert set(inspect_surface(written).solids) == {"inlet", "outlet", DEFAULT_REGION}

    def test_every_triangle_survives(self, cube: Path) -> None:
        """A triangle in no solid block is a triangle snappyHexMesh will not mesh."""
        before = inspect_surface(cube).triangles
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0], "inlet")
        written = write_named_surface(cube, assignment)
        assert inspect_surface(written).triangles == before

    def test_naming_nothing_still_writes_a_meshable_surface(self, cube: Path) -> None:
        written = write_named_surface(cube, FaceAssignment(surface=cube))
        assert inspect_surface(written).solids == (DEFAULT_REGION,)

    def test_the_original_is_left_alone(self, cube: Path) -> None:
        """A user who names six faces and then changes their mind still has it."""
        original = cube.read_bytes()
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0], "inlet")
        write_named_surface(cube, assignment)
        assert cube.read_bytes() == original

    def test_it_is_written_beside_the_original(self, cube: Path) -> None:
        assert named_surface_path(cube) == cube.with_name("cube_regions.stl")

    def test_renaming_again_does_not_stack_suffixes(self, cube: Path) -> None:
        """Otherwise a second pass gives cube_regions_regions.stl."""
        once = named_surface_path(cube)
        assert named_surface_path(once) == once

    def test_no_partial_file_is_left_where_the_mesher_looks(self, cube: Path) -> None:
        assignment = FaceAssignment(surface=cube)
        assignment.assign([0], "inlet")
        write_named_surface(cube, assignment)
        assert [p.name for p in cube.parent.glob("*.partial")] == []

    def test_a_surface_that_cannot_be_grouped_is_refused(self, tmp_path: Path) -> None:
        """Refused rather than written short: half a surface is a mesh with holes."""
        empty = tmp_path / "empty.stl"
        empty.write_text("solid nothing\nendsolid nothing\n")
        with pytest.raises(GeometryError):
            write_named_surface(empty, FaceAssignment(surface=empty))

    def test_the_written_surface_reads_back_into_the_same_faces(self, cube: Path) -> None:
        """Ids are positions, so the round trip has to agree about how many."""
        _triangles, _faces, before = read_faces(cube)
        written = write_named_surface(cube, FaceAssignment(surface=cube))
        _triangles, _faces, after = read_faces(written)
        assert after == before
