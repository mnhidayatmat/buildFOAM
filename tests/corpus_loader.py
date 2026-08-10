"""Access to the vendored corpus (§12.1).

The corpus is partitioned three ways, and the partition is part of the gate
rather than a convenience:

* **round-trip** — must parse and satisfy all four §12.2 properties.
* **must-reject** — OpenFOAM's ``fatal-*`` fixtures, which must raise E-C02. A
  parser loose enough to accept these is loose enough to swallow a user's real
  mistake, so accepting one is a failure in the same way that rejecting a good
  file is.
* **structural limitations** — files that tokenise and round-trip byte-for-byte
  but whose structure this parser does not model. Named, explained, and still
  asserted against for the properties they *do* satisfy.

Kept out of ``conftest.py`` so the opt-in wide sweep can import it without
pulling in fixtures it does not use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
MANIFEST = CORPUS_DIR / "corpus.json"


@dataclass(frozen=True, slots=True)
class CorpusFile:
    relative: str
    """Path relative to the tutorials root, e.g.
    ``incompressible/simpleFoam/pitzDaily/system/controlDict``."""

    path: Path

    @property
    def text(self) -> str:
        # Bytes then decode, never read_text: universal-newline translation would
        # silently rewrite CRLF and make a byte-identity assertion meaningless.
        return self.path.read_bytes().decode("utf-8")

    @property
    def id(self) -> str:
        """Compact pytest id — the case and the dictionary name."""
        parts = self.relative.split("/")
        return "/".join(parts[-3:]) if len(parts) > 3 else self.relative


@cache
def manifest() -> dict:
    if not MANIFEST.exists():
        raise RuntimeError(
            "Corpus not vendored. Run:\n"
            "  python tools/vendor_corpus.py --tutorials <OpenFOAM>/tutorials"
        )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@cache
def known_defects() -> dict[str, str]:
    """Upstream files that are genuinely malformed."""
    return manifest()["known_defects"]


@cache
def structural_limitations() -> dict[str, str]:
    """Files this parser cannot structure, with the reason for each."""
    return manifest()["structural_limitations"]


def _file(relative: str) -> CorpusFile:
    return CorpusFile(relative=relative, path=CORPUS_DIR / relative)


@cache
def corpus_files() -> tuple[CorpusFile, ...]:
    """Dictionaries expected to parse and satisfy every §12.2 property."""
    reject_prefix = manifest()["must_reject_prefix"]
    excluded = set(known_defects()) | set(structural_limitations())
    return tuple(
        _file(relative)
        for relative in manifest()["files"]
        if relative not in excluded and not relative.startswith(reject_prefix)
    )


@cache
def must_reject_files() -> tuple[CorpusFile, ...]:
    """Fixtures OpenFOAM ships expecting a parser to reject them."""
    reject_prefix = manifest()["must_reject_prefix"]
    return tuple(
        _file(relative) for relative in manifest()["files"] if relative.startswith(reject_prefix)
    )


@cache
def limitation_files() -> tuple[CorpusFile, ...]:
    return tuple(_file(relative) for relative in structural_limitations())


def ids(files: tuple[CorpusFile, ...]) -> list[str]:
    return [f.id for f in files]
