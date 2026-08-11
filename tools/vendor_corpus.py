#!/usr/bin/env python3
"""Vendor the test corpus from an OpenFOAM installation (§12.1).

The corpus is **vendored into the repo at a pinned OpenFOAM version and updated
deliberately**, because it is the reference the parser gate measures against.
Regenerating it silently — say, because a developer upgraded OpenFOAM — would
move the goalposts without anyone reviewing the move, and a round-trip test whose
inputs drift is not a gate.

CI has no OpenFOAM until M2, so the vendored files must be committed rather than
fetched. That constrains what is worth copying: only text dictionaries, capped in
size, with mesh payloads excluded. ``constant/polyMesh/boundary`` *is* kept, since
the boundary-condition matrix (FR-P4) is driven by the patch list in it, while
``points``/``faces``/``owner``/``neighbour`` are megabytes of list data that would
add nothing the small cases do not already cover.

Usage:
    python tools/vendor_corpus.py --tutorials /path/to/OpenFOAM/tutorials
    python tools/vendor_corpus.py --tutorials ... --check   # verify, write nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "tests" / "corpus"
MANIFEST = CORPUS_DIR / "corpus.json"

#: Cases chosen to span the §12.1 axes: incompressible/compressible,
#: steady/transient, blockMesh/snappyHexMesh, single/multiphase, plus the
#: preprocessor constructs that break naive parsers. The comment on each says
#: what it is there to exercise — a case with no stated reason is a case nobody
#: can justify keeping when the corpus needs trimming.
CASES: tuple[tuple[str, str], ...] = (
    ("basic/laplacianFoam/flange", "minimal case; non-trivial mesh conversion"),
    ("basic/potentialFoam/cylinder", "potential flow; analytic comparison case"),
    ("basic/scalarTransportFoam/pitzDaily", "passive scalar; function objects"),
    ("incompressible/icoFoam/cavity/cavity", "the canonical first case (M-2, §12.3)"),
    ("incompressible/simpleFoam/pitzDaily", "steady RAS, blockMesh; §12.3 golden case"),
    ("incompressible/simpleFoam/motorBike", "snappyHexMesh; large realistic case"),
    ("incompressible/pisoFoam/LES/pitzDaily", "transient LES"),
    ("incompressible/boundaryFoam/steadyBoundaryLayer", "wall functions, y+ (FR-VVT7)"),
    ("incompressible/lumpedPointMotion/building/steady", "nested macro ${_${VAR}}"),
    ("compressible/rhoSimpleFoam/squareBend", "steady compressible"),
    ("compressible/rhoSimpleFoam/gasMixing/injectorPipe", "macro inclusion as a dict body"),
    ("compressible/rhoPimpleFoam/RAS/angledDuct", "transient compressible RAS"),
    ("compressible/rhoCentralFoam/shockTube", "density-based; 1D shock"),
    ("multiphase/interFoam/laminar/damBreak/damBreak", "VOF; §12.3 golden case"),
    ("multiphase/interFoam/RAS/floatingObject", "#codeStream, sixDoF motion"),
    ("multiphase/overInterDyMFoam/floatingBody", "#eval{} and #codeStream together"),
    ("multiphase/multiphaseInterFoam/laminar/damBreak4phase", "four-phase VOF"),
    ("heatTransfer/buoyantSimpleFoam/circuitBoardCooling", "'# include' with a space"),
    ("heatTransfer/chtMultiRegionFoam/multiRegionHeater", "multi-region; per-region dicts"),
    ("combustion/fireFoam/LES/simplePMMApanel", "bare top-level list files"),
    ("lagrangian/MPPICFoam/column", "lagrangian clouds; see KNOWN_DEFECTS"),
    ("mesh/snappyHexMesh/flange", "snappyHexMesh dictionaries in isolation"),
    ("IO/dictionary", "OpenFOAM's own dictionary parser test suite"),
)

#: Upstream files that are genuinely malformed. Recorded rather than quietly
#: skipped: a corpus with invisible exclusions overstates what the gate proves.
KNOWN_DEFECTS: dict[str, str] = {
    "lagrangian/MPPICFoam/column/constant/kinematicCloudPositions": (
        "Final line begins '/ ****' instead of '// ****' — a single-slash typo "
        "upstream, so the trailing banner parses as an unterminated entry. "
        "OpenFOAM reads the file because it stops at the closing ')' of the list."
    ),
}

#: Files OpenFOAM ships *expecting* a parser to reject them. They are part of the
#: gate, not an exclusion from it: E-C02 has to fire on genuinely broken input,
#: and a parser tolerant enough to accept these would be tolerant enough to
#: swallow a user's real mistake.
MUST_REJECT_PREFIX = "IO/dictionary/fatal-"

#: Files that tokenise and round-trip byte-for-byte but whose *structure* this
#: parser does not model. Separated from KNOWN_DEFECTS because the file is not
#: defective — the limitation is ours, and it is bounded and understood.
STRUCTURAL_LIMITATIONS: dict[str, str] = {
    "IO/dictionary/good-if3.dict": (
        "Contains a deliberately stray '}' inside an #else branch, placed there "
        "to provoke a parse error if a reader evaluates the wrong branch. "
        "OpenFOAM skips the untaken branch as raw text and never sees the brace. "
        "Doing the same requires evaluating #ifeq, which needs environment "
        "variables and full macro expansion — out of scope for v1.0. The file "
        "still tokenises and round-trips byte-for-byte, so the raw-text tab "
        "(FR-P6) works on it; only the form editors do not. No file in the 9,781 "
        "dictionaries of the v2512 tutorial suite relies on this construct."
    ),
}

#: Mesh payload: large, uninteresting to a parser, and reproducible by blockMesh.
POLYMESH_SKIP = frozenset({"points", "faces", "owner", "neighbour", "cells", "sets"})

#: Preprocessor templates that only become dictionaries after m4/sed runs.
TEMPLATE_SUFFIXES = frozenset({".m4", ".template", ".resolvedBlocks"})

MAX_FILE_BYTES = 128 * 1024

_VERSION_RE = re.compile(r"\bv\d{4}\b")


def _openfoam_version(tutorials: Path) -> str:
    """Derive the pinned version from the installation path.

    Recorded in the manifest so a corpus refresh is visible in review as a version
    change, per NFR-M3's principle that version knowledge lives in data.
    """
    for part in reversed(tutorials.resolve().parts):
        if match := _VERSION_RE.search(part):
            return match.group()
    return "unknown"


def _is_dictionary(path: Path, data: bytes) -> bool:
    if path.suffix in TEMPLATE_SUFFIXES:
        return False
    if path.parent.name == "polyMesh" and path.stem in POLYMESH_SKIP:
        return False
    if b"\x00" in data[:4096]:
        return False
    if len(data) > MAX_FILE_BYTES:
        return False
    # The FoamFile header is the canonical marker of an OpenFOAM dictionary. The
    # .dict fixtures in IO/dictionary carry one too, including the fatal-* ones.
    #
    # This deliberately excludes the fragments a case pulls in with #include —
    # system/sampling and its like carry no header. They are not dictionaries in
    # their own right, which is why they are out of the *parser* corpus, but a
    # case is not runnable without them. That is the line between this corpus and
    # the tutorial suite: dictionaries for §12.2, real cases for anything that
    # runs.
    return b"FoamFile" in data[:2000]


def _collect(tutorials: Path, case: str) -> list[tuple[Path, bytes]]:
    root = tutorials / case
    if not root.is_dir():
        raise SystemExit(f"Case not found: {root}")

    found: list[tuple[Path, bytes]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if _is_dictionary(path, data):
            found.append((path.relative_to(tutorials), data))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tutorials", required=True, type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the vendored corpus matches the source; write nothing",
    )
    args = parser.parse_args()

    tutorials: Path = args.tutorials
    if not tutorials.is_dir():
        raise SystemExit(f"Not a directory: {tutorials}")

    version = _openfoam_version(tutorials)
    entries: dict[str, str] = {}
    total_bytes = 0

    if not args.check:
        if CORPUS_DIR.exists():
            shutil.rmtree(CORPUS_DIR)
        CORPUS_DIR.mkdir(parents=True)

    for case, _reason in CASES:
        for relative, data in _collect(tutorials, case):
            key = relative.as_posix()
            entries[key] = hashlib.sha256(data).hexdigest()
            total_bytes += len(data)
            if not args.check:
                destination = CORPUS_DIR / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)

    manifest = {
        "openfoam_version": version,
        "lineage": "esi",
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "cases": dict(CASES),
        "known_defects": KNOWN_DEFECTS,
        "must_reject_prefix": MUST_REJECT_PREFIX,
        "structural_limitations": STRUCTURAL_LIMITATIONS,
        "files": dict(sorted(entries.items())),
    }

    if args.check:
        if not MANIFEST.exists():
            print("No vendored corpus found; run without --check", file=sys.stderr)
            return 1
        existing = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if existing["files"] != manifest["files"]:
            only_new = set(manifest["files"]) - set(existing["files"])
            only_old = set(existing["files"]) - set(manifest["files"])
            print("Vendored corpus differs from the source tree.", file=sys.stderr)
            for path in sorted(only_new)[:10]:
                print(f"  + {path}", file=sys.stderr)
            for path in sorted(only_old)[:10]:
                print(f"  - {path}", file=sys.stderr)
            return 1
        print(f"corpus check: OK — {len(entries)} files match {version}")
        return 0

    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"Vendored {len(entries)} dictionaries from {len(CASES)} cases "
        f"({total_bytes / 1024:.0f} KiB) at OpenFOAM {version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
