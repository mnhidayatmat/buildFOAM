"""Planning a WSL provision, including the reboot (FR-R3, §7.3 step 5, DEC-12).

FR-R3 is two promises at once — **at most one elevation prompt**, and **survive
the reboot it may require** — and they pull in opposite directions. Enabling the
Windows features needs administrator rights; importing the distribution and
running ``apt`` do not. The naive ordering asks for elevation, reboots, and then
asks again for something that never needed it.

So the plan is ordered by *privilege*, not by convenience: every elevated
operation is batched into a single call, it happens first, and everything after
the reboot runs as the ordinary user. ``authorisation_prompts`` counts it, so the
promise is asserted by a test rather than believed.

**apt runs as root inside the distribution, which is not a Windows elevation.**
``wsl -u root apt-get install`` raises no UAC prompt — the root there is the
distro's, and the distro belongs to the user who imported it. Conflating the two
is the easy way to end up with a second prompt nobody needed.

The reboot is the part that cannot be papered over. Windows will not let a
newly enabled optional feature be used before a restart, so the wizard has to
stop, persist what it has done, and pick up afterwards. That state is
:mod:`foamwb.services.runtime.resume`; this module decides *where* the seam
falls, and marks the step after which it is unavoidable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from foamwb.branding import WSL_DISTRO_NAME
from foamwb.codes import Code, ErrorCode
from foamwb.services.runtime.provision import (
    ProvisionAction,
    ProvisionPlan,
    ProvisionStep,
    Strategy,
)

__all__ = [
    "WslAction",
    "WslPreconditions",
    "wsl_plan",
]


class WslAction(StrEnum):
    """The WSL-side actions, additional to :class:`ProvisionAction`.

    A separate enumeration because these are Windows-only and the macOS plan
    must never be able to name one. Values are distinct from the existing
    actions, so a single plan can carry both without collision.
    """

    ENABLE_FEATURES = "enable_wsl_features"
    """``wsl --install --no-distribution``: the VM platform and WSL itself.

    The **only** elevated step, and the only one that can require a reboot."""

    IMPORT_DISTRO = "import_distro"
    """``wsl --import`` of a Canonical rootfs into a dedicated distribution.

    DEC-12: a distribution of our own rather than the user's existing Ubuntu.
    Installing OpenFOAM into someone's working environment is a change they did
    not ask for and cannot easily undo."""

    APT_INSTALL = "apt_install"
    """OpenFOAM from the ESI apt repository, as root *inside* the distro."""

    VERIFY = "verify"


@dataclass(frozen=True, slots=True)
class WslPreconditions:
    """What the system check (§7.3 step 2) found.

    Every field is something that changes the plan rather than merely decorating
    it, and each maps to a §9 code so a blocked plan can explain itself.
    """

    wsl_present: bool = False
    """WSL itself is installed. Distinct from a distribution existing."""

    features_enabled: bool = False
    """The optional Windows features are on, so no reboot will be needed."""

    distro_present: bool = False
    openfoam_present: bool = False
    virtualization_enabled: bool = True
    has_admin: bool = True
    free_disk_bytes: int = 60 * 1024**3
    network_reachable: bool = True

    def blocking_code(self, needed_bytes: int) -> Code | None:
        """The first condition that stops a provision, in the order it matters.

        Virtualization first: it is a firmware setting, needs a reboot of its
        own, and no amount of disk or network makes up for it. Telling a user to
        free disk space and only then that their BIOS setting is wrong would
        waste the trip.
        """
        if not self.virtualization_enabled:
            return ErrorCode.VIRTUALIZATION_DISABLED
        if not self.has_admin:
            return ErrorCode.NO_ADMIN_RIGHTS
        if self.free_disk_bytes < needed_bytes:
            return ErrorCode.INSUFFICIENT_DISK
        if not self.network_reachable:
            return ErrorCode.DOWNLOAD_BLOCKED
        return None


#: Sizes are indicative and come from the manifest where it has them. They exist
#: so §7.3 step 4 can say what will be downloaded *before* anything is, which is
#: the screen that makes the install reviewable rather than a leap of faith.
_ROOTFS_BYTES = 650 * 1024**2
_ROOTFS_ON_DISK = 1_600 * 1024**2
_OPENFOAM_BYTES = 1_400 * 1024**2
_OPENFOAM_ON_DISK = 4_500 * 1024**2


def wsl_plan(
    version: str,
    preconditions: WslPreconditions | None = None,
    *,
    distro: str = WSL_DISTRO_NAME,
) -> ProvisionPlan:
    """Build the reviewable plan for provisioning OpenFOAM under WSL.

    Steps already satisfied are omitted rather than included-and-skipped: §7.3
    step 4 is a promise about what *will happen*, and a list containing work that
    will not be done is a worse promise than a shorter list.
    """
    found = preconditions or WslPreconditions()

    if found.openfoam_present:
        return ProvisionPlan(
            strategy=Strategy.ADOPT,
            version=version,
            steps=(ProvisionStep(action=ProvisionAction.ADOPT, target=distro),),
        )

    steps: list[ProvisionStep] = []

    if not found.wsl_present or not found.features_enabled:
        # The single elevated call. Batched deliberately: enabling the VM
        # platform and WSL separately is two prompts for one decision.
        steps.append(
            ProvisionStep(
                action=WslAction.ENABLE_FEATURES,
                target="wsl",
                needs_authorisation=True,
            )
        )

    if not found.distro_present:
        steps.append(
            ProvisionStep(
                action=WslAction.IMPORT_DISTRO,
                target=distro,
                download_bytes=_ROOTFS_BYTES,
                disk_bytes=_ROOTFS_ON_DISK,
            )
        )

    steps.append(
        ProvisionStep(
            action=WslAction.APT_INSTALL,
            target=version,
            download_bytes=_OPENFOAM_BYTES,
            disk_bytes=_OPENFOAM_ON_DISK,
        )
    )
    steps.append(ProvisionStep(action=WslAction.VERIFY, target=version))

    needed = sum(step.disk_bytes for step in steps)
    blocked = found.blocking_code(needed)

    return ProvisionPlan(
        strategy=Strategy.WSL,
        version=version,
        steps=tuple(steps),
        blocked_by=blocked,
    )


def reboot_falls_after(plan: ProvisionPlan) -> str | None:
    """Which step the user will be interrupted after, or ``None`` if none.

    Answered from the plan rather than discovered at run time, so §7.3 step 5 can
    warn *before* starting: "this will restart your computer once" is a fact a
    user needs while deciding, not while it is happening.
    """
    for step in plan.steps:
        if step.action == WslAction.ENABLE_FEATURES:
            return str(step.action)
    return None


def remaining_after(plan: ProvisionPlan, completed: tuple[str, ...]) -> ProvisionPlan:
    """The same plan with finished steps removed, for resuming after a reboot.

    Returns a *plan*, not a step list, so the resumed half is reviewable on
    exactly the same screen as the original — and so its remaining download size
    is right rather than restating the whole job.
    """
    done = set(completed)
    return replace(
        plan,
        steps=tuple(step for step in plan.steps if str(step.action) not in done),
    )
