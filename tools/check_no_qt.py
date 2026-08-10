#!/usr/bin/env python3
"""NFR-M1 / §4.1 — the service layer must not import Qt.

The rule exists so the services are exercised headlessly by the test suite and
could later back a CLI. It is easy to state and easy to breach by accident: one
``from PySide6.QtCore import Signal`` in a service, added for convenience,
quietly welds the layers together and is expensive to unpick once callers depend
on the signal.

AST-based rather than a grep, so that a mention inside a docstring or a comment
is not a false positive, while an aliased or nested import is still caught.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "src" / "foamwb"

#: Subtrees permitted to import Qt.
QT_ALLOWED = (PACKAGE_ROOT / "ui",)

FORBIDDEN_ROOTS = frozenset(
    {"PySide6", "PySide2", "PyQt5", "PyQt6", "shiboken2", "shiboken6", "qtpy"}
)


def _is_allowed(path: Path) -> bool:
    return any(path.is_relative_to(allowed) for allowed in QT_ALLOWED)


def _imported_roots(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name.split(".")[0]))
        # level > 0 is a relative import, which can never reach a top-level
        # third-party package.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def main() -> int:
    violations: list[str] = []

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if _is_allowed(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(
                f"{path.relative_to(REPO_ROOT)}:{exc.lineno}: syntax error: {exc.msg}"
            )
            continue
        for lineno, root in _imported_roots(tree):
            if root in FORBIDDEN_ROOTS:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: imports {root} "
                    "outside the presentation layer"
                )

    if violations:
        print("NFR-M1 violation — Qt imported outside src/foamwb/ui/:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        print(
            "\nThe service layer is Qt-free so it can be tested headlessly and "
            "reused by a CLI (§4.1). Move the Qt dependency into foamwb.ui and "
            "communicate through a plain-Python callback or return value.",
            file=sys.stderr,
        )
        return 1

    print("check_no_qt: OK — service layer is Qt-free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
