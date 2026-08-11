"""Colours come from the palette, never from a literal (NFR-A2, NFR-A4).

The contrast tests prove that every *palette token pair* meets WCAG. They cannot
prove that a view only uses palette tokens — a stylesheet with ``color: #888``
in it would sail past them while being unreadable in one theme and invisible in
the other.

So this guard checks the other half: outside ``theme.py``, the presentation layer
contains no colour literals at all. Together the two give the property NFR-A2
actually asks for, which is about what appears on screen rather than about what
is written in a table.

It also catches the subtler failure. A hardcoded colour is not merely a contrast
risk; it is a colour that does not change when the user switches to dark mode,
so it survives every theme test by being wrong in exactly one of them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_ROOT = REPO_ROOT / "src" / "foamwb" / "ui"

#: Where the palettes are defined, and the only place literals belong.
EXEMPT = {UI_ROOT / "theme.py"}

#: Hex colours, and the CSS named colours a stylesheet might reach for. Named
#: colours are worth catching too: `color: white` is exactly as theme-blind as
#: `#ffffff`, and easier to write by accident.
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_NAMED = re.compile(
    r"\b(?:color|background|background-color|border-color|border)\s*:\s*"
    r"(white|black|red|green|blue|grey|gray|yellow|orange|silver|navy)\b",
    re.IGNORECASE,
)


def main() -> int:
    offences: list[str] = []

    for source in sorted(UI_ROOT.rglob("*.py")):
        if source in EXEMPT or "__pycache__" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # A '#' comment is not a colour, and neither is a docstring mention.
            if stripped.startswith("#"):
                continue
            for match in (*_HEX.finditer(line), *_NAMED.finditer(line)):
                relative = source.relative_to(REPO_ROOT)
                offences.append(f"  {relative}:{number}: {match.group(0)}")

    if offences:
        print(
            "NFR-A2/A4 violation — a colour literal outside theme.py:\n" + "\n".join(offences),
            file=sys.stderr,
        )
        print(
            "\nTake the colour from the Palette instead. A literal does not "
            "change when the user switches theme, so it is wrong in exactly one "
            "of them — and passes every test that checks the palettes.",
            file=sys.stderr,
        )
        return 1

    print("check_palette_only: OK — every colour in the UI comes from the palette")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
