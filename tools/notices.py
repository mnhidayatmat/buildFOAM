"""Generate THIRD-PARTY-NOTICES (§13.5).

Several components this application redistributes require attribution: Qt under
LGPLv3, Python under the PSF licence, pyqtgraph and others under MIT or BSD, and
the bundled tutorial cases under GPL-3.0. Shipping their code without their
notices is the one licensing failure that is both easy to commit and easy to
avoid.

**Licence *text* is copied where the package ships it, and never invented where
it does not.** PySide6 is the case in point: the wheel carries no licence file,
so this file records the SPDX identifier its metadata declares and says where the
text can be obtained. Pasting in a licence nobody shipped would be a statement
about someone else's terms that we are not entitled to make.

The bundled content is listed separately, because it is not a Python dependency
and its obligations run to a different party — those cases are OpenCFD's, under
GPL-3.0, and the catalogue already records that per item.
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from foamwb.branding import APP_DISPLAY_NAME  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tools"))
from sbom import _closure, _direct_dependencies, _licence_of  # noqa: E402

#: Where a licence text can be obtained when the package does not ship one.
KNOWN_SOURCES = {
    "pyside6": "https://doc.qt.io/qtforpython/licenses.html",
    "pyside6-essentials": "https://doc.qt.io/qtforpython/licenses.html",
    "pyside6-addons": "https://doc.qt.io/qtforpython/licenses.html",
    "shiboken6": "https://doc.qt.io/qtforpython/licenses.html",
}

RULE = "=" * 78


def _licence_text(name: str) -> str | None:
    """The licence text the distribution ships, if it ships one."""
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    for path in dist.files or []:
        text = str(path)
        if "licen" not in text.lower() and "COPYING" not in text:
            continue
        if not text.lower().endswith((".txt", ".md", "license", "licence", "copying")):
            continue
        try:
            # locate_file, not read_text: read_text resolves relative to the
            # .dist-info directory, so passing the path files() gave us finds
            # nothing and every package looks as if it ships no licence.
            return Path(dist.locate_file(path)).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return None


def build() -> str:
    names = _closure(_direct_dependencies())
    lines = [
        f"THIRD-PARTY NOTICES for {APP_DISPLAY_NAME}",
        "",
        f"{APP_DISPLAY_NAME} is distributed under GPL-3.0-or-later; see LICENSE.",
        "",
        "It redistributes the components below. Where a component ships its own",
        "licence text that text is reproduced in full. Where it does not, the",
        "licence its metadata declares is named and a source for the text is given",
        "— a licence nobody shipped is not one this file will invent.",
        "",
        RULE,
        "",
    ]

    missing: list[str] = []
    for name in names:
        declared = _licence_of(name)
        lines += [f"{name}", f"    Licence: {declared}", ""]

        text = _licence_text(name)
        if text:
            lines += [line.rstrip() for line in text.strip().splitlines()]
        else:
            source = KNOWN_SOURCES.get(name)
            missing.append(name)
            lines.append(
                f"    This package ships no licence text. See {source}"
                if source
                else "    This package ships no licence text and names no source."
            )
        lines += ["", RULE, ""]

    lines += [
        "BUNDLED CONTENT",
        "",
        "The example cases in the content library are OpenFOAM tutorials,",
        "copyright OpenCFD Ltd, distributed under GPL-3.0-or-later. Each case",
        "records its licence and publisher in the signed catalogue.",
        "",
        "OpenFOAM itself is not distributed with this application. It is invoked",
        "as a separate process and is installed by the user.",
        "",
        RULE,
        "",
        "OPENFOAM TRADE MARK",
        "",
        "OPENFOAM is a registered trade mark of OpenCFD Limited, producer and",
        f"distributor of the OpenFOAM software via www.openfoam.com. {APP_DISPLAY_NAME}",
        "is not approved or endorsed by OpenCFD Limited.",
        "",
    ]

    if missing:
        print(
            "notices: no licence text shipped by: " + ", ".join(missing),
            file=sys.stderr,
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "THIRD-PARTY-NOTICES")
    parser.add_argument("--check", action="store_true", help="fail if out of date")
    arguments = parser.parse_args(argv)

    generated = build()
    if arguments.check:
        if not arguments.out.is_file():
            print("notices: THIRD-PARTY-NOTICES is missing", file=sys.stderr)
            return 1
        if arguments.out.read_text(encoding="utf-8") != generated:
            print(
                "notices: THIRD-PARTY-NOTICES is out of date. Regenerate with "
                "`python tools/notices.py`.",
                file=sys.stderr,
            )
            return 1
        print(f"notices: OK — {arguments.out.name} matches the installed set")
        return 0

    arguments.out.write_text(generated, encoding="utf-8")
    print(f"wrote {arguments.out} ({len(generated.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
