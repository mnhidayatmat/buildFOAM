"""Opt-in sweep over a full OpenFOAM tutorial suite.

The vendored corpus (§12.1) is ~25 cases, sized to live in the repo and run in CI
where no OpenFOAM is installed. This sweep runs the same round-trip properties
over *every* dictionary in a real installation — 9,781 files in v2512 — which is
what actually found the constructs the curated corpus was then built to cover:
bare top-level lists, ``# include`` with a space, ``${_${VAR}}`` nesting, and
macro inclusion as a whole dictionary body.

Not part of the CI gate: it needs an OpenFOAM install, and vendoring 9,781 files
would bloat the repo for a diminishing return. It is the thing to run after any
lexer or parser change, and before a corpus refresh.

    FOAMWB_TUTORIALS=/Volumes/OpenFOAM-v2512/tutorials uv run pytest -m slow

A non-dictionary file living under ``system/``, ``constant/`` or ``0/`` — an STL,
a CSV, an m4 template, a shell script — is not a parser failure and is excluded
by the same FoamFile-header rule the vendoring tool uses.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from corpus_loader import known_defects
from foamwb.services.foamdict import Document, ParseError

TUTORIALS = os.environ.get("FOAMWB_TUTORIALS")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not TUTORIALS, reason="set FOAMWB_TUTORIALS to a tutorials directory"),
]

CASE_DIRS = {"system", "constant", "0", "0.orig"}
TEMPLATE_SUFFIXES = {".m4", ".template", ".resolvedBlocks"}


def _candidate_dictionaries(root: Path) -> list[Path]:
    found = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if not (set(path.parts) & CASE_DIRS):
            continue
        if path.suffix in TEMPLATE_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:4096] or b"FoamFile" not in data[:2000]:
            continue
        found.append(path)
    return found


def test_every_dictionary_round_trips_byte_for_byte() -> None:
    root = Path(TUTORIALS)
    assert root.is_dir(), f"not a directory: {root}"

    defects = {Path(d).name for d in known_defects()}
    candidates = _candidate_dictionaries(root)
    assert len(candidates) > 1000, "suspiciously few dictionaries — wrong directory?"

    failures: list[str] = []
    not_identical: list[str] = []
    checked = 0

    for path in candidates:
        if path.name in defects:
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"{path}: not utf-8")
            continue

        checked += 1
        try:
            document = Document.parse(text)
        except ParseError as exc:
            failures.append(f"{path}: {exc}")
            continue

        if document.render() != text:
            not_identical.append(str(path))

    report = "\n".join(
        [f"checked {checked} dictionaries"]
        + [f"  NOT IDENTICAL: {p}" for p in not_identical[:20]]
        + [f"  PARSE FAILED:  {f}" for f in failures[:20]]
    )
    assert not not_identical and not failures, report
