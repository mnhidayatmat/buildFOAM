"""Pseudo-localisation (NFR-A5, M7).

Substitutes an accented, expanded version of every string so that layout
problems appear before a translator does. Three faults it makes visible:

* **Truncation.** German and Malay routinely run 30-40% longer than English, so
  a label that just fits in English is a label that will be clipped. Every string
  is padded to at least 140% of its length.
* **Concatenation.** A sentence assembled from fragments reads as nonsense once
  the fragments are accented, which is exactly the sentence a translator cannot
  reorder. The catalogue's format strings are the supported way to compose.
* **Strings that were never routed through the catalogue.** Anything still in
  plain ASCII on a pseudo-localised screen was hard-coded, and no amount of
  reading the source finds those as reliably as looking at one.

**Placeholders are preserved exactly.** ``{0}`` must survive, or the pseudo run
fails with a formatting error rather than showing the layout problem it exists to
show — and a check that breaks the application is one nobody runs twice.
"""

from __future__ import annotations

import re

__all__ = ["PADDING", "pseudo_locale", "pseudo_text"]

#: How much longer the pseudo text is. 1.4 is the usual figure for European
#: languages against English; Bahasa Melayu is comparable.
PADDING = 1.4

#: Kept out of the substitution so composition still works.
_PLACEHOLDER = re.compile(r"\{[^}]*\}")

_ACCENTS = str.maketrans(
    "aeiouAEIOUcnsyzCNSYZ",
    "àéîöûÀÉÎÖÛçñšýžÇÑŠÝŽ",
)

#: Padding characters, chosen to be obviously not English and to have no meaning
#: that a reader might mistake for content.
_FILLER = "·"


def pseudo_text(source: str) -> str:
    """Accent and expand one string, leaving its placeholders untouched."""
    if not source:
        return source

    parts: list[str] = []
    last = 0
    for match in _PLACEHOLDER.finditer(source):
        parts.append(source[last : match.start()].translate(_ACCENTS))
        parts.append(match.group(0))
        last = match.end()
    parts.append(source[last:].translate(_ACCENTS))
    accented = "".join(parts)

    # Padding goes at the end rather than inside, so a translator reading the
    # screen still recognises the phrase.
    wanted = int(len(source) * PADDING)
    if len(accented) < wanted:
        accented += " " + _FILLER * (wanted - len(accented) - 1)
    return accented


def pseudo_locale(catalogue: dict[str, str]) -> dict[str, str]:
    """Pseudo-localise a whole catalogue.

    Keys are untouched: they are lookup identifiers, not user-visible text, and
    accenting them would break every widget that asks for one.
    """
    return {key: pseudo_text(value) for key, value in catalogue.items()}
