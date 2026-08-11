"""The post-run y+ audit (FR-VVT7, FR-VVT8).

§6.9.1's closing move: after a run, say where the mesh actually landed rather
than where it was aimed. FR-VVT5's first-cell-height estimate claims a factor of
two; this is what turns that claim into a measurement.

**The buffer layer is the finding that matters.** Between y+ 5 and 30 neither the
viscous sublayer nor the log law holds, so neither a wall function nor a resolved
model is doing what it assumes. Nothing in a solver's output says so, and the run
converges perfectly happily — which is precisely why a student can produce and
defend a wrong answer without ever seeing a warning.

This is not hypothetical. OpenFOAM's own ``pitzDaily`` tutorial runs ``kEpsilon``
with wall functions and achieves y+ between 4.4 and 26.3, entirely inside the
buffer layer. The audit is meant to say that out loud.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from foamwb.services.advisor import Model, WallTreatment

__all__ = [
    "BUFFER_LAYER",
    "PatchYPlus",
    "Verdict",
    "YPlusAudit",
    "audit",
    "parse_y_plus",
]

#: Where neither wall functions nor a resolved model is valid. The single most
#: consequential band in this whole module.
BUFFER_LAYER = (5.0, 30.0)


class Verdict(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class PatchYPlus:
    """What one wall patch achieved."""

    patch: str
    minimum: float
    maximum: float
    average: float
    time: str = ""

    @property
    def spans_buffer_layer(self) -> bool:
        low, high = BUFFER_LAYER
        return self.minimum < high and self.maximum > low


@dataclass(frozen=True, slots=True)
class PatchVerdict:
    """A patch's verdict against the treatment the case actually uses."""

    patch: PatchYPlus
    verdict: Verdict
    message: str

    @property
    def name(self) -> str:
        return self.patch.patch


@dataclass(slots=True)
class YPlusAudit:
    """The whole audit, per patch, with the caveat it must travel with."""

    patches: list[PatchVerdict]
    treatment: WallTreatment | None = None
    model: Model | None = None

    @property
    def verdict(self) -> Verdict:
        if any(p.verdict is Verdict.FAIL for p in self.patches):
            return Verdict.FAIL
        if any(p.verdict is Verdict.WARN for p in self.patches):
            return Verdict.WARN
        return Verdict.PASS

    @property
    def offending(self) -> list[str]:
        """Patches that are not passing — FR-VVT7 requires them named."""
        return [p.name for p in self.patches if p.verdict is not Verdict.PASS]

    @property
    def has_data(self) -> bool:
        return bool(self.patches)


_ROW = re.compile(
    r"^\s*(?P<time>\S+)\s+(?P<patch>\S+)\s+"
    r"(?P<min>\S+)\s+(?P<max>\S+)\s+(?P<avg>\S+)\s*$"
)


def parse_y_plus(text: str) -> list[PatchYPlus]:
    """Read the ``yPlus`` function object's output.

    Only the last write is kept. A steady run writes a row per patch per output
    interval, and the audit is about the converged state — averaging over the
    transient would report a mesh the solution never had.
    """
    rows: dict[str, PatchYPlus] = {}
    latest = ""
    for line in text.splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        match = _ROW.match(line)
        if match is None:
            continue
        try:
            entry = PatchYPlus(
                patch=match.group("patch"),
                minimum=float(match.group("min")),
                maximum=float(match.group("max")),
                average=float(match.group("avg")),
                time=match.group("time"),
            )
        except ValueError:
            continue
        if entry.time != latest:
            latest = entry.time
            rows = {}
        rows[entry.patch] = entry
    return list(rows.values())


def read_y_plus(case: Path) -> list[PatchYPlus]:
    """Read the audit data a run produced, or nothing if it produced none."""
    directory = case / "postProcessing" / "yPlus"
    if not directory.is_dir():
        return []
    files = sorted(directory.rglob("*.dat"))
    if not files:
        return []
    return parse_y_plus(files[-1].read_text(encoding="utf-8", errors="replace"))


def audit(
    patches: list[PatchYPlus],
    *,
    treatment: WallTreatment | None = None,
    model: Model | None = None,
) -> YPlusAudit:
    """Judge each patch against the treatment in force (FR-VVT7, FR-VVT8).

    Judged against what the case *uses*, not against an ideal. A resolved mesh is
    not a failure because it is not a wall-function mesh; it is a failure only if
    the model assumes otherwise.
    """
    verdicts = [_judge(patch, treatment, model) for patch in patches]
    return YPlusAudit(patches=verdicts, treatment=treatment, model=model)


def _judge(patch: PatchYPlus, treatment: WallTreatment | None, model: Model | None) -> PatchVerdict:
    low, high = BUFFER_LAYER
    name = model.name if model is not None else "the model"

    if treatment is None:
        return PatchVerdict(
            patch=patch,
            verdict=Verdict.WARN,
            message=(
                f"y+ is {patch.minimum:.3g}–{patch.maximum:.3g} (mean "
                f"{patch.average:.3g}). No wall treatment is recorded for this "
                "case, so there is nothing to judge it against."
            ),
        )

    target_low, target_high = treatment.target_y_plus

    # The buffer layer first: it is the one case where *no* treatment is valid,
    # so it outranks any comparison against a target band.
    if patch.spans_buffer_layer and target_low >= high:
        return PatchVerdict(
            patch=patch,
            verdict=Verdict.FAIL,
            message=(
                f"y+ reaches {patch.minimum:.3g}–{patch.maximum:.3g}, inside the "
                f"buffer layer ({low:.0f}–{high:.0f}), where neither the viscous "
                "sublayer nor the log law holds. Wall functions assume the log "
                "layer, so this patch is outside what they model. Refine to y+ "
                "below 5 or coarsen above 30."
            ),
        )

    if patch.maximum > target_high:
        return PatchVerdict(
            patch=patch,
            verdict=Verdict.FAIL if target_high <= 1 else Verdict.WARN,
            message=(
                f"y+ reaches {patch.maximum:.3g}, above the {target_high:.3g} that "
                f"{treatment.label.lower()} expects"
                + (
                    f". {name} needs the viscous sublayer resolved, so this "
                    "result is not what the model assumes."
                    if target_high <= 1
                    else ". Wall functions become less reliable this far out."
                )
            ),
        )

    if patch.minimum < target_low:
        return PatchVerdict(
            patch=patch,
            verdict=Verdict.WARN,
            message=(
                f"y+ falls to {patch.minimum:.3g}, below the {target_low:.3g} that "
                f"{treatment.label.lower()} expects. The first cell is inside the "
                "viscous sublayer, where the log law the wall function applies "
                "does not hold."
            ),
        )

    return PatchVerdict(
        patch=patch,
        verdict=Verdict.PASS,
        message=(
            f"y+ is {patch.minimum:.3g}–{patch.maximum:.3g} (mean "
            f"{patch.average:.3g}), within the {target_low:.3g}–{target_high:.3g} "
            f"that {treatment.label.lower()} expects."
        ),
    )


def model_mismatches(model: Model, answers_separation: bool, answers_apg: bool) -> list[str]:
    """FR-VVT8's non-y+ mismatch: an epsilon model where it is known to fail.

    Separate from the y+ checks because it is a *modelling* mismatch rather than
    a meshing one, and it is visible before a run rather than after.
    """
    warnings: list[str] = []
    if model.name in {"kEpsilon", "realizableKE", "RNGkEpsilon"} and (
        answers_separation or answers_apg
    ):
        warnings.append(
            f"{model.name} is being used with "
            + ("separation" if answers_separation else "an adverse pressure gradient")
            + ", which epsilon-based models systematically get wrong — they delay "
            "or miss separation onset. kOmegaSST is the usual alternative."
        )
    return warnings
