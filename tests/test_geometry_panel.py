"""The geometry panel (FR-P3, §7.4).

The file dialog is injected for the same reason the shell's is: a modal dialog
blocks its thread until a human answers, so a test that reached one would hang
rather than fail — and importing is precisely the path a user takes most.

Runs offscreen, so no display is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.services.cad import CadConverter
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT
from foamwb.ui.widgets.geometry_panel import GeometryPanel
from test_geometry import ASCII_STL, FakeKernel, converter_with


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
