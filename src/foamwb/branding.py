"""Product identity — the single point of rename (NFR-M5).

This module is the only place in the source tree where the product name may
appear as a literal. Every path, bundle identifier, runtime distribution name,
case-metadata directory and content namespace is *derived* from the two
constants below, so reversing the naming decision (DEC-03) is a two-line change
here plus a migration shim, rather than an excavation across the installer,
bundle identifier, distro name, case metadata and content namespace.

Enforced in CI by ``tools/check_branding.py``.

Import package and distribution names are deliberately *not* derived from these
constants: the import package is neutral (``foamwb``) so that no module path
carries the product name, and the distribution name lives in ``pyproject.toml``.
Those two, plus documentation, are the migration-shim surface.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# The two literals. Nothing else in src/, tests/ or tools/ may contain them.
# --------------------------------------------------------------------------

APP_ID: Final = "buildfoam"
"""Lowercase, filesystem- and identifier-safe form.

Used for every derived path segment, bundle identifier component, runtime
distribution name, case-metadata directory and content namespace. Must remain a
single lowercase ASCII word so that it is safe in a POSIX path, an NTFS path, a
reverse-DNS identifier and a WSL distribution name without escaping.
"""

APP_DISPLAY_NAME: Final = "BuildFOAM"
"""Human-facing name, as shown in the UI, the window title and installers.

Localisable in principle (NFR-A5), though in practice a product name is not
translated. User-visible directories in §5.3 use this form.
"""

# --------------------------------------------------------------------------
# Everything below is derived. Adding a literal here is a CI failure.
# --------------------------------------------------------------------------

APP_TAGLINE: Final = f"{APP_DISPLAY_NAME} — a desktop workbench for OpenFOAM®"
"""The permitted trade-mark construction: a distinctive name plus a descriptor.

§13.3 forbids the ``OpenFOAM <Something>`` form and requires ® on first
prominent use.
"""

NON_ENDORSEMENT_NOTICE: Final = (
    f"{APP_DISPLAY_NAME} is not approved or endorsed by OpenCFD Limited, "
    "producer and distributor of the OpenFOAM software via www.openfoam.com, "
    "and owner of the OPENFOAM® and OpenCFD® trade marks."
)
"""Required verbatim in the setup wizard, the About dialog, the README and the
release page (§13.3)."""

CASE_METADATA_DIR: Final = f".{APP_ID}"
"""Per-case metadata directory (§3.5, §5.2).

Deleting it must leave a case that runs correctly from the command line
(FR-C7) — this is the mechanical expression of D4.
"""

CASE_METADATA_FILE: Final = "case.json"
"""Name of the metadata document inside :data:`CASE_METADATA_DIR`."""

WSL_DISTRO_NAME: Final = APP_DISPLAY_NAME
"""Name of the dedicated WSL distribution imported by the wizard (DEC-12).

Deliberately *not* the user's default Ubuntu: a deterministic support surface, no
collision with the user's toolchain, and a self-contained uninstall.
"""

BUNDLE_ID: Final = f"io.github.{APP_ID}"
"""Reverse-DNS bundle identifier for the macOS application and its signing
identity (§15.3)."""

CONTENT_NAMESPACE: Final = APP_ID
"""Namespace under ``$WM_PROJECT_USER_DIR`` for installed content (§5.3).

Content installs into the runtime rather than the host home directory, because
host-side content would be read across the slow bridge on Windows and, for
future compiled extensions, would not be on ``$WM_PROJECT_USER_DIR`` at all.
"""

USER_DATA_DIR_NAME: Final = APP_DISPLAY_NAME
"""Segment used for user-visible application directories, per §5.3 —
``%APPDATA%\\<name>``, ``~/Library/Application Support/<name>``, ``~/<name>``."""
