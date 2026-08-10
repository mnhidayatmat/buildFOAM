#!/usr/bin/env python3
"""NFR-M5 — the product name appears exactly twice in the source tree.

DEC-03 accepts a known naming risk and NFR-M5 is the insurance: because the
identifier lives in exactly two places, reversing the decision costs two lines
plus a migration shim, rather than an excavation across the installer, bundle
identifier, distro name, case metadata and content namespace. That guarantee is
worth nothing unless it is mechanically enforced, because the third occurrence
always looks harmless at the time it is written.

The checker reads the current name *out of* the branding module rather than
hard-coding it, so it keeps working across a rename — and so that this file does
not itself become a third occurrence.

**Scope.** ``src/``, ``tests/`` and ``tools/``. Deliberately excluded, as the
declared migration-shim surface: ``pyproject.toml`` (the distribution name),
``README.md``, ``CITATION.cff``, ``docs/`` and the CI workflow. A rename touches
those too; the point of NFR-M5 is that it does not touch *code*.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDING_FILE = REPO_ROOT / "src" / "foamwb" / "branding.py"
SCANNED_ROOTS = ("src", "tests", "tools")

#: One literal per constant, and no more.
EXPECTED_OCCURRENCES = 2

_CONSTANT = re.compile(
    r"^(APP_ID|APP_DISPLAY_NAME)\s*(?::\s*[^=]+)?=\s*['\"](?P<value>[^'\"]+)['\"]",
    re.MULTILINE,
)


def _terms() -> set[str]:
    """The name forms to search for, lowercased, read from the branding module."""
    source = BRANDING_FILE.read_text(encoding="utf-8")
    values = {m.group("value").lower() for m in _CONSTANT.finditer(source)}
    if not values:
        raise SystemExit(
            f"{BRANDING_FILE}: could not find APP_ID / APP_DISPLAY_NAME assignments. "
            "check_branding.py reads the product name from this file; keep the "
            "assignments as simple string literals."
        )
    return values


def main() -> int:
    terms = _terms()
    pattern = re.compile("|".join(re.escape(t) for t in sorted(terms)), re.IGNORECASE)

    branding_hits = 0
    strays: list[str] = []

    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".toml", ".json", ".cfg"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                for match in pattern.finditer(line):
                    if path == BRANDING_FILE:
                        branding_hits += 1
                    else:
                        strays.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {match.group(0)!r}")

    failed = False

    if strays:
        failed = True
        print(
            "NFR-M5 violation — the product name appears outside branding.py:",
            file=sys.stderr,
        )
        for stray in strays:
            print(f"  {stray}", file=sys.stderr)
        print(
            "\nDerive it instead: import APP_ID or APP_DISPLAY_NAME from "
            "foamwb.branding, or add a derived constant there. A rename must stay "
            "a two-line change (DEC-03, NFR-M5).",
            file=sys.stderr,
        )

    if branding_hits != EXPECTED_OCCURRENCES:
        failed = True
        print(
            f"NFR-M5 violation — expected exactly {EXPECTED_OCCURRENCES} occurrences of "
            f"the product name in {BRANDING_FILE.relative_to(REPO_ROOT)}, found "
            f"{branding_hits}.\nOne literal per constant; every other use must be "
            "derived from them, including in docstrings.",
            file=sys.stderr,
        )

    if failed:
        return 1

    print(
        f"check_branding: OK — product name confined to "
        f"{BRANDING_FILE.relative_to(REPO_ROOT)} ({branding_hits} occurrences)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
