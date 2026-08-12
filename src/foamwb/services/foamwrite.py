"""Writing a dictionary this application authored (NFR-C3).

Distinct from :mod:`foamwb.services.foamdict`, which *edits* a file the user
owns and guarantees every other byte survives. These are files the application
writes whole — a background mesh, a meshing dictionary, a new case's
``controlDict`` — where there is no prior content to preserve and the question
is instead how the file discloses what wrote it.

**The header is the disclosure.** NFR-C3 asks that anything written into a user's
case be fenced, disclosed and reversibly removable. A generated file needs no
fence: there is no surrounding content of the user's to keep separate, because
the whole file is ours. What it does need is to say so in a place a person
reading it in an editor will look, which is the top — including that editing it
is allowed, since a generated dictionary the user is afraid to touch is worse
than no dictionary.

Reversal is deleting the file, which is why nothing here ever writes over
something that already exists. That decision belongs to the caller, which is the
only layer that can ask.
"""

from __future__ import annotations

from foamwb.branding import APP_DISPLAY_NAME

__all__ = ["dictionary", "header"]

#: The dictionary *format* version — 2.0 for every OpenFOAM release in living
#: memory. Not a release identifier, which is why it is a literal here rather
#: than something read from the runtime manifest (NFR-M3).
_FORMAT_VERSION = "2.0"

_BANNER = """\
/*--------------------------------*- C++ -*----------------------------------*\\
| Written by {product}. Edit it freely — it is an ordinary OpenFOAM
| dictionary and nothing here reads it back. Deleting it undoes this
| completely; the application will offer to write it again.
\\*---------------------------------------------------------------------------*/
"""

_FOAMFILE = """\
FoamFile
{{
    version     {version};
    format      ascii;
    class       {class_name};
    object      {object_name};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

"""


def header(object_name: str, *, class_name: str = "dictionary") -> str:
    """The banner and ``FoamFile`` entry for a dictionary we author."""
    return _BANNER.format(product=APP_DISPLAY_NAME) + _FOAMFILE.format(
        version=_FORMAT_VERSION, class_name=class_name, object_name=object_name
    )


def dictionary(object_name: str, body: str, *, class_name: str = "dictionary") -> bytes:
    """A complete dictionary, ready to write.

    Bytes rather than text, so the caller writes exactly what was rendered and
    no platform newline translation happens on the way to disk.
    """
    return (header(object_name, class_name=class_name) + body).encode("utf-8")
