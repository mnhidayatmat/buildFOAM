"""Generate a software bill of materials (M8, §13.5).

Every dependency that ships, with its version and licence, in CycloneDX JSON —
the format most licence scanners and university procurement processes ask for.

**Read from the lockfile, not from the environment.** ``uv.lock`` is what a
release is built from and is the same on every machine; the installed
environment may hold development extras, a locally patched wheel, or whatever
was left over from an experiment. An SBOM that describes the developer's laptop
rather than the artefact is worse than none, because it will be believed.

**Runtime dependencies only.** Test and lint tooling is not in the artefact and
listing it invites questions about licences that were never distributed.

Licences come from the installed distributions' own metadata, which is the only
authority that travels with a package; where a package states none, the field
says so rather than guessing from the project name.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from foamwb.branding import APP_DISPLAY_NAME  # noqa: E402

SPEC = "https://cyclonedx.org/schema/bom-1.5.schema.json"


def _direct_dependencies() -> list[str]:
    """The names this project declares, before resolution."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    names: list[str] = []
    for spec in project.get("dependencies", ()):
        name = spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
        if name:
            names.append(name)
    return names


def _locked() -> dict[str, str]:
    """Every pinned package and version from the lockfile."""
    lock = REPO_ROOT / "uv.lock"
    if not lock.is_file():
        return {}
    with lock.open("rb") as handle:
        data = tomllib.load(handle)
    return {p["name"]: p.get("version", "") for p in data.get("package", ())}


def _licence_of(name: str) -> str:
    """What the installed distribution says about its own licence."""
    try:
        info = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return "unknown (not installed)"

    if declared := info.get("License-Expression"):
        return declared
    classifiers = [
        value.split("::")[-1].strip()
        for value in info.get_all("Classifier", ())
        if value.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    if declared := info.get("License"):
        # Some packages put the whole licence text here. A bill of materials
        # wants the name, and a reader wants a line rather than a page.
        first = declared.strip().splitlines()[0]
        return first if len(first) < 80 else "see package metadata"
    return "unstated"


def _is_installed(name: str) -> bool:
    try:
        metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def _closure(direct: list[str]) -> list[str]:
    """Direct dependencies and everything they actually pull in.

    **Membership is "is it installed", not "is it required".** Requirements carry
    environment markers, and a marker that does not apply describes a package
    that is not in the artefact: PySide6 requires ``tomli`` only for Python
    before 3.11, so on a 3.13 build an SBOM that trusted the requirement list
    would name a package the user never receives. An SBOM is believed, so a
    wrong entry is worse than a missing tool.

    Resolving markers properly would mean depending on a resolver. Asking
    whether the distribution is present answers the same question from the
    artefact itself.
    """
    seen: set[str] = set()
    queue = list(direct)
    while queue:
        name = queue.pop()
        key = name.lower().replace("_", "-")
        if key in seen or not _is_installed(name):
            continue
        seen.add(key)
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        for spec in requires:
            # Extras are not installed unless asked for, so they are not here.
            if ";" in spec and "extra" in spec.split(";", 1)[1]:
                continue
            child = spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0]
            child = child.split(";")[0].strip()
            if child:
                queue.append(child)
    return sorted(seen)


def build(version: str) -> dict:
    locked = _locked()
    direct = _direct_dependencies()
    names = _closure(direct)

    components = []
    for name in names:
        resolved = next((v for k, v in locked.items() if k.lower() == name), "")
        components.append(
            {
                "type": "library",
                "name": name,
                "version": resolved or "unpinned",
                "licenses": [{"license": {"name": _licence_of(name)}}],
                "purl": f"pkg:pypi/{name}@{resolved}" if resolved else f"pkg:pypi/{name}",
                "scope": "required" if name in {d.lower() for d in direct} else "optional",
            }
        )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "$schema": SPEC,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": APP_DISPLAY_NAME,
                "version": version,
            },
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.0.0", help="the release being described")
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report packages whose licence could not be established, and fail",
    )
    arguments = parser.parse_args(argv)

    bom = build(arguments.version)

    if arguments.check:
        unknown = [
            c["name"]
            for c in bom["components"]
            if c["licenses"][0]["license"]["name"] in {"unstated", "unknown (not installed)"}
        ]
        if unknown:
            print(
                "SBOM: these packages state no licence and must be checked by "
                "hand before release:\n  " + "\n  ".join(unknown),
                file=sys.stderr,
            )
            return 1
        print(f"sbom: OK — {len(bom['components'])} components, every licence stated")
        return 0

    text = json.dumps(bom, indent=2) + "\n"
    if arguments.out:
        arguments.out.write_text(text, encoding="utf-8")
        print(f"wrote {arguments.out} ({len(bom['components'])} components)")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
