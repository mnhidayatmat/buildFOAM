"""Detect, verify and describe the OpenFOAM runtime (FR-R1, FR-R5, §6.1).

Two requirements drive the whole design.

**FR-R1 — detect before proposing to install anything.** A machine that already
has a working OpenFOAM must be adopted, not overwritten. Downloading four
gigabytes onto a machine that did not need it is the fastest way to lose a user
in the first five minutes, and on a lab image it may be impossible anyway
(FR-R8).

**FR-R5 — verify by executing a canary and parsing its output.** "Installed" and
"works" are different claims, and only the second matters. A corrupted install
must land in :data:`RuntimeState.BROKEN`, never :data:`RuntimeState.READY`, so
detection alone is never enough: the canary runs a real OpenFOAM binary, which
proves the environment sources *and* the libraries load.

The canary is deliberately not ``foamVersion``. FR-R5 names it or
``blockMesh -help``, and on the macOS bundle ``foamVersion`` is not an executable
at all — so the canary executes ``blockMesh`` and reads the version from
``WM_PROJECT_VERSION``, which the sourced environment always defines. Assuming
the first of two documented alternatives would have reported every macOS install
as broken.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from foamwb.codes import ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.runtime.manifest import Manifest, load_manifest
from foamwb.services.runtime.native import DEFAULT_CANARY_TIMEOUT, NativeSession
from foamwb.services.runtime.provision import (
    ProgressCallback,
    Provisioner,
    ProvisionPlan,
    ProvisionResult,
)
from foamwb.services.runtime.session import RuntimeSession
from foamwb.services.runtime.status import RuntimeState, RuntimeStatus
from foamwb.services.runtime.windows import (
    CANARY_UTILITY,
    STATUS_DLL_NOT_FOUND,
    WindowsNativeSession,
    find_platform_dir,
    read_api_version,
)

__all__ = ["Installation", "RuntimeManager"]

_log = get_logger("runtime.manager")

#: Where the Homebrew cask puts the bundle, and where a hand-installed one goes.
_APPLICATION_DIRS = (Path("/Applications"), Path.home() / "Applications")

#: `vYYMM`. Used to read a version out of a bundle name before the canary has
#: run; the canary's answer always wins, because a renamed bundle would lie.
_VERSION_IN_NAME = re.compile(r"(v\d{4})")

#: Executes a real OpenFOAM binary and reports the environment's own version.
#: Redirecting the binary's output keeps the version alone on stdout, so parsing
#: cannot be confused by a usage banner.
_CANARY = "blockMesh -help >/dev/null 2>&1 && printf '%s\\n' \"$WM_PROJECT_VERSION\""


@dataclass(frozen=True, slots=True)
class Installation:
    """One OpenFOAM installation found on this machine."""

    launcher: Path | None = None
    """The ``etc/openfoam`` wrapper, where the installation ships one."""

    bashrc: Path | None = None
    """``etc/bashrc``, used where there is no wrapper — the Debian packages that
    serve Linux and the WSL distribution (§3.2)."""

    bundle: Path = Path()
    version: str | None = None
    """Version as reported by the canary, or as guessed from the bundle name
    before verification. ``None`` when neither is available."""

    verified: bool = False

    platform_dir: Path | None = None
    """``platforms/<arch>`` of a native Windows build (FR-N), which has neither a
    launcher nor a bashrc that anything can run. ``None`` for every other kind."""

    @property
    def is_windows_native(self) -> bool:
        return self.platform_dir is not None

    @property
    def label(self) -> str:
        return f"{self.version or 'unknown'} ({self.bundle.name})"

    @property
    def entry_point(self) -> Path:
        """Whichever of the two exists — for logging and error messages."""
        if self.platform_dir is not None:
            return self.platform_dir / "bin" / f"{CANARY_UTILITY}.exe"
        entry = self.launcher or self.bashrc
        assert entry is not None
        return entry


def default_windows_roots(manifest: Manifest) -> tuple[Path, ...]:
    """Where native Windows builds are looked for when the caller does not say.

    Only on Windows: ``C:/Simulation`` means nothing on a Mac, and probing it
    there would be pointless work in a call the wizard makes during its system
    check. A module function rather than inline, so the test suite can make
    discovery hermetic on a machine that has a real installation.
    """
    if os.name != "nt":
        return ()
    return tuple(Path(r) for r in manifest.windows_native.get("search_roots", ()))


class RuntimeManager:
    """Finds and verifies runtimes. Provisioning arrives with the wizard."""

    def __init__(
        self,
        manifest: Manifest | None = None,
        *,
        application_dirs: tuple[Path, ...] = _APPLICATION_DIRS,
        provisioner: Provisioner | None = None,
        windows_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self._manifest = manifest or load_manifest()
        self._application_dirs = application_dirs
        self._windows_roots = (
            windows_roots if windows_roots is not None else default_windows_roots(self._manifest)
        )
        self._provisioner = provisioner or Provisioner(self._manifest)

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    # -- detection ---------------------------------------------------------

    def discover(self) -> list[Installation]:
        """Find candidate installations without running anything.

        Cheap and side-effect free, so it is safe to call during the wizard's
        system check. Nothing here proves an installation *works*; that is
        :meth:`verify`'s job.

        Ordered newest-version first, so adopting the first candidate adopts the
        best one.
        """
        found: dict[Path, Installation] = {}

        # Linux install roots come from the manifest (NFR-M3). They matter even
        # though NG4 rules out a Linux desktop build: the §12.3 golden-case gate
        # runs on a Linux CI runner, and without this it would find no runtime,
        # skip every test, and report green having verified nothing.
        for version in self._manifest.versions:
            spec = self._manifest.release(version).platform("linux")
            if spec is None or not spec.get("root"):
                continue
            root = Path(spec.get("root"))
            launcher = root / (spec.launcher or "etc/openfoam")
            bashrc = Path(spec.bashrc) if spec.bashrc else root / "etc" / "bashrc"

            # An installation is real if *either* entry point exists. The Debian
            # packages ship etc/bashrc and no wrapper, and requiring the wrapper
            # is exactly why the first CI run found nothing, skipped every gate,
            # and would have reported green having verified nothing.
            if launcher.is_file():
                found[launcher] = Installation(launcher=launcher, bundle=root, version=version)
            elif bashrc.is_file():
                found[bashrc] = Installation(bashrc=bashrc, bundle=root, version=version)

        for directory in self._application_dirs:
            if not directory.is_dir():
                continue
            for bundle in sorted(directory.glob("OpenFOAM-*.app")):
                launcher = self._launcher_in(bundle)
                if launcher is not None:
                    found[launcher] = Installation(
                        launcher=launcher,
                        bundle=bundle,
                        version=self._version_from_name(bundle.name),
                    )

        # An environment that is already sourced — a lab image, or a user who ran
        # the app from a configured shell. Adopting it avoids provisioning a
        # second copy of something already present (FR-R8).
        project_dir = os.environ.get("WM_PROJECT_DIR")
        # A native Windows build ships etc/openfoam too, but it is a bash script
        # nothing on that machine can run; adopting it produced an installation
        # that failed its canary. Such a build is found by layout below instead.
        if project_dir and find_platform_dir(Path(project_dir)) is None:
            launcher = Path(project_dir) / "etc" / "openfoam"
            if launcher.is_file() and launcher not in found:
                found[launcher] = Installation(
                    launcher=launcher,
                    bundle=Path(project_dir),
                    version=os.environ.get("WM_PROJECT_VERSION"),
                )

        for installation in self._discover_windows_native():
            found.setdefault(installation.entry_point, installation)

        installations = sorted(found.values(), key=lambda i: i.version or "", reverse=True)
        log_event(
            _log,
            Event.RUNTIME_DETECT_RESULT,
            count=len(installations),
            versions=[i.version for i in installations],
        )
        return installations

    def _launcher_in(self, bundle: Path) -> Path | None:
        """Locate the launcher inside a bundle, per the manifest's layout."""
        candidates = {
            spec.launcher
            for version in self._manifest.versions
            if (spec := self._manifest.release(version).platform("macos")) is not None
            and spec.launcher
        }
        for relative in sorted(candidates):
            launcher = bundle / relative
            if launcher.is_file():
                return launcher
        return None

    def _discover_windows_native(self) -> list[Installation]:
        """Native Windows builds (FR-N), found by layout rather than by name.

        ``WM_PROJECT_DIR`` first: such installers set it system-wide, and it is
        the user's own statement of which installation they mean. Then every
        ``project_glob`` match under the manifest's search roots.
        """
        candidates: list[Path] = []
        project_dir = os.environ.get("WM_PROJECT_DIR")
        if project_dir:
            candidates.append(Path(project_dir))
        pattern = self._manifest.windows_native.get("project_glob", "OpenFOAM-*")
        for root in self._windows_roots:
            if root.is_dir():
                candidates.extend(sorted(root.glob(pattern)))

        found: list[Installation] = []
        seen: set[Path] = set()
        for root in candidates:
            try:
                resolved = root.resolve()
            except OSError:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            platform_dir = find_platform_dir(resolved)
            if platform_dir is None:
                continue
            found.append(
                Installation(
                    bundle=resolved,
                    version=read_api_version(resolved) or self._version_from_name(resolved.name),
                    platform_dir=platform_dir,
                )
            )
        return found

    @staticmethod
    def _version_from_name(name: str) -> str | None:
        match = _VERSION_IN_NAME.search(name)
        return match.group(1) if match else None

    # -- verification ------------------------------------------------------

    def verify(
        self, installation: Installation, *, timeout: float = DEFAULT_CANARY_TIMEOUT
    ) -> RuntimeStatus:
        """Run the canary and translate the result into a status (FR-R5).

        Every outcome carries a §9 code, because a status the user cannot act on
        is a dead end and a status support cannot name is a screenshot.
        """
        if installation.is_windows_native:
            return self._verify_windows_native(installation, timeout=timeout)

        entry = installation.launcher or installation.bashrc
        if entry is None or not entry.is_file():
            return RuntimeStatus(
                state=RuntimeState.BROKEN,
                reason=ErrorCode.RUNTIME_BROKEN,
                detail=f"No usable entry point for {installation.bundle}",
            )

        session = self.session_for(installation)
        try:
            code, output = session.run_to_completion(["bash", "-c", _CANARY], timeout=timeout)
        except TimeoutError:
            # Not reported as broken. The bundle mounts a disk image on first
            # use, so a slow answer is far more likely to be a cold mount than a
            # corrupt install, and calling it broken would send the user to
            # reinstall something that works.
            return RuntimeStatus(
                state=RuntimeState.DEGRADED,
                reason=ErrorCode.RUNTIME_BROKEN,
                detail=f"Canary did not answer within {timeout:.0f}s",
                kind=session.kind,
            )
        except OSError as exc:
            return RuntimeStatus(
                state=RuntimeState.BROKEN,
                reason=ErrorCode.RUNTIME_BROKEN,
                detail=f"Could not start the runtime: {exc}",
            )
        finally:
            session.close()

        version = self._parse_canary(output)

        if code != 0 or version is None:
            return RuntimeStatus(
                state=RuntimeState.BROKEN,
                reason=ErrorCode.RUNTIME_BROKEN,
                # Bounded, matching E-R06's "last 20 lines": enough to diagnose,
                # not enough to bury the message or breach FR-A4's size budget.
                detail=_tail(output, 20) or f"Canary exited {code} with no output",
                kind=session.kind,
            )

        if not self._manifest.supports(version):
            # Usable, but outside the rolling support window (§3.4), so the user
            # is told rather than left to discover it when a schema lookup fails.
            return RuntimeStatus(
                state=RuntimeState.DEGRADED,
                reason=ErrorCode.VERSION_MISMATCH,
                detail=(
                    f"OpenFOAM {version} is installed but is not in the supported "
                    f"range ({', '.join(self._manifest.versions)})"
                ),
                kind=session.kind,
                openfoam_version=version,
            )

        return RuntimeStatus(state=RuntimeState.READY, kind=session.kind, openfoam_version=version)

    def _verify_windows_native(
        self, installation: Installation, *, timeout: float
    ) -> RuntimeStatus:
        """FR-R5 for a native Windows build: start a real executable.

        There is no shell to report ``WM_PROJECT_VERSION``, so the version comes
        from the build's ``META-INFO`` and the canary proves the other half of
        the claim — that the executable starts and every DLL it needs loads.
        That second half is where these builds fail in practice.
        """
        session = self.session_for(installation)
        try:
            code, output = session.run_to_completion([CANARY_UTILITY, "-help"], timeout=timeout)
        except TimeoutError:
            return RuntimeStatus(
                state=RuntimeState.DEGRADED,
                reason=ErrorCode.RUNTIME_BROKEN,
                detail=f"{CANARY_UTILITY} did not answer within {timeout:.0f}s",
                kind=session.kind,
            )
        except OSError as exc:
            return RuntimeStatus(
                state=RuntimeState.BROKEN,
                reason=ErrorCode.RUNTIME_BROKEN,
                detail=f"Could not start {CANARY_UTILITY}: {exc}",
                kind=session.kind,
            )
        finally:
            session.close()

        if code != 0:
            detail = _tail(output, 20) or f"{CANARY_UTILITY} exited {code} with no output"
            if code & 0xFFFFFFFF == STATUS_DLL_NOT_FOUND:
                detail = (
                    "A DLL the OpenFOAM executables need could not be loaded "
                    "(STATUS_DLL_NOT_FOUND). The installation may be incomplete, or "
                    "the Microsoft MPI runtime may be missing."
                )
            return RuntimeStatus(
                state=RuntimeState.BROKEN,
                reason=ErrorCode.RUNTIME_BROKEN,
                detail=detail,
                kind=session.kind,
            )

        version = installation.version
        if version is None or not self._manifest.supports(version):
            return RuntimeStatus(
                state=RuntimeState.DEGRADED,
                reason=ErrorCode.VERSION_MISMATCH,
                detail=(
                    f"OpenFOAM {version or '(unknown release)'} runs, but is not in the "
                    f"supported range ({', '.join(self._manifest.versions)})"
                ),
                kind=session.kind,
                openfoam_version=version,
            )
        return RuntimeStatus(state=RuntimeState.READY, kind=session.kind, openfoam_version=version)

    @staticmethod
    def _parse_canary(output: str) -> str | None:
        """Extract the version from the canary's output.

        Scans every line rather than taking the last, because the launcher may
        print mount progress to the same stream.
        """
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if _VERSION_IN_NAME.fullmatch(candidate):
                return candidate
        return None

    # -- convenience -------------------------------------------------------

    def detect(self, *, timeout: float = DEFAULT_CANARY_TIMEOUT) -> RuntimeStatus:
        """Find the best installation and verify it (FR-R1 then FR-R5).

        Returns the first status that is usable. A machine with a broken v2506
        beside a working v2512 should report ready, not broken — so a failed
        candidate is a reason to try the next one, not to stop.
        """
        log_event(_log, Event.RUNTIME_DETECT_BEGIN)
        installations = self.discover()

        if not installations:
            return RuntimeStatus(
                state=RuntimeState.MISSING,
                reason=ErrorCode.NOT_PROVISIONED,
                detail="No OpenFOAM installation found",
            )

        first_failure: RuntimeStatus | None = None
        for installation in installations:
            status = self.verify(installation, timeout=timeout)
            if status.is_usable:
                log_event(
                    _log,
                    Event.RUNTIME_VERIFY_RESULT,
                    state=status.state.value,
                    version=status.openfoam_version,
                )
                return status
            first_failure = first_failure or status

        assert first_failure is not None
        log_event(_log, Event.RUNTIME_VERIFY_RESULT, state=first_failure.state.value)
        return first_failure

    def session_for(self, installation: Installation) -> RuntimeSession:
        if installation.platform_dir is not None:
            return WindowsNativeSession(
                installation.bundle,
                platform_dir=installation.platform_dir,
                version=installation.version,
                mpi=self._manifest.windows_native.get("mpiexec"),
            )
        return NativeSession(installation.launcher, bashrc=installation.bashrc)

    def environment(
        self,
        installation: Installation,
        variables: Sequence[str],
        *,
        timeout: float = DEFAULT_CANARY_TIMEOUT,
    ) -> dict[str, str]:
        """Read variables from the sourced OpenFOAM environment.

        Asking the runtime where its own files are, rather than guessing paths
        per platform. ``$FOAM_TUTORIALS`` is a mounted disk image on macOS, a
        package directory on Debian and a distribution path under WSL — three
        answers to one question the environment already knows.

        Values are read one per line in the order requested, so a caller gets a
        dictionary rather than having to parse.
        """
        if installation.is_windows_native:
            # No shell to ask, and nothing to ask it: the layout is the upstream
            # tree, so the variables are paths under the installation.
            known = {
                "WM_PROJECT_DIR": installation.bundle,
                "FOAM_TUTORIALS": installation.bundle / "tutorials",
                "FOAM_ETC": installation.bundle / "etc",
            }
            return {
                name: str(known[name])
                for name in variables
                if name in known and known[name].exists()
            }

        script = "; ".join(f'printf "%s\\n" "${{{name}}}"' for name in variables)
        session = self.session_for(installation)
        try:
            code, output = session.run_to_completion(["bash", "-c", script], timeout=timeout)
        except (OSError, TimeoutError):
            return {}
        finally:
            session.close()

        if code != 0:
            return {}
        lines = output.splitlines()
        return {
            name: lines[index].strip()
            for index, name in enumerate(variables)
            if index < len(lines) and lines[index].strip()
        }

    def tutorials_dir(self, installation: Installation) -> Path | None:
        """Where this installation keeps its tutorial suite, or ``None``."""
        value = self.environment(installation, ("FOAM_TUTORIALS",)).get("FOAM_TUTORIALS")
        if not value:
            return None
        path = Path(value)
        return path if path.is_dir() else None

    # -- provisioning ------------------------------------------------------

    @property
    def provisioner(self) -> Provisioner:
        return self._provisioner

    def plan_provision(self, version: str | None = None) -> ProvisionPlan:
        """Decide what installing would involve, without installing (§7.3 step 4).

        Detection runs first so FR-R1 is honoured by construction: a machine that
        already has a working OpenFOAM gets an adopt-only plan that downloads
        nothing, and the user sees that on the review screen rather than being
        asked to approve a download they do not need.
        """
        version = version or self._manifest.default_version
        usable = any(
            self.verify(installation).is_usable
            and self.verify(installation).openfoam_version == version
            for installation in self.discover()
        )
        return self._provisioner.plan(version, already_usable=usable)

    def provision(
        self, plan: ProvisionPlan, *, on_progress: ProgressCallback | None = None
    ) -> tuple[ProvisionResult, RuntimeStatus]:
        """Carry out a plan and then verify the result (FR-R5).

        Verification is not optional and not the caller's to skip: "the installer
        said OK" and "this machine can run CFD" are different claims, and §7.3
        step 8 makes the second one the wizard's actual completion criterion.
        A provisioning run that succeeded but cannot pass the canary is reported
        as broken, not ready.
        """
        result = self._provisioner.provision(plan, on_progress=on_progress)
        if not result.succeeded:
            return result, RuntimeStatus(
                state=RuntimeState.MISSING if not result.completed else RuntimeState.BROKEN,
                reason=result.reason or ErrorCode.NOT_PROVISIONED,
                detail=result.detail,
            )
        return result, self.detect()


def _tail(text: str, lines: int) -> str:
    return "\n".join(text.splitlines()[-lines:])
