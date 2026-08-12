"""Error taxonomy (§9).

Every failure has a stable code, a plain-language condition, and a guide anchor,
so that a support conversation can start from a code rather than a screenshot.

Two requirements depend on this table being data rather than scattered strings:

* **FR-R2** — a machine-readable ``RuntimeStatus`` reason at all times.
* **FR-G2** — every error code resolves to a guide page. The M7 exit criterion is
  an automated link check with zero dangling anchors, which is only mechanisable
  if the codes and their anchors live in one enumerable place.

User-facing *message* text is deliberately not stored here. Messages are
translatable (NFR-A5) and belong in the presentation layer's catalogue; this
module holds the stable machine vocabulary that survives translation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Final

__all__ = ["Code", "ErrorCode", "Severity", "by_id"]


class Severity(IntEnum):
    """How bad a finding or a parsed output line is.

    Lives here rather than with the run plan because it is diagnostic
    vocabulary: a validation finding (FR-C3), a ``checkMesh`` verdict (E-S02) and
    a solver log line are all graded on one scale, and a case that had two scales
    would eventually disagree with itself about whether something blocks a run.

    Ordered, so a threshold is a comparison rather than a set membership test:
    ``fail_on=Severity.WARNING`` also fails on an error.
    """

    INFO = 10
    WARNING = 20
    ERROR = 30
    FATAL = 40


@dataclass(frozen=True, slots=True)
class Code:
    """One entry in the error taxonomy."""

    id: str
    """Stable identifier, e.g. ``E-R01``. Never reused, never renumbered."""

    condition: str
    """Short description of the condition, for logs and issue templates."""

    guide_anchor: str
    """Slug of the guide page section that documents the remediation (FR-G2)."""


def _c(id_: str, condition: str, guide_anchor: str) -> Code:
    return Code(id=id_, condition=condition, guide_anchor=guide_anchor)


class ErrorCode:
    """The taxonomy, grouped as in §9.

    Abridged in the PRD and here alike — the full table is a living appendix.
    Codes are added, never renumbered.
    """

    # -- Runtime (R) -------------------------------------------------------
    VIRTUALIZATION_DISABLED = _c(
        "E-R01", "Virtualization disabled in firmware", "runtime/virtualization-disabled"
    )
    NO_ADMIN_RIGHTS = _c("E-R02", "No administrator rights", "runtime/administrator-rights")
    REBOOT_REQUIRED = _c("E-R03", "Reboot required after enabling WSL", "runtime/reboot-required")
    DOWNLOAD_BLOCKED = _c(
        "E-R04", "Download blocked by proxy or firewall", "runtime/download-blocked"
    )
    INSUFFICIENT_DISK = _c("E-R05", "Insufficient disk space", "runtime/insufficient-disk")
    PACKAGE_MANAGER_FAILED = _c(
        "E-R06", "apt or Homebrew failure", "runtime/package-manager-failed"
    )
    RUNTIME_BROKEN = _c(
        "E-R07", "Runtime detected but canary command fails", "runtime/broken-install"
    )
    MACOS_INTEL_UNSUPPORTED = _c(
        "E-R08", "Intel hardware, Homebrew tap unsupported", "runtime/intel-mac"
    )
    MACOS_GATEKEEPER_BLOCKED = _c(
        "E-R09", "Gatekeeper or quarantine blocks a downloaded component", "runtime/gatekeeper"
    )
    NOT_PROVISIONED = _c("E-R10", "No runtime provisioned yet", "runtime/first-run")
    """The expected first-launch state, and not an error the user caused.

    It exists because FR-R2 requires a machine-readable reason for *every*
    non-ready state, and reusing E-R07 would have the footer report a working
    machine as broken — the precise failure §7.9 rule 4 forbids.
    """

    # -- Case (C) ----------------------------------------------------------
    NOT_A_CASE = _c("E-C01", "Directory is not a case", "cases/not-a-case")
    PARSE_ERROR = _c("E-C02", "Dictionary parse error", "cases/parse-error")
    MISSING_BOUNDARY_FIELD = _c(
        "E-C03", "Missing boundaryField entry", "cases/missing-boundary-field"
    )
    PATCH_BC_INCOMPATIBLE = _c(
        "E-C04", "Patch and boundary-condition type incompatible", "cases/patch-bc-mismatch"
    )
    MODIFIED_EXTERNALLY = _c(
        "E-C05", "Case modified outside the application", "cases/modified-externally"
    )
    MISSING_INITIAL_FIELD = _c(
        "E-C08", "A field the solver solves has no initial condition", "cases/missing-field"
    )
    """``fvSolution`` names a field to solve and ``0`` has no file for it.

    The solver stops before its first timestep with "cannot find file". Observed
    on a real case: ``damBreak`` ships ``0.orig`` and fails exactly this way when
    it is run without restoring it."""

    SLOW_PATH = _c("E-C06", "Case on a slow or network path", "cases/slow-storage")
    VERSION_MISMATCH = _c(
        "E-C07", "Case authored for an unsupported release", "cases/version-mismatch"
    )

    GEOMETRY_UNREADABLE = _c(
        "E-C09", "Geometry file could not be read", "cases/geometry-unreadable"
    )
    """The file exists but is not a surface: empty, truncated mid-facet, or not
    geometry at all. Caught on import rather than left for ``snappyHexMesh``,
    which reports the same file minutes later as a meshing failure."""

    GEOMETRY_UNSUPPORTED = _c(
        "E-C10", "Geometry format not supported", "cases/geometry-unsupported"
    )
    """A native CAD document — ``.sldprt``, ``.catpart`` — that no available
    reader opens. Distinct from E-C11: no converter would help, so the remedy is
    to export an exchange format from the CAD package."""

    CAD_CONVERTER_MISSING = _c(
        "E-C11", "No CAD converter is installed", "cases/cad-converter-missing"
    )
    """STEP or IGES, on a machine with no geometry kernel. The file is fine and
    the format is supported; what is missing is the tool, so the remedy is to
    install one or to export STL instead."""

    NEW_CASE_EXISTS = _c("E-C13", "A case is already there", "cases/new-case-exists")
    """Creating into an occupied directory would destroy it, and there is no
    undo. Refused rather than merged."""

    NEW_CASE_NAME_INVALID = _c(
        "E-C14", "That name cannot be used as a folder", "cases/new-case-name"
    )

    NEW_CASE_NOT_WRITABLE = _c(
        "E-C15", "The case could not be written there", "cases/new-case-not-writable"
    )

    NO_GEOMETRY_TO_MESH = _c(
        "E-C16", "There is no geometry to mesh around", "cases/no-geometry-to-mesh"
    )

    MESH_DICT_EXISTS = _c(
        "E-C17", "The meshing dictionaries are already there", "cases/mesh-dict-exists"
    )
    """A case that arrived with its own tuned ``snappyHexMeshDict`` must not lose
    it to a button labelled *Generate*. Overwriting is offered, never assumed."""

    CAD_CONVERSION_FAILED = _c("E-C12", "CAD conversion failed", "cases/cad-conversion-failed")
    """The converter ran and did not produce a usable surface. Carries the
    tool's own output, because the cause is in the model — an unhealed solid, a
    tolerance the kernel could not satisfy — and only that text names it."""

    # -- Run (S) -----------------------------------------------------------
    MESH_FAILED = _c("E-S01", "Mesh generation failed", "running/mesh-failed")
    CHECKMESH_ERRORS = _c("E-S02", "checkMesh reports errors", "running/checkmesh-errors")
    DIVERGED = _c("E-S03", "Solver diverged", "running/divergence")
    FLOATING_POINT_EXCEPTION = _c("E-S04", "Floating point exception", "running/floating-point")
    SOLVER_NOT_FOUND = _c("E-S05", "Solver binary not found", "running/solver-not-found")
    OUT_OF_MEMORY = _c("E-S06", "Out of memory or OOM-killed", "running/out-of-memory")
    DISK_FULL = _c("E-S07", "Disk full mid-run", "running/disk-full")
    DECOMPOSITION_MISMATCH = _c(
        "E-S08", "Processor count and numberOfSubdomains mismatch", "running/decomposition-mismatch"
    )
    SOLVER_SETUP_ERROR = _c("E-S09", "Solver rejected the case setup", "running/setup-error")
    """A ``FOAM FATAL ERROR`` before or during the run: a missing field, an
    unknown keyword, an unreadable dictionary.

    Distinct from :attr:`PARSE_ERROR` (E-C02), which is *this application's*
    parser failing. A case can parse perfectly here and still be rejected by the
    solver, and telling the user their file is unparseable when OpenFOAM has just
    named the exact line is the sort of second-hand diagnosis §9 exists to stop.
    """

    SOLVER_FAILED = _c("E-S10", "Solver failed for an unstated reason", "running/solver-failed")
    """The honest fallback when the log explains nothing.

    Vague on purpose. A solver exits **1** for a diverged solution, a mistyped
    keyword and a missing field alike, so a code chosen from the exit status
    would name a cause that was never established."""

    # -- Content (L) -------------------------------------------------------
    SIGNATURE_INVALID = _c("E-L01", "Signature verification failed", "library/signature-invalid")
    CHECKSUM_MISMATCH = _c("E-L02", "Checksum mismatch", "library/checksum-mismatch")
    UNKNOWN_PUBLISHER = _c(
        "E-L03", "Sideloaded package from an unknown publisher", "library/sideloading"
    )
    PACKAGE_NOT_DATA = _c("E-L04", "Package contains something other than data", "library/not-data")
    """FR-L3: an executable bit, a build recipe, a symlink, or a path that would
    escape the destination.

    Distinct from E-L03, which is about *who* published something. A package can
    come from a perfectly known publisher and still contain a ``Make/``
    directory — 7 of the shipped OpenFOAM tutorials do — and telling that user
    their publisher is unknown would name the wrong problem."""

    DESTINATION_EXISTS = _c("E-L05", "A case of that name is already there", "library/destination")
    """Not an error in the package, and never resolved by overwriting: the
    directory in the way is the user's own work."""

    # -- Post (V) ----------------------------------------------------------
    PARAVIEW_NOT_FOUND = _c("E-V01", "ParaView not found", "postprocessing/paraview-not-found")
    PARAVIEW_CANNOT_OPEN = _c(
        "E-V02", "ParaView cannot open the case", "postprocessing/paraview-open-failed"
    )

    # -- Application (A) ---------------------------------------------------
    UPDATE_FAILED = _c("E-A01", "Update failed and was rolled back", "application/update-failed")


def _collect() -> dict[str, Code]:
    codes = [v for v in vars(ErrorCode).values() if isinstance(v, Code)]
    table: dict[str, Code] = {}
    for code in codes:
        if code.id in table:  # pragma: no cover - guarded by test_codes
            raise AssertionError(f"Duplicate error code {code.id}")
        table[code.id] = code
    return table


ALL_CODES: Final[dict[str, Code]] = _collect()
"""Every code, keyed by id. The M7 guide link check iterates this."""


def by_id(code_id: str) -> Code:
    """Look up a code, raising :class:`KeyError` for an unknown id."""
    return ALL_CODES[code_id]
