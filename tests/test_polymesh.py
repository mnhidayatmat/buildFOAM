"""The generated mesh's boundary, as something that can be drawn (DEC-23).

A synthetic mesh rather than a real one: these assert the reader's contract —
which faces it keeps, how it thins them, and what it does when it cannot read —
and a real ``blockMesh`` output would test OpenFOAM's writer as well, in a test
that could only run where OpenFOAM does. The sweep against a real installation
belongs with the other ``requires_runtime`` tests.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from foamwb.services.polymesh import (
    MAX_SOURCE_BYTES,
    MeshSurface,
    Unavailable,
    read_mesh_surface,
)

_HEADER = "FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {0};\n    object {1};\n}}\n"


def _write_list(path: Path, klass: str, name: str, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(entries)
    path.write_text(f"{_HEADER.format(klass, name)}\n{len(entries)}\n(\n{body}\n)\n")


def _cube(case: Path, *, internal: int = 2) -> Path:
    """A box: eight corners, ``internal`` faces nobody can see, six boundary ones.

    The internal faces matter to the test — they are what the reader must step
    past — and are given nonsense vertices so that reading them by mistake would
    produce something visibly wrong rather than something plausible.
    """
    polymesh = case / "constant" / "polyMesh"
    _write_list(
        polymesh / "points",
        "vectorField",
        "points",
        [
            "(0 0 0)",
            "(1 0 0)",
            "(1 1 0)",
            "(0 1 0)",
            "(0 0 1)",
            "(1 0 1)",
            "(1 1 1)",
            "(0 1 1)",
        ],
    )
    faces = ["4(0 1 2 3)"] * internal + [
        "4(0 1 5 4)",  # front
        "4(2 3 7 6)",  # back
        "4(0 3 7 4)",  # left
        "4(1 2 6 5)",  # right
        "4(4 5 6 7)",  # top
        "4(0 1 2 3)",  # bottom
    ]
    _write_list(polymesh / "faces", "faceList", "faces", faces)

    entries = [
        ("inlet", "patch", 1, internal),
        ("outlet", "patch", 1, internal + 1),
        ("walls", "wall", 4, internal + 2),
    ]
    body = "\n".join(
        f"    {name}\n    {{\n        type {kind};\n"
        f"        nFaces {count};\n        startFace {start};\n    }}"
        for name, kind, count, start in entries
    )
    (polymesh / "boundary").write_text(
        f"{_HEADER.format('polyBoundaryMesh', 'boundary')}\n{len(entries)}\n(\n{body}\n)\n"
    )
    return case


@pytest.fixture
def case(tmp_path: Path) -> Path:
    return _cube(tmp_path / "box")


class TestWhatItReads:
    def test_it_reads_a_mesh(self, case: Path) -> None:
        assert isinstance(read_mesh_surface(case), MeshSurface)

    def test_every_patch_is_named(self, case: Path) -> None:
        result = read_mesh_surface(case)
        assert sorted(result.patch_of.values()) == ["inlet", "outlet", "walls"]

    def test_the_patches_carry_their_type(self, case: Path) -> None:
        """The matrix selects by patch and the type decides which conditions are
        legal on it, so both travel together."""
        result = read_mesh_surface(case)
        assert {p.name: p.type for p in result.patches}["walls"] == "wall"

    def test_it_counts_the_boundary_faces(self, case: Path) -> None:
        result = read_mesh_surface(case)
        assert result.faces_total == 6
        assert result.faces_read == 6
        assert not result.is_partial

    def test_a_quad_becomes_two_triangles(self, case: Path) -> None:
        assert len(read_mesh_surface(case).sample.triangles) == 12

    def test_every_triangle_names_its_patch(self, case: Path) -> None:
        result = read_mesh_surface(case)
        assert len(result.sample.faces) == len(result.sample.triangles)
        assert set(result.sample.faces) == set(result.patch_of)

    def test_the_faces_are_a_real_answer(self, case: Path) -> None:
        """Not "nobody looked": every triangle's patch is known from the file."""
        assert read_mesh_surface(case).sample.faces_known

    def test_it_uses_the_real_coordinates(self, case: Path) -> None:
        corners = {c for t in read_mesh_surface(case).sample.triangles for c in t}
        assert (0.0, 0.0, 0.0) in corners
        assert (1.0, 1.0, 1.0) in corners

    def test_internal_faces_are_stepped_past(self, tmp_path: Path) -> None:
        """They are between two cells, so nothing can see them — and matching
        them into Python objects is most of the work of reading the file."""
        few = read_mesh_surface(_cube(tmp_path / "few", internal=2))
        many = read_mesh_surface(_cube(tmp_path / "many", internal=500))
        assert few.faces_total == many.faces_total == 6
        assert len(few.sample.triangles) == len(many.sample.triangles)


class TestThinning:
    def test_a_small_mesh_is_drawn_whole(self, case: Path) -> None:
        assert not read_mesh_surface(case).is_partial

    def test_a_budget_thins_it(self, case: Path) -> None:
        result = read_mesh_surface(case, budget=2)
        assert result.is_partial
        assert result.faces_read < result.faces_total

    def test_no_patch_can_vanish(self, case: Path) -> None:
        """A stride over the flat list takes faces in proportion to their number,
        so a patch of one face beside one of thousands loses every face it has —
        leaving a patch named in the matrix and nowhere on the model."""
        result = read_mesh_surface(case, budget=1)
        drawn = Counter(result.sample.faces)
        assert set(drawn) == set(result.patch_of), "a patch was thinned away"

    def test_it_still_says_how_much_it_drew(self, case: Path) -> None:
        """A picture drawn from a fraction of a mesh must not claim to be it."""
        result = read_mesh_surface(case, budget=2)
        assert result.faces_total == 6
        assert 0 < result.faces_read < 6


class TestWhenThereIsNothingToDraw:
    """Absence is a state, not an error (§7.9 rule 1)."""

    def test_no_case(self) -> None:
        assert read_mesh_surface(None) is Unavailable.NO_MESH

    def test_no_mesh(self, tmp_path: Path) -> None:
        assert read_mesh_surface(tmp_path) is Unavailable.NO_MESH

    def test_a_mesh_with_no_boundary_file(self, case: Path) -> None:
        (case / "constant" / "polyMesh" / "boundary").unlink()
        assert read_mesh_surface(case) is Unavailable.UNREADABLE

    def test_a_mesh_too_large_to_preview(self, case: Path, monkeypatch) -> None:
        """ParaView is what opens large meshes (NG3), and a preview that locked
        the window for a minute would be worse than one that declines."""
        monkeypatch.setattr("foamwb.services.polymesh.MAX_SOURCE_BYTES", 10)
        assert read_mesh_surface(case) is Unavailable.TOO_LARGE

    def test_the_cap_is_generous_enough_for_a_real_mesh(self) -> None:
        """A few million cells must still preview; the cap is for research scale."""
        assert MAX_SOURCE_BYTES >= 64 * 1024 * 1024

    def test_a_truncated_points_file(self, case: Path) -> None:
        _write_list(case / "constant" / "polyMesh" / "points", "vectorField", "points", [])
        assert read_mesh_surface(case) is Unavailable.UNREADABLE

    def test_a_binary_mesh_is_declined_rather_than_crashing(self, case: Path) -> None:
        points = case / "constant" / "polyMesh" / "points"
        points.write_bytes(b"FoamFile\n{\n format binary;\n}\n8\n(" + bytes(range(200)) + b")\n")
        assert read_mesh_surface(case) is Unavailable.UNREADABLE

    def test_a_face_naming_a_vertex_that_does_not_exist_is_skipped(self, case: Path) -> None:
        """A mismatched mesh loses that face, not the whole picture."""
        polymesh = case / "constant" / "polyMesh"
        text = (polymesh / "faces").read_text().replace("4(4 5 6 7)", "4(4 5 6 99)")
        (polymesh / "faces").write_text(text)
        result = read_mesh_surface(case)
        assert isinstance(result, MeshSurface)
        assert result.faces_read == 5

    def test_reading_changes_nothing_about_the_case(self, case: Path) -> None:
        """§5.1 — opening someone else's case must not modify it."""
        before = {p: p.stat().st_mtime for p in case.rglob("*") if p.is_file()}
        read_mesh_surface(case)
        assert {p: p.stat().st_mtime for p in case.rglob("*") if p.is_file()} == before
