"""The patch and initial-condition editors (FR-P3, FR-P4, E-C04).

Both edit files the application did not write, so both are checked for FR-P7:
the diff of a change is the line that changed, and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.services.boundary import read_boundary
from foamwb.services.initial import (
    format_dimensions,
    read_initial_fields,
    set_internal_field,
)
from foamwb.services.regions import (
    SELECTABLE_TYPES,
    apply_patch_type,
    plan_patch_type,
)
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT
from foamwb.ui.views.initial import InitialConditionsView
from foamwb.ui.views.regions import RegionsView

BOUNDARY = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       polyBoundaryMesh;
    object      boundary;
}

3
(
    movingWall
    {
        type            wall;
        inGroups        1(wall);
        nFaces          20;
        startFace       760;
    }
    fixedWalls
    {
        type            wall;
        inGroups        1(wall);
        nFaces          60;
        startFace       780;
    }
    frontAndBack
    {
        type            empty;
        inGroups        1(empty);
        nFaces          800;
        startFace       840;
    }
)
"""

FIELD_U = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}

dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{
    movingWall
    {
        type            fixedValue;
        value           uniform (1 0 0);
    }
    frontAndBack
    {
        type            empty;
    }
}
"""


@pytest.fixture
def case(tmp_path) -> Path:
    root = tmp_path / "cavity"
    (root / "constant" / "polyMesh").mkdir(parents=True)
    (root / "system").mkdir()
    (root / "0").mkdir()
    (root / "constant" / "polyMesh" / "boundary").write_text(BOUNDARY)
    (root / "0" / "U").write_text(FIELD_U)
    (root / "system" / "controlDict").write_text("application icoFoam;\n")
    return root


@pytest.fixture
def region_labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.regions_strings()}


@pytest.fixture
def initial_labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.initial_strings()}


class TestChangingAPatchType:
    def test_a_change_is_planned_before_it_is_made(self, case) -> None:
        change = plan_patch_type(case, "movingWall", "patch")
        assert change.can_apply
        assert (case / "constant" / "polyMesh" / "boundary").read_text() == BOUNDARY

    def test_only_the_type_line_changes(self, case) -> None:
        """FR-P7 on a file we did not write and do not fully understand."""
        source = case / "constant" / "polyMesh" / "boundary"
        change = plan_patch_type(case, "movingWall", "patch")
        assert apply_patch_type(case, change)

        before = BOUNDARY.splitlines()
        after = source.read_text().splitlines()
        assert len(before) == len(after)
        differing = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        assert len(differing) == 1
        assert "wall" in before[differing[0]]
        assert "patch" in after[differing[0]]

    def test_the_face_counts_are_untouched(self, case) -> None:
        """The mesh's own numbers must survive an edit to a label."""
        change = plan_patch_type(case, "movingWall", "patch")
        apply_patch_type(case, change)
        patches = {p.name: p for p in read_boundary(case)}
        assert patches["movingWall"].n_faces == 20
        assert patches["frontAndBack"].n_faces == 800

    def test_a_no_op_writes_nothing(self, case) -> None:
        source = case / "constant" / "polyMesh" / "boundary"
        change = plan_patch_type(case, "movingWall", "wall")
        assert change.is_noop
        assert not apply_patch_type(case, change)
        assert source.read_text() == BOUNDARY

    def test_an_unknown_patch_is_refused_by_name(self, case) -> None:
        change = plan_patch_type(case, "nosuch", "wall")
        assert change.blocked
        assert "nosuch" in change.blocked

    def test_a_type_this_editor_does_not_set_is_refused(self, case) -> None:
        """`processor` is decomposition machinery, not a choice."""
        change = plan_patch_type(case, "movingWall", "processor")
        assert change.blocked
        assert not change.can_apply


class TestConsequencesAreStated:
    def test_becoming_a_wall_mentions_wall_functions(self, case) -> None:
        change = plan_patch_type(case, "frontAndBack", "wall")
        assert any("wall function" in line for line in change.consequences)

    def test_leaving_wall_says_the_audit_stops_applying(self, case) -> None:
        change = plan_patch_type(case, "movingWall", "patch")
        assert any("y+" in line for line in change.consequences)

    def test_empty_warns_about_dimensionality(self, case) -> None:
        """Two keystrokes that make a 3D case unsolvable."""
        change = plan_patch_type(case, "movingWall", "empty")
        assert any("2D" in line for line in change.consequences)

    def test_cyclic_says_it_needs_a_partner(self, case) -> None:
        change = plan_patch_type(case, "movingWall", "cyclic")
        assert any("partner" in line for line in change.consequences)

    def test_a_constrained_type_lists_the_fields_that_must_follow(self, case) -> None:
        change = plan_patch_type(case, "movingWall", "empty")
        assert change.fields_needing_update == {"U": "empty"}

    def test_those_fields_are_not_rewritten_here(self, case) -> None:
        """A large edit must not hide behind a small one."""
        original = (case / "0" / "U").read_text()
        change = plan_patch_type(case, "movingWall", "empty")
        apply_patch_type(case, change)
        assert (case / "0" / "U").read_text() == original

    def test_a_field_already_correct_is_not_listed(self, case) -> None:
        change = plan_patch_type(case, "frontAndBack", "empty")
        assert change.is_noop or "U" not in change.fields_needing_update

    def test_the_face_count_is_reported(self, case) -> None:
        change = plan_patch_type(case, "movingWall", "patch")
        assert any("20 faces" in line for line in change.consequences)


class TestDimensionRendering:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("[0 1 -1 0 0 0 0]", "m/s"),
            ("[0 2 -2 0 0 0 0]", "m²/s²"),
            ("[0 2 -3 0 0 0 0]", "m²/s³"),
            ("[1 -1 -2 0 0 0 0]", "kg/m·s²"),
            ("[0 0 0 1 0 0 0]", "K"),
            ("[0 0 -1 0 0 0 0]", "1/s"),
            ("[0 0 0 0 0 0 0]", "-"),
        ],
    )
    def test_the_exponent_vector_is_rendered(self, raw: str, expected: str) -> None:
        assert format_dimensions(raw) == expected

    @pytest.mark.parametrize("raw", ["", "junk", "[0 1 -1]", "[a b c d e f g]"])
    def test_an_unusable_vector_yields_nothing_rather_than_a_guess(self, raw: str) -> None:
        """A wrong unit beside a number invites trust it has not earned."""
        assert format_dimensions(raw) == ""


class TestInitialConditions:
    def test_fields_are_read_with_their_units(self, case) -> None:
        fields = {f.name: f for f in read_initial_fields(case)}
        assert fields["U"].unit == "m/s"
        assert fields["U"].value == "(0 0 0)"

    def test_a_vector_is_recognised(self, case) -> None:
        entry = next(f for f in read_initial_fields(case) if f.name == "U")
        assert entry.is_vector
        assert entry.is_uniform

    def test_editing_changes_one_line(self, case) -> None:
        entry = next(f for f in read_initial_fields(case) if f.name == "U")
        assert set_internal_field(entry, "(1 0 0)")

        before, after = FIELD_U.splitlines(), (case / "0" / "U").read_text().splitlines()
        differing = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        assert len(differing) == 1

    def test_the_boundary_field_is_untouched(self, case) -> None:
        """Boundary values belong to the matrix; two owners would disagree."""
        entry = next(f for f in read_initial_fields(case) if f.name == "U")
        set_internal_field(entry, "(1 0 0)")
        text = (case / "0" / "U").read_text()
        assert "uniform (1 0 0);" in text
        assert "type            fixedValue;" in text

    def test_the_uniform_keyword_is_added_for_the_user(self, case) -> None:
        """It is part of the file format, not part of the physics."""
        entry = next(f for f in read_initial_fields(case) if f.name == "U")
        set_internal_field(entry, "(3 0 0)")
        assert "internalField   uniform (3 0 0);" in (case / "0" / "U").read_text()

    def test_an_identical_value_writes_nothing(self, case) -> None:
        entry = next(f for f in read_initial_fields(case) if f.name == "U")
        assert not set_internal_field(entry, "(0 0 0)")

    def test_an_empty_value_is_refused(self, case) -> None:
        entry = next(f for f in read_initial_fields(case) if f.name == "U")
        assert not set_internal_field(entry, "   ")

    def test_an_unreadable_file_is_still_listed(self, case) -> None:
        """Omitting it would understate what the case contains."""
        (case / "0" / "broken").write_text("{{{ not a dictionary")
        assert "broken" in [f.name for f in read_initial_fields(case)]


class TestTheRegionsView:
    def test_it_lists_the_patches(self, qtbot, case, region_labels) -> None:
        view = RegionsView(LIGHT, region_labels)
        qtbot.addWidget(view)
        view.set_case(case)
        assert view.patch_names == ["movingWall", "fixedWalls", "frontAndBack"]

    def test_no_mesh_is_said_plainly(self, qtbot, tmp_path, region_labels) -> None:
        view = RegionsView(LIGHT, region_labels)
        qtbot.addWidget(view)
        view.set_case(tmp_path)
        assert view.status_text == strings.regions_strings()["no_mesh_yet"]

    def test_choosing_a_new_type_shows_the_consequences(self, qtbot, case, region_labels) -> None:
        view = RegionsView(LIGHT, region_labels)
        qtbot.addWidget(view)
        view.set_case(case)
        view.choose("movingWall", "empty")
        assert view.shows_consequences
        assert "2D" in view.consequence_text

    def test_the_same_type_shows_nothing(self, qtbot, case, region_labels) -> None:
        view = RegionsView(LIGHT, region_labels)
        qtbot.addWidget(view)
        view.set_case(case)
        view.choose("movingWall", "wall")
        assert not view.shows_consequences

    def test_the_fields_that_must_follow_are_named(self, qtbot, case, region_labels) -> None:
        view = RegionsView(LIGHT, region_labels)
        qtbot.addWidget(view)
        view.set_case(case)
        view.choose("movingWall", "empty")
        assert "U" in view.followers_text

    def test_applying_updates_the_table(self, qtbot, case, region_labels) -> None:
        view = RegionsView(LIGHT, region_labels)
        qtbot.addWidget(view)
        view.set_case(case)
        view.choose("movingWall", "patch")
        with qtbot.waitSignal(view.patches_changed, timeout=2000):
            view._apply_type()
        assert view.status_text

    def test_every_selectable_type_is_offered(self, qtbot, case, region_labels) -> None:
        view = RegionsView(LIGHT, region_labels)
        qtbot.addWidget(view)
        view.set_case(case)
        offered = {view._type.itemData(i) for i in range(view._type.count())}
        assert offered == set(SELECTABLE_TYPES)

    def test_processor_is_never_offered(self, qtbot, case, region_labels) -> None:
        assert "processor" not in SELECTABLE_TYPES


class TestTheInitialConditionsView:
    def _view(self, qtbot, labels, case) -> InitialConditionsView:
        view = InitialConditionsView(LIGHT, labels)
        qtbot.addWidget(view)
        view.set_case(case)
        return view

    def test_it_lists_the_fields_with_units(self, qtbot, case, initial_labels) -> None:
        view = self._view(qtbot, initial_labels, case)
        assert view.field_names == ["U"]
        assert view.unit_of("U") == "m/s"

    def test_a_uniform_field_is_editable(self, qtbot, case, initial_labels) -> None:
        view = self._view(qtbot, initial_labels, case)
        assert view.is_editable("U")

    def test_editing_writes_through_and_confirms(self, qtbot, case, initial_labels) -> None:
        """The confirmation must survive the refresh that follows the write."""
        view = self._view(qtbot, initial_labels, case)
        view.set_value("U", "(5 0 0)")
        assert view.value_of("U") == "(5 0 0)"
        assert "5 0 0" in view.status_text

    def test_the_hint_matches_the_field_shape(self, qtbot, case, initial_labels) -> None:
        view = self._view(qtbot, initial_labels, case)
        assert view.hint_text == strings.initial_strings()["vector_hint"]

    def test_a_nonuniform_field_is_not_offered_for_editing(
        self, qtbot, case, initial_labels
    ) -> None:
        """A text box for a million numbers is worse than none."""
        (case / "0" / "T").write_text(
            "FoamFile { version 2.0; format ascii; class volScalarField; object T; }\n"
            "dimensions      [0 0 0 1 0 0 0];\n"
            "internalField   nonuniform List<scalar> 3(1 2 3);\n"
            "boundaryField { }\n"
        )
        view = self._view(qtbot, initial_labels, case)
        assert "T" in view.field_names
        assert not view.is_editable("T")

    def test_no_fields_is_said_plainly(self, qtbot, tmp_path, initial_labels) -> None:
        view = self._view(qtbot, initial_labels, tmp_path)
        assert view.status_text == strings.initial_strings()["no_fields"]
