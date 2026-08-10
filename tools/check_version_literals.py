#!/usr/bin/env python3
"""NFR-M3 — version- and lineage-specific knowledge lives only in data.

No OpenFOAM version number appears anywhere in application code (§3.4). Every
schema lookup goes through the manifest's ``dictionaries`` block, so that a new
ESI release is supported by shipping a manifest update over the content channel,
without an application release — and so that the Foundation lineage stays
additive (DEC-15, NG5) rather than a fork of every call site.

The two literal families this catches:

* **Release identifiers** — ``v2606``, ``openfoam2606``. One of these in code is
  a version the manifest cannot override.
* **Lineage-specific dictionary filenames** — ESI's ``transportProperties`` and
  ``turbulenceProperties`` against the Foundation's ``physicalProperties`` and
  ``momentumTransport``. This divergence is barrier 2 of §1.2 and the reason NG5
  defers dual-lineage support; a filename hard-coded in a service is exactly the
  thing that would make adding Foundation support a rewrite.

Data files under ``src/foamwb/data/`` are exempt — the manifest and the JSON
schemas are *supposed* to name versions and dictionaries. That is the whole
design.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "src" / "foamwb"

#: The manifest and the declarative dictionary schemas (§3.4, §5.4).
EXEMPT_DIRS = (PACKAGE_ROOT / "data",)

PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bv2[0-9]{3}\b"),
        "OpenFOAM release identifier — read it from the runtime manifest (§3.4)",
    ),
    (
        re.compile(r"\bopenfoam[0-9]{4}\b", re.IGNORECASE),
        "versioned OpenFOAM package or bashrc path — belongs in the manifest",
    ),
    (
        re.compile(
            r"\b(transportProperties|turbulenceProperties|physicalProperties|momentumTransport)\b"
        ),
        "lineage-specific dictionary filename — look it up via the manifest's "
        "'dictionaries' block (DEC-15)",
    ),
)


def _is_exempt(path: Path) -> bool:
    return any(path.is_relative_to(exempt) for exempt in EXEMPT_DIRS)


def main() -> int:
    violations: list[str] = []

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if _is_exempt(path):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern, explanation in PATTERNS:
                match = pattern.search(line)
                if match:
                    where = f"{path.relative_to(REPO_ROOT)}:{lineno}"
                    violations.append(f"{where}: {match.group(0)!r} — {explanation}")

    if violations:
        print("NFR-M3 violation — version or lineage literal in application code:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    print("check_version_literals: OK — no version or lineage literals in code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
