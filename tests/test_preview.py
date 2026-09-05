"""Reading and projecting an imported surface for the preview (FR-P3).

The maths lives in the service so it can be checked without a display, which is
the whole reason it is not in the widget.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from foamwb.services.preview import (
    DEFAULT_BUDGET,
    group_faces,
    pick,
    project,
    read_triangles,
)

# A unit cube's front face: two triangles, in the z = 1 plane.
ASCII_STL = """\
solid box
  facet normal 0 0 1
    outer loop
      vertex 0 0 1
      vertex 1 0 1
      vertex 1 1 1
    endloop
  endfacet
  facet normal 0 0 1
    outer loop
      vertex 0 0 1
      vertex 1 1 1
      vertex 0 1 1
    endloop
  endfacet
endsolid box
"""


def binary_stl(triangles: int) -> bytes:
    out = b"exported".ljust(80, b"\0") + struct.pack("<I", triangles)
    for index in range(triangles):
        out += struct.pack(
            "<12f", 0, 0, 1, 0, 0, float(index), 1, 0, float(index), 1, 1, float(index)
        )
        out += b"\0\0"
    return out


class TestReading:
    def test_an_ascii_stl_yields_its_triangles(self, tmp_path: Path) -> None:
        path = tmp_path / "box.stl"
        path.write_text(ASCII_STL)
        sample = read_triangles(path)
        assert sample.total == 2
        assert sample.triangles[0] == ((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0))

    def test_a_binary_stl_yields_its_triangles(self, tmp_path: Path) -> None:
        path = tmp_path / "box.stl"
        path.write_bytes(binary_stl(3))
        sample = read_triangles(path)
        assert sample.total == 3
        assert len(sample.triangles) == 3

    def test_a_binary_header_saying_solid_is_still_read_as_binary(self, tmp_path: Path) -> None:
        # The same trap geometry.py documents: exporters write "solid" into the
        # 80-byte header, and the arithmetic is what settles it.
        path = tmp_path / "box.stl"
        path.write_bytes(b"solid from an exporter".ljust(80, b"\0") + binary_stl(2)[80:])
        assert len(read_triangles(path).triangles) == 2

    def test_an_obj_face_becomes_triangles(self, tmp_path: Path) -> None:
        path = tmp_path / "box.obj"
        path.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n")
        # One quad fans into two triangles.
        assert read_triangles(path).total == 2

    def test_a_large_model_is_thinned_and_says_so(self, tmp_path: Path) -> None:
        path = tmp_path / "big.stl"
        path.write_bytes(binary_stl(DEFAULT_BUDGET * 2))
        sample = read_triangles(path, budget=100)
        assert sample.total == DEFAULT_BUDGET * 2
        assert len(sample.triangles) <= 100
        assert sample.is_partial

    def test_thinning_samples_across_the_file_not_off_the_front(self, tmp_path: Path) -> None:
        # The first n facets of an STL are one corner of the model; a preview
        # drawn from them is a fragment presented as the shape.
        path = tmp_path / "big.stl"
        path.write_bytes(binary_stl(500))
        sample = read_triangles(path, budget=10)
        depths = [corner[2] for triangle in sample.triangles for corner in triangle]
        assert max(depths) > 400

    def test_an_unreadable_file_is_silent(self, tmp_path: Path) -> None:
        # The import already validated this file; a picture failing to appear
        # must not be louder than the import was.
        path = tmp_path / "nope.stl"
        path.write_bytes(b"\x00\x01\x02")
        assert read_triangles(path).triangles == ()

    def test_a_missing_file_is_silent(self, tmp_path: Path) -> None:
        assert read_triangles(tmp_path / "gone.stl").triangles == ()


class TestProjection:
    def _cube(self) -> list:
        return [
            ((0, 0, 0), (1, 0, 0), (1, 1, 0)),
            ((0, 0, 1), (1, 0, 1), (1, 1, 1)),
            ((0, 0, 0), (0, 0, 1), (1, 0, 1)),
        ]

    def test_it_fits_inside_the_box_it_is_given(self) -> None:
        facets = project(self._cube(), width=200, height=100)
        xs = [x for facet in facets for x, _ in facet.points]
        ys = [y for facet in facets for _, y in facet.points]
        assert min(xs) >= 0 and max(xs) <= 200
        assert min(ys) >= 0 and max(ys) <= 100

    def test_it_still_fits_after_being_turned(self) -> None:
        # A preview the user has to re-centre after every drag is one they stop
        # turning, so the fit is computed from the rotated geometry.
        for yaw in (0.0, 1.0, 2.5, 4.0):
            facets = project(self._cube(), width=120, height=120, yaw=yaw)
            xs = [x for facet in facets for x, _ in facet.points]
            assert min(xs) >= 0 and max(xs) <= 120, yaw

    def test_facets_come_back_to_front(self) -> None:
        # There is no depth buffer, so the order is the only thing making the
        # far side of the model stay behind the near side.
        facets = project(self._cube(), width=100, height=100)
        assert all(facets[i].depth <= facets[i + 1].depth for i in range(len(facets) - 1))

    def test_shading_varies_with_orientation(self) -> None:
        shades = {round(facet.shade, 4) for facet in project(self._cube(), width=100, height=100)}
        assert len(shades) > 1

    def test_shade_stays_within_range(self) -> None:
        for facet in project(self._cube(), width=100, height=100):
            assert 0.0 <= facet.shade <= 1.0

    def test_a_degenerate_facet_does_not_divide_by_zero(self) -> None:
        flat = [((0, 0, 0), (1, 0, 0), (2, 0, 0))]
        assert project(flat, width=100, height=100)

    def test_nothing_to_draw_is_not_an_error(self) -> None:
        assert project([], width=100, height=100) == ()

    def test_a_zero_sized_widget_is_not_an_error(self) -> None:
        assert project(self._cube(), width=0, height=0) == ()


def cube_triangles(size: float = 1.0) -> list:
    """A closed unit cube: six flat faces, two triangles each."""
    v = [
        (0, 0, 0),
        (size, 0, 0),
        (size, size, 0),
        (0, size, 0),
        (0, 0, size),
        (size, 0, size),
        (size, size, size),
        (0, size, size),
    ]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    triangles = []
    for a, b, c, d in quads:
        triangles.append((v[a], v[b], v[c]))
        triangles.append((v[a], v[c], v[d]))
    return triangles


def cylinder_triangles(segments: int = 32, radius: float = 1.0, height: float = 2.0) -> list:
    ring = [
        (
            radius * math.cos(2 * math.pi * i / segments),
            radius * math.sin(2 * math.pi * i / segments),
        )
        for i in range(segments)
    ]
    triangles = []
    for i in range(segments):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % segments]
        triangles.append(((x0, y0, 0), (x1, y1, 0), (x1, y1, height)))
        triangles.append(((x0, y0, 0), (x1, y1, height), (x0, y0, height)))
    for i in range(1, segments - 1):
        for z in (0, height):
            triangles.append(
                (
                    (ring[0][0], ring[0][1], z),
                    (ring[i][0], ring[i][1], z),
                    (ring[i + 1][0], ring[i + 1][1], z),
                )
            )
    return triangles


def write_ascii(path: Path, triangles: list, name: str = "body") -> Path:
    lines = [f"solid {name}"]
    for triangle in triangles:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for corner in triangle:
            lines.append("      vertex {:.6f} {:.6f} {:.6f}".format(*corner))
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    path.write_text("\n".join(lines))
    return path


class TestGroupingIntoFaces:
    """What a user means when they point at "that face"."""

    def test_a_cube_has_six(self) -> None:
        faces, count = group_faces(cube_triangles())
        assert count == 6
        # Two triangles each, and the pair from one quad lands together.
        assert [faces[i] == faces[i + 1] for i in range(0, 12, 2)] == [True] * 6

    def test_a_cylinder_is_a_barrel_and_two_caps(self) -> None:
        """The point of a feature angle: smooth curvature is one face."""
        _faces, count = group_faces(cylinder_triangles())
        assert count == 3

    def test_touching_is_required_as_well_as_the_angle(self) -> None:
        """Opposite walls of a duct are parallel and are not the same face."""
        near = [((0, 0, 0), (1, 0, 0), (1, 1, 0))]
        far = [((0, 0, 10), (1, 0, 10), (1, 1, 10))]
        _faces, count = group_faces(near + far)
        assert count == 2

    def test_the_angle_is_what_separates_them(self) -> None:
        """The same cube at a permissive angle collapses to one face."""
        _faces, count = group_faces(cube_triangles(), feature_angle=100.0)
        assert count == 1

    def test_inconsistent_winding_does_not_split_a_face(self) -> None:
        """Imported STLs wind inconsistently; a flat face must stay one face."""
        a = ((0, 0, 0), (1, 0, 0), (1, 1, 0))
        flipped = ((0, 0, 0), (1, 1, 0), (1, 0, 0))
        _faces, count = group_faces([a, flipped])
        assert count == 1

    def test_scale_does_not_change_the_answer(self) -> None:
        """The same part in millimetres and in metres must weld identically."""
        assert group_faces(cube_triangles(1.0))[1] == group_faces(cube_triangles(1000.0))[1]

    def test_nothing_is_not_an_error(self) -> None:
        assert group_faces([]) == ((), 0)

    def test_ids_are_stable_across_reads(self, tmp_path: Path) -> None:
        """A name given to face 3 has to still mean face 3 when it is written."""
        path = write_ascii(tmp_path / "cube.stl", cube_triangles())
        assert read_triangles(path).faces == read_triangles(path).faces


class TestGroupingIsReadBeforeThinning:
    def test_a_small_file_reports_its_faces(self, tmp_path: Path) -> None:
        sample = read_triangles(write_ascii(tmp_path / "cube.stl", cube_triangles()))
        assert sample.faces_known
        assert sample.face_count == 6
        assert len(sample.faces) == len(sample.triangles)

    def test_thinning_keeps_each_facet_pointing_at_its_own_face(self, tmp_path: Path) -> None:
        """The ids survive the sampling, so a drawn facet still knows its face."""
        path = write_ascii(tmp_path / "cube.stl", cube_triangles())
        sample = read_triangles(path, budget=6)
        assert len(sample.faces) == len(sample.triangles)
        assert set(sample.faces) <= set(range(sample.face_count))

    def test_a_model_past_the_grouping_budget_says_it_does_not_know(self, tmp_path: Path) -> None:
        """Not "one face" — nobody looked, and the two are different answers."""
        path = tmp_path / "big.stl"
        path.write_bytes(binary_stl(40))
        sample = read_triangles(path, grouping_budget=10)
        assert not sample.faces_known
        assert sample.faces == ()
        assert sample.face_count == 0


class TestPicking:
    def _facets(self, triangles: list, faces: tuple):
        return project(triangles, width=400, height=300, faces=faces)

    def test_a_click_on_the_model_names_a_face(self) -> None:
        triangles = cube_triangles()
        faces, _count = group_faces(triangles)
        facets = self._facets(triangles, faces)
        assert pick(facets, 200, 150) is not None

    def test_a_click_on_empty_space_names_nothing(self) -> None:
        triangles = cube_triangles()
        faces, _count = group_faces(triangles)
        facets = self._facets(triangles, faces)
        assert pick(facets, 1, 1) is None

    def test_the_near_face_wins_over_the_one_behind_it(self) -> None:
        """A cube is closed, so every point on it has a hidden face behind."""
        triangles = cube_triangles()
        faces, _count = group_faces(triangles)
        facets = self._facets(triangles, faces)
        hit = pick(facets, 200, 150)
        behind = [f.face for f in facets if _contains_point(f, 200, 150)]
        assert len(behind) > 1, "the test point should have something behind it"
        assert hit == behind[-1]

    def test_turning_the_model_shows_a_different_set_of_faces(self) -> None:
        """Picking follows the view, which is the point of turning it.

        Asserted over the whole picture rather than one pixel: the centre of a
        cube seen from above is the top face at every yaw, so a single point
        would report no change while three of the six faces had swapped.
        """
        triangles = cube_triangles()
        faces, _count = group_faces(triangles)

        def visible(yaw: float, pitch: float) -> set[int]:
            facets = project(triangles, width=400, height=300, yaw=yaw, pitch=pitch, faces=faces)
            found = set()
            for y in range(20, 280, 10):
                for x in range(20, 380, 10):
                    if (hit := pick(facets, x, y)) is not None:
                        found.add(hit)
            return found

        assert visible(0.6, -1.1) != visible(0.6, -2.0)

    def test_a_facet_with_no_faces_given_falls_back_to_zero(self) -> None:
        """Projection without grouping still draws; it just has nothing to pick."""
        facets = project(cube_triangles(), width=400, height=300)
        assert {facet.face for facet in facets} == {0}


def _contains_point(facet, x: float, y: float) -> bool:
    from foamwb.services.preview import _contains

    return _contains(facet, x, y)
