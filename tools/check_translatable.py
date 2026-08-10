#!/usr/bin/env python3
"""NFR-A5 — user-visible strings are externalised for translation.

"All user-visible strings externalised for translation **from M1**. English ships
in v1.0; Bahasa Melayu in v1.1. Retrofitting i18n later is expensive — the
extraction discipline starts immediately."

The expensive part of retrofitting is not the translating; it is finding the
strings. They accumulate one convenient literal at a time, each obviously fine on
its own, and by the time anyone looks there are hundreds scattered across the
widget tree. This catches the first one.

The rule: a string literal passed to a method that puts text on screen must come
from the catalogue (:mod:`foamwb.ui.strings`) or from ``tr()`` — never be written
inline. Checked by AST, so a literal built from a variable is unaffected and a
mention in a docstring is not a false positive.

Exempt: ``setObjectName`` and ``setProperty``, which are style-sheet selectors
rather than text; and the catalogue module itself, which is where the literals
are supposed to live.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_ROOT = REPO_ROOT / "src" / "foamwb" / "ui"
CATALOGUE = UI_ROOT / "strings.py"

#: Qt methods that place text in front of a user.
TEXT_SETTERS = frozenset(
    {
        "setText",
        "setWindowTitle",
        "setToolTip",
        "setStatusTip",
        "setWhatsThis",
        "setPlaceholderText",
        "setAccessibleName",
        "setAccessibleDescription",
        "addItem",
        "addTab",
        "setTitle",
        "setLabelText",
        "setInformativeText",
    }
)


def _is_translated(node: ast.AST) -> bool:
    """Whether an expression already routes through the translation machinery."""
    if isinstance(node, ast.Call):
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in {"tr", "translate"}:
            return True
        if isinstance(function, ast.Name) and function.id == "_":
            return True
        # `_("...").format(x)` and `self.tr("...").format(x)`, and also
        # `catalogue["key"].format(x)` — anything whose base is not itself a
        # literal came from somewhere that can be translated.
        if isinstance(function, ast.Attribute) and function.attr == "format":
            base = function.value
            if isinstance(base, ast.Constant):
                return False
            return _is_translated(base) or not isinstance(base, ast.JoinedStr)
    return False


def _violations(tree: ast.AST, path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute) or function.attr not in TEXT_SETTERS:
            continue
        for argument in node.args:
            # An f-string is worse than a bare literal: it cannot be extracted at
            # all, and its interpolation order cannot be changed by a translator.
            if isinstance(argument, ast.JoinedStr):
                found.append(f"{path}:{node.lineno}: {function.attr}() is given an f-string")
            elif (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and argument.value.strip()
                and not _is_translated(argument)
            ):
                found.append(
                    f"{path}:{node.lineno}: {function.attr}() is given the literal "
                    f"{argument.value[:40]!r}"
                )
    return found


def main() -> int:
    if not UI_ROOT.exists():
        print("check_translatable: OK — no presentation layer yet")
        return 0

    violations: list[str] = []
    for path in sorted(UI_ROOT.rglob("*.py")):
        if path == CATALOGUE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_violations(tree, path.relative_to(REPO_ROOT)))

    if violations:
        print("NFR-A5 violation — user-visible text is not translatable:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        print(
            "\nTake the string from foamwb.ui.strings, or wrap it in self.tr(). "
            "Strings that are style-sheet selectors belong in setObjectName or "
            "setProperty, which are exempt.",
            file=sys.stderr,
        )
        return 1

    print("check_translatable: OK — user-visible strings are externalised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
