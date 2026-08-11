"""The divergence banner (FR-S6, §7.5).

Offscreen, like every Qt test here. ``isVisibleTo`` rather than ``isVisible``
throughout: the latter is False for any descendant of a window that was never
shown, so a test written the obvious way passes whatever the widget does.
"""

from __future__ import annotations

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.run.diagnosis import Confidence, Diagnosis, Signal
from foamwb.ui.strings import run_strings
from foamwb.ui.theme import DARK, LIGHT
from foamwb.ui.widgets.diagnosis_banner import DiagnosisBanner

CERTAIN = Diagnosis(
    signal=Signal.NON_FINITE_RESIDUAL,
    code=ErrorCode.DIVERGED,
    field_name="p",
    time="1",
    message="Solution diverged: the residual for p became nan at t = 1.",
    detail="GAMG:  Solving for p, Initial residual = nan",
)

SUSPECTED = Diagnosis(
    signal=Signal.COURANT_EXCEEDED,
    code=ErrorCode.DIVERGED,
    time="3",
    confidence=Confidence.LIKELY,
    message="Solution diverging: Courant number reached 4500 at t = 3.",
    detail="Reduce deltaT.",
)


@pytest.fixture
def banner(qtbot):
    widget = DiagnosisBanner(LIGHT, run_strings())
    qtbot.addWidget(widget)
    return widget


class TestItStaysOutOfTheWay:
    def test_it_is_hidden_until_there_is_something_to_say(self, banner) -> None:
        assert not banner.is_showing
        assert banner.diagnosis is None

    def test_dismissing_hides_it_again(self, banner) -> None:
        banner.show_diagnosis(CERTAIN)
        assert banner.is_showing
        banner.clear()
        assert not banner.is_showing


class TestItStatesTheFinding:
    def test_the_message_is_shown_verbatim(self, banner) -> None:
        banner.show_diagnosis(CERTAIN)
        assert banner.message_text == CERTAIN.message

    def test_the_error_code_travels_with_it(self, banner) -> None:
        """§9: a support conversation should start from a code."""
        banner.show_diagnosis(CERTAIN)
        assert "E-S03" in banner._code.text()

    def test_a_certain_finding_is_stated_plainly(self, banner) -> None:
        banner.show_diagnosis(CERTAIN)
        assert banner.title_text == run_strings()["diverged_title"]

    def test_a_suspicion_is_labelled_as_one(self, banner) -> None:
        """§6.9: a confident wrong answer is worse than a hedged right one."""
        banner.show_diagnosis(SUSPECTED)
        assert banner.title_text == run_strings()["diverging_suspected"]
        assert banner.title_text != run_strings()["diverged_title"]

    def test_confidence_is_not_carried_by_colour_alone(self, banner) -> None:
        """NFR-A3 — the words differ, not just the border."""
        banner.show_diagnosis(CERTAIN)
        certain = banner.title_text
        banner.show_diagnosis(SUSPECTED)
        assert banner.title_text != certain


class TestItOffersTheRemedy:
    def test_a_running_run_can_be_stopped_from_the_banner(self, banner) -> None:
        banner.show_diagnosis(CERTAIN, running=True)
        assert banner.offers_stop

    def test_a_finished_run_is_not_offered_a_stop(self, banner) -> None:
        """There is nothing left to stop, and a dead button teaches distrust."""
        banner.show_diagnosis(CERTAIN, running=False)
        assert not banner.offers_stop

    def test_stopping_emits_the_request(self, banner, qtbot) -> None:
        banner.show_diagnosis(CERTAIN, running=True)
        with qtbot.waitSignal(banner.stop_requested, timeout=1000):
            banner._stop.click()

    def test_the_guide_link_carries_the_anchor(self, banner, qtbot) -> None:
        """FR-G2 — a finding the user cannot follow up is half an answer."""
        banner.show_diagnosis(CERTAIN)
        with qtbot.waitSignal(banner.guide_requested, timeout=1000) as caught:
            banner._guide.click()
        assert caught.args == [ErrorCode.DIVERGED.guide_anchor]

    def test_a_running_run_is_told_it_is_still_burning_time(self, banner) -> None:
        banner.show_diagnosis(CERTAIN, running=True)
        assert run_strings()["diverged_still_running"] in banner._detail.text()

    def test_a_finished_run_is_not(self, banner) -> None:
        banner.show_diagnosis(CERTAIN, running=False)
        assert run_strings()["diverged_still_running"] not in banner._detail.text()


class TestAccessibility:
    def test_it_has_an_accessible_name_carrying_the_finding(self, banner) -> None:
        banner.show_diagnosis(CERTAIN)
        name = banner.accessibleName()
        assert CERTAIN.message in name
        assert banner.title_text in name

    def test_both_themes_apply_without_error(self, banner) -> None:
        banner.show_diagnosis(CERTAIN)
        for palette in (LIGHT, DARK):
            banner.set_palette(palette)
            assert palette.surface_alt in banner.styleSheet()
