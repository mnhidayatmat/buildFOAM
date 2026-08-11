"""The V&V view and the apply path (§7.7, FR-VVT4, FR-VVT7, FR-VVT9)."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from foamwb.services.advisor import load_catalogue
from foamwb.services.apply_turbulence import (
    apply_turbulence,
    current_choice,
    plan_apply,
)
from foamwb.services.case import CaseService
from foamwb.services.foamdict import Document
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT
from foamwb.ui.views.vandv import VandVView
from test_preprocessor import BOUNDARY, CONTROL_DICT, field_file

TURBULENCE = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}
simulationType      RAS;

RAS
{
    RASModel        kEpsilon;
    turbulence      on;
    printCoeffs     on;
}
"""

Y_PLUS = """\
# y+ ()
# Time        	patch         	min           	max           	average
283           	movingWall	4.419546e+00	1.446546e+01	9.385647e+00
"""

DICT_NAME = "turbulenceProperties"


def make_case(root: Path) -> Path:
    case = root / "cavity"
    for part in ("system", "constant/polyMesh", "0"):
        (case / part).mkdir(parents=True)
    (case / "system" / "controlDict").write_text(CONTROL_DICT)
    (case / "constant" / "polyMesh" / "boundary").write_text(BOUNDARY)
    (case / "constant" / DICT_NAME).write_text(TURBULENCE)
    for name, conditions in (
        ("U", {"movingWall": "fixedValue", "fixedWalls": "noSlip", "frontAndBack": "empty"}),
        ("p", {".*": "zeroGradient", "frontAndBack": "empty"}),
        (
            "k",
            {
                "movingWall": "kqRWallFunction",
                "fixedWalls": "kqRWallFunction",
                "frontAndBack": "empty",
            },
        ),
        (
            "nut",
            {
                "movingWall": "nutkWallFunction",
                "fixedWalls": "nutkWallFunction",
                "frontAndBack": "empty",
            },
        ),
    ):
        (case / "0" / name).write_text(field_file(conditions))
    return case


@pytest.fixture
def labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.vandv_strings()}


@pytest.fixture
def view(qtbot, labels, tmp_path) -> VandVView:
    widget = VandVView(LIGHT, labels)
    qtbot.addWidget(widget)
    case = CaseService().open(make_case(tmp_path))
    widget.set_case(case, version="v0000", dictionary_name=DICT_NAME)
    return widget


class TestProvenance:
    """§7.7 — the strip that stops a table outliving its case."""

    def test_names_the_case_version_and_current_model(self, view) -> None:
        text = view.provenance_text
        assert "cavity" in text
        assert "v0000" in text
        assert "kEpsilon" in text

    def test_says_so_when_no_case_is_open(self, qtbot, labels) -> None:
        widget = VandVView(LIGHT, labels)
        qtbot.addWidget(widget)
        assert "Open a case" in widget.provenance_text

    def test_it_follows_an_applied_change(self, view) -> None:
        view.set_answer("separation", True)
        view.select_model("kOmegaSST")
        view.apply_selection()
        assert "kOmegaSST" in view.provenance_text


class TestShortlist:
    """FR-VVT2 — never a single silent answer."""

    def test_shows_several_candidates_with_trade_offs(self, view) -> None:
        assert len(view.shortlist_names) >= 2
        text = view.shortlist_text
        assert "Good at:" in text
        assert "Known to fail:" in text
        assert "Cost:" in text

    def test_it_re_ranks_when_an_answer_changes(self, view) -> None:
        before = view.shortlist_names
        view.set_answer("transition", True)
        view.set_answer("resolve_near_wall", True)
        assert view.shortlist_names != before
        assert view.shortlist_names[0] == "kOmegaSSTLM"

    def test_the_cases_own_model_is_always_accounted_for(self, view) -> None:
        # FR-VVT1: recommends the tutorial's model or explains an alternative. A
        # model that merely fell off a truncated list explains nothing.
        view.set_answer("separation", True)
        assert "kEpsilon" not in view.shortlist_names
        note = view.current_model_note
        assert "kEpsilon" in note
        assert "separation" in note


class TestWallCoupling:
    """FR-VVT4 — an inconsistent pairing is unreachable."""

    def test_only_the_models_own_treatments_are_offered(self, view) -> None:
        view.select_model("kEpsilon")
        assert view.treatment_options == ["Wall functions"]

    def test_a_model_valid_both_ways_offers_both(self, view) -> None:
        view.set_answer("separation", True)
        view.select_model("kOmegaSST")
        assert len(view.treatment_options) == 2

    def test_the_target_band_follows_the_treatment(self, view) -> None:
        view.set_answer("separation", True)
        view.select_model("kOmegaSST")
        view.select_treatment("wall_functions")
        assert "30" in view.numbers_text
        view.select_treatment("resolved")
        assert "aiming at 1" in view.numbers_text


class TestCoupledNumbers:
    """§7.7's right-hand panel, and §7.9 rule 6."""

    def test_shows_the_derived_quantities(self, view) -> None:
        text = view.numbers_text
        assert "First cell height" in text
        assert "Inflation layers" in text
        assert "Reynolds number" in text

    def test_inlet_values_carry_their_formulas(self, view) -> None:
        # FR-VVT6 requires the formula shown, not just the number.
        assert "1.5·(U·I)²" in view.numbers_text

    def test_only_the_models_own_fields_are_offered(self, view) -> None:
        view.set_answer("separation", True)
        view.select_model("kOmegaSST")
        assert "Inlet omega" in view.numbers_text
        assert "Inlet epsilon" not in view.numbers_text

    def test_no_number_appears_without_its_caveat(self, view) -> None:
        # §7.9 rule 6. A number that looks authoritative and is not is worse
        # than no number.
        assert "Schlichting" in view.caveat_text

    def test_an_out_of_range_reynolds_is_admitted(self, view) -> None:
        # The defaults give Re below the correlation's range, and the panel says
        # so rather than presenting the estimate at face value.
        assert "order of magnitude" in view.caveat_text


class TestApply:
    """FR-VVT9 — rewrites only what changed."""

    def test_changing_the_model_touches_one_line(self, view, tmp_path) -> None:
        source = tmp_path / "cavity" / "constant" / DICT_NAME
        before = source.read_text()
        view.set_answer("separation", True)
        view.select_model("kOmegaSST")
        view.select_treatment("wall_functions")
        assert view.apply_selection()

        changed = [
            line
            for line in difflib.unified_diff(
                before.splitlines(), source.read_text().splitlines(), n=0, lineterm=""
            )
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        assert len(changed) == 2
        assert "kOmegaSST" in changed[1]

    def test_the_wall_conditions_follow_the_treatment(self, view, tmp_path) -> None:
        # The coupling that makes the pairing consistent by construction.
        view.set_answer("separation", True)
        view.select_model("kOmegaSST")
        view.select_treatment("resolved")
        view.apply_selection()

        nut = Document.parse_bytes((tmp_path / "cavity" / "0" / "nut").read_bytes())
        assert nut.get("boundaryField/movingWall/type") == "nutLowReWallFunction"
        # An unconstrained patch that is not a wall is untouched: an inlet's
        # condition is a physical boundary, not the wall treatment's to decide.
        assert nut.get("boundaryField/frontAndBack/type") == "empty"

    def test_applying_the_same_choice_twice_writes_nothing(self, view, tmp_path) -> None:
        view.select_model("kEpsilon")
        view.apply_selection()
        source = tmp_path / "cavity" / "constant" / DICT_NAME
        before = source.read_bytes()
        view.apply_selection()
        assert source.read_bytes() == before

    def test_a_family_change_is_refused_with_a_reason(self, view, tmp_path) -> None:
        # Not a limitation: switching to LES needs a transient setup, and doing
        # a tenth of the job silently would produce a case that runs and means
        # nothing.
        catalogue = load_catalogue()
        case = CaseService().open(tmp_path / "cavity")
        plan = plan_apply(
            case,
            catalogue.model("kEqn"),
            catalogue.treatment("resolved"),
            dictionary_name=DICT_NAME,
        )
        assert plan.blocked
        assert "transient" in plan.blocked
        assert not apply_turbulence(case, plan).changed_anything

    def test_the_case_still_parses_afterwards(self, view, tmp_path) -> None:
        view.set_answer("separation", True)
        view.select_model("kOmegaSST")
        view.apply_selection()
        reopened = CaseService().open(tmp_path / "cavity")
        assert reopened.application == "icoFoam"
        assert current_choice(reopened, dictionary_name=DICT_NAME) == (
            "kOmegaSST",
            "RAS",
        )


class TestAudit:
    """FR-VVT7 — per-patch, against the band the case actually uses."""

    def test_says_so_when_there_is_no_data(self, view) -> None:
        assert view.audit_rows == 0
        assert "No y+ data yet" in view.audit_note

    def test_reports_each_patch_after_a_run(self, view, tmp_path) -> None:
        target = tmp_path / "cavity" / "postProcessing" / "yPlus" / "0"
        target.mkdir(parents=True)
        (target / "yPlus.dat").write_text(Y_PLUS)
        view.refresh_audit()
        assert view.audit_rows == 1

    def test_a_buffer_layer_result_is_flagged_and_named(self, view, tmp_path) -> None:
        # The finding §6.9.1 exists for, on data from a real tutorial.
        target = tmp_path / "cavity" / "postProcessing" / "yPlus" / "0"
        target.mkdir(parents=True)
        (target / "yPlus.dat").write_text(Y_PLUS)
        view.select_model("kEpsilon")
        view.refresh_audit()
        assert "movingWall" in view.audit_note
        assert "outside" in view.audit_note


class TestDeferredTabs:
    """§7.9 rule 1 applies to unbuilt modules too."""

    def test_all_three_tabs_exist(self, view) -> None:
        assert view._tabs.count() == 3

    def test_each_deferred_tab_says_what_it_will_hold(self, view) -> None:
        from PySide6.QtWidgets import QLabel

        for index in (1, 2):
            text = " ".join(label.text() for label in view._tabs.widget(index).findChildren(QLabel))
            assert len(text.split()) > 15

    def test_the_validation_tab_promises_no_boolean_verdict(self, view) -> None:
        # DEC-20 and FR-VVE8, stated before the module exists so the promise is
        # on record rather than discovered later.
        from PySide6.QtWidgets import QLabel

        text = " ".join(label.text() for label in view._tabs.widget(2).findChildren(QLabel))
        assert "validated" in text
        assert "belongs to you" in text
