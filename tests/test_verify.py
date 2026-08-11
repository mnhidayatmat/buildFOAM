"""The setup check (FR-C3) and the mesh-settings schema.

The check exists to catch what stops a run. The test that matters most is the
one where a field is missing: before E-C08 that produced no finding at all, so
the panel reported "this case can run" about a case that stops before its first
timestep — a check that misses its own purpose is worse than none (§7.9 rule 6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.case import CaseService
from foamwb.services.properties import groups_for_step
from foamwb.services.schema import load_schema
from foamwb.services.validation import validate_case
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT
from foamwb.ui.views.verify import VerifyView

FV_SOLUTION = """\
FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }
solvers
{
    p               { solver PCG; tolerance 1e-06; }
    pFinal          { $p; relTol 0; }
    U               { solver smoothSolver; tolerance 1e-05; }
    "(k|epsilon|omega)" { solver smoothSolver; tolerance 1e-05; }
}
PISO { nCorrectors 2; }
"""

BLOCK_MESH = """\
FoamFile { version 2.0; format ascii; class dictionary; object blockMeshDict; }
scale   0.1;
vertices ( (0 0 0) (1 0 0) );
blocks ( hex (0 1 2 3 4 5 6 7) (20 20 1) simpleGrading (1 1 1) );
edges ( );
boundary ( );
"""


@pytest.fixture
def case(tmp_path) -> Path:
    root = tmp_path / "cavity"
    (root / "system").mkdir(parents=True)
    (root / "constant").mkdir()
    (root / "0").mkdir()
    # A complete controlDict: the schema check is already strict about required
    # entries, and a half-written fixture would test that instead of E-C08.
    (root / "system" / "controlDict").write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
        "application     icoFoam;\n"
        "startFrom       startTime;\n"
        "startTime       0;\n"
        "stopAt          endTime;\n"
        "endTime         0.5;\n"
        "deltaT          0.005;\n"
        "writeControl    timeStep;\n"
        "writeInterval   20;\n"
    )
    (root / "system" / "fvSolution").write_text(FV_SOLUTION)
    (root / "system" / "blockMeshDict").write_text(BLOCK_MESH)
    for name in ("p", "U"):
        (root / "0" / name).write_text(
            f"FoamFile {{ version 2.0; format ascii; class volScalarField; object {name}; }}\n"
            "dimensions [0 2 -2 0 0 0 0];\ninternalField uniform 0;\nboundaryField {}\n"
        )
    return root


@pytest.fixture
def labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.verify_strings()}


class TestTheMissingFieldCheck:
    def test_a_complete_case_produces_no_blocking_finding(self, case) -> None:
        assert validate_case(CaseService().open(case)).is_runnable

    def test_a_missing_field_blocks_the_run(self, case) -> None:
        (case / "0" / "p").unlink()
        validation = validate_case(CaseService().open(case))
        assert not validation.is_runnable
        assert any(f.code is ErrorCode.MISSING_INITIAL_FIELD for f in validation.blocking)

    def test_the_finding_names_the_field_and_the_consequence(self, case) -> None:
        (case / "0" / "U").unlink()
        finding = next(
            f
            for f in validate_case(CaseService().open(case)).findings
            if f.code is ErrorCode.MISSING_INITIAL_FIELD
        )
        assert "U" in finding.detail
        assert "first timestep" in finding.detail

    def test_a_final_variant_is_not_a_separate_field(self, case) -> None:
        """`pFinal` tunes the last corrector for `p`; there is no 0/pFinal."""
        validation = validate_case(CaseService().open(case))
        assert not any("pFinal" in f.detail for f in validation.findings)

    def test_a_pattern_key_is_skipped(self, case) -> None:
        """`"(k|epsilon|omega)"` is a catch-all no case satisfies in full.

        Requiring every alternative would report healthy cases as broken, and a
        panel that cries wolf is one users learn to close.
        """
        validation = validate_case(CaseService().open(case))
        assert not any(
            f.code is ErrorCode.MISSING_INITIAL_FIELD and "epsilon" in f.detail
            for f in validation.findings
        )

    def test_the_orig_directory_is_accepted(self, case) -> None:
        """Most tutorials ship 0.orig; demanding 0 would flag them all."""
        (case / "0").rename(case / "0.orig")
        assert validate_case(CaseService().open(case)).is_runnable

    def test_no_fv_solution_means_no_claim(self, case) -> None:
        (case / "system" / "fvSolution").unlink()
        (case / "0" / "p").unlink()
        validation = validate_case(CaseService().open(case))
        assert not any(f.code is ErrorCode.MISSING_INITIAL_FIELD for f in validation.findings)


class TestTheVerifyView:
    def _view(self, qtbot, labels, case) -> VerifyView:
        view = VerifyView(LIGHT, labels)
        qtbot.addWidget(view)
        view.set_case(case)
        return view

    def test_a_clean_case_says_so(self, qtbot, case, labels) -> None:
        view = self._view(qtbot, labels, case)
        assert view.verdict_text == strings.verify_strings()["verify_ready"]
        assert view.finding_count == 0

    def test_a_clean_result_still_shows_what_it_does_not_prove(self, qtbot, case, labels) -> None:
        """§6.9 — a tick implying correctness is the failure mode that matters."""
        view = self._view(qtbot, labels, case)
        assert view.shows_caveat

    def test_a_broken_case_is_reported_as_unrunnable(self, qtbot, case, labels) -> None:
        (case / "0" / "p").unlink()
        view = self._view(qtbot, labels, case)
        assert view.verdict_text == strings.verify_strings()["verify_not_ready"]
        assert view.finding_count >= 1
        assert not view.is_runnable

    def test_severity_is_stated_as_its_consequence(self, qtbot, case, labels) -> None:
        """NFR-A2 — "blocks the run" is what the user needs, not "error"."""
        (case / "0" / "p").unlink()
        view = self._view(qtbot, labels, case)
        assert view.severity_of(0) == strings.verify_strings()["sev_error"]

    def test_checking_again_picks_up_an_external_edit(self, qtbot, case, labels) -> None:
        """The person pressing this has just edited a file in another window."""
        view = self._view(qtbot, labels, case)
        assert view.is_runnable
        (case / "0" / "p").unlink()
        view.run_check()
        assert not view.is_runnable

    def test_no_case_is_said_plainly(self, qtbot, labels) -> None:
        view = VerifyView(LIGHT, labels)
        qtbot.addWidget(view)
        view.set_case(None)
        assert view.summary_text == strings.verify_strings()["verify_no_case"]


class TestTheMeshSettingsSchema:
    def test_it_loads(self) -> None:
        assert load_schema("blockMeshDict") is not None

    def test_scale_is_described_with_its_unit(self, case) -> None:
        group = groups_for_step(case, "mesh.settings")[0]
        row = next(r for r in group.rows if r.path == "scale")
        assert row.label == "Scale"
        assert row.unit == "m"

    def test_the_structural_entries_are_shown_and_marked(self, case) -> None:
        """A form offering "vertex 3" would invite topology-breaking edits."""
        group = groups_for_step(case, "mesh.settings")[0]
        structural = {r.path for r in group.rows if r.unknown}
        assert {"vertices", "blocks", "boundary"} <= structural

    def test_structural_entries_are_not_editable_here(self, case) -> None:
        group = groups_for_step(case, "mesh.settings")[0]
        assert all(not r.editable for r in group.rows if r.unknown)

    def test_the_file_header_is_not_a_setting(self, case) -> None:
        """FoamFile would otherwise head every panel with file metadata."""
        for step in ("mesh.settings", "conditions.basic"):
            for group in groups_for_step(case, step):
                assert all(r.path != "FoamFile" for r in group.rows)
