"""Generated background mesh and meshing dictionary (FR-P3).

The strongest check available here is that the generated files go back through
this project's *own* parser. ``foamdict`` is deliberately strict about structural
impossibility (E-C02), so a dictionary it accepts is one whose braces, lists and
entries are well formed — which catches the whole class of bug an f-string
template invites, and catches it without needing OpenFOAM installed.

What it cannot check is whether OpenFOAM likes the *contents*. That is what the
``requires_runtime`` mesh test is for, and it is marked as such.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.foamdict import Document
from foamwb.services.geometry import import_geometry
from foamwb.services.mesh import available_utilities
from foamwb.services.newcase import create_case
from foamwb.services.snappy import (
    BLOCK_MESH_DICT,
    SNAPPY_DICT,
    FlowRegion,
    MeshSettings,
    SnappyError,
    plan_mesh,
    render_block_mesh,
    render_snappy,
    write_dictionaries,
)
from test_geometry import ASCII_STL, binary_stl


@pytest.fixture
def case(tmp_path: Path) -> Path:
    return create_case(tmp_path, "wing").path


def with_geometry(case: Path, tmp_path: Path, name: str = "wing", data: str | None = None) -> Path:
    source = tmp_path / f"{name}.stl"
    source.write_text(data or ASCII_STL)
    import_geometry(case, source)
    return case


class TestPlanning:
    def test_refuses_when_there_is_no_geometry(self, case: Path) -> None:
        with pytest.raises(SnappyError) as caught:
            plan_mesh(case)
        assert caught.value.code is ErrorCode.NO_GEOMETRY_TO_MESH

    def test_the_domain_encloses_the_geometry(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        plan = plan_mesh(case)
        # The fixture surface spans 0..1 in x and y.
        assert plan.low[0] < 0.0
        assert plan.high[0] > 1.0

    def test_external_flow_pads_the_domain_around_the_body(
        self, case: Path, tmp_path: Path
    ) -> None:
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(region=FlowRegion.EXTERNAL, padding=3.0))
        # Padding 3 means the domain is three times the body's extent.
        assert plan.high[0] - plan.low[0] == pytest.approx(3.0, rel=1e-6)

    def test_internal_flow_keeps_the_domain_at_the_geometry(
        self, case: Path, tmp_path: Path
    ) -> None:
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(region=FlowRegion.INTERNAL))
        # Only a small margin, not a multiple: the surface is the boundary.
        assert plan.high[0] - plan.low[0] < 1.2

    def test_the_body_stays_centred_in_an_external_domain(self, case: Path, tmp_path: Path) -> None:
        """Grown about the centre, not from one corner.

        Padding from a corner would leave the body against whichever face
        happened to be nearest, which is where the boundary influences it most.
        """
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(padding=3.0))
        assert plan.low[0] == pytest.approx(-1.0)
        assert plan.high[0] == pytest.approx(2.0)

    def test_background_cells_are_as_cubic_as_the_domain_allows(
        self, case: Path, tmp_path: Path
    ) -> None:
        """snappyHexMesh bisects, so it cannot correct a background aspect ratio."""
        source = tmp_path / "long.stl"
        source.write_bytes(binary_stl(20))  # spans 20 x 1 x 0
        import_geometry(case, source)

        plan = plan_mesh(case, MeshSettings(background_cells=40))
        edges = [
            (plan.high[axis] - plan.low[axis]) / plan.cells[axis]
            for axis in range(3)
            if plan.cells[axis] > 1
        ]
        assert max(edges) / min(edges) < 1.5

    def test_a_flat_axis_still_gets_a_cell(self, case: Path, tmp_path: Path) -> None:
        # The fixture surface is flat in z; a zero cell count is not a mesh.
        with_geometry(case, tmp_path)
        plan = plan_mesh(case)
        assert all(count >= 1 for count in plan.cells)

    def test_the_cell_count_is_reported_before_anything_is_written(
        self, case: Path, tmp_path: Path
    ) -> None:
        # A ten-million-cell background mesh is cheap to see and expensive to
        # discover by waiting.
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(background_cells=40))
        assert plan.background_cell_count == plan.cells[0] * plan.cells[1] * plan.cells[2]
        assert not (case / BLOCK_MESH_DICT).exists()

    def test_impossible_settings_are_clamped_rather_than_refused(self) -> None:
        settings = MeshSettings(refinement_min=5, refinement_max=2, background_cells=0).normalised()
        assert settings.refinement_max >= settings.refinement_min
        assert settings.background_cells >= 4


class TestLocationInMesh:
    """The entry that decides whether the mesh is the fluid or the solid."""

    def test_external_flow_puts_the_point_outside_the_body(
        self, case: Path, tmp_path: Path
    ) -> None:
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(region=FlowRegion.EXTERNAL, padding=3.0))
        # The body spans 0..1; the point must be clear of it.
        assert plan.location_in_mesh[0] < 0.0

    def test_the_external_point_is_not_on_a_boundary_face(self, case: Path, tmp_path: Path) -> None:
        # snappyHexMesh refuses a point that sits exactly on a face.
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(padding=3.0))
        assert plan.location_in_mesh[0] > plan.low[0]

    def test_internal_flow_puts_the_point_inside(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(region=FlowRegion.INTERNAL))
        assert 0.0 < plan.location_in_mesh[0] < 1.0

    def test_an_explicit_point_overrides_the_derived_one(self, case: Path, tmp_path: Path) -> None:
        """The derived point is a guess, so it has to be correctable."""
        with_geometry(case, tmp_path)
        plan = plan_mesh(case, MeshSettings(location_in_mesh=(9.0, 9.0, 9.0)))
        assert plan.location_in_mesh == (9.0, 9.0, 9.0)
        assert b"9.0 9.0 9.0" in render_snappy(plan)


class TestGeneratedDictionaries:
    """The generated text is a dictionary, checked by this project's parser."""

    def test_the_block_mesh_dict_parses(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        Document.parse(render_block_mesh(plan_mesh(case)).decode())

    def test_the_snappy_dict_parses(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        Document.parse(render_snappy(plan_mesh(case)).decode())

    def test_both_parse_with_several_surfaces(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path, "wing")
        with_geometry(case, tmp_path, "fuselage")
        plan = plan_mesh(case)
        Document.parse(render_block_mesh(plan).decode())
        Document.parse(render_snappy(plan).decode())

    def test_every_surface_is_named_in_the_dictionary(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path, "wing")
        with_geometry(case, tmp_path, "fuselage")
        rendered = render_snappy(plan_mesh(case)).decode()
        assert "wing.stl" in rendered
        assert "fuselage.stl" in rendered

    def test_refinement_levels_reach_the_dictionary(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        rendered = render_snappy(
            plan_mesh(case, MeshSettings(refinement_min=1, refinement_max=4))
        ).decode()
        assert "level (1 4)" in rendered

    def test_layers_are_off(self, case: Path, tmp_path: Path) -> None:
        """The part that fails late and on exactly a beginner's mesh."""
        with_geometry(case, tmp_path)
        assert "addLayers       false;" in render_snappy(plan_mesh(case)).decode()

    def test_the_six_faces_are_named_patches(self, case: Path, tmp_path: Path) -> None:
        # After meshing these are the patches the user assigns conditions to,
        # and "xMin" is something they can act on where "background" is not.
        with_geometry(case, tmp_path)
        rendered = render_block_mesh(plan_mesh(case)).decode()
        for name in ("xMin", "xMax", "yMin", "yMax", "zMin", "zMax"):
            assert name in rendered

    def test_the_file_says_what_wrote_it(self, case: Path, tmp_path: Path) -> None:
        """NFR-C3's disclosure, at the top where a person reading it will look."""
        from foamwb.branding import APP_DISPLAY_NAME

        with_geometry(case, tmp_path)
        assert APP_DISPLAY_NAME in render_snappy(plan_mesh(case)).decode()


class TestWriting:
    def test_writes_both_dictionaries(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        written = write_dictionaries(case, plan_mesh(case))
        assert set(written) == {BLOCK_MESH_DICT, SNAPPY_DICT}
        assert (case / BLOCK_MESH_DICT).is_file()
        assert (case / SNAPPY_DICT).is_file()

    def test_refuses_to_overwrite_a_tuned_dictionary(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        (case / SNAPPY_DICT).write_text("// mine, carefully tuned\n")

        plan = plan_mesh(case)
        assert not plan.can_write
        with pytest.raises(SnappyError) as caught:
            write_dictionaries(case, plan)
        assert caught.value.code is ErrorCode.MESH_DICT_EXISTS
        assert "carefully tuned" in (case / SNAPPY_DICT).read_text()

    def test_overwrites_when_told_to(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        (case / SNAPPY_DICT).write_text("// mine\n")
        write_dictionaries(case, plan_mesh(case), replace_existing=True)
        assert "castellatedMesh" in (case / SNAPPY_DICT).read_text()

    def test_the_plan_names_what_would_be_lost(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        (case / BLOCK_MESH_DICT).write_text("// mine\n")
        assert plan_mesh(case).existing == (BLOCK_MESH_DICT,)


class TestTheLoopCloses:
    """The point of the whole path: import geometry, then be able to mesh it."""

    def test_a_case_with_geometry_alone_offers_no_way_to_mesh(
        self, case: Path, tmp_path: Path
    ) -> None:
        # The dead end this closes.
        with_geometry(case, tmp_path)
        offered = {u.name for u in available_utilities(case, meshed=False)}
        assert "blockMesh" not in offered
        assert "snappyHexMesh" not in offered

    def test_generating_the_dictionaries_offers_both_utilities(
        self, case: Path, tmp_path: Path
    ) -> None:
        with_geometry(case, tmp_path)
        write_dictionaries(case, plan_mesh(case))

        offered = [u.name for u in available_utilities(case, meshed=False)]
        assert "blockMesh" in offered
        assert "snappyHexMesh" in offered
        # blockMesh first: snappyHexMesh refines what blockMesh produced.
        assert offered.index("blockMesh") < offered.index("snappyHexMesh")

    def test_new_case_to_meshable_in_three_steps(self, tmp_path: Path) -> None:
        """Create, import, generate — the whole path a CAD user takes."""
        created = create_case(tmp_path, "aircraft").path

        source = tmp_path / "model.stl"
        source.write_text(ASCII_STL)
        import_geometry(created, source)

        write_dictionaries(created, plan_mesh(created))
        assert {"blockMesh", "snappyHexMesh"} <= {
            u.name for u in available_utilities(created, meshed=False)
        }


class TestRegionCoercion:
    """The region survives a round trip through a Qt combo box.

    Qt returns item user data as a plain ``str``, so a ``StrEnum`` stored in a
    combo comes back as ``"external"`` rather than as the enum member. Every
    ``is FlowRegion.EXTERNAL`` comparison then reads False and the internal
    branch runs instead — putting locationInMesh inside the body while the user
    had selected external flow, which produces an inside-out mesh with nothing
    on screen to explain it.
    """

    def test_a_plain_string_region_is_honoured(self, case: Path, tmp_path: Path) -> None:
        with_geometry(case, tmp_path)
        from_ui = plan_mesh(case, MeshSettings(region="external", padding=3.0))
        from_enum = plan_mesh(case, MeshSettings(region=FlowRegion.EXTERNAL, padding=3.0))
        assert from_ui.location_in_mesh == from_enum.location_in_mesh
        assert from_ui.low == from_enum.low

    def test_the_normalised_region_is_always_the_enum(self) -> None:
        assert MeshSettings(region="internal").normalised().region is FlowRegion.INTERNAL
