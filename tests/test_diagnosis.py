"""M5 — divergence detection and failure diagnosis (FR-S6).

The fixtures here are **abridged real logs**, not invented ones. Every pattern
asserted was first observed by running the installed OpenFOAM v2512 and making it
fail on purpose: relaxation factors at 1.0 to blow up ``simpleFoam``, a mistyped
keyword, a deleted ``0/p``. Inventing the shapes would only prove the parser
matches the author's imagination.
"""

from __future__ import annotations

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.run.diagnosis import (
    COURANT_LIMIT,
    Confidence,
    DivergenceWatcher,
    Signal,
    diagnose,
)

# ---------------------------------------------------------------------------
# Fixtures taken from real runs.
# ---------------------------------------------------------------------------

#: simpleFoam/pitzDaily with relaxation 1.0 and FOAM_SIGFPE=false. The trailing
#: fatal error is genuine and is a *consequence* of the nan, not its cause.
DIVERGED_TO_NAN = """\
Time = 1

smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.0767884, No Iterations 1
smoothSolver:  Solving for Uy, Initial residual = 1, Final residual = 0.0613675, No Iterations 2
GAMG:  Solving for p, Initial residual = nan, Final residual = nan, No Iterations 1000
smoothSolver:  Solving for epsilon, Initial residual = nan, Final residual = nan, No Iterations 1000
ExecutionTime = 1.14 s  ClockTime = 1 s

--> FOAM FATAL IO ERROR: (openfoam-2512)
Wrong token type - expected scalar value, found on line 2: word 'nan'

file: system/data/solver/p at line 2.

FOAM exiting
"""

#: The same case with trapping left at its default. Exit status 132.
DIVERGED_TO_TRAP = """\
Time = 1

smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.0767884, No Iterations 1
[stack trace]
=============
#1  Foam::sigFpe::sigHandler(int) in libOpenFOAM.dylib
#2  _sigtramp in libsystem_platform.dylib
=============
"""

#: A mistyped ``endTime`` keyword. Exit status 1, exactly like a divergence.
TYPO_IN_CONTROL_DICT = """\
--> FOAM FATAL IO ERROR: (openfoam-2512)
Entry 'endTime' not found in dictionary "/case/system/controlDict"

FOAM exiting
"""

#: A deleted ``0/p``. Also exit status 1.
MISSING_FIELD = """\
--> FOAM FATAL ERROR: (openfoam-2512)
cannot find file "/case/0/p"

FOAM exiting
"""

#: icoFoam/cavity at a tenfold timestep: Courant 8.5 and perfectly converged.
HEALTHY_HIGH_COURANT = """\
Time = 0.05

Courant Number mean: 2.2217 max: 8.52139
smoothSolver:  Solving for Ux, Initial residual = 1.53e-08, Final residual = 1.5e-08, No Iters 0
DICPCG:  Solving for p, Initial residual = 1.04e-06, Final residual = 1.27e-07, No Iterations 1
ExecutionTime = 0.06 s  ClockTime = 0 s

End
"""


class TestDivergenceIsNamed:
    def test_a_nan_residual_is_reported_as_divergence(self) -> None:
        found = diagnose(DIVERGED_TO_NAN, 1)
        assert found is not None
        assert found.signal is Signal.NON_FINITE_RESIDUAL
        assert found.code is ErrorCode.DIVERGED
        assert found.confidence is Confidence.CERTAIN

    def test_the_message_names_the_field_and_the_time(self) -> None:
        """FR-S6 fixes the shape: what happened, to which quantity, when."""
        found = diagnose(DIVERGED_TO_NAN, 1)
        assert "diverged" in found.message.lower()
        assert found.field_name == "p"
        assert found.time == "1"
        assert "t = 1" in found.message

    def test_the_nan_beats_the_fatal_error_it_caused(self) -> None:
        """The ordering that makes the difference between help and misdirection.

        A diverged run ends with a fatal IO error about a *generated* file
        (``system/data/solver/p``). Matching that first would tell the user to go
        and fix a file they never wrote and cannot meaningfully edit.
        """
        found = diagnose(DIVERGED_TO_NAN, 1)
        assert found.signal is Signal.NON_FINITE_RESIDUAL
        assert "system/data" not in found.message

    def test_a_floating_point_trap_is_reported_as_divergence(self) -> None:
        found = diagnose(DIVERGED_TO_TRAP, 132)
        assert found.signal is Signal.FLOATING_POINT_TRAP
        assert found.code is ErrorCode.DIVERGED

    def test_the_trap_message_does_not_blame_the_stack_trace(self) -> None:
        """A C++ stack trace is not a fact about the user's case."""
        found = diagnose(DIVERGED_TO_TRAP, 132)
        assert "sigFpe" not in found.message
        assert "diverged" in found.message.lower()


class TestSetupErrorsAreNotDivergences:
    """The correction M5 makes to M2's exit-code rule."""

    def test_a_typo_is_not_called_a_divergence(self) -> None:
        found = diagnose(TYPO_IN_CONTROL_DICT, 1)
        assert found.code is ErrorCode.SOLVER_SETUP_ERROR
        assert "diverg" not in found.message.lower()

    def test_the_typo_message_names_the_entry(self) -> None:
        found = diagnose(TYPO_IN_CONTROL_DICT, 1)
        assert "endTime" in found.message

    def test_a_missing_field_is_not_called_a_divergence(self) -> None:
        found = diagnose(MISSING_FIELD, 1)
        assert found.code is ErrorCode.SOLVER_SETUP_ERROR
        assert "0/p" in found.message

    def test_the_same_exit_code_yields_three_different_answers(self) -> None:
        """Exit 1 covers all three, which is why the log is the evidence."""
        codes = {
            diagnose(text, 1).code
            for text in (DIVERGED_TO_NAN, TYPO_IN_CONTROL_DICT, MISSING_FIELD)
        }
        assert codes == {ErrorCode.DIVERGED, ErrorCode.SOLVER_SETUP_ERROR}
        assert diagnose(DIVERGED_TO_NAN, 1).code is not diagnose(MISSING_FIELD, 1).code


class TestFalseAlarms:
    def test_a_healthy_run_gets_no_diagnosis(self) -> None:
        assert diagnose(HEALTHY_HIGH_COURANT, 0) is None

    def test_courant_of_eight_is_not_an_alarm(self) -> None:
        """Measured, not assumed: this run converged cleanly at Co 8.5.

        A textbook "Co < 1" threshold would have condemned a healthy run, and a
        warning users learn to dismiss is worse than none (§7.9 rule 6).
        """
        assert COURANT_LIMIT > 8.52139
        assert diagnose(HEALTHY_HIGH_COURANT, 0) is None

    def test_an_empty_log_yields_nothing_rather_than_a_guess(self) -> None:
        assert diagnose("", 1) is None

    def test_no_diagnosis_is_preferred_to_an_invented_one(self) -> None:
        assert diagnose("Time = 5\nsomething unremarkable\n", 1) is None


class TestCourantBlowUp:
    def test_a_runaway_courant_number_is_flagged(self) -> None:
        log = "Time = 3\nCourant Number mean: 900 max: 4500\n"
        found = diagnose(log, 1)
        assert found.signal is Signal.COURANT_EXCEEDED
        assert "4.5e+03" in found.message or "4500" in found.message

    def test_it_is_hedged_because_it_is_an_inference(self) -> None:
        found = diagnose("Time = 3\nCourant Number mean: 900 max: 4500\n", 1)
        assert found.confidence is Confidence.LIKELY

    def test_a_non_finite_courant_number_is_certain(self) -> None:
        found = diagnose("Time = 3\nCourant Number mean: nan max: nan\n", 1)
        assert found.confidence is Confidence.CERTAIN


class TestResidualGrowth:
    def _rising(self, count: int) -> str:
        lines = ["Time = 1"]
        value = 1e-3
        for _ in range(count):
            lines.append(
                f"smoothSolver:  Solving for Ux, Initial residual = {value:.6g}, "
                "Final residual = 1, No Iterations 1"
            )
            value *= 5
        return "\n".join(lines)

    def test_sustained_growth_is_reported(self) -> None:
        found = diagnose(self._rising(12), 1)
        assert found is not None
        assert found.signal is Signal.RESIDUAL_GROWTH

    def test_a_short_rise_is_not(self) -> None:
        """Residuals bounce. Three points rising is noise, not divergence."""
        assert diagnose(self._rising(3), 1) is None

    def test_growth_is_hedged(self) -> None:
        assert diagnose(self._rising(12), 1).confidence is Confidence.LIKELY


class TestOtherFailures:
    def test_out_of_memory(self) -> None:
        found = diagnose("Time = 2\nstd::bad_alloc\n", 1)
        assert found.code is ErrorCode.OUT_OF_MEMORY

    def test_disk_full(self) -> None:
        found = diagnose("Time = 2\nNo space left on device\n", 1)
        assert found.code is ErrorCode.DISK_FULL

    def test_a_signal_death_with_no_message_is_hedged(self) -> None:
        found = diagnose("Time = 4\n", 139)
        assert found.signal is Signal.KILLED_BY_SIGNAL
        assert found.confidence is Confidence.LIKELY


class TestGuideLinks:
    @pytest.mark.parametrize(
        "log,code",
        [
            (DIVERGED_TO_NAN, 1),
            (DIVERGED_TO_TRAP, 132),
            (TYPO_IN_CONTROL_DICT, 1),
            (MISSING_FIELD, 1),
        ],
    )
    def test_every_diagnosis_resolves_to_a_guide_anchor(self, log: str, code: int) -> None:
        """FR-G2 — a diagnosis the user cannot follow up is half an answer."""
        found = diagnose(log, code)
        assert found.guide_anchor
        assert "/" in found.guide_anchor


class TestLiveWatcher:
    """The watcher exists to catch a blow-up while the run can still be stopped."""

    def test_it_reports_a_nan_as_the_line_arrives(self) -> None:
        watcher = DivergenceWatcher()
        found = None
        for line in DIVERGED_TO_NAN.splitlines():
            found = watcher.feed(line) or found
        assert found is not None
        assert found.signal is Signal.NON_FINITE_RESIDUAL

    def test_it_knows_the_time_it_happened(self) -> None:
        watcher = DivergenceWatcher()
        results = [watcher.feed(line) for line in DIVERGED_TO_NAN.splitlines()]
        found = next(r for r in results if r is not None)
        assert found.time == "1"

    def test_it_reports_once_not_once_per_line(self) -> None:
        """A diverged run emits thousands of nan lines. A banner per line is noise."""
        watcher = DivergenceWatcher()
        reports = [watcher.feed(line) for line in DIVERGED_TO_NAN.splitlines() * 20]
        assert len([r for r in reports if r is not None]) == 1

    def test_a_healthy_run_never_triggers_it(self) -> None:
        watcher = DivergenceWatcher()
        assert all(watcher.feed(line) is None for line in HEALTHY_HIGH_COURANT.splitlines())
        assert not watcher.reported

    def test_it_catches_growth_before_the_run_ends(self) -> None:
        watcher = DivergenceWatcher()
        value, found = 1e-6, None
        watcher.feed("Time = 1")
        for _ in range(14):
            found = found or watcher.feed(
                f"smoothSolver:  Solving for Ux, Initial residual = {value:.6g}, "
                "Final residual = 1, No Iterations 1"
            )
            value *= 6
        assert found is not None
        assert found.signal is Signal.RESIDUAL_GROWTH
