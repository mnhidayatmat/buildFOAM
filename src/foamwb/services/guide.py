"""The bundled guide (FR-G1, FR-G2, FR-G3).

Markdown files under ``data/guide``, parsed into pages and anchored sections.
Two requirements shape everything here.

**Every §9 code must resolve** (FR-G2). An error message that offers a link to
nothing is worse than one that offers no link: the user follows it, finds
nothing, and learns the help is decorative. The anchors are not written twice —
:attr:`Code.guide_anchor` is ``area/section``, which *is* ``area.md#section``, so
the code table and the guide cannot drift apart without the check noticing.

**Search works offline** (FR-G1). It is a plain inverted index built at load
time over a few dozen pages; there is no service to call and nothing to fail when
the network is absent. §2's users include a lab machine behind a proxy that
blocks everything, and a help system that needs the internet is no help there.

Content is **original** (FR-G3). Upstream OpenFOAM documentation is deep-linked,
never copied: rehosting it would make this application a stale mirror of a
document that moves, and §13.5 is explicit about not redistributing it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

__all__ = [
    "GUIDE_DIR",
    "Guide",
    "GuidePage",
    "GuideSection",
    "load_guide",
]


def GUIDE_DIR() -> Path:  # noqa: N802 - a function so tests can point elsewhere
    """Where the bundled markdown lives, inside the wheel."""
    from foamwb import data

    return Path(data.__file__).parent / "guide"


_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_WORD = re.compile(r"[a-z0-9+.\-]{2,}")


def _slug(title: str) -> str:
    """A heading's anchor, in the form the §9 codes already use."""
    text = title.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text).strip("-")


@dataclass(frozen=True, slots=True)
class GuideSection:
    """One anchored heading and the prose under it."""

    anchor: str
    title: str
    body: str
    level: int = 2

    @property
    def summary(self) -> str:
        """The first sentence, for a search result line."""
        stripped = " ".join(self.body.split())
        if not stripped:
            return ""
        head = stripped.split(". ")[0]
        return head if head.endswith(".") else head + "."


@dataclass(frozen=True, slots=True)
class GuidePage:
    """One markdown file."""

    name: str
    """The file stem, which is the first half of every anchor it holds."""

    title: str
    sections: tuple[GuideSection, ...] = ()
    source: Path | None = field(default=None, compare=False)

    def section(self, anchor: str) -> GuideSection | None:
        return next((s for s in self.sections if s.anchor == anchor), None)

    @property
    def anchors(self) -> tuple[str, ...]:
        return tuple(f"{self.name}/{s.anchor}" for s in self.sections)


@dataclass
class Guide:
    """Every page, with an offline search index."""

    pages: tuple[GuidePage, ...] = ()
    _index: dict[str, set[str]] = field(default_factory=dict, repr=False)

    def page(self, name: str) -> GuidePage | None:
        return next((p for p in self.pages if p.name == name), None)

    def resolve(self, anchor: str) -> tuple[GuidePage, GuideSection] | None:
        """Find what an ``area/section`` anchor points at, or ``None``.

        ``None`` rather than a raised error or a fallback page: the caller is a
        help link, and silently landing the user somewhere unrelated is how a
        guide loses their trust for the rest of the session.
        """
        name, _, section = anchor.partition("/")
        page = self.page(name)
        if page is None:
            return None
        found = page.section(section)
        return (page, found) if found is not None else None

    @property
    def anchors(self) -> tuple[str, ...]:
        return tuple(anchor for page in self.pages for anchor in page.anchors)

    def search(self, query: str, *, limit: int = 20) -> list[tuple[GuidePage, GuideSection]]:
        """Offline full-text search over the sections (FR-G1).

        Every term must appear, so a two-word query narrows rather than widens.
        Results are ordered by how many times the terms occur, then by title, so
        the ordering is stable between runs — a search that reshuffles identical
        results looks broken.
        """
        terms = _WORD.findall(query.lower())
        if not terms:
            return []

        matching: set[str] | None = None
        for term in terms:
            hits = {
                anchor
                for word, anchors in self._index.items()
                if word.startswith(term)
                for anchor in anchors
            }
            matching = hits if matching is None else (matching & hits)
            if not matching:
                return []

        scored: list[tuple[int, str, GuidePage, GuideSection]] = []
        for anchor in matching or ():
            found = self.resolve(anchor)
            if found is None:
                continue
            page, section = found
            haystack = f"{section.title} {section.body}".lower()
            score = sum(haystack.count(term) for term in terms)
            scored.append((-score, section.title, page, section))

        scored.sort(key=lambda row: (row[0], row[1]))
        return [(page, section) for _score, _title, page, section in scored[:limit]]


def parse_page(name: str, text: str, *, source: Path | None = None) -> GuidePage:
    """Split one markdown file into anchored sections.

    A level-1 heading is the page title; level 2 and 3 become sections. Nothing
    else is interpreted — the view renders the markdown, and a parser that also
    tried to understand emphasis would be a second, worse markdown renderer.
    """
    headings = list(_HEADING.finditer(text))
    title = name
    sections: list[GuideSection] = []

    for index, match in enumerate(headings):
        level = len(match.group(1))
        heading = match.group(2)
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[start:end].strip()

        if level == 1 and not sections:
            title = heading
            continue
        sections.append(GuideSection(anchor=_slug(heading), title=heading, body=body, level=level))

    return GuidePage(name=name, title=title, sections=tuple(sections), source=source)


def load_guide(directory: Path | None = None) -> Guide:
    """Read every page and build the search index."""
    root = directory or GUIDE_DIR()
    pages: list[GuidePage] = []

    if root.is_dir():
        for source in sorted(root.glob("*.md")):
            pages.append(parse_page(source.stem, source.read_text(encoding="utf-8"), source=source))

    guide = Guide(pages=tuple(pages))
    for page in pages:
        for section in page.sections:
            anchor = f"{page.name}/{section.anchor}"
            for word in _WORD.findall(f"{section.title} {section.body}".lower()):
                guide._index.setdefault(word, set()).add(anchor)
    return guide


@lru_cache(maxsize=1)
def bundled_guide() -> Guide:
    """The shipped guide, parsed once.

    Cached because the guide is read-only data and every error banner may ask for
    it; re-parsing forty files each time a link is clicked would be felt.
    """
    return load_guide()
