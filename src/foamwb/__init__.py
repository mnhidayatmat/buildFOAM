"""Application root.

Layering (§4.1), enforced rather than documented:

* ``foamwb.services`` — pure Python, **no Qt imports**. Exercised headlessly by
  the test suite and capable of backing a CLI later. Guarded by
  ``tools/check_no_qt.py`` (NFR-M1).
* ``foamwb.ui`` — PySide6. The only subtree permitted to import Qt.

The import package is deliberately not named for the product, so that a rename
(DEC-03) stays the two-line change NFR-M5 promises. Product identity lives in
:mod:`foamwb.branding`.
"""

from __future__ import annotations

__version__ = "0.0.0"
"""Semantic version of the application (§15.1).

The runtime manifest and content catalog are versioned independently, so a new
OpenFOAM release ships without an application release.
"""
