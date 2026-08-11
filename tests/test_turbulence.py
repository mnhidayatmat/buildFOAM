"""The turbulence advisor (§6.9.1, FR-VVT1..VVT8).

Organised around M4a's four exit criteria (§11), because those are the claims
the milestone is judged on:

* the questionnaire recommends each tutorial's actual model, or justifies an
  alternative;
* no model/wall-treatment/mesh combination can be saved inconsistent;
* the first-cell-height prediction lands within a factor of two on a flat plate
  at three Reynolds numbers;
* the post-run y+ audit flags a deliberately mismatched case, naming the patches.
"""

from __future__ import annotations

import math

import pytest

from foamwb.services.advisor import (
    Answers,
    Compute,
    explain,
    load_catalogue,
    rank_all,
    rank_of,
    recommend,
    wall_treatments_for,
)
from foamwb.services.turbulence import (
    C_MU,
    boundary_layer_cells,
    first_cell_height,
    inlet_turbulence,
    length_scale_from_hydraulic_diameter,
)
from foamwb.services.yplus import (
    BUFFER_LAYER,
    PatchYPlus,
    Verdict,
    audit,
    model_mismatches,
    parse_y_plus,
)

#: Real output from OpenFOAM's pitzDaily tutorial, which runs kEpsilon with wall
#: functions and lands in the buffer layer. Kept verbatim because a fixture that
#: was invented could be made to say anything.
REAL_Y_PLUS = """\
# y+ ()
# Time        	patch         	min           	max           	average
283           	upperWall	4.419546e+00	1.446546e+01	9.385647e+00
283           	lowerWall	2.391041e-01	2.631898e+01	1.518929e+01
"""


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue()


class TestCatalogue:
    """FR-VVT3 — the model list is data, not code."""

    def test_covers_the_prd_model_set(self, catalogue) -> None:
        # §6.9.1 names these explicitly.
        required = {
            "kEpsilon",
            "realizableKE",
            "RNGkEpsilon",
            "kOmega",
            "kOmegaSST",
            "kOmegaSSTLM",
            "SpalartAllmaras",
            "LaunderSharmaKE",
            "v2f",
            "LRR",
            "SSG",
            "Smagorinsky",
            "WALE",
            "kEqn",
            "dynamicKEqn",
            "SpalartAllmarasDDES",
            "SpalartAllmarasIDDES",
            "kOmegaSSTDES",
        }
        assert required <= set(catalogue.names)

    def test_every_model_states_its_trade_offs(self, catalogue) -> None:
        # FR-VVT2: what it is good at, where it is known to fail, its cost. A
        # shortlist without these is a single silent answer with extra steps.
        for model in catalogue.models:
            assert len(model.good_at) > 30, model.name
            assert len(model.fails_at) > 30, model.name
            assert 1 <= model.cost <= 4, model.name

    def test_every_model_names_at_least_one_wall_treatment(self, catalogue) -> None:
        for model in catalogue.models:
            assert model.wall, model.name
            assert all(catalogue.treatment(key) for key in model.wall), model.name

    def test_wall_treatments_carry_their_boundary_conditions(self, catalogue) -> None:
        functions = catalogue.treatment("wall_functions")
        assert functions.condition_for("k") == "kqRWallFunction"
        assert functions.condition_for("epsilon") == "epsilonWallFunction"
        assert functions.condition_for("omega") == "omegaWallFunction"
        assert functions.target_y_plus == (30, 300)

    def test_the_resolved_treatment_targets_unity(self, catalogue) -> None:
        resolved = catalogue.treatment("resolved")
        assert resolved.target_y_plus[1] <= 1


class TestExitCriterionModelChoice:
    """§11: recommends each tutorial's actual model, or justifies an alternative."""

    #: (case, answers describing its physics, the model it actually uses).
    CASES = (
        ("motorBike", Answers(external=True, separation=True), "kOmegaSST"),
        ("angledDuct", Answers(), "kEpsilon"),
        ("pitzDaily", Answers(separation=True), "kEpsilon"),
        ("squareBend", Answers(swirl=True), "kEpsilon"),
        (
            "simplePMMApanel",
            Answers(
                unsteady=True,
                scale_resolving=True,
                resolve_near_wall=True,
                compute=Compute.CLUSTER,
            ),
            "kEqn",
        ),
        (
            "flatPlateTransition",
            Answers(transition=True, resolve_near_wall=True),
            "kOmegaSSTLM",
        ),
    )

    @pytest.mark.parametrize(("case", "answers", "actual"), CASES, ids=[c[0] for c in CASES])
    def test_recommended_or_justified(self, case: str, answers: Answers, actual: str) -> None:
        shortlist = recommend(answers)
        if shortlist[0].name == actual:
            return  # recommended outright

        # Otherwise the alternative must be defensible *and* the tutorial's own
        # model accounted for. A model that simply vanished from a truncated list
        # explains nothing.
        entry = explain(actual, answers)
        assert entry is not None, f"{case}: {actual} is not in the catalogue"
        assert entry.caveats or entry.reasons, (
            f"{case}: {actual} ranked below {shortlist[0].name} with no reason given"
        )
        assert shortlist[0].reasons, f"{case}: the alternative offers no justification"

    def test_a_known_failure_is_named_as_the_reason(self) -> None:
        # pitzDaily is the classic separating flow where kEpsilon is poor, and
        # the advisor should say so rather than silently reorder.
        entry = explain("kEpsilon", Answers(separation=True))
        assert any("separation" in caveat for caveat in entry.caveats)
        assert rank_of("kEpsilon", Answers(separation=True)) > 1

    @pytest.mark.parametrize(("case", "answers", "actual"), CASES, ids=[c[0] for c in CASES])
    def test_at_least_two_candidates_on_every_path(
        self, case: str, answers: Answers, actual: str
    ) -> None:
        # FR-VVT2's acceptance criterion, on every questionnaire path.
        shortlist = recommend(answers)
        assert len(shortlist) >= 2, case
        assert all(r.model.good_at and r.model.fails_at for r in shortlist)


class TestRanking:
    def test_scale_resolving_puts_les_and_hybrid_first(self) -> None:
        # Without a separate question, an LES would be ranked against a URANS as
        # if they cost the same. The near-wall answer matters too: pure LES needs
        # the wall resolved, so it is only a candidate once the user says so.
        answers = Answers(
            unsteady=True,
            scale_resolving=True,
            resolve_near_wall=True,
            compute=Compute.CLUSTER,
        )
        top = rank_all(answers)[:5]
        assert all(r.model.family in {"LES", "hybrid"} for r in top)

    def test_scale_resolving_without_wall_resolution_prefers_wall_modelled(self) -> None:
        # The physically right answer: a scale-resolving run on a wall-function
        # mesh is wall-modelled LES, which is what the hybrid models are for.
        # Pure LES assumes a resolved wall and should not lead here.
        answers = Answers(unsteady=True, scale_resolving=True, compute=Compute.CLUSTER)
        assert rank_all(answers)[0].model.family == "hybrid"

    def test_a_steady_run_never_recommends_an_unsteady_model(self) -> None:
        for entry in recommend(Answers()):
            assert entry.model.family == "RAS"

    def test_a_laptop_budget_rejects_expensive_models(self) -> None:
        # Not a tiebreak: an LES on a laptop is a run the user never sees finish.
        for entry in recommend(Answers(compute=Compute.LAPTOP)):
            assert entry.model.cost <= 2

    def test_transition_promotes_the_only_model_that_predicts_it(self) -> None:
        assert recommend(Answers(transition=True, resolve_near_wall=True))[0].name == (
            "kOmegaSSTLM"
        )

    def test_the_ranking_is_stable(self) -> None:
        # A shortlist that reshuffled between runs would be impossible to discuss.
        answers = Answers(separation=True, external=True)
        assert [r.name for r in recommend(answers)] == [r.name for r in recommend(answers)]

    def test_a_model_absent_from_the_release_is_excluded(self, catalogue) -> None:
        # FR-VVT3: unselectable, not merely warned about.
        from dataclasses import replace

        limited = replace(
            catalogue,
            models=tuple(
                replace(m, since="v9999") if m.name == "kOmegaSST" else m for m in catalogue.models
            ),
        )
        names = [
            r.name
            for r in recommend(
                Answers(separation=True),
                catalogue=limited,
                version="v2506",
                # Newest first, as the manifest orders them: a model "since"
                # a release newer than the installed one is unavailable.
                supported_versions=("v9999", "v2606", "v2512", "v2506"),
            )
        ]
        assert "kOmegaSST" not in names


class TestExitCriterionWallCoupling:
    """§11: no model/wall-treatment combination can be saved inconsistent."""

    def test_a_low_re_model_offers_only_the_resolved_treatment(self, catalogue) -> None:
        # FR-VVT4 by construction: the inconsistent pairing is unreachable rather
        # than warned about.
        model = catalogue.model("LaunderSharmaKE")
        keys = [t.key for t in wall_treatments_for(model, catalogue)]
        assert keys == ["resolved"]

    def test_a_wall_function_model_does_not_offer_a_resolved_pairing_it_lacks(
        self, catalogue
    ) -> None:
        model = catalogue.model("kEpsilon")
        assert [t.key for t in wall_treatments_for(model, catalogue)] == ["wall_functions"]

    def test_a_model_valid_both_ways_offers_both(self, catalogue) -> None:
        model = catalogue.model("kOmegaSST")
        assert {t.key for t in wall_treatments_for(model, catalogue)} == {
            "wall_functions",
            "resolved",
        }

    def test_every_offered_pairing_supplies_conditions_for_the_models_fields(
        self, catalogue
    ) -> None:
        # The pairing is only consistent if the treatment can actually set the
        # fields the model transports.
        for model in catalogue.models:
            for treatment in wall_treatments_for(model, catalogue):
                for field_name in model.fields:
                    if field_name == "R":
                        continue  # Reynolds-stress models set R by their own rules
                    assert treatment.condition_for(field_name), (
                        f"{model.name} with {treatment.key} has no condition for {field_name}"
                    )

    def test_a_resolved_mesh_never_recommends_a_wall_function_only_model(self) -> None:
        for entry in recommend(Answers(resolve_near_wall=True)):
            assert "resolved" in entry.model.wall


class TestExitCriterionFirstCellHeight:
    """§11: within a factor of two at three Reynolds numbers."""

    #: Schlichting's published flat-plate skin friction, for the correlation to
    #: be checked against rather than merely asserted about itself.
    PUBLISHED = ((1e6, 0.00363), (5e6, 0.00263), (1e7, 0.00229))

    @pytest.mark.parametrize(("reynolds", "published"), PUBLISHED)
    def test_skin_friction_matches_published_values(
        self, reynolds: float, published: float
    ) -> None:
        nu = 1.5e-5
        result = first_cell_height(velocity=reynolds * nu, length=1.0, kinematic_viscosity=nu)
        assert result.skin_friction == pytest.approx(published, rel=0.01)

    @pytest.mark.parametrize("reynolds", [1e6, 5e6, 1e7])
    def test_the_computed_height_recovers_the_target(self, reynolds: float) -> None:
        # The claim is a factor of two, and the correlation carries that error.
        # The arithmetic itself must be exact, or the estimate would be wrong for
        # a second, avoidable reason.
        nu = 1.5e-5
        target = 30.0
        result = first_cell_height(
            velocity=reynolds * nu,
            length=1.0,
            kinematic_viscosity=nu,
            target_y_plus=target,
        )
        recovered = result.centre_distance * result.friction_velocity / nu
        assert recovered == pytest.approx(target, rel=1e-9)

    def test_the_height_is_twice_the_centre_distance(self) -> None:
        # A common factor-of-two error: y+ is defined at the cell *centre*, so a
        # mesh built to put its first node there gets half the intended y+.
        result = first_cell_height(velocity=10, length=1, kinematic_viscosity=1.5e-5)
        assert result.height == pytest.approx(2 * result.centre_distance)

    def test_a_finer_target_gives_a_smaller_cell(self) -> None:
        common = {"velocity": 10.0, "length": 1.0, "kinematic_viscosity": 1.5e-5}
        assert (
            first_cell_height(**common, target_y_plus=1).height
            < first_cell_height(**common, target_y_plus=30).height
        )

    def test_the_correlation_is_named(self) -> None:
        # §6.9's rule: a number travels with what produced it.
        result = first_cell_height(velocity=10, length=1, kinematic_viscosity=1.5e-5)
        assert "Schlichting" in result.correlation
        assert "factor of two" in result.accuracy_note
        assert "Re" in result.formula

    def test_out_of_range_reynolds_says_so(self) -> None:
        # Below 5e5 the turbulent flat-plate correlation does not apply, and
        # claiming the usual accuracy there would be a confident wrong number.
        result = first_cell_height(velocity=0.1, length=0.1, kinematic_viscosity=1.5e-5)
        assert "order of magnitude" in result.accuracy_note

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"velocity": 0},
            {"length": -1},
            {"kinematic_viscosity": 0},
            {"target_y_plus": 0},
        ],
    )
    def test_degenerate_input_is_refused(self, kwargs: dict) -> None:
        base = {"velocity": 10.0, "length": 1.0, "kinematic_viscosity": 1.5e-5}
        with pytest.raises(ValueError, match="greater than zero"):
            first_cell_height(**{**base, **kwargs})

    def test_the_inflation_layer_count_is_reported(self) -> None:
        # The height alone does not say what the mesh will cost.
        assert boundary_layer_cells(first_height=1e-4, total_thickness=1e-2) > 5


class TestInletTurbulence:
    """FR-VVT6 — values match hand calculation, formulas shown."""

    def test_matches_the_published_formulas(self) -> None:
        result = inlet_turbulence(velocity=10.0, intensity=0.05, length_scale=0.007)
        k = 1.5 * (10.0 * 0.05) ** 2
        assert result.k == pytest.approx(k)
        assert result.epsilon == pytest.approx(C_MU**0.75 * k**1.5 / 0.007)
        assert result.omega == pytest.approx(k**0.5 / (C_MU**0.25 * 0.007))

    def test_epsilon_and_omega_are_consistent(self) -> None:
        # ω = ε/(Cμ·k) is the defining relation; if these disagreed one of them
        # would be wrong.
        result = inlet_turbulence(velocity=10.0, intensity=0.05, length_scale=0.007)
        assert result.omega == pytest.approx(result.epsilon / (C_MU * result.k))

    def test_every_value_carries_its_formula(self) -> None:
        result = inlet_turbulence(velocity=5.0, intensity=0.05, length_scale=0.01)
        assert set(result.formulas) == {"k", "epsilon", "omega", "nuTilda"}
        assert "approximation" in result.formulas["nuTilda"]

    def test_only_the_fields_a_model_needs_are_offered(self) -> None:
        # A k-omega case has no epsilon to set, and offering one invites writing
        # a field the solver will not read.
        result = inlet_turbulence(velocity=5.0, intensity=0.05, length_scale=0.01)
        assert set(result.for_fields(("k", "omega"))) == {"k", "omega"}
        assert set(result.for_fields(("nuTilda",))) == {"nuTilda"}

    def test_a_percentage_is_refused(self) -> None:
        # 5 rather than 0.05 would give values four hundred times too large, and
        # the run would look plausible while being wrong.
        with pytest.raises(ValueError, match="fraction"):
            inlet_turbulence(velocity=10.0, intensity=5.0, length_scale=0.01)

    def test_length_scale_from_hydraulic_diameter(self) -> None:
        assert length_scale_from_hydraulic_diameter(0.1) == pytest.approx(0.007)


class TestExitCriterionYPlusAudit:
    """§11: flags a deliberately mismatched case, naming the patches."""

    def test_reads_the_function_object_output(self) -> None:
        patches = {p.patch: p for p in parse_y_plus(REAL_Y_PLUS)}
        assert set(patches) == {"upperWall", "lowerWall"}
        assert patches["lowerWall"].maximum == pytest.approx(26.31898)
        assert patches["lowerWall"].average == pytest.approx(15.18929)

    def test_only_the_last_write_is_kept(self) -> None:
        # A steady run writes a row per interval; averaging over the transient
        # would report a mesh the converged solution never had.
        text = REAL_Y_PLUS + "300           \tupperWall\t9.0e+00\t9.0e+00\t9.0e+00\n"
        patches = {p.patch: p for p in parse_y_plus(text)}
        assert patches["upperWall"].maximum == pytest.approx(9.0)
        assert set(patches) == {"upperWall"}

    def test_a_real_tutorial_is_flagged_for_the_buffer_layer(self, catalogue) -> None:
        # pitzDaily runs kEpsilon with wall functions and lands at y+ 4.4-26.3,
        # entirely inside the buffer layer. Nothing in the solver's output says
        # so, which is exactly why the audit exists.
        result = audit(
            parse_y_plus(REAL_Y_PLUS),
            treatment=catalogue.treatment("wall_functions"),
            model=catalogue.model("kEpsilon"),
        )
        assert result.verdict is Verdict.FAIL
        assert set(result.offending) == {"upperWall", "lowerWall"}
        assert all("buffer layer" in p.message for p in result.patches)

    def test_the_message_names_the_patch_and_its_range(self, catalogue) -> None:
        result = audit(
            parse_y_plus(REAL_Y_PLUS),
            treatment=catalogue.treatment("wall_functions"),
            model=catalogue.model("kEpsilon"),
        )
        lower = next(p for p in result.patches if p.name == "lowerWall")
        assert "26.3" in lower.message

    def test_a_mesh_inside_the_target_band_passes(self, catalogue) -> None:
        patches = [PatchYPlus(patch="wall", minimum=45, maximum=180, average=90)]
        result = audit(patches, treatment=catalogue.treatment("wall_functions"))
        assert result.verdict is Verdict.PASS
        assert result.offending == []

    def test_a_low_re_model_on_a_coarse_mesh_fails(self, catalogue) -> None:
        # FR-VVT8's second mismatch: the model needs the sublayer resolved and it
        # is not.
        patches = [PatchYPlus(patch="wall", minimum=20, maximum=60, average=40)]
        result = audit(
            patches,
            treatment=catalogue.treatment("resolved"),
            model=catalogue.model("LaunderSharmaKE"),
        )
        assert result.verdict is Verdict.FAIL
        assert "LaunderSharmaKE" in result.patches[0].message

    def test_a_resolved_mesh_is_not_judged_against_wall_functions(self, catalogue) -> None:
        # Judged against what the case uses. A resolved mesh is not a failure for
        # not being a wall-function mesh.
        patches = [PatchYPlus(patch="wall", minimum=0.3, maximum=0.9, average=0.6)]
        assert audit(patches, treatment=catalogue.treatment("resolved")).verdict is Verdict.PASS

    def test_no_treatment_recorded_warns_rather_than_guessing(self) -> None:
        patches = [PatchYPlus(patch="wall", minimum=1, maximum=2, average=1.5)]
        result = audit(patches)
        assert result.verdict is Verdict.WARN
        assert "nothing to judge it against" in result.patches[0].message

    def test_a_run_with_no_audit_data_is_not_a_failure(self) -> None:
        result = audit([])
        assert not result.has_data
        assert result.verdict is Verdict.PASS

    def test_the_buffer_layer_bounds_are_the_conventional_ones(self) -> None:
        assert BUFFER_LAYER == (5.0, 30.0)


class TestModellingMismatch:
    """FR-VVT8's non-y+ warning."""

    def test_an_epsilon_model_with_separation_is_flagged(self, catalogue) -> None:
        warnings = model_mismatches(
            catalogue.model("kEpsilon"), answers_separation=True, answers_apg=False
        )
        assert warnings
        assert "kOmegaSST" in warnings[0]

    def test_a_suitable_model_is_not_flagged(self, catalogue) -> None:
        assert not model_mismatches(
            catalogue.model("kOmegaSST"), answers_separation=True, answers_apg=True
        )

    def test_an_epsilon_model_without_separation_is_not_flagged(self, catalogue) -> None:
        assert not model_mismatches(
            catalogue.model("kEpsilon"), answers_separation=False, answers_apg=False
        )


def test_c_mu_is_the_standard_value() -> None:
    assert math.isclose(C_MU, 0.09)
