"""Locating and launching ParaView (FR-V1, FR-V2, FR-V3, DEC-16).

NG3 is explicit: this does not replace ParaView, it launches it. So the job here
is small and the constraints are all about not annoying the user.

**Detection before download** (FR-V1, DEC-16). "On a machine with ParaView
already installed, no download is offered." Much of the target audience already
has it, detection is free, and a ~1 GB installer materially depresses download
conversion — so ParaView is never bundled in the default installer and the search
runs first. Spotlight is consulted as well as the standard locations, because a
user who keeps applications somewhere else should not be told to download a
second copy.

**Always skippable** (§7.3 step 6, DEC-16). Postprocessing is not on the path to a
first result. A failed or declined ParaView download must not block setup, so
nothing here raises when ParaView is absent — it returns ``None`` and the caller
offers E-V01's three actions.

**The ``.foam`` stub** (FR-V2) is an empty file at the case root whose name
ParaView's reader uses to identify an OpenFOAM case. Empty is the whole point:
it carries no state, so it can be recreated at any time and deleted without
consequence, which keeps it compatible with FR-C7 and D4.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from foamwb.logs import Event, get_logger, log_event

__all__ = ["ParaViewInstall", "ParaViewService", "ensure_foam_stub", "foam_stub_path"]

_log = get_logger("paraview")

_VERSION_IN_NAME = re.compile(r"(\d+\.\d+(?:\.\d+)?)")

#: Where a macOS install normally lands. Checked before Spotlight because it is
#: instant and covers the overwhelming majority of machines.
_MACOS_APP_DIRS = (Path("/Applications"), Path.home() / "Applications")


@dataclass(frozen=True, slots=True)
class ParaViewInstall:
    """A ParaView installation found on this machine."""

    executable: Path
    version: str | None = None
    bundle: Path | None = None

    @property
    def label(self) -> str:
        return f"ParaView {self.version}" if self.version else "ParaView"


def foam_stub_path(case: Path) -> Path:
    """``<case>/<case>.foam`` — the file ParaView's reader identifies a case by."""
    return case / f"{case.name}.foam"


def ensure_foam_stub(case: Path) -> Path:
    """Create the stub if absent and return it (FR-V2).

    Deliberately never rewritten when it already exists: the file is empty, so
    there is nothing to refresh, and touching it would change the case tree hash
    for no reason and trip FR-C4's external-modification detection.
    """
    stub = foam_stub_path(case)
    if not stub.exists():
        stub.touch()
    return stub


class ParaViewService:
    """Finds ParaView and opens cases in it."""

    def __init__(
        self,
        *,
        app_dirs: Sequence[Path] = _MACOS_APP_DIRS,
        configured: Path | None = None,
        launcher: object | None = None,
    ) -> None:
        """``configured`` is the user-specified path from settings (FR-V1's third
        source). ``launcher`` is injected in tests so nothing opens a window."""
        self._app_dirs = tuple(app_dirs)
        self._configured = configured
        self._launch = launcher or self._spawn

    # -- detection ---------------------------------------------------------

    def locate(self) -> ParaViewInstall | None:
        """Find ParaView, in FR-V1's order. Returns ``None`` rather than raising.

        Absence is an ordinary state, not an error: it is what every machine looks
        like before setup step 6, and E-V01 offers detect / download / locate.
        """
        finders = (
            self._from_configuration,
            self._from_app_dirs,
            self._from_path,
            self._from_spotlight,
        )
        for finder in finders:
            install = finder()
            if install is not None:
                log_event(
                    _log,
                    Event.RUNTIME_DETECT_RESULT,
                    component="paraview",
                    version=install.version,
                )
                return install
        return None

    def _from_configuration(self) -> ParaViewInstall | None:
        if self._configured is None:
            return None
        executable = self._executable_in(self._configured) or self._configured
        if executable.exists():
            return ParaViewInstall(
                executable=executable,
                version=_version_from(self._configured.name),
                bundle=self._configured if self._configured.suffix == ".app" else None,
            )
        return None

    def _from_app_dirs(self) -> ParaViewInstall | None:
        for directory in self._app_dirs:
            if not directory.is_dir():
                continue
            # Reverse-sorted so ParaView-6.1 wins over ParaView-5.11 — a user with
            # two versions means the newer one.
            for bundle in sorted(directory.glob("ParaView*.app"), reverse=True):
                executable = self._executable_in(bundle)
                if executable is not None:
                    return ParaViewInstall(
                        executable=executable,
                        version=_version_from(bundle.name),
                        bundle=bundle,
                    )
        return None

    def _from_path(self) -> ParaViewInstall | None:
        found = shutil.which("paraview")
        return ParaViewInstall(executable=Path(found)) if found else None

    def _from_spotlight(self) -> ParaViewInstall | None:
        """Ask Spotlight, for a user who keeps applications somewhere else.

        Last because it shells out and can be slow on a cold index, and because
        the cheap checks above cover almost every machine.
        """
        if sys.platform != "darwin" or not shutil.which("mdfind"):
            return None
        try:
            completed = subprocess.run(
                ["mdfind", "kMDItemCFBundleIdentifier == 'org.paraview.ParaView'"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover
            return None
        for line in completed.stdout.splitlines():
            bundle = Path(line.strip())
            if bundle.suffix == ".app" and (executable := self._executable_in(bundle)):
                return ParaViewInstall(
                    executable=executable,
                    version=_version_from(bundle.name),
                    bundle=bundle,
                )
        return None

    @staticmethod
    def _executable_in(bundle: Path) -> Path | None:
        if bundle.suffix != ".app":
            return None
        macos = bundle / "Contents" / "MacOS"
        if not macos.is_dir():
            return None
        for candidate in ("paraview", "ParaView"):
            executable = macos / candidate
            if executable.is_file():
                return executable
        return next((p for p in sorted(macos.iterdir()) if os.access(p, os.X_OK)), None)

    @property
    def is_available(self) -> bool:
        return self.locate() is not None

    # -- launching ---------------------------------------------------------

    def open_case(self, case: Path, *, install: ParaViewInstall | None = None) -> bool:
        """Create the stub and open the case in ParaView (FR-V2).

        Returns ``False`` when ParaView is not installed, rather than raising:
        the caller turns that into E-V01's detect / download / locate offer, and
        an exception here would take down the Post view for a state that is
        entirely normal.

        The process is detached. ParaView outlives this application by design —
        a user who quits the workbench should not lose the window they were
        reading their results in.
        """
        install = install or self.locate()
        if install is None:
            return False

        stub = ensure_foam_stub(case)
        log_event(_log, Event.COMMAND_BEGIN, component="paraview", case=str(case))
        self._launch([str(install.executable), str(stub)], case)
        return True

    @staticmethod
    def _spawn(argv: Sequence[str], cwd: Path) -> None:
        subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


def _version_from(name: str) -> str | None:
    match = _VERSION_IN_NAME.search(name)
    return match.group(1) if match else None
