"""M7 — the guide, its links, and the pseudo-locale (FR-G1, FR-G2, NFR-A5).

The link check is the milestone's headline: every §9 code must resolve to a
section that exists. It is asserted here as well as in the preflight guard,
because the guard can be skipped and a test cannot.
"""

from __future__ import annotations

import pytest

from foamwb.codes import ALL_CODES
from foamwb.services.guide import load_guide, parse_page
from foamwb.ui import strings
from foamwb.ui.pseudo import PADDING, pseudo_locale, pseudo_text
from foamwb.ui.theme import LIGHT
from foamwb.ui.views.guide import GuideView

#: Every catalogue the application ships, so the pseudo pass covers all of them.
CATALOGUES = [
    strings.shell_strings,
    strings.run_strings,
    strings.workflow_strings,
    strings.library_strings,
    strings.post_strings,
    strings.verify_strings,
    strings.guide_strings,
    strings.regions_strings,
    strings.initial_strings,
    strings.vandv_strings,
    strings.preprocessor_strings,
]


@pytest.fixture(scope="module")
def guide():
    return load_guide()


class TestEveryCodeResolves:
    """FR-G2, and M7's exit criterion: zero dangling anchors."""

    @pytest.mark.parametrize("code_id", sorted(ALL_CODES))
    def test_the_anchor_points_at_a_real_section(self, guide, code_id: str) -> None:
        anchor = ALL_CODES[code_id].guide_anchor
        assert guide.resolve(anchor) is not None, f"{code_id} -> {anchor}"

    def test_no_code_is_left_without_a_page(self, guide) -> None:
        dangling = [c.guide_anchor for c in ALL_CODES.values() if not guide.resolve(c.guide_anchor)]
        assert dangling == []

    def test_the_section_says_something(self, guide) -> None:
        """A heading with no prose under it resolves and helps nobody."""
        for code in ALL_CODES.values():
            _page, section = guide.resolve(code.guide_anchor)
            assert len(section.body) > 80, f"{code.id} has almost no content"

    def test_the_section_names_its_code(self, guide) -> None:
        """So a user searching for "E-S03" finds the page that explains it."""
        for code in ALL_CODES.values():
            _page, section = guide.resolve(code.guide_anchor)
            assert code.id in section.body, f"{section.anchor} never mentions {code.id}"


class TestParsing:
    def test_a_level_one_heading_is_the_title(self) -> None:
        page = parse_page("x", "# Running a case\n\n## Divergence\n\nbody\n")
        assert page.title == "Running a case"

    def test_headings_become_anchors_in_the_code_form(self) -> None:
        page = parse_page("running", "# T\n\n## Floating point\n\nbody\n")
        assert page.anchors == ("running/floating-point",)

    def test_punctuation_is_dropped_from_an_anchor(self) -> None:
        page = parse_page("x", "# T\n\n## checkMesh errors\n\nbody\n")
        assert page.anchors == ("x/checkmesh-errors",)

    def test_a_page_with_no_headings_has_no_sections(self) -> None:
        assert parse_page("x", "just prose\n").sections == ()


class TestOfflineSearch:
    """FR-G1 — the machine most likely to need help is the one behind a proxy."""

    def test_a_term_finds_its_section(self, guide) -> None:
        assert guide.search("divergence")

    def test_every_term_must_match(self, guide) -> None:
        """A second word narrows; any-term matching would widen it."""
        one = guide.search("mesh")
        two = guide.search("mesh checkMesh")
        assert len(two) <= len(one)

    def test_an_unmatched_term_yields_nothing(self, guide) -> None:
        assert guide.search("mesh zzzznosuchword") == []

    def test_an_empty_query_yields_nothing(self, guide) -> None:
        assert guide.search("") == []
        assert guide.search("   ") == []

    def test_results_are_stable_between_runs(self, guide) -> None:
        """A search that reshuffles identical results looks broken."""
        first = [(p.name, s.anchor) for p, s in guide.search("mesh")]
        second = [(p.name, s.anchor) for p, s in guide.search("mesh")]
        assert first == second

    def test_a_prefix_matches(self, guide) -> None:
        assert guide.search("diverg")


class TestTheGuideView:
    def _view(self, qtbot) -> GuideView:
        view = GuideView(LIGHT, {**strings.shell_strings(), **strings.guide_strings()})
        qtbot.addWidget(view)
        return view

    def test_it_lists_every_page(self, qtbot, guide) -> None:
        view = self._view(qtbot)
        assert view.result_count == len(guide.pages)

    def test_a_code_link_lands_on_the_section(self, qtbot) -> None:
        """Not the top of a nine-section page."""
        view = self._view(qtbot)
        assert view.show_anchor("running/divergence")
        assert "E-S03" in view.body_text

    def test_an_unknown_anchor_is_refused_rather_than_approximated(self, qtbot) -> None:
        """Landing somewhere unrelated is how a guide loses trust."""
        view = self._view(qtbot)
        assert not view.show_anchor("running/no-such-section")

    def test_searching_replaces_the_contents(self, qtbot) -> None:
        view = self._view(qtbot)
        view.search_for("divergence")
        assert view.result_count >= 1
        assert "results for" in view.status_text

    def test_clearing_the_search_restores_the_contents(self, qtbot, guide) -> None:
        view = self._view(qtbot)
        view.search_for("divergence")
        view.search_for("")
        assert view.result_count == len(guide.pages)

    def test_a_fruitless_search_says_so(self, qtbot) -> None:
        view = self._view(qtbot)
        view.search_for("zzzznosuchword")
        assert view.result_count == 0
        assert "Nothing found" in view.status_text


class TestPseudoLocale:
    """NFR-A5 — layout faults should surface before a translator does."""

    def test_text_is_expanded(self) -> None:
        assert len(pseudo_text("End time")) >= len("End time") * PADDING - 1

    def test_placeholders_survive_exactly(self) -> None:
        """Otherwise the pseudo run fails with a format error instead of showing
        the layout problem it exists to show."""
        assert "{0}" in pseudo_text("Run failed at {0} ({1}).")
        assert "{1}" in pseudo_text("Run failed at {0} ({1}).")

    def test_a_formatted_string_still_formats(self) -> None:
        assert "solve" in pseudo_text("Run failed at {0} ({1}).").format("solve", "E-S03")

    def test_the_text_is_visibly_not_english(self) -> None:
        assert pseudo_text("Solution diverging") != "Solution diverging"

    def test_keys_are_untouched(self) -> None:
        """They are lookup identifiers; accenting them breaks every widget."""
        catalogue = pseudo_locale(strings.run_strings())
        assert "stop_write" in catalogue

    @pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda f: f.__name__)
    def test_every_catalogue_survives_the_transform(self, catalogue) -> None:
        original = catalogue()
        pseudo = pseudo_locale(original)
        assert set(pseudo) == set(original)

    @pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda f: f.__name__)
    def test_every_placeholder_survives(self, catalogue) -> None:
        import re

        for key, value in catalogue().items():
            placeholders = set(re.findall(r"\{[^}]*\}", value))
            assert placeholders <= set(re.findall(r"\{[^}]*\}", pseudo_text(value))), key

    def test_the_shell_builds_pseudo_localised(self, qtbot) -> None:
        """The strongest check available headlessly: nothing raises, and every
        widget still finds the key it asked for."""
        from foamwb.ui.views.run import RunView

        labels = pseudo_locale({**strings.shell_strings(), **strings.run_strings()})
        view = RunView(LIGHT, labels)
        qtbot.addWidget(view)
        assert view.stop_button_text != "Stop && Write"
