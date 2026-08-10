#!/usr/bin/env python3
"""NFR-M3 — version- and lineage-specific knowledge lives only in data.

No OpenFOAM version number appears anywhere in application code (§3.4). Every
schema lookup goes through the manifest's ``dictionaries`` block, so that a new
ESI release is supported by shipping a manifest update over the content channel,
without an application release — and so that the Foundation lineage stays
additive (DEC-15, NG5) rather than a fork of every call site.

The two literal families this catches:

* **Release identifiers** — one of these in code is a version the manifest cannot
  override.
* **Lineage-specific dictionary filenames** — ESI and the Foundation name the
  same two files differently. That divergence is barrier 2 of §1.2 and the reason
  NG5 defers dual-lineage support; a filename hard-coded in a service is exactly
  what would make adding Foundation support a rewrite.

**AST-based, not a grep.** Docstrings and comments must be able to *explain* the
rule — a module that cannot name the thing it forbids cannot document why it
forbids it. So only string constants that are actually used as values are
checked; prose is not code, and treating it as code taxes the documentation this
project depends on. Nothing is lost: a literal reaches the runtime only by being
a value, and every such position is still checked.

Data files under ``src/foamwb/data/`` are exempt — the manifest and the JSON
schemas are *supposed* to name versions and dictionaries. That is the design.
"""

from __future__ import annotations

import ast
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


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Identity of every string node that is a docstring, so it can be skipped."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            found.add(id(body[0].value))
    return found


def _violations(source: str, path: Path) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    docstrings = _docstring_nodes(tree)

    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        for pattern, explanation in PATTERNS:
            match = pattern.search(node.value)
            if match:
                found.append(f"{path}:{node.lineno}: {match.group(0)!r} — {explanation}")
                break
    return found


def main() -> int:
    violations: list[str] = []

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if _is_exempt(path):
            continue
        violations.extend(
            _violations(path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT))
        )

    if violations:
        print("NFR-M3 violation — version or lineage literal in application code:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        print(
            "\nRead the version from the runtime manifest, or the dictionary name "
            "from its 'dictionaries' block. Version-specific data belongs in "
            "src/foamwb/data/, which is exempt.",
            file=sys.stderr,
        )
        return 1

    print("check_version_literals: OK — no version or lineage literals in code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
