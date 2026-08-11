"""The turbulence model advisor (FR-VVT1, FR-VVT2, FR-VVT3, FR-VVT4).

§6.9.1: "Model choice is the single highest-leverage decision a novice makes and
the one they most often get wrong — usually by pairing a low-Reynolds model with
a wall-function mesh, or vice versa."

Three properties are requirements, not style.

**Never a single silent answer** (FR-VVT2). The result is a *ranked shortlist*,
each entry carrying what the model is good at, where it is known to fail, and its
relative cost. A tool that named one model would be teaching students that
turbulence modelling is a lookup, which is the opposite of what §14.6 wants the
exercise to teach.

**Model availability comes from data** (FR-VVT3), so a model absent from the
installed release is unselectable rather than merely warned about — and adding a
release is a data change.

**The model, the wall treatment and the mesh cannot disagree** (FR-VVT4).
:func:`wall_treatments_for` is the coupling: a model that can only be integrated
to the wall offers only the resolved treatment, and the boundary conditions that
follow are the ones that treatment defines. The advisor never produces a pairing
the case cannot run.

Scoring is transparent on purpose. Each answer contributes a stated reason to a
model's score, and those reasons are what the shortlist displays — so a
recommendation can be argued with, which is the only kind worth giving.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache
from importlib import resources

__all__ = [
    "Answers",
    "Catalogue",
    "Model",
    "Recommendation",
    "WallTreatment",
    "load_catalogue",
    "recommend",
    "wall_treatments_for",
]


class Compute(StrEnum):
    """How much the user can afford. FR-VVT1's "available compute"."""

    LAPTOP = "laptop"
    WORKSTATION = "workstation"
    CLUSTER = "cluster"


#: What each budget will tolerate, on the catalogue's 1-4 cost scale.
_AFFORDABLE = {Compute.LAPTOP: 1, Compute.WORKSTATION: 3, Compute.CLUSTER: 4}


@dataclass(frozen=True, slots=True)
class Answers:
    """FR-VVT1's questionnaire.

    Every field defaults to the commonest case, so a user who answers only the
    questions they are sure about still gets a defensible shortlist rather than
    an interrogation. Being unsure is not the same as saying no.
    """

    external: bool = False
    """External aerodynamics rather than an internal, confined flow."""

    separation: bool = False
    adverse_pressure_gradient: bool = False
    swirl: bool = False
    transition: bool = False
    """Laminar-turbulent transition matters to the answer."""

    buoyancy: bool = False
    unsteady: bool = False
    scale_resolving: bool = False
    """The user wants the turbulent structures resolved, not modelled.

    Distinct from :attr:`unsteady`, and the questionnaire is unusable without the
    distinction: an unsteady RANS run and an LES are both "unsteady", but they
    are different decisions with a hundredfold cost difference. Asking only about
    time-dependence would rank LES against URANS as if they were alternatives at
    the same price.
    """

    compressible: bool = False
    resolve_near_wall: bool = False
    """The user intends to mesh into the viscous sublayer (y+ ≈ 1)."""

    compute: Compute = Compute.WORKSTATION


@dataclass(frozen=True, slots=True)
class WallTreatment:
    """A near-wall treatment and the boundary conditions it implies."""

    key: str
    label: str
    description: str
    target_y_plus: tuple[float, float]
    conditions: dict[str, str]

    def condition_for(self, field_name: str) -> str | None:
        """The wall boundary condition this treatment wants for a field."""
        return self.conditions.get(field_name)

    def covers(self, y_plus: float) -> bool:
        low, high = self.target_y_plus
        return low <= y_plus <= high


@dataclass(frozen=True, slots=True)
class Model:
    """One turbulence model, with what the advisor must be able to say about it."""

    name: str
    family: str
    fields: tuple[str, ...]
    cost: int
    wall: tuple[str, ...]
    good_at: str
    fails_at: str
    block: str = "RAS"
    """Which dictionary block declares this model.

    Not the same as :attr:`family`: a hybrid RANS-LES model is declared under
    ``simulationType LES`` with ``LESModel``, so writing it into a RAS block
    would produce a case that does not run.
    """

    model_key: str = "RASModel"
    baseline: float = 0.0
    """How broadly applicable this model is when nothing distinguishes the
    candidates. Small, so any real answer outweighs it — its job is to stop the
    leader being chosen by alphabet."""

    since: str | None = None

    def available_in(self, version: str, ordered: tuple[str, ...]) -> bool:
        """Whether an installed release ships this model.

        Compared against the manifest's ordering rather than by parsing the
        version string, so the rule lives with the release list rather than in a
        comparison this module would have to keep correct.
        """
        if self.since is None:
            return True
        if self.since not in ordered or version not in ordered:
            return True
        return ordered.index(version) <= ordered.index(self.since)


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One entry in the shortlist (FR-VVT2)."""

    model: Model
    score: float
    reasons: tuple[str, ...]
    """Why this model rose or fell. Displayed, so the ranking can be argued with
    rather than merely accepted."""

    caveats: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.model.name


@dataclass(frozen=True, slots=True)
class Catalogue:
    """The model list and the wall treatments, loaded from data."""

    models: tuple[Model, ...]
    wall_treatments: dict[str, WallTreatment]
    families: dict[str, str] = field(default_factory=dict)

    def model(self, name: str) -> Model | None:
        return next((m for m in self.models if m.name == name), None)

    def treatment(self, key: str) -> WallTreatment | None:
        return self.wall_treatments.get(key)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.models)


@cache
def load_catalogue() -> Catalogue:
    """Read the bundled model catalogue (FR-VVT3)."""
    raw = json.loads(
        resources.files("foamwb.data").joinpath("turbulence.json").read_text(encoding="utf-8")
    )
    treatments = {
        key: WallTreatment(
            key=key,
            label=spec["label"],
            description=spec["description"],
            target_y_plus=tuple(spec["target_y_plus"]),
            conditions=dict(spec["conditions"]),
        )
        for key, spec in raw["wall_treatments"].items()
    }
    models = tuple(
        Model(
            name=entry["name"],
            family=entry["family"],
            fields=tuple(entry["fields"]),
            cost=int(entry["cost"]),
            wall=tuple(entry["wall"]),
            good_at=entry["good_at"],
            fails_at=entry["fails_at"],
            block=entry.get("block", "RAS"),
            model_key=entry.get("model_key", "RASModel"),
            baseline=float(entry.get("baseline", 0.0)),
            since=entry.get("since"),
        )
        for entry in raw["models"]
    )
    return Catalogue(models=models, wall_treatments=treatments, families=raw["families"])


def wall_treatments_for(model: Model, catalogue: Catalogue) -> list[WallTreatment]:
    """The treatments this model may be used with (FR-VVT4).

    The coupling that makes an inconsistent pairing unreachable rather than
    merely warned about: a low-Reynolds model offers only the resolved treatment,
    so "no combination of model and wall treatment can be saved that produces
    inconsistent BCs" holds by construction.
    """
    return [treatment for key in model.wall if (treatment := catalogue.treatment(key)) is not None]


#: Scored contributions. Each is (predicate on the answers, model names it
#: favours or penalises, weight, reason). Kept as data so the ranking is
#: inspectable and every reason shown to the user comes from the same place the
#: score does — a score and an explanation that could disagree would be worse
#: than either alone.
_RULES: tuple[tuple[str, tuple[str, ...], float, str], ...] = (
    (
        "adverse_pressure_gradient",
        ("kOmegaSST", "kOmega", "SpalartAllmarasDDES", "kOmegaSSTDES"),
        3.0,
        "handles adverse pressure gradients, which is where k-epsilon models fail",
    ),
    (
        "adverse_pressure_gradient",
        ("kEpsilon", "realizableKE", "RNGkEpsilon"),
        -3.0,
        "epsilon-based models systematically delay separation under an adverse "
        "pressure gradient (FR-VVT8)",
    ),
    (
        "separation",
        ("kOmegaSST", "SpalartAllmarasDDES", "kOmegaSSTDES", "SpalartAllmarasIDDES"),
        3.0,
        "predicts separation onset far better than an epsilon-based model",
    ),
    ("separation", ("kEpsilon",), -3.0, "known to miss or delay separation"),
    (
        "swirl",
        ("RNGkEpsilon", "realizableKE", "LRR", "SSG"),
        2.0,
        "accounts for streamline curvature and swirl",
    ),
    (
        "transition",
        ("kOmegaSSTLM",),
        4.0,
        "the only model here that predicts laminar-turbulent transition",
    ),
    (
        "transition",
        ("kEpsilon", "realizableKE", "SpalartAllmaras"),
        -2.0,
        "assumes fully turbulent flow, so transition is not represented",
    ),
    (
        "external",
        ("kOmegaSST", "SpalartAllmaras", "SpalartAllmarasDDES"),
        2.0,
        "a standard choice for external aerodynamics",
    ),
    (
        "external",
        ("kOmega",),
        -2.0,
        "sensitive to the free-stream omega value, which makes external flows unreliable",
    ),
    (
        "buoyancy",
        ("kEpsilon", "realizableKE", "kOmegaSST"),
        1.0,
        "widely used with buoyancy-driven flows",
    ),
    (
        "unsteady",
        ("kOmegaSST", "kOmega", "kEpsilon"),
        0.5,
        "commonly used for unsteady RANS",
    ),
    (
        "resolve_near_wall",
        ("kOmegaSST", "kOmega", "LaunderSharmaKE", "v2f", "kOmegaSSTLM"),
        2.0,
        "can be integrated to the wall on a resolved mesh",
    ),
)


def recommend(
    answers: Answers,
    *,
    catalogue: Catalogue | None = None,
    version: str | None = None,
    supported_versions: tuple[str, ...] = (),
    limit: int = 5,
) -> list[Recommendation]:
    """Rank the models for a set of answers (FR-VVT1, FR-VVT2).

    Always returns at least two candidates where two are available, because
    FR-VVT2 requires a shortlist with trade-offs on every path: a list of one is
    a silent answer wearing a list's clothes.
    """
    catalogue = catalogue or load_catalogue()
    # Coerced, because Compute is a StrEnum and a caller that round-tripped it
    # through Qt or JSON holds the string form. Rejecting that would be pedantry
    # about a value that is already unambiguous.
    compute = Compute(answers.compute)
    affordable = _AFFORDABLE[compute]

    scored: list[Recommendation] = []
    for model in catalogue.models:
        if version and not model.available_in(version, supported_versions):
            continue

        score = model.baseline
        reasons: list[str] = []
        caveats: list[str] = []
        if model.baseline > 0:
            reasons.append(
                "a broadly applicable default for this kind of flow, so it leads "
                "when nothing more specific separates the candidates"
            )

        for attribute, names, weight, reason in _RULES:
            if not getattr(answers, attribute) or model.name not in names:
                continue
            score += weight
            (reasons if weight > 0 else caveats).append(reason)

        # Cost is a real constraint, not a tiebreak: an LES on a laptop is not a
        # slower answer, it is one the user will never see finish.
        if model.cost > affordable:
            score -= 4.0
            caveats.append(f"needs more compute than a {compute.value} provides")
        else:
            score += (affordable - model.cost) * 0.5

        # Steady runs cannot use an inherently unsteady model at all.
        if not answers.unsteady and model.family in {"LES", "hybrid"}:
            score -= 5.0
            caveats.append("inherently unsteady; not usable for a steady run")
        elif answers.scale_resolving and model.family in {"LES", "hybrid"}:
            # Asked for explicitly, so the models that answer it should lead.
            score += 4.0
            reasons.append("resolves turbulent structures rather than modelling them")
        elif answers.scale_resolving and model.family == "RAS":
            score -= 3.0
            caveats.append(
                "models all of the turbulence, so it cannot resolve the "
                "structures this run is asking for"
            )

        if answers.resolve_near_wall and "resolved" not in model.wall:
            score -= 5.0
            caveats.append(
                "cannot be integrated to the wall, so it contradicts a resolved "
                "near-wall mesh (FR-VVT4)"
            )
        if not answers.resolve_near_wall and "wall_functions" not in model.wall:
            score -= 5.0
            caveats.append(
                "requires a resolved near-wall mesh; it cannot be used with wall "
                "functions (FR-VVT8)"
            )

        scored.append(
            Recommendation(
                model=model,
                score=score,
                reasons=tuple(reasons),
                caveats=tuple(caveats),
            )
        )

    # Name breaks ties, so the same answers always give the same order — a
    # shortlist that reshuffled between runs would be impossible to discuss.
    scored.sort(key=lambda r: (-r.score, r.model.name))
    return scored[:limit]


def rank_all(
    answers: Answers,
    *,
    catalogue: Catalogue | None = None,
    version: str | None = None,
    supported_versions: tuple[str, ...] = (),
) -> list[Recommendation]:
    """Every available model, ranked. The shortlist is the head of this."""
    catalogue = catalogue or load_catalogue()
    return recommend(
        answers,
        catalogue=catalogue,
        version=version,
        supported_versions=supported_versions,
        limit=len(catalogue.models),
    )


def explain(
    model_name: str,
    answers: Answers,
    *,
    catalogue: Catalogue | None = None,
) -> Recommendation | None:
    """Why *this* model ranks where it does, whether or not it made the shortlist.

    FR-VVT1 allows the advisor to recommend something other than the model a case
    already uses, provided it "explains why an alternative is defensible". A
    model that simply vanished from a truncated list explains nothing: the user
    is left unable to tell whether it was rejected or merely crowded out. This is
    how the case's current model is always accounted for.
    """
    for entry in rank_all(answers, catalogue=catalogue):
        if entry.name == model_name:
            return entry
    return None


def rank_of(model_name: str, answers: Answers, **kwargs: object) -> int | None:
    """Where a model places overall, 1-based."""
    ranked = rank_all(answers, **kwargs)  # type: ignore[arg-type]
    for position, entry in enumerate(ranked, start=1):
        if entry.name == model_name:
            return position
    return None
