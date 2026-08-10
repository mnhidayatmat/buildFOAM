"""The GUI-owned fence in ``controlDict`` (FR-S3, FR-C5, NFR-C3).

To plot residuals the application injects a ``solverInfo`` function object into
the user's ``controlDict``. That is writing to a file the user owns, in a way
they did not ask for, so NFR-C3 sets three conditions: the modification is
**fenced**, **disclosed**, and **reversible**.

Fenced, because the alternative is editing the user's own ``functions`` entry and
then trying to remember which parts were theirs. Comment markers make ownership
unambiguous to the code *and* to a person reading the file — the fence says what
it is and that deleting it is safe, so a P4 user who opens the file in vim is not
left guessing.

Reversible is the load-bearing one, and it is stronger than "removable":
:func:`remove` restores the file **byte-for-byte**, so a case that has been run
and then cleaned is byte-identical to the case that was imported (FR-C5). That is
asserted, not assumed.

Comment markers rather than a dictionary entry because OpenFOAM ignores comments
entirely. A malformed fence can therefore never make the case unrunnable — the
worst case is that the residual plot falls back to log parsing, which DEC-13
already provides for.
"""

from __future__ import annotations

import re

from foamwb.branding import APP_DISPLAY_NAME, APP_ID

__all__ = ["FENCE_BEGIN", "FENCE_END", "install", "is_installed", "remove"]

FENCE_BEGIN = f"// >>> {APP_ID}:begin"
FENCE_END = f"// <<< {APP_ID}:end"

#: Explains itself in the file, so someone reading it in a text editor knows what
#: wrote it and that removing it is safe (NFR-C3's "disclosed").
_NOTICE = (
    f"// Added by {APP_DISPLAY_NAME} to plot residuals. Safe to delete: removing\n"
    "// this block leaves a valid case and only costs the live residual plot."
)

_FENCE_PATTERN = re.compile(
    re.escape(FENCE_BEGIN) + r".*?" + re.escape(FENCE_END) + r"[ \t]*\n?",
    re.DOTALL,
)

#: The function object DEC-13 makes the primary monitoring source. `fields` is
#: filled per case: naming fields the case does not solve makes the object emit
#: empty columns rather than fail, but the empty columns then reach the plot.
SOLVER_INFO_TEMPLATE = """\
functions
{{
    {name}
    {{
        type            solverInfo;
        libs            (utilityFunctionObjects);
        fields          ({fields});
        writeResidualFields no;
    }}
}}"""


def solver_info_block(fields: tuple[str, ...], name: str = "solverInfo") -> str:
    """Render the ``solverInfo`` function object for the given fields."""
    if not fields:
        raise ValueError("At least one field is needed for solverInfo")
    return SOLVER_INFO_TEMPLATE.format(name=name, fields=" ".join(fields))


def is_installed(text: str) -> bool:
    return FENCE_BEGIN in text and FENCE_END in text


def remove(text: str) -> str:
    """Strip the fence, restoring the file to its pre-injection bytes.

    Also removes the blank line :func:`install` added before the fence, which is
    what makes the round trip byte-exact rather than merely close. A stray blank
    line would be invisible to a person and glaring in a diff — and FR-C5 asks
    for byte-identical, not similar.
    """
    if not is_installed(text):
        return text
    stripped = _FENCE_PATTERN.sub("", text)
    return stripped[: -len("\n")] if stripped.endswith("\n\n") else stripped


def install(text: str, block: str) -> str:
    """Append a fenced block, replacing any fence already present.

    Idempotent by construction: the existing fence is removed first, so repeated
    launches cannot stack blocks. Appended at the end because a ``controlDict``
    is read as a whole and appending cannot disturb the byte offsets of anything
    the user wrote — which keeps every error line number the solver reports still
    pointing where the user expects.
    """
    base = remove(text)
    if not base.endswith("\n"):
        base += "\n"
    return f"{base}\n{FENCE_BEGIN}\n{_NOTICE}\n{block}\n{FENCE_END}\n"
