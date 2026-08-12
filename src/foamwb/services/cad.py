"""Turning CAD exchange formats into a surface OpenFOAM can mesh (FR-P3).

``snappyHexMesh`` reads triangulated surfaces — STL and OBJ — and nothing else.
A STEP or IGES file describes trimmed analytic surfaces, so there is no reading
it without a geometry kernel to tessellate it first. That kernel is the entire
subject of this module.

**The converter is found, not bundled.** This is the same decision
:mod:`foamwb.services.paraview` makes about ParaView, for the same three reasons.
A geometry kernel is tens of megabytes against NFR-M8's size budget; Gmsh is
GPL-2.0+, and invoking it as a separate process is a boundary the licence
recognises where linking it into the application is not; and NG1 says this
product does not do CAD, which is a statement about scope that bundling a CAD
kernel would quietly contradict.

**Absence is a state, not an error.** :meth:`CadConverter.locate` returns
``None`` on a machine with no converter, exactly as ``ParaViewService.locate``
does. The caller turns that into E-C11, which offers the two things that
actually help — install the converter, or export STL from the CAD package the
model came from — rather than an exception in the middle of an import.

**Conversion never touches the source file.** It reads the user's CAD model and
writes a new surface into the case; the original is left where it was, byte for
byte. A tessellation is lossy and its fineness is a judgement call, so the
conversion is something the user can redo at a different tolerance without
having lost anything.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from foamwb.logs import Event, get_logger, log_event

__all__ = [
    "DEFAULT_TIMEOUT",
    "CadConverter",
    "CadTool",
    "ConversionResult",
]

_log = get_logger("cad")

#: How long a tessellation may take before it is abandoned, in seconds.
#:
#: Generous because the work is genuinely slow — a detailed assembly can take
#: minutes on one core — and because the alternative to waiting is an import
#: that fails on exactly the models the user most needed converted. It is still
#: bounded: a kernel that has hung must not leave the application waiting for it
#: for the rest of the session.
DEFAULT_TIMEOUT = 600.0

#: Suffixes that need a kernel before OpenFOAM can do anything with them.
CAD_SUFFIXES = frozenset({".step", ".stp", ".iges", ".igs", ".brep"})

#: Where a macOS install normally lands, checked before ``PATH`` because Gmsh
#: ships as an app bundle whose executable is not on ``PATH`` by default.
_MACOS_APP_DIRS = (Path("/Applications"), Path.home() / "Applications")


@dataclass(frozen=True, slots=True)
class CadTool:
    """A geometry kernel found on this machine."""

    executable: Path
    name: str = "gmsh"
    version: str | None = None

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}" if self.version else self.name


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """What a tessellation produced, or why it produced nothing."""

    ok: bool
    target: Path | None = None
    output: str = ""
    """The tool's own stdout and stderr.

    Kept whether or not the conversion succeeded: a kernel that *warned* about a
    self-intersecting face still wrote a surface, and that warning is the reason
    the mesh will misbehave later. Discarding it on success would throw away the
    one explanation the user is going to need."""

    detail: str = ""


class CadConverter:
    """Finds a geometry kernel and tessellates CAD with it."""

    def __init__(
        self,
        *,
        app_dirs: Sequence[Path] = _MACOS_APP_DIRS,
        configured: Path | None = None,
        runner: object | None = None,
    ) -> None:
        """``configured`` is a path the user set in Settings, tried first.

        ``runner`` is injected by tests so the suite never needs a CAD kernel
        installed to exercise every branch of the conversion logic.
        """
        self._app_dirs = tuple(app_dirs)
        self._configured = configured
        self._run = runner or self._invoke

    # -- detection ---------------------------------------------------------

    def locate(self) -> CadTool | None:
        """Find a converter. Returns ``None`` rather than raising.

        A machine with no CAD kernel is an ordinary machine, and the great
        majority of users — who import STL exported from their own CAD package —
        never need one.
        """
        for finder in (self._from_configuration, self._from_path, self._from_app_dirs):
            tool = finder()
            if tool is not None:
                log_event(
                    _log,
                    Event.RUNTIME_DETECT_RESULT,
                    component="cad",
                    version=tool.version,
                )
                return tool
        return None

    def _from_configuration(self) -> CadTool | None:
        if self._configured is None or not self._configured.exists():
            return None
        return CadTool(executable=self._configured, version=self._version_of(self._configured))

    def _from_path(self) -> CadTool | None:
        found = shutil.which("gmsh")
        if not found:
            return None
        return CadTool(executable=Path(found), version=self._version_of(Path(found)))

    def _from_app_dirs(self) -> CadTool | None:
        if sys.platform != "darwin":
            return None
        for directory in self._app_dirs:
            if not directory.is_dir():
                continue
            # Reverse-sorted so a newer bundle wins, matching how ParaView is
            # chosen when a machine holds two versions.
            for bundle in sorted(directory.glob("Gmsh*.app"), reverse=True):
                executable = bundle / "Contents" / "MacOS" / "gmsh"
                if executable.is_file():
                    return CadTool(executable=executable, version=self._version_of(executable))
        return None

    def _version_of(self, executable: Path) -> str | None:
        """Ask the tool its version. Never raises — this is a label, not a gate."""
        try:
            completed = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment
            return None
        # Gmsh prints its version on stderr, which is unusual enough to be worth
        # stating: reading stdout alone finds nothing and reports no version on a
        # machine that has a perfectly good converter.
        reported = (completed.stderr or completed.stdout).strip().splitlines()
        return reported[0].strip() if reported else None

    @property
    def is_available(self) -> bool:
        return self.locate() is not None

    # -- conversion --------------------------------------------------------

    def convert(
        self,
        source: Path,
        target: Path,
        *,
        tool: CadTool | None = None,
        max_element: float | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> ConversionResult:
        """Tessellate ``source`` into an STL at ``target``.

        ``max_element`` caps the length of a tessellation edge, in the model's
        own units. It is the one knob worth exposing: left to itself a kernel
        picks a tolerance from the model's bounding box, which is right for a
        manifold and far too coarse for a small feature that happens to be the
        thing being simulated.

        Returns a result rather than raising, because every caller has to report
        the tool's own output either way — a conversion that failed and one that
        succeeded with warnings need the same text in front of the user.
        """
        tool = tool or self.locate()
        if tool is None:
            return ConversionResult(ok=False, detail="no converter found")

        target.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            str(tool.executable),
            str(source),
            # A surface mesh: the boundary of the solid is exactly what
            # snappyHexMesh wants, and asking for a volume mesh here would spend
            # minutes computing interior cells that are then thrown away.
            "-2",
            "-format",
            "stl",
            "-o",
            str(target),
        ]
        if max_element is not None:
            argv += ["-clmax", repr(max_element)]

        log_event(_log, Event.COMMAND_BEGIN, component="cad", source=str(source))
        try:
            completed = self._run(argv, timeout)
        except subprocess.TimeoutExpired:
            return ConversionResult(ok=False, detail=f"timed out after {timeout:.0f}s")
        except (OSError, subprocess.SubprocessError) as exc:
            return ConversionResult(ok=False, detail=str(exc))

        output = f"{completed.stdout}{completed.stderr}".strip()
        # The exit status is not enough on its own: a kernel can report success
        # having written nothing when it failed to read the file's geometry, and
        # an empty surface passed downstream fails much later with a message
        # about the mesh rather than about the model.
        if completed.returncode != 0:
            return ConversionResult(
                ok=False, output=output, detail=f"exit status {completed.returncode}"
            )
        if not target.exists() or target.stat().st_size == 0:
            return ConversionResult(ok=False, output=output, detail="no surface was written")

        return ConversionResult(ok=True, target=target, output=output)

    @staticmethod
    def _invoke(argv: Sequence[str], timeout: float):
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )


def needs_conversion(path: Path) -> bool:
    """Whether a file has to go through a kernel before OpenFOAM can read it."""
    return path.suffix.lower() in CAD_SUFFIXES
