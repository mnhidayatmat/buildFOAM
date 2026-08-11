"""Every §9 code resolves to a guide section (FR-G2). M7's exit criterion.

Zero dangling anchors, checked mechanically rather than by reading. An error
message offering a link to nothing is worse than one offering no link at all:
the user follows it, finds nothing, and learns that the help in this application
is decorative. That lesson is learned once and applies to every later message.

The check runs both ways.

*Forward*: every code's ``guide_anchor`` names a section that exists. This is the
requirement.

*Backward*: every guide section that looks like a code target is reachable from
some code. A section nobody links to is not a failure — a quick-start page is
full of them — so this half only reports, and only for the pages that exist to
document codes. It catches the rename that moved a section and left the code
pointing at the old name, which the forward check catches too, and the one that
left an orphan behind, which it does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from foamwb.codes import ALL_CODES  # noqa: E402
from foamwb.services.guide import load_guide  # noqa: E402

#: Pages that exist to document error codes. Sections on any other page are
#: reference material and are not expected to be linked from the code table.
_CODE_PAGES = frozenset({"runtime", "cases", "running", "library", "postprocessing", "application"})


def main() -> int:
    guide = load_guide(REPO_ROOT / "src" / "foamwb" / "data" / "guide")

    if not guide.pages:
        print("check_guide_links: no guide pages found", file=sys.stderr)
        return 1

    dangling: list[str] = []
    for code_id, code in sorted(ALL_CODES.items()):
        if guide.resolve(code.guide_anchor) is None:
            dangling.append(f"  {code_id}  ->  {code.guide_anchor}")

    if dangling:
        print(
            "FR-G2 violation — these error codes link to a guide section that "
            "does not exist:\n" + "\n".join(dangling),
            file=sys.stderr,
        )
        print(
            "\nAdd the section, or correct the anchor in src/foamwb/codes.py. "
            "An error message whose link goes nowhere teaches the user that the "
            "help is decorative.",
            file=sys.stderr,
        )
        return 1

    linked = {code.guide_anchor for code in ALL_CODES.values()}
    orphans = [
        anchor
        for page in guide.pages
        if page.name in _CODE_PAGES
        for anchor in page.anchors
        if anchor not in linked
    ]

    print(f"check_guide_links: OK — {len(ALL_CODES)} codes resolve across {len(guide.pages)} pages")
    if orphans:
        print(f"  note: {len(orphans)} section(s) on code pages are linked by no code:")
        for anchor in orphans:
            print(f"    {anchor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
