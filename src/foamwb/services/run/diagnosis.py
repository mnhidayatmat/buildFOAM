"""Telling the user why a run failed (FR-S6).

**OpenFOAM never says a solution is diverging.** That is not an oversight in this
module's research; it is a measured fact about the installed runtime: neither
``libOpenFOAM`` nor ``libfiniteVolume`` contains the substring ``diverg`` at all.
A diverging run either dies in a floating-point trap with a C++ stack trace, or —
with trapping disabled — quietly fills its residuals with ``nan`` and keeps
iterating. Neither outcome tells a P4 user what happened. Producing that sentence
is therefore this application's job, which is exactly why FR-S6 exists.

Diagnosis is made from **log content, never from the exit code**. The exit code
cannot carry the distinction:

* a diverged run with trapping off exits **1**;
* a mistyped ``endTime`` keyword exits **1**;
* a missing ``0/p`` exits **1**;
* a diverged run with trapping on exits **132**.

Reporting "solution diverged" for a typo would send someone hunting for a
numerical instability that does not exist — the confidently wrong diagnosis §7.9
rule 6 forbids, and the reason the previous exit-code test is replaced here.

**Order of checks is load-bearing, and not obvious.** A run that diverges to
``nan`` ends with::

    --> FOAM FATAL IO ERROR: (openfoam-2512)
    Wrong token type - expected scalar value, found on line 2: word 'nan'
    file: system/data/solver/p at line 2.

That fatal error is a *consequence* of the divergence: the ``nan`` was written
into a generated file and then failed to read back. Matching the fatal error
first would point the user at a file they never wrote. The non-finite residual is
the cause and is therefore checked first, and every ordering below is justified
the same way — by which signal explains the other.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise

from foamwb.codes import Code, ErrorCode

__all__ = [
    "COURANT_LIMIT",
    "Confidence",
    "Diagnosis",
    "DivergenceWatcher",
    "Signal",
    "diagnose",
]

#: Above this, a Courant number is reported as trouble rather than merely high.
#:
#: Deliberately far above the textbook "Co < 1": the ``icoFoam`` cavity tutorial
#: run at a tenfold timestep reaches **Co 8.5 and still converges cleanly**, so a
#: limit of 1 or 5 would cry wolf on a run that is perfectly healthy. PIMPLE cases
#: routinely run at Co of 5-20 by design. A number this high is not a rule of
#: thumb being broken; it is a solution running away.
COURANT_LIMIT = 100.0

#: How far an initial residual must climb before growth alone is called out.
#: Residuals bounce by an order of magnitude in normal steady runs; three decades
#: of sustained growth does not happen to a converging solution.
_GROWTH_FACTOR = 1.0e3

#: Consecutive rises required before growth is believed. A single rise is noise.
_GROWTH_RUN = 8


class Confidence(StrEnum):
    """How much the evidence supports the conclusion.

    Surfaced rather than hidden because §6.9's whole argument is that a confident
    wrong answer is worse than a hedged right one. A ``nan`` is not a guess; a
    high Courant number is.
    """

    CERTAIN = "certain"
    """The log states the failure outright: a nan, a trap, a named fatal error."""

    LIKELY = "likely"
    """Consistent with the evidence, but inferred. Phrased as a suspicion."""


class Signal(StrEnum):
    """What was actually observed, separate from what it is taken to mean."""

    NON_FINITE_RESIDUAL = "non-finite-residual"
    FLOATING_POINT_TRAP = "floating-point-trap"
    OUT_OF_MEMORY = "out-of-memory"
    DISK_FULL = "disk-full"
    COURANT_EXCEEDED = "courant-exceeded"
    RESIDUAL_GROWTH = "residual-growth"
    FATAL_IO_ERROR = "fatal-io-error"
    FATAL_ERROR = "fatal-error"
    KILLED_BY_SIGNAL = "killed-by-signal"


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """One conclusion about why a run ended badly."""

    signal: Signal
    code: Code
    message: str
    """The sentence shown to the user. FR-S6 fixes its shape: what happened,
    which quantity, and when."""

    detail: str = ""
    """The evidence, quoted from the log, for a user who wants to check."""

    time: str = ""
    """Solver time at which it happened, empty if the log never reached one."""

    field_name: str = ""
    confidence: Confidence = Confidence.CERTAIN

    @property
    def guide_anchor(self) -> str:
        """FR-G2: every diagnosis resolves to a guide page."""
        return self.code.guide_anchor

    @property
    def at_time(self) -> str:
        return f" at t = {self.time}" if self.time else ""


_TIME = re.compile(r"^Time = (\S+)")
_RESIDUAL = re.compile(r"Solving for (\S+?),\s+Initial residual = (\S+?),")
_COURANT = re.compile(r"Courant Number mean: (\S+) max: (\S+)")
_NON_FINITE = re.compile(r"^[+-]?(nan|inf|infinity)$", re.IGNORECASE)


def _as_float(text: str) -> float | None:
    """Parse a residual, treating OpenFOAM's ``nan`` spellings as non-finite."""
    cleaned = text.rstrip(",")
    if _NON_FINITE.match(cleaned):
        return math.nan if "n" in cleaned.lower() else math.inf
    try:
        return float(cleaned)
    except ValueError:
        return None


def diagnose(log: str, exit_code: int | None = None) -> Diagnosis | None:
    """Explain a failed run, or return ``None`` if nothing explains it.

    ``None`` is a real answer and is preferred to a guess: the run experience
    shows the raw log when there is no diagnosis, which is honest, whereas an
    invented cause is not.
    """
    lines = log.splitlines()
    time = ""
    residuals: dict[str, list[float]] = {}
    courant_peak = 0.0
    courant_time = ""
    fatal_io: tuple[str, str] | None = None
    fatal: tuple[str, str] | None = None
    trapped = False

    for index, line in enumerate(lines):
        if (match := _TIME.match(line)) is not None:
            time = match.group(1)
            continue

        if (match := _RESIDUAL.search(line)) is not None:
            name, raw = match.group(1), match.group(2)
            value = _as_float(raw)
            if value is None:
                continue
            if not math.isfinite(value):
                # Checked here, before any fatal-error text, because the fatal
                # error a diverged run ends with is caused by this nan.
                return Diagnosis(
                    signal=Signal.NON_FINITE_RESIDUAL,
                    code=ErrorCode.DIVERGED,
                    field_name=name,
                    time=time,
                    message=(
                        f"Solution diverged: the residual for {name} became "
                        f"{raw.rstrip(',')}" + (f" at t = {time}" if time else "") + "."
                    ),
                    detail=line.strip(),
                )
            residuals.setdefault(name, []).append(value)
            continue

        if (match := _COURANT.search(line)) is not None:
            value = _as_float(match.group(2))
            if value is not None and math.isfinite(value) and value > courant_peak:
                courant_peak, courant_time = value, time
            elif value is not None and not math.isfinite(value):
                return Diagnosis(
                    signal=Signal.NON_FINITE_RESIDUAL,
                    code=ErrorCode.DIVERGED,
                    time=time,
                    message=(
                        "Solution diverged: the Courant number became "
                        f"{match.group(2)}" + (f" at t = {time}" if time else "") + "."
                    ),
                    detail=line.strip(),
                )
            continue

        if "[stack trace]" in line or "sigFpe" in line:
            trapped = True
            continue

        if "FOAM FATAL IO ERROR" in line and fatal_io is None:
            fatal_io = (time, _following(lines, index))
            continue

        if "FOAM FATAL ERROR" in line and fatal is None:
            fatal = (time, _following(lines, index))
            continue

        lowered = line.lower()
        if "std::bad_alloc" in line or "out of memory" in lowered or "oom-killed" in lowered:
            return Diagnosis(
                signal=Signal.OUT_OF_MEMORY,
                code=ErrorCode.OUT_OF_MEMORY,
                time=time,
                message="The run ran out of memory" + (f" at t = {time}" if time else "") + ".",
                detail=line.strip(),
            )
        if "no space left on device" in lowered:
            return Diagnosis(
                signal=Signal.DISK_FULL,
                code=ErrorCode.DISK_FULL,
                time=time,
                message="The disk filled up during the run"
                + (f" at t = {time}" if time else "")
                + ".",
                detail=line.strip(),
            )

    if trapped:
        return Diagnosis(
            signal=Signal.FLOATING_POINT_TRAP,
            code=ErrorCode.DIVERGED,
            time=time,
            message=(
                "Solution diverged: the solver hit a floating-point exception"
                + (f" at t = {time}" if time else "")
                + ". This is what a blow-up looks like when the run is stopped "
                "at the moment a number stops being finite."
            ),
            detail=(
                "The stack trace in the log is the solver's own, and names C++ "
                "internals rather than anything in the case."
            ),
        )

    if courant_peak > COURANT_LIMIT:
        return Diagnosis(
            signal=Signal.COURANT_EXCEEDED,
            code=ErrorCode.DIVERGED,
            time=courant_time,
            confidence=Confidence.LIKELY,
            message=(
                f"Solution diverging: Courant number reached {courant_peak:.3g}"
                + (f" at t = {courant_time}" if courant_time else "")
                + f", far above the {COURANT_LIMIT:.0f} this check allows."
            ),
            detail=(
                "A Courant number this high means the flow crosses several cells "
                "in one timestep. Reduce deltaT, or switch on adjustTimeStep with "
                "a maxCo the scheme can support."
            ),
        )

    if (growth := _growing(residuals)) is not None:
        name, first, last = growth
        return Diagnosis(
            signal=Signal.RESIDUAL_GROWTH,
            code=ErrorCode.DIVERGED,
            field_name=name,
            time=time,
            confidence=Confidence.LIKELY,
            message=(
                f"Solution diverging: the residual for {name} grew from "
                f"{first:.3g} to {last:.3g} and is still rising."
            ),
            detail=(
                "A converging run's residuals fall. Sustained growth usually "
                "means the timestep, the relaxation factors or the mesh quality "
                "is beyond what the scheme tolerates."
            ),
        )

    if fatal_io is not None:
        when, text = fatal_io
        return Diagnosis(
            signal=Signal.FATAL_IO_ERROR,
            code=ErrorCode.SOLVER_SETUP_ERROR,
            time=when,
            message="The solver could not read the case: " + text,
            detail="Reported by OpenFOAM before the run could proceed.",
        )

    if fatal is not None:
        when, text = fatal
        return Diagnosis(
            signal=Signal.FATAL_ERROR,
            code=ErrorCode.SOLVER_SETUP_ERROR,
            time=when,
            message="The solver stopped with an error: " + text,
            detail="Reported by OpenFOAM.",
        )

    if exit_code is not None and exit_code > 128:
        return Diagnosis(
            signal=Signal.KILLED_BY_SIGNAL,
            code=ErrorCode.DIVERGED,
            time=time,
            confidence=Confidence.LIKELY,
            message=(
                f"The solver was killed by signal {exit_code - 128}"
                + (f" at t = {time}" if time else "")
                + ", without reporting a reason."
            ),
            detail=(
                "A solver that dies without a message has usually hit an "
                "arithmetic fault, which almost always means the solution "
                "diverged."
            ),
        )

    return None


def _following(lines: list[str], index: int) -> str:
    """The first meaningful line after a fatal-error banner.

    OpenFOAM prints the banner, then the message, then the C++ location. The
    message is the only part worth showing; the location names a source file in
    OpenFOAM itself, which cannot help a user fix their case.
    """
    for line in lines[index + 1 : index + 6]:
        text = line.strip()
        if text and not text.startswith("--"):
            return text.rstrip(".") + "."
    return "no further detail in the log."


def _growing(residuals: dict[str, list[float]]) -> tuple[str, float, float] | None:
    """Find a field whose residual climbed steadily by orders of magnitude."""
    for name, series in residuals.items():
        if len(series) < _GROWTH_RUN + 1:
            continue
        tail = series[-(_GROWTH_RUN + 1) :]
        rising = all(b > a for a, b in pairwise(tail))
        if rising and tail[-1] > tail[0] * _GROWTH_FACTOR:
            return name, tail[0], tail[-1]
    return None


@dataclass
class DivergenceWatcher:
    """Live divergence detection while the run is still going (FR-S6).

    Separate from :func:`diagnose` because the two answer different questions.
    :func:`diagnose` explains a corpse; this watches a patient. Catching a
    blow-up at t = 2 of a twelve-hour run is worth far more than explaining it
    afterwards, and it is the only one of the two that can save machine time.

    It reports **once**. A diverging run produces thousands of nan lines, and a
    banner that reappears every line would be noise rather than a warning.
    """

    courant_limit: float = COURANT_LIMIT
    _time: str = ""
    _reported: bool = False
    _series: dict[str, list[float]] = field(default_factory=dict)

    @property
    def reported(self) -> bool:
        return self._reported

    def feed(self, line: str) -> Diagnosis | None:
        """Consume one log line, returning a diagnosis the first time one fits."""
        if self._reported:
            return None
        if (match := _TIME.match(line)) is not None:
            self._time = match.group(1)
            return None

        found = self._check(line)
        if found is not None:
            self._reported = True
        return found

    def _check(self, line: str) -> Diagnosis | None:
        if (match := _RESIDUAL.search(line)) is not None:
            name, raw = match.group(1), match.group(2)
            value = _as_float(raw)
            if value is None:
                return None
            if not math.isfinite(value):
                return Diagnosis(
                    signal=Signal.NON_FINITE_RESIDUAL,
                    code=ErrorCode.DIVERGED,
                    field_name=name,
                    time=self._time,
                    message=(
                        f"Solution diverged: the residual for {name} became "
                        f"{raw.rstrip(',')}" + (f" at t = {self._time}" if self._time else "") + "."
                    ),
                    detail=line.strip(),
                )
            series = self._series.setdefault(name, [])
            series.append(value)
            del series[: -(_GROWTH_RUN + 1)]
            if grown := _growing({name: series}):
                _, first, last = grown
                return Diagnosis(
                    signal=Signal.RESIDUAL_GROWTH,
                    code=ErrorCode.DIVERGED,
                    field_name=name,
                    time=self._time,
                    confidence=Confidence.LIKELY,
                    message=(
                        f"Solution diverging: the residual for {name} grew from "
                        f"{first:.3g} to {last:.3g} and is still rising."
                    ),
                    detail="Stop the run and reduce the timestep or relaxation.",
                )
            return None

        if (match := _COURANT.search(line)) is not None:
            value = _as_float(match.group(2))
            if value is None:
                return None
            if not math.isfinite(value) or value > self.courant_limit:
                return Diagnosis(
                    signal=Signal.COURANT_EXCEEDED,
                    code=ErrorCode.DIVERGED,
                    time=self._time,
                    confidence=(
                        Confidence.CERTAIN if not math.isfinite(value) else Confidence.LIKELY
                    ),
                    message=(
                        f"Solution diverging: Courant number reached {match.group(2)}"
                        + (f" at t = {self._time}" if self._time else "")
                        + "."
                    ),
                    detail="Reduce deltaT, or enable adjustTimeStep with a maxCo.",
                )
        return None
