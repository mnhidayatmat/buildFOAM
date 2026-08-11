"""Turbulence estimates: first-cell height and inlet values (FR-VVT5, FR-VVT6).

Both are correlations, and the module says so at every turn. §6.9's whole
argument is that a confident wrong number is worse than no number, so each result
carries the formula it came from and the accuracy actually claimed for it.

**FR-VVT5 claims a factor of two, and the test asserts the claim rather than
perfection.** A flat-plate skin-friction correlation applied to a real geometry
is an estimate: the boundary layer on a curved, pressure-gradient-bearing surface
is not a flat plate's. Getting a user into the right band before they mesh is the
point, and the y+ audit after the run (FR-VVT7) is what tells them where they
actually landed.

The correlations are the standard ones, named so a reader can check them rather
than trust this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "C_MU",
    "FirstCellHeight",
    "InletTurbulence",
    "first_cell_height",
    "inlet_turbulence",
    "length_scale_from_hydraulic_diameter",
]

#: The k-epsilon model constant, and the one these correlations use.
C_MU = 0.09

#: von Karman constant, used by the log-law inverse.
KAPPA = 0.41


@dataclass(frozen=True, slots=True)
class FirstCellHeight:
    """A first-cell-height estimate and everything it was derived from."""

    height: float
    """Full cell height, not the centre distance.

    The distinction matters and is a common source of a factor-of-two error:
    ``y+`` is defined at the first cell *centre*, so a mesh built to put its
    first *node* at the computed distance ends up with half the intended y+.
    """

    centre_distance: float
    reynolds: float
    skin_friction: float
    wall_shear_stress: float
    friction_velocity: float
    target_y_plus: float
    correlation: str
    accuracy_note: str

    @property
    def formula(self) -> str:
        """The chain, for the UI's "show its formula on hover" (§7.7)."""
        return (
            "Re = U·L/ν   →   "
            f"Cf = {self.correlation}   →   "
            "τw = ½·ρ·U²·Cf   →   "
            "uτ = √(τw/ρ)   →   "
            "y = y⁺·ν/uτ   →   height = 2y"
        )


def first_cell_height(
    *,
    velocity: float,
    length: float,
    kinematic_viscosity: float,
    target_y_plus: float = 30.0,
    density: float = 1.0,
) -> FirstCellHeight:
    """Estimate the first cell height for a target y+ (FR-VVT5).

    Uses the Schlichting flat-plate correlation ``Cf = 0.0576·Re^(-1/5)``, valid
    for a turbulent boundary layer over roughly 5×10⁵ < Re < 10⁷. It is stated
    rather than hidden because a user checking the number needs to know which
    correlation produced it — and because outside that range the estimate is
    weaker than the factor of two claimed inside it.

    ``density`` defaults to 1 because an incompressible OpenFOAM case works in
    kinematic terms throughout; the shear stress then comes out per unit density,
    which cancels in the friction velocity.
    """
    for name, value in (
        ("velocity", velocity),
        ("length", length),
        ("kinematic_viscosity", kinematic_viscosity),
        ("target_y_plus", target_y_plus),
        ("density", density),
    ):
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero, got {value}")

    reynolds = velocity * length / kinematic_viscosity
    skin_friction = 0.0576 * reynolds ** (-0.2)
    wall_shear_stress = 0.5 * density * velocity**2 * skin_friction
    friction_velocity = math.sqrt(wall_shear_stress / density)
    centre_distance = target_y_plus * kinematic_viscosity / friction_velocity

    if reynolds < 5e5:
        note = (
            "Re is below 5×10⁵, where the flat-plate turbulent correlation does "
            "not apply. Treat this as an order of magnitude, not an estimate."
        )
    elif reynolds > 1e7:
        note = (
            "Re is above 10⁷, beyond the correlation's usual range. Expect worse "
            "than the usual factor of two."
        )
    else:
        note = (
            "Expect the achieved y⁺ to be within a factor of two of the target. "
            "The audit after the run reports where it actually landed."
        )

    return FirstCellHeight(
        height=2.0 * centre_distance,
        centre_distance=centre_distance,
        reynolds=reynolds,
        skin_friction=skin_friction,
        wall_shear_stress=wall_shear_stress,
        friction_velocity=friction_velocity,
        target_y_plus=target_y_plus,
        correlation="0.0576·Re^(-1/5)  (Schlichting, flat plate)",
        accuracy_note=note,
    )


def boundary_layer_cells(
    *,
    first_height: float,
    total_thickness: float,
    growth_ratio: float = 1.2,
) -> int:
    """How many layers it takes to cross a boundary layer at a growth ratio.

    §7.7 shows this beside the height, because the height alone does not tell a
    user what it will cost: a first cell of 10⁻⁶ m under a 10 mm layer is thirty
    cells of inflation, and that is the number that decides whether the mesh is
    affordable.
    """
    if first_height <= 0 or total_thickness <= 0:
        raise ValueError("heights must be greater than zero")
    if growth_ratio <= 1:
        raise ValueError("growth ratio must be greater than 1")

    covered, count = 0.0, 0
    height = first_height
    while covered < total_thickness and count < 1000:
        covered += height
        height *= growth_ratio
        count += 1
    return count


def length_scale_from_hydraulic_diameter(diameter: float) -> float:
    """Turbulent length scale for fully developed internal flow.

    ``l = 0.07·D_h``, the standard estimate: 0.07 approximates the ratio of the
    mixing length to the pipe radius away from the wall.
    """
    if diameter <= 0:
        raise ValueError("hydraulic diameter must be greater than zero")
    return 0.07 * diameter


@dataclass(frozen=True, slots=True)
class InletTurbulence:
    """Inlet values for whichever fields the chosen model transports."""

    k: float
    epsilon: float
    omega: float
    nu_tilda: float
    intensity: float
    length_scale: float
    formulas: dict[str, str]

    def for_fields(self, fields: tuple[str, ...]) -> dict[str, float]:
        """Only the values the model actually needs.

        A k-omega case has no ``epsilon`` to set, and offering one would invite
        writing a field the solver will not read.
        """
        available = {
            "k": self.k,
            "epsilon": self.epsilon,
            "omega": self.omega,
            "nuTilda": self.nu_tilda,
        }
        return {name: available[name] for name in fields if name in available}


def inlet_turbulence(
    *,
    velocity: float,
    intensity: float,
    length_scale: float,
    kinematic_viscosity: float | None = None,
) -> InletTurbulence:
    """Derive inlet k, ε, ω and ν̃ from intensity and length scale (FR-VVT6).

    ``intensity`` is a fraction, not a percentage: 0.05 for 5%. Taking a
    percentage here would silently produce values four hundred times too large,
    and the resulting run would look plausible while being wrong.

    Every formula is returned alongside its value, because §6.9 requires a number
    to travel with what produced it.
    """
    if velocity <= 0 or length_scale <= 0:
        raise ValueError("velocity and length scale must be greater than zero")
    if not 0 < intensity < 1:
        raise ValueError(f"intensity is a fraction between 0 and 1, got {intensity}. 5% is 0.05.")

    k = 1.5 * (velocity * intensity) ** 2
    epsilon = C_MU**0.75 * k**1.5 / length_scale
    omega = k**0.5 / (C_MU**0.25 * length_scale)
    # The usual engineering estimate; ν̃ has no exact relation to k and l, and
    # this is stated as an approximation rather than presented as derived.
    nu_tilda = math.sqrt(1.5) * velocity * intensity * length_scale

    return InletTurbulence(
        k=k,
        epsilon=epsilon,
        omega=omega,
        nu_tilda=nu_tilda,
        intensity=intensity,
        length_scale=length_scale,
        formulas={
            "k": "k = 1.5·(U·I)²",
            "epsilon": "ε = Cμ^(3/4)·k^(3/2)/l",
            "omega": "ω = k^(1/2)/(Cμ^(1/4)·l)",
            "nuTilda": "ν̃ ≈ √1.5·U·I·l   (approximation)",
        },
    )
