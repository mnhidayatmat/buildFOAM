"""Provisioning an OpenFOAM runtime on macOS (FR-R3, FR-R4, FR-R10, FR-R11).

The wizard's fifth step, and the part of the product D1 rests on: "one installer
that leaves a working OpenFOAM stack behind, on a machine that had nothing."

Four requirements shape this module.

**Nothing installs before the plan is accepted** (§7.3 step 4). Planning is
therefore separate from execution and produces data: what will be installed,
where, how many bytes downloaded and occupied. :meth:`Provisioner.plan` writes
nothing and can be called freely during the system check.

**Idempotent and resumable** (NFR-R4): "re-running the wizard after any failure
converges to the same state." Every step re-checks its own precondition and
reports itself already satisfied rather than repeating work, so a user who lost
their network halfway through and pressed the button again does not reinstall
Homebrew.

**Homebrew installation is not silent** (§3.3, FR-R11). Its installer wants an
interactive ``sudo``, and a GUI wizard cannot answer a TTY prompt. The order is
fixed: use Homebrew if present and never prompt; otherwise request authorisation
through the **native macOS dialog** so the user sees a system password box rather
than a terminal; and if that is refused or fails, fall back to Docker rather than
dead-ending. FR-R11 is a v1.0 MUST and this ordering is the requirement, not an
implementation preference.

**No user-visible text lives here.** Steps carry a machine-readable action and its
parameters; the wizard renders the sentence from its catalogue (NFR-A5). A
service that owned English strings could not be translated and could not be
reused by a CLI.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from foamwb.codes import Code, ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.runtime.manifest import Manifest

__all__ = [
    "ProvisionAction",
    "ProvisionOutcome",
    "ProvisionPlan",
    "ProvisionResult",
    "ProvisionStep",
    "Provisioner",
    "Strategy",
]

_log = get_logger("runtime.provision")

#: Runs a host command and returns (exit code, merged output). Injected so the
#: whole planner and executor can be tested without installing anything — a test
#: suite that actually ran `brew install` would be untestable in CI and unkind
#: anywhere else.
CommandRunner = Callable[[Sequence[str]], tuple[int, str]]

#: Called before each step with the step about to run, so §7.9 rule 2's "anything
#: that downloads or takes over five seconds shows progress" is satisfiable.
ProgressCallback = Callable[["ProvisionStep"], None]


class Strategy(StrEnum):
    """How a runtime will be obtained."""

    ADOPT = "adopt"
    """Already present and usable — FR-R1's outcome, and the cheapest one."""

    HOMEBREW = "homebrew"
    """The tap, per §3.3's primary path."""

    DOCKER = "docker"
    """FR-R10's fallback: Intel hardware, or Homebrew unavailable or refused."""

    WSL = "wsl"
    """A dedicated WSL2 distribution on Windows (DEC-12, §3.2)."""

    UNAVAILABLE = "unavailable"
    """Nothing can be done without user action — no network, no Docker, no
    Homebrew and no way to install one."""


class ProvisionAction(StrEnum):
    ADOPT = "adopt"
    INSTALL_HOMEBREW = "install_homebrew"
    ADD_TAP = "add_tap"
    INSTALL_CASK = "install_cask"
    PULL_DOCKER_IMAGE = "pull_docker_image"
    VERIFY = "verify"


@dataclass(frozen=True, slots=True)
class ProvisionStep:
    """One reviewable unit of work.

    Carries parameters, never prose: the wizard renders "Install OpenFOAM v2512
    (1.4 GB download)" from the action and the numbers, in the user's language.
    """

    action: ProvisionAction | str
    """Widened to accept :class:`~foamwb.services.runtime.wslprovision.WslAction`
    too. Both are ``StrEnum``, so a step compares and serialises identically
    whichever platform produced it — and a Windows-only action stays out of the
    macOS enumeration, where it could otherwise be planned by mistake."""
    target: str = ""
    download_bytes: int = 0
    disk_bytes: int = 0
    needs_authorisation: bool = False
    """Whether this step raises the macOS authorisation dialog. Surfaced in the
    plan so the prompt is expected rather than alarming, and so FR-R3's "at most
    one elevation prompt" is checkable by counting."""


@dataclass(frozen=True, slots=True)
class ProvisionPlan:
    """Exactly what will happen, before anything happens (§7.3 step 4)."""

    strategy: Strategy
    version: str
    steps: tuple[ProvisionStep, ...] = ()
    blocked_by: Code | None = None
    """Set when the plan cannot proceed — a §9 code the wizard can explain and
    offer a remedy for, rather than an empty step list and no reason."""

    @property
    def download_bytes(self) -> int:
        return sum(step.download_bytes for step in self.steps)

    @property
    def disk_bytes(self) -> int:
        return sum(step.disk_bytes for step in self.steps)

    @property
    def authorisation_prompts(self) -> int:
        """How many times the user will be asked for a password.

        FR-R3 caps this at one. Exposed as a number so the requirement is
        asserted rather than assumed.
        """
        return sum(1 for step in self.steps if step.needs_authorisation)

    @property
    def installs_anything(self) -> bool:
        return any(step.action is not ProvisionAction.ADOPT for step in self.steps)


class ProvisionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(slots=True)
class ProvisionResult:
    outcome: ProvisionOutcome
    completed: list[ProvisionStep] = field(default_factory=list)
    failed_step: ProvisionStep | None = None
    reason: Code | None = None
    detail: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome is ProvisionOutcome.SUCCEEDED


def _run_host_command(argv: Sequence[str]) -> tuple[int, str]:
    """Run a command on the host, outside any OpenFOAM environment.

    Provisioning happens *before* a runtime exists, so it cannot go through
    :class:`RuntimeSession` — there is nothing to source yet.
    """
    completed = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


class Provisioner:
    """Plans and carries out runtime installation."""

    def __init__(
        self,
        manifest: Manifest,
        *,
        runner: CommandRunner = _run_host_command,
        machine: str | None = None,
    ) -> None:
        self._manifest = manifest
        self._run = runner
        self._machine = machine or platform.machine()

    # -- environment probes -------------------------------------------------

    def homebrew_path(self) -> Path | None:
        """Locate ``brew``, checking the standard prefixes as well as ``PATH``.

        The prefixes matter: a GUI application launched from Finder does not
        inherit the shell's ``PATH``, so a user with Homebrew installed would
        otherwise be told to install it again — and FR-R11's first rule is that a
        present Homebrew is used and never prompts.
        """
        found = shutil.which("brew")
        if found:
            return Path(found)
        for prefix in self._manifest.raw.get("homebrew", {}).get("prefixes", []):
            candidate = Path(prefix) / "bin" / "brew"
            if candidate.is_file():
                return candidate
        return None

    def docker_path(self) -> Path | None:
        return Path(p) if (p := shutil.which("docker")) else None

    def is_apple_silicon(self) -> bool:
        return self._machine in {"arm64", "aarch64"}

    def free_disk_bytes(self, path: Path | None = None) -> int:
        try:
            return shutil.disk_usage(path or Path.home()).free
        except OSError:  # pragma: no cover - only on an unreadable mount
            return 0

    # -- planning ----------------------------------------------------------

    def plan(self, version: str | None = None, *, already_usable: bool = False) -> ProvisionPlan:
        """Decide what to install. Writes nothing.

        ``already_usable`` comes from detection: FR-R1 requires an existing
        working installation to be adopted rather than overwritten, and the plan
        must show that as a single no-cost step so the user can see that nothing
        will be downloaded.
        """
        version = version or self._manifest.default_version
        release = self._manifest.release(version)
        spec = release.platform("macos")

        if already_usable:
            return ProvisionPlan(
                strategy=Strategy.ADOPT,
                version=version,
                steps=(ProvisionStep(action=ProvisionAction.ADOPT, target=version),),
            )

        if spec is None:  # pragma: no cover - every release defines macos
            return ProvisionPlan(
                strategy=Strategy.UNAVAILABLE,
                version=version,
                blocked_by=ErrorCode.VERSION_MISMATCH,
            )

        architectures = spec.architectures
        supported_here = (
            "arm64" in architectures if self.is_apple_silicon() else "x86_64" in architectures
        )
        if not supported_here:
            # E-R08: the tap's Intel support ends at an older release, so Intel
            # hardware goes to Docker by default rather than being offered a path
            # that cannot work (§3.3).
            return self._docker_plan(version, blocked_reason=ErrorCode.MACOS_INTEL_UNSUPPORTED)

        download = int(spec.get("download_bytes", 0))
        disk = int(spec.get("disk_bytes", 0))
        steps: list[ProvisionStep] = []

        brew = self.homebrew_path()
        if brew is None:
            homebrew = self._manifest.raw.get("homebrew", {})
            steps.append(
                ProvisionStep(
                    action=ProvisionAction.INSTALL_HOMEBREW,
                    target=homebrew.get("install_url", ""),
                    download_bytes=int(homebrew.get("download_bytes", 0)),
                    disk_bytes=int(homebrew.get("disk_bytes", 0)),
                    # The one prompt FR-R3 allows. Everything after it runs as the
                    # user, so no second dialog appears.
                    needs_authorisation=True,
                )
            )

        cask = str(spec.get("cask", ""))
        tap = "/".join(cask.split("/")[:2]) if cask.count("/") >= 2 else ""
        if tap:
            steps.append(ProvisionStep(action=ProvisionAction.ADD_TAP, target=tap))
        steps.append(
            ProvisionStep(
                action=ProvisionAction.INSTALL_CASK,
                target=cask,
                download_bytes=download,
                disk_bytes=disk,
            )
        )
        steps.append(ProvisionStep(action=ProvisionAction.VERIFY, target=version))

        plan = ProvisionPlan(strategy=Strategy.HOMEBREW, version=version, steps=tuple(steps))

        # E-R05 before anything downloads, not after 1.4 GB has landed. §7.3's
        # system check exists so failures move from the middle of a lab session
        # to the setup screen.
        if self.free_disk_bytes() < plan.disk_bytes:
            return ProvisionPlan(
                strategy=plan.strategy,
                version=version,
                steps=plan.steps,
                blocked_by=ErrorCode.INSUFFICIENT_DISK,
            )
        return plan

    def _docker_plan(self, version: str, *, blocked_reason: Code | None) -> ProvisionPlan:
        """FR-R10's fallback.

        Planned but not executable in this build: driving a container needs a
        ``DockerSession``, which does not exist yet. The plan says so through
        ``blocked_by`` rather than promising an install that would leave the user
        with a runtime nothing can talk to — a wizard that "succeeds" into a
        broken state is worse than one that says it cannot help.
        """
        if self.docker_path() is None:
            return ProvisionPlan(
                strategy=Strategy.UNAVAILABLE,
                version=version,
                blocked_by=blocked_reason or ErrorCode.MACOS_INTEL_UNSUPPORTED,
            )
        return ProvisionPlan(
            strategy=Strategy.DOCKER,
            version=version,
            steps=(ProvisionStep(action=ProvisionAction.PULL_DOCKER_IMAGE, target=version),),
            blocked_by=blocked_reason,
        )

    # -- execution ---------------------------------------------------------

    def provision(
        self, plan: ProvisionPlan, *, on_progress: ProgressCallback | None = None
    ) -> ProvisionResult:
        """Carry out an accepted plan.

        Steps run in order and stop at the first failure, each re-checking its own
        precondition first so a re-run after a failure resumes rather than repeats
        (NFR-R4).
        """
        if plan.blocked_by is not None:
            return ProvisionResult(
                outcome=ProvisionOutcome.BLOCKED,
                reason=plan.blocked_by,
                detail="The plan cannot proceed as described",
            )

        log_event(
            _log,
            Event.RUNTIME_PROVISION_BEGIN,
            strategy=plan.strategy.value,
            version=plan.version,
            download_bytes=plan.download_bytes,
        )

        completed: list[ProvisionStep] = []
        for step in plan.steps:
            if on_progress is not None:
                on_progress(step)
            log_event(
                _log,
                Event.RUNTIME_PROVISION_STAGE,
                action=step.action.value,
                target=step.target,
            )

            reason, detail = self._execute(step)
            if reason is not None:
                log_event(
                    _log,
                    Event.RUNTIME_PROVISION_RESULT,
                    outcome="failed",
                    action=step.action.value,
                    code=reason.id,
                )
                return ProvisionResult(
                    outcome=ProvisionOutcome.FAILED,
                    completed=completed,
                    failed_step=step,
                    reason=reason,
                    detail=detail,
                )
            completed.append(step)

        log_event(_log, Event.RUNTIME_PROVISION_RESULT, outcome="succeeded")
        return ProvisionResult(outcome=ProvisionOutcome.SUCCEEDED, completed=completed)

    def _execute(self, step: ProvisionStep) -> tuple[Code | None, str]:
        """Run one step. Returns a §9 code and detail on failure, or ``(None, "")``."""
        match step.action:
            case ProvisionAction.ADOPT | ProvisionAction.VERIFY:
                # Verification is the caller's, through RuntimeManager.verify —
                # the canary belongs with the thing that owns FR-R5, not here.
                return None, ""

            case ProvisionAction.INSTALL_HOMEBREW:
                return self._install_homebrew(step.target)

            case ProvisionAction.ADD_TAP:
                return self._brew(["tap", step.target], ErrorCode.PACKAGE_MANAGER_FAILED)

            case ProvisionAction.INSTALL_CASK:
                if self._cask_installed(step.target):
                    # Idempotence (NFR-R4): a resumed wizard must not reinstall
                    # 1.4 GB it already has.
                    return None, ""
                return self._brew(
                    ["install", "--cask", step.target], ErrorCode.PACKAGE_MANAGER_FAILED
                )

            case ProvisionAction.PULL_DOCKER_IMAGE:  # pragma: no cover - blocked in plan()
                return (
                    ErrorCode.MACOS_INTEL_UNSUPPORTED,
                    "The Docker runtime is not implemented in this build",
                )

        return None, ""  # pragma: no cover - match is exhaustive

    def _brew(self, arguments: Sequence[str], failure: Code) -> tuple[Code | None, str]:
        brew = self.homebrew_path()
        if brew is None:
            return failure, "Homebrew is not available"
        code, output = self._run([str(brew), *arguments])
        if code != 0:
            # E-R06 shows the last 20 lines of the tool's own output: the user
            # needs what brew said, not a paraphrase of it.
            return failure, _tail(output, 20)
        return None, ""

    def _cask_installed(self, cask: str) -> bool:
        brew = self.homebrew_path()
        if brew is None:
            return False
        code, _ = self._run([str(brew), "list", "--cask", cask])
        return code == 0

    def _install_homebrew(self, install_url: str) -> tuple[Code | None, str]:
        """Install Homebrew through the native macOS authorisation dialog (FR-R11).

        ``osascript``'s ``with administrator privileges`` raises the system
        password dialog and runs the command as root — so the user sees a macOS
        prompt, not a terminal, which is precisely the hole §3.3 identifies in the
        zero-terminal promise.

        A refused dialog is not a failure of the machine; it is a decision. It
        returns E-R02, which the wizard turns into the Docker fallback rather than
        a dead end.
        """
        if not install_url:
            return ErrorCode.PACKAGE_MANAGER_FAILED, "No Homebrew installer URL in the manifest"

        # NONINTERACTIVE stops the installer waiting on a TTY confirmation that
        # nothing can answer from a GUI.
        script = (
            f'do shell script "NONINTERACTIVE=1 /bin/bash -c '
            f'\\"$(curl -fsSL {install_url})\\"" with administrator privileges'
        )
        code, output = self._run(["osascript", "-e", script])
        if code == 0:
            return None, ""
        if "User canceled" in output or "-128" in output:
            return ErrorCode.NO_ADMIN_RIGHTS, "Authorisation was declined"
        return ErrorCode.PACKAGE_MANAGER_FAILED, _tail(output, 20)


def _tail(text: str, lines: int) -> str:
    return "\n".join(text.splitlines()[-lines:])


def environment_summary() -> dict[str, object]:
    """What the wizard's system check reports (§7.3 step 2).

    Collected here so the diagnostics bundle (FR-A4) and the check screen agree
    on one source rather than probing the machine twice with two answers.
    """
    return {
        "platform": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }
