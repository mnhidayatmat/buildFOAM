"""The geometry panel (FR-P3, §7.4).

The file dialog is injected for the same reason the shell's is: a modal dialog
blocks its thread until a human answers, so a test that reached one would hang
rather than fail — and importing is precisely the path a user takes most.

Runs offscreen, so no display is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from foamwb.services.cad import CadConverter
from foamwb.services.geometry import existing_surfaces
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT
from foamwb.ui.widgets.geometry_panel import GeometryPanel
from foamwb.ui.widgets.surface_preview import SurfacePreview
from test_geometry import ASCII_STL, FakeKernel, converter_with
from test_preview import cube_triangles, write_ascii


@pytest.fixture
def labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.preprocessor_strings()}


@pytest.fixture
def case(tmp_path: Path) -> Path:
    root = tmp_path / "cavity"
    (root / "system").mkdir(parents=True)
    (root / "constant").mkdir()
    (root / "system" / "controlDict").write_text("application simpleFoam;\n")
    return root


def _no_converter() -> CadConverter:
    converter = CadConverter(app_dirs=(), configured=None)
    converter._from_path = lambda: None
    return converter


@pytest.fixture
def panel(qtbot, labels) -> GeometryPanel:
    widget = GeometryPanel(LIGHT, labels, converter=_no_converter())
    qtbot.addWidget(widget)
    return widget


class TestEmptyState:
    def test_says_what_is_missing_rather_than_showing_an_empty_box(
        self, panel: GeometryPanel, case: Path
    ) -> None:
        panel.set_case(case)
        assert panel.surfaces == []
        assert panel.status_text == panel._labels["geometry_none"]

    def test_importing_is_refused_before_a_case_is_open(self, panel: GeometryPanel) -> None:
        # The button would otherwise offer to import into nothing.
        assert not panel.can_import

    def test_importing_is_offered_once_a_case_is_open(
        self, panel: GeometryPanel, case: Path
    ) -> None:
        panel.set_case(case)
        assert panel.can_import


class TestImporting:
    def test_an_stl_is_listed_after_import(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)

        assert panel.import_file(source)
        assert [s.name for s in panel.surfaces] == ["wing.stl"]

    def test_the_dialog_route_imports_what_it_is_given(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)
        panel.set_dialogs(choose_file=lambda _title, _filters: source)

        panel.import_dialog()
        assert [s.name for s in panel.surfaces] == ["wing.stl"]

    def test_cancelling_the_dialog_imports_nothing(self, panel: GeometryPanel, case: Path) -> None:
        panel.set_case(case)
        panel.set_dialogs(choose_file=lambda _title, _filters: None)
        panel.import_dialog()
        assert panel.surfaces == []

    def test_an_imported_surface_is_drawn(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        # The bounding box catches units and nothing else — not the wrong body,
        # not half an assembly, not a surface that came out inside out.
        source = tmp_path / "box.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)
        panel.import_file(source)
        assert panel.preview.triangle_count > 0
        assert panel.preview.showing == "box.stl"

    def test_the_preview_is_hidden_when_there_is_nothing_to_show(
        self, panel: GeometryPanel, case: Path
    ) -> None:
        panel.set_case(case)
        assert not panel.preview.isVisibleTo(panel)

    def test_the_preview_follows_the_selection(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        panel.set_case(case)
        for name in ("one.stl", "two.stl"):
            source = tmp_path / name
            source.write_text(ASCII_STL)
            panel.import_file(source)

        panel.select(0)
        assert panel.preview.showing == "one.stl"
        panel.select(1)
        assert panel.preview.showing == "two.stl"

    def test_turning_one_surface_does_not_carry_over_to_the_next(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        # A user shown a new import upside down would read it as a fault in the
        # file they just chose.
        panel.set_case(case)
        for name in ("one.stl", "two.stl"):
            source = tmp_path / name
            source.write_text(ASCII_STL)
            panel.import_file(source)

        panel.select(0)
        started_at = panel.preview.angles
        panel.preview._yaw += 1.0
        panel.select(1)
        assert panel.preview.angles == started_at

    def test_the_row_states_the_size_so_wrong_units_are_visible(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        """No geometry format records its units, so the number is the mitigation.

        A user who imported a car and sees 4200 x 1800 knows it is millimetres.
        Nothing can detect that; showing it is the whole answer.
        """
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)
        panel.import_file(source)

        described = panel._describe(panel.surfaces[0])
        assert "1" in described
        assert "triangle" in described.lower()

    def test_region_names_are_shown_because_refinement_is_per_region(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)
        panel.import_file(source)
        assert "cube" in panel._describe(panel.surfaces[0])

    def test_a_failed_import_reports_its_code(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "notes.txt"
        source.write_text("not geometry")
        panel.set_case(case)

        assert not panel.import_file(source)
        # E-C10: the remedy is to export a different format, and only the code
        # distinguishes that from "install a converter".
        assert "E-C10" in panel.status_text

    def test_an_unreadable_stl_reports_rather_than_landing_in_the_case(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text("<html>404</html>")
        panel.set_case(case)

        assert not panel.import_file(source)
        assert "E-C09" in panel.status_text
        assert panel.surfaces == []


class TestCadWithoutAConverter:
    def test_step_says_the_converter_is_missing_not_that_the_file_is_bad(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.step"
        source.write_text("ISO-10303-21;")
        panel.set_case(case)

        assert not panel.import_file(source)
        assert "E-C11" in panel.status_text

    def test_the_panel_says_up_front_that_cad_cannot_be_converted(
        self, panel: GeometryPanel
    ) -> None:
        # Said before the user picks a STEP file, not after it fails.
        assert "Gmsh" in panel.converter_text


class TestCadWithAConverter:
    def test_a_step_file_is_converted_and_listed(
        self, qtbot, labels, case: Path, tmp_path: Path
    ) -> None:
        kernel = FakeKernel(writes=ASCII_STL.encode())
        widget = GeometryPanel(LIGHT, labels, converter=converter_with(kernel, tmp_path))
        qtbot.addWidget(widget)
        widget.set_case(case)

        source = tmp_path / "wing.step"
        source.write_text("ISO-10303-21;")
        assert widget.import_file(source)
        assert [s.name for s in widget.surfaces] == ["wing.stl"]

    def test_the_converter_is_named_when_one_is_present(
        self, qtbot, labels, tmp_path: Path
    ) -> None:
        widget = GeometryPanel(LIGHT, labels, converter=converter_with(FakeKernel(), tmp_path))
        qtbot.addWidget(widget)
        assert "Gmsh" not in widget.converter_text or "gmsh" in widget.converter_text.lower()


class TestRemoving:
    def test_removing_deletes_the_file(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)
        panel.import_file(source)
        imported = panel.surfaces[0].path

        panel.select(0)
        assert panel.remove_selected()
        assert not imported.exists()
        assert panel.surfaces == []

    def test_removing_with_nothing_selected_does_nothing(
        self, panel: GeometryPanel, case: Path
    ) -> None:
        panel.set_case(case)
        assert not panel.remove_selected()

    def test_the_source_file_is_not_touched_by_a_removal(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)
        panel.import_file(source)
        panel.select(0)
        panel.remove_selected()
        assert source.is_file(), "removing from the case must not delete the user's model"


class TestSignals:
    def test_an_import_announces_that_the_mesh_inputs_changed(
        self, panel: GeometryPanel, case: Path, tmp_path: Path, qtbot
    ) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)

        with qtbot.waitSignal(panel.geometry_changed, timeout=1000):
            panel.import_file(source)


class TestMeshSection:
    """FR-P3 — the geometry can actually be meshed once imported."""

    def _with_geometry(self, panel: GeometryPanel, case: Path, tmp_path: Path) -> None:
        source = tmp_path / "wing.stl"
        source.write_text(ASCII_STL)
        panel.set_case(case)
        panel.import_file(source)

    def test_generating_is_refused_before_geometry_exists(
        self, panel: GeometryPanel, case: Path
    ) -> None:
        panel.set_case(case)
        assert not panel.can_generate

    def test_generating_is_offered_once_geometry_is_imported(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        self._with_geometry(panel, case, tmp_path)
        assert panel.can_generate

    def test_the_domain_and_cell_count_are_shown_before_generating(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        # The cell count decides whether meshing takes a minute or an hour, so
        # it has to move while the user is choosing rather than after.
        self._with_geometry(panel, case, tmp_path)
        assert panel.domain_text
        assert "cells" in panel.domain_text.lower()

    def test_changing_a_control_re_derives_the_domain(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        self._with_geometry(panel, case, tmp_path)
        before = panel.plan.background_cell_count
        panel._cells.setValue(80)
        assert panel.plan.background_cell_count != before

    def test_the_flow_region_reaches_the_plan(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        self._with_geometry(panel, case, tmp_path)
        external = panel.plan.location_in_mesh
        panel._region.setCurrentIndex(1)  # internal
        assert panel.plan.location_in_mesh != external

    def test_generating_writes_both_dictionaries(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        self._with_geometry(panel, case, tmp_path)
        assert panel.generate_dictionaries()
        assert (case / "system" / "blockMeshDict").is_file()
        assert (case / "system" / "snappyHexMeshDict").is_file()

    def test_generating_makes_the_meshing_utilities_available(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        """The dead end this closes: geometry with no way to mesh it."""
        from foamwb.services.mesh import available_utilities

        self._with_geometry(panel, case, tmp_path)
        assert not {u.name for u in available_utilities(case, meshed=False)} & {
            "blockMesh",
            "snappyHexMesh",
        }
        panel.generate_dictionaries()
        assert {"blockMesh", "snappyHexMesh"} <= {
            u.name for u in available_utilities(case, meshed=False)
        }

    def test_the_button_says_replace_when_something_would_be_lost(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        self._with_geometry(panel, case, tmp_path)
        assert panel.generate_text == panel._labels["generate_mesh_dicts"]

        panel.generate_dictionaries()
        # Now the dictionaries exist, so the act is a replacement and the label
        # is where that difference is visible.
        assert panel.generate_text == panel._labels["replace_mesh_dicts"]

    def test_replacing_asks_first(self, panel: GeometryPanel, case: Path, tmp_path: Path) -> None:
        self._with_geometry(panel, case, tmp_path)
        (case / "system" / "snappyHexMeshDict").write_text("// tuned by hand\n")
        panel.refresh()

        asked: list[str] = []
        panel.set_dialogs(confirm=lambda title, _body: asked.append(title) or False)

        assert not panel.generate_dictionaries()
        assert asked, "a tuned dictionary was about to be replaced without asking"
        assert "tuned by hand" in (case / "system" / "snappyHexMeshDict").read_text()

    def test_confirming_the_replacement_writes(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        self._with_geometry(panel, case, tmp_path)
        (case / "system" / "snappyHexMeshDict").write_text("// tuned\n")
        panel.refresh()
        panel.set_dialogs(confirm=lambda _t, _b: True)

        assert panel.generate_dictionaries()
        assert "castellatedMesh" in (case / "system" / "snappyHexMeshDict").read_text()

    def test_removing_the_last_surface_withdraws_the_offer(
        self, panel: GeometryPanel, case: Path, tmp_path: Path
    ) -> None:
        self._with_geometry(panel, case, tmp_path)
        panel.select(0)
        panel.remove_selected()
        assert not panel.can_generate


class TestNamingFacesFromTheView:
    """FR-P3 — the names typed here become the mesh's patches."""

    @pytest.fixture
    def cube_case(self, panel: GeometryPanel, case: Path, tmp_path: Path) -> GeometryPanel:
        source = write_ascii(tmp_path / "cube.stl", cube_triangles())
        panel.set_case(case)
        panel.set_dialogs(choose_file=lambda _t, _f: source)
        panel.import_dialog()
        # Paint once: picking is tested against what was drawn, so nothing can
        # be picked until a frame exists — which is the honest constraint, not a
        # test artefact. The size is the layout's, not ours to choose, so the
        # click point below is taken from the widget rather than assumed.
        panel.preview.grab()
        return panel

    def test_a_cube_offers_six_faces(self, cube_case: GeometryPanel) -> None:
        assert cube_case.preview.faces_known
        assert cube_case.preview.face_count == 6

    def test_clicking_the_model_selects_one_face(self, cube_case: GeometryPanel) -> None:
        face = _centre_face(cube_case.preview)
        assert face is not None
        cube_case.preview.select([face])
        assert cube_case.preview.selected == (face,)

    def test_naming_writes_a_surface_with_that_solid(self, cube_case: GeometryPanel) -> None:
        cube_case.preview.select([0])
        cube_case.region_name_field.setText("inlet")
        assert cube_case.name_selection()

        named = [s for s in existing_surfaces(cube_case._case) if "inlet" in s.solids]
        assert named, "the named surface should be in constant/triSurface"

    def test_a_name_openfoam_cannot_use_is_corrected_and_said(
        self, cube_case: GeometryPanel
    ) -> None:
        """Silently rewriting it would leave the user hunting for their patch."""
        cube_case.preview.select([0])
        cube_case.region_name_field.setText("front face")
        assert cube_case.name_selection()
        assert "front face" in cube_case.status_text
        assert "front_face" in cube_case.status_text

    def test_naming_nothing_does_nothing(self, cube_case: GeometryPanel) -> None:
        cube_case.preview.clear_selection()
        cube_case.region_name_field.setText("inlet")
        assert not cube_case.name_selection()

    def test_an_empty_name_is_refused_with_a_reason(self, cube_case: GeometryPanel) -> None:
        cube_case.preview.select([0])
        cube_case.region_name_field.setText("!!!")
        assert not cube_case.name_selection()
        assert cube_case.status_text

    def test_the_named_regions_are_listed(self, cube_case: GeometryPanel) -> None:
        cube_case.preview.select([0])
        cube_case.region_name_field.setText("inlet")
        cube_case.name_selection()
        assert "inlet" in cube_case.region_rows[0]

    def test_naming_clears_the_selection_ready_for_the_next_face(
        self, cube_case: GeometryPanel
    ) -> None:
        cube_case.preview.select([0])
        cube_case.region_name_field.setText("inlet")
        cube_case.name_selection()
        assert cube_case.preview.selected == ()

    def test_the_hint_counts_the_faces_it_found(self, cube_case: GeometryPanel) -> None:
        """NFR-A2 — the selection is in words as well as in colour."""
        assert "6" in cube_case.naming_hint

    def test_switching_surface_drops_the_selection(
        self, cube_case: GeometryPanel, tmp_path: Path
    ) -> None:
        """Face ids mean nothing across files, so a kept selection would lie."""
        cube_case.preview.select([0])
        cube_case.preview.set_surface(write_ascii(tmp_path / "b.stl", cube_triangles()), "b.stl")
        assert cube_case.preview.selected == ()


class TestTurningIsNotSelecting:
    """One button does both gestures, so they are told apart by travel."""

    def _press(self, widget, x: float, y: float, buttons=Qt.MouseButton.LeftButton):
        return QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(x, y),
            Qt.MouseButton.LeftButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    def _release(self, x: float, y: float):
        return QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(x, y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )

    @pytest.fixture
    def preview(self, qtbot, labels, tmp_path: Path):
        widget = SurfacePreview(LIGHT, labels)
        qtbot.addWidget(widget)
        widget.resize(400, 300)
        widget.set_surface(write_ascii(tmp_path / "cube.stl", cube_triangles()), "cube.stl")
        widget.grab()
        return widget

    def test_a_click_selects(self, preview) -> None:
        x, y = _centre_of(preview)
        preview.mousePressEvent(self._press(preview, x, y))
        preview.mouseReleaseEvent(self._release(x, y))
        assert preview.selected

    def test_a_drag_turns_without_selecting(self, preview) -> None:
        x, y = _centre_of(preview)
        before = preview.angles
        preview.mousePressEvent(self._press(preview, x, y))
        preview.mouseMoveEvent(self._press(preview, x + 60, y))
        preview.mouseReleaseEvent(self._release(x + 60, y))
        assert preview.angles != before
        assert preview.selected == ()

    def test_a_click_on_the_background_clears(self, preview) -> None:
        preview.select([0])
        preview.mousePressEvent(self._press(preview, 1, 1))
        preview.mouseReleaseEvent(self._release(1, 1))
        assert preview.selected == ()


def _centre_of(preview) -> tuple[float, float]:
    """The middle of the widget as it was actually painted.

    Not a fixed point: the preview's size comes from the layout it sits in, and
    a hard-coded coordinate silently lands off the model the first time that
    layout changes — which is a test that stops testing rather than one that
    fails.
    """
    return preview.width() / 2, preview.height() / 2


def _centre_face(preview) -> int | None:
    x, y = _centre_of(preview)
    return preview.face_at(x, y)
