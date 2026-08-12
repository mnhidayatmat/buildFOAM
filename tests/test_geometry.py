"""Geometry import, CAD conversion and new-case creation (FR-P3, FR-C1).

No CAD kernel is installed on a test runner, and requiring one would make every
conversion path untested on every machine that matters. So the converter is
injected: :class:`FakeKernel` behaves like the real tool at the one boundary that
matters — argv in, exit status and a written file out — which is enough to
exercise refusal, failure, partial output and success without gmsh present.

The STL fixtures are built byte by byte rather than vendored. A binary STL whose
header begins with the word ``solid`` is the case that breaks the usual
format-detection heuristic, and there is no way to obtain one on demand except to
write it.
"""

from __future__ import annotations

import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.cad import CadConverter, CadTool, needs_conversion
from foamwb.services.geometry import (
    TRISURFACE_DIR,
    GeometryError,
    SurfaceFormat,
    classify,
    existing_surfaces,
    import_geometry,
    inspect_surface,
)
from foamwb.services.newcase import (
    DEFAULT_APPLICATION,
    NewCaseError,
    create_case,
    is_valid_name,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ASCII_STL = """\
solid cube
  facet normal 0 0 -1
    outer loop
      vertex 0 0 0
      vertex 1 1 0
      vertex 1 0 0
    endloop
  endfacet
  facet normal 0 0 -1
    outer loop
      vertex 0 0 0
      vertex 0 1 0
      vertex 1 1 0
    endloop
  endfacet
endsolid cube
"""

OBJ = """\
# a triangle
o body
v 0.0 0.0 0.0
v 2.0 0.0 0.0
v 0.0 3.0 0.0
f 1 2 3
"""


def binary_stl(triangles: int = 2, *, header: bytes = b"exported") -> bytes:
    """A valid binary STL, with a controllable header."""
    out = bytearray(header.ljust(80, b"\0")[:80])
    out += struct.pack("<I", triangles)
    for index in range(triangles):
        # normal, then three corners; the corners walk along x so the bounding
        # box is predictable.
        floats = [0.0, 0.0, 1.0, float(index), 0.0, 0.0, float(index) + 1, 0.0, 0.0, 0.0, 1.0, 0.0]
        out += struct.pack("<12f", *floats)
        out += struct.pack("<H", 0)
    return bytes(out)


@pytest.fixture
def case(tmp_path: Path) -> Path:
    root = tmp_path / "cavity"
    (root / "system").mkdir(parents=True)
    (root / "constant").mkdir()
    (root / "system" / "controlDict").write_text("application simpleFoam;\n")
    return root


@dataclass
class _Completed:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class FakeKernel:
    """Stands in for gmsh at the process boundary."""

    def __init__(
        self, *, returncode: int = 0, writes: bytes | None = None, output: str = ""
    ) -> None:
        self.returncode = returncode
        self.writes = writes
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if self.writes is not None:
            Path(argv[argv.index("-o") + 1]).write_bytes(self.writes)
        return _Completed(self.returncode, stdout=self.output)


def converter_with(kernel, tmp_path: Path) -> CadConverter:
    """A converter that finds a tool without one being installed."""
    executable = tmp_path / "gmsh"
    executable.write_text("#!/bin/sh\n")
    return CadConverter(configured=executable, runner=kernel)


# ---------------------------------------------------------------------------
# Format classification
# ---------------------------------------------------------------------------


class TestClassify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("wing.stl", SurfaceFormat.STL),
            ("wing.STL", SurfaceFormat.STL),
            ("wing.obj", SurfaceFormat.OBJ),
            ("wing.step", SurfaceFormat.CAD),
            ("wing.stp", SurfaceFormat.CAD),
            ("wing.iges", SurfaceFormat.CAD),
            ("wing.igs", SurfaceFormat.CAD),
            ("wing.sldprt", SurfaceFormat.UNSUPPORTED),
            ("notes.txt", SurfaceFormat.UNSUPPORTED),
        ],
    )
    def test_by_suffix_case_insensitively(self, name: str, expected: SurfaceFormat) -> None:
        assert classify(Path(name)) is expected

    def test_only_cad_formats_need_a_kernel(self) -> None:
        assert needs_conversion(Path("a.step"))
        assert not needs_conversion(Path("a.stl"))


# ---------------------------------------------------------------------------
# Reading a surface
# ---------------------------------------------------------------------------


class TestInspect:
    def test_reads_an_ascii_stl(self, tmp_path: Path) -> None:
        path = tmp_path / "cube.stl"
        path.write_text(ASCII_STL)
        surface = inspect_surface(path)
        assert surface.triangles == 2
        assert not surface.is_binary
        assert surface.solids == ("cube",)
        assert surface.bounds == ((0.0, 0.0, 0.0), (1.0, 1.0, 0.0))
        assert surface.size == (1.0, 1.0, 0.0)

    def test_reads_a_binary_stl(self, tmp_path: Path) -> None:
        path = tmp_path / "part.stl"
        path.write_bytes(binary_stl(3))
        surface = inspect_surface(path)
        assert surface.triangles == 3
        assert surface.is_binary
        assert surface.bounds == ((0.0, 0.0, 0.0), (3.0, 1.0, 0.0))

    def test_a_binary_stl_whose_header_says_solid_is_not_read_as_ascii(
        self, tmp_path: Path
    ) -> None:
        """The case the usual keyword heuristic gets wrong.

        Exporters exist that begin the arbitrary 80-byte header with the word
        ``solid``. Detecting by keyword reports such a file as ASCII, finds no
        facets in it, and refuses a perfectly good surface.
        """
        path = tmp_path / "part.stl"
        path.write_bytes(binary_stl(2, header=b"solid produced by an exporter"))
        surface = inspect_surface(path)
        assert surface.is_binary
        assert surface.triangles == 2

    def test_reads_an_obj(self, tmp_path: Path) -> None:
        path = tmp_path / "body.obj"
        path.write_text(OBJ)
        surface = inspect_surface(path)
        assert surface.triangles == 1
        assert surface.solids == ("body",)
        assert surface.bounds == ((0.0, 0.0, 0.0), (2.0, 3.0, 0.0))

    def test_an_html_error_page_named_stl_is_refused(self, tmp_path: Path) -> None:
        # The single most common bad import: a browser saved an error page.
        path = tmp_path / "wing.stl"
        path.write_text("<!doctype html><html><body>404 Not Found</body></html>")
        with pytest.raises(GeometryError) as caught:
            inspect_surface(path)
        assert caught.value.code is ErrorCode.GEOMETRY_UNREADABLE

    def test_an_empty_file_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "wing.stl"
        path.write_bytes(b"")
        with pytest.raises(GeometryError) as caught:
            inspect_surface(path)
        assert caught.value.code is ErrorCode.GEOMETRY_UNREADABLE

    def test_a_binary_stl_truncated_mid_facet_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "wing.stl"
        # Claims four triangles, carries one and a half.
        path.write_bytes(binary_stl(4)[: 84 + 75])
        with pytest.raises(GeometryError) as caught:
            inspect_surface(path)
        assert caught.value.code is ErrorCode.GEOMETRY_UNREADABLE

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(GeometryError):
            inspect_surface(tmp_path / "nothing.stl")


# ---------------------------------------------------------------------------
# Importing
# ---------------------------------------------------------------------------


class TestImport:
    def test_an_stl_lands_in_trisurface(self, case: Path, tmp_path: Path) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        surface = import_geometry(case, source)

        assert surface.path == case / TRISURFACE_DIR / "wing.stl"
        assert surface.path.is_file()
        assert surface.triangles == 2

    def test_the_source_file_is_left_alone(self, case: Path, tmp_path: Path) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        before = source.read_bytes()
        import_geometry(case, source)
        assert source.read_bytes() == before

    def test_a_second_import_of_the_same_name_does_not_overwrite(
        self, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        first = import_geometry(case, source)
        second = import_geometry(case, source)
        assert first.path != second.path
        assert second.path.name == "wing-1.stl"
        assert first.path.is_file(), "the first import must survive the second"

    def test_a_native_cad_document_is_refused_with_its_own_code(
        self, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "bracket.sldprt"
        source.write_bytes(b"\x00binary CAD")
        with pytest.raises(GeometryError) as caught:
            import_geometry(case, source)
        assert caught.value.code is ErrorCode.GEOMETRY_UNSUPPORTED

    def test_a_bad_surface_never_reaches_the_case(self, case: Path, tmp_path: Path) -> None:
        """Inspected before it is copied, so there is nothing to undo."""
        source = tmp_path / "wing.stl"
        source.write_text("not a surface")
        with pytest.raises(GeometryError):
            import_geometry(case, source)
        assert not (case / TRISURFACE_DIR / "wing.stl").exists()

    def test_existing_surfaces_lists_what_is_there(self, case: Path, tmp_path: Path) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        import_geometry(case, source)
        listed = existing_surfaces(case)
        assert [s.name for s in listed] == ["wing.stl"]

    def test_an_unreadable_surface_is_listed_rather_than_hidden(self, case: Path) -> None:
        # snappyHexMesh will try to read it, so the user has to be able to see it.
        directory = case / TRISURFACE_DIR
        directory.mkdir(parents=True)
        (directory / "broken.stl").write_text("junk")
        listed = existing_surfaces(case)
        assert [s.name for s in listed] == ["broken.stl"]
        assert listed[0].triangles == 0

    def test_no_surfaces_on_a_case_without_the_directory(self, case: Path) -> None:
        assert existing_surfaces(case) == []


# ---------------------------------------------------------------------------
# CAD conversion
# ---------------------------------------------------------------------------


class TestCadConversion:
    def test_step_without_a_converter_reports_the_missing_tool(
        self, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.step"
        source.write_text("ISO-10303-21;")
        # A converter that finds nothing, which is every machine without gmsh.
        empty = CadConverter(app_dirs=(), configured=None, runner=lambda *_: None)
        empty._from_path = lambda: None

        with pytest.raises(GeometryError) as caught:
            import_geometry(case, source, converter=empty)
        assert caught.value.code is ErrorCode.CAD_CONVERTER_MISSING

    def test_a_converted_step_lands_as_an_stl(self, case: Path, tmp_path: Path) -> None:
        source = tmp_path / "wing.step"
        source.write_text("ISO-10303-21;")
        kernel = FakeKernel(writes=ASCII_STL.encode())

        surface = import_geometry(case, source, converter=converter_with(kernel, tmp_path))

        assert surface.path == case / TRISURFACE_DIR / "wing.stl"
        assert surface.triangles == 2
        assert "-2" in kernel.calls[0], "a surface mesh, not a volume mesh"
        assert "stl" in kernel.calls[0]

    def test_the_max_element_size_reaches_the_tool(self, case: Path, tmp_path: Path) -> None:
        source = tmp_path / "wing.step"
        source.write_text("ISO-10303-21;")
        kernel = FakeKernel(writes=ASCII_STL.encode())

        import_geometry(case, source, converter=converter_with(kernel, tmp_path), max_element=0.25)
        assert "-clmax" in kernel.calls[0]

    def test_a_failed_conversion_leaves_nothing_behind(self, case: Path, tmp_path: Path) -> None:
        source = tmp_path / "wing.step"
        source.write_text("ISO-10303-21;")
        # Writes a partial file and then fails, which is the dangerous shape:
        # a surface left in the case would be listed and meshed against.
        kernel = FakeKernel(returncode=1, writes=b"partial", output="cannot heal solid")

        with pytest.raises(GeometryError) as caught:
            import_geometry(case, source, converter=converter_with(kernel, tmp_path))
        assert caught.value.code is ErrorCode.CAD_CONVERSION_FAILED
        assert list((case / TRISURFACE_DIR).iterdir()) == []

    def test_success_with_no_output_file_is_a_failure(self, case: Path, tmp_path: Path) -> None:
        """Exit status 0 is not proof a surface was written.

        A kernel can read a file holding only sketches, decide there was nothing
        to mesh, and exit cleanly having written nothing.
        """
        source = tmp_path / "wing.step"
        source.write_text("ISO-10303-21;")
        kernel = FakeKernel(returncode=0, writes=None)

        with pytest.raises(GeometryError) as caught:
            import_geometry(case, source, converter=converter_with(kernel, tmp_path))
        assert caught.value.code is ErrorCode.CAD_CONVERSION_FAILED

    def test_a_timeout_is_reported_rather_than_raised(self, tmp_path: Path) -> None:
        def hang(argv, timeout):
            raise subprocess.TimeoutExpired(cmd="gmsh", timeout=timeout)

        converter = converter_with(hang, tmp_path)
        result = converter.convert(tmp_path / "a.step", tmp_path / "b.stl")
        assert not result.ok
        assert "timed out" in result.detail

    def test_the_tools_own_output_is_kept_on_success(self, tmp_path: Path) -> None:
        # A warning about a self-intersecting face explains a mesh that misbehaves
        # later; discarding it on success throws that explanation away.
        kernel = FakeKernel(writes=ASCII_STL.encode(), output="Warning: self-intersecting face")
        converter = converter_with(kernel, tmp_path)
        result = converter.convert(tmp_path / "a.step", tmp_path / "out.stl")
        assert result.ok
        assert "self-intersecting" in result.output

    def test_no_converter_reports_rather_than_raising(self, tmp_path: Path) -> None:
        converter = CadConverter(app_dirs=(), configured=None)
        converter._from_path = lambda: None
        result = converter.convert(tmp_path / "a.step", tmp_path / "b.stl")
        assert not result.ok
        assert converter.locate() is None

    def test_a_configured_path_is_found(self, tmp_path: Path) -> None:
        executable = tmp_path / "gmsh"
        executable.write_text("#!/bin/sh\n")
        converter = CadConverter(configured=executable, runner=FakeKernel())
        found = converter.locate()
        assert isinstance(found, CadTool)
        assert found.executable == executable


# ---------------------------------------------------------------------------
# Creating a case
# ---------------------------------------------------------------------------


class TestCreateCase:
    def test_writes_a_case_that_opens(self, tmp_path: Path) -> None:
        from foamwb.services.case import CaseService

        created = create_case(tmp_path, "wing")
        assert created.path == tmp_path / "wing"

        # The point of the skeleton: what it writes is enough for the rest of the
        # application to treat the folder as a case.
        opened = CaseService().open(created.path)
        assert opened.name == "wing"
        assert opened.application == DEFAULT_APPLICATION

    def test_writes_a_plannable_case(self, tmp_path: Path) -> None:
        from foamwb.services.case import CaseService
        from foamwb.services.run import build_plan

        created = create_case(tmp_path, "wing")
        # A case the Run view cannot plan would open into a dead end.
        plan = build_plan(CaseService().open(created.path))
        assert plan is not None

    def test_creates_the_directories_a_case_needs(self, tmp_path: Path) -> None:
        created = create_case(tmp_path, "wing")
        for directory in ("system", "constant", "0"):
            assert (created.path / directory).is_dir()

    def test_does_not_invent_initial_conditions(self, tmp_path: Path) -> None:
        """Which fields a case needs depends on a mesh that does not exist yet."""
        created = create_case(tmp_path, "wing")
        assert list((created.path / "0").iterdir()) == []

    def test_refuses_to_write_into_an_occupied_folder(self, tmp_path: Path) -> None:
        (tmp_path / "wing").mkdir()
        (tmp_path / "wing" / "important.txt").write_text("do not lose me")

        with pytest.raises(NewCaseError) as caught:
            create_case(tmp_path, "wing")
        assert caught.value.code is ErrorCode.NEW_CASE_EXISTS
        assert (tmp_path / "wing" / "important.txt").read_text() == "do not lose me"

    def test_an_empty_folder_is_usable(self, tmp_path: Path) -> None:
        (tmp_path / "wing").mkdir()
        created = create_case(tmp_path, "wing")
        assert (created.path / "system" / "controlDict").is_file()

    @pytest.mark.parametrize("name", ["", " ", ".", "..", "a/b", "a:b", "a?b", " wing", "wing "])
    def test_refuses_names_that_are_not_safe_folder_names(self, tmp_path: Path, name: str) -> None:
        assert not is_valid_name(name)
        with pytest.raises(NewCaseError) as caught:
            create_case(tmp_path, name)
        assert caught.value.code is ErrorCode.NEW_CASE_NAME_INVALID

    @pytest.mark.parametrize("name", ["wing", "wing-2", "wing_2", "Wing2", "aircraft.v3"])
    def test_accepts_ordinary_names(self, name: str) -> None:
        assert is_valid_name(name)

    def test_the_new_case_takes_geometry(self, tmp_path: Path) -> None:
        """The whole point of the path: create, then import."""
        created = create_case(tmp_path, "wing")
        source = tmp_path / "model.stl"
        source.write_text(ASCII_STL)

        surface = import_geometry(created.path, source)
        assert surface.path.is_file()
        assert existing_surfaces(created.path)[0].triangles == 2
