"""Tokeniser for OpenFOAM dictionaries.

**The load-bearing property is byte conservation.** Every character of the source
lands in exactly one token, whitespace and comments included, so that

    "".join(t.text for t in tokenize(src)) == src

holds for *any* input the lexer accepts. Rendering a document is that join, which
makes the FR-P7 round-trip guarantee a property of the data structure rather than
something the emitter has to be careful about. The invariant is asserted at the
end of :func:`tokenize` — it costs one comparison per file and it is the single
assumption D4 rests on, so it is not left to the test suite alone.

This is why §4.2 specifies a token stream rather than an AST rebuild. An emitter
that reconstructs text from a parsed tree has to re-derive every formatting
decision the user made — indentation, alignment, blank lines, comment placement —
and will get some of them wrong on a file it has never seen. A token stream
cannot: it does not know what formatting *is*.

The corollary matters just as much. Because fidelity does not depend on
understanding the grammar, the parser above this layer is free to be tolerant.
OpenFOAM dictionaries contain conditional blocks (``#ifeq``/``#else``/``#endif``),
directives that generate keywords (``#word``), inline expression evaluation
(``#eval{...}``) and embedded C++ (``#codeStream``/``#{...#}``). Modelling all of
that structurally is a research project; preserving it byte-for-byte is a scanner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Token", "TokenKind", "tokenize"]


class TokenKind(StrEnum):
    WHITESPACE = "whitespace"
    COMMENT = "comment"
    WORD = "word"
    """An unquoted token: a keyword, a number, a dimension component, a type name."""

    STRING = "string"
    """A double-quoted token. Also how regex patch keys are written, e.g. ``".*Wall"``."""

    VERBATIM = "verbatim"
    """A ``#{ ... #}`` block of embedded C++. Opaque by design — its contents are
    not OpenFOAM dictionary syntax and must never be interpreted as such."""

    DIRECTIVE = "directive"
    """``#include``, ``#calc``, ``#codeStream``, ``#if``, ``#eval``, ``#word``, …

    A space between the hash and the name is legal and appears in the tutorial
    suite (``# include "extrudeModel"``), so the token may contain interior
    whitespace.
    """

    VARIABLE = "variable"
    """``$var``, ``${var}``, ``${var:-default}`` — macro expansion.

    Hyphens are part of the name: ``$relaxationFactors-SIMPLE`` is one variable,
    not a subtraction. OpenFOAM keywords admit ``-`` and there is no arithmetic at
    this level — expression syntax only exists inside ``#eval``/``#calc``, which
    are opaque regions.

    Braced forms nest: ``${_${FOAM_EXECUTABLE}}`` selects an entry by the running
    solver's name. Two levels are matched, which covers the tutorial suite; a
    third would lex as separate tokens and still round-trip, only without being
    recognised as one variable.
    """

    LBRACE = "lbrace"
    RBRACE = "rbrace"
    LPAREN = "lparen"
    RPAREN = "rparen"
    LBRACKET = "lbracket"
    RBRACKET = "rbracket"
    SEMICOLON = "semicolon"

    UNKNOWN = "unknown"
    """A character the lexer has no rule for.

    Deliberately *not* an error. A dictionary containing one stray byte must still
    round-trip, because refusing to open the file would strand the user with no
    way to fix it in-app — and FR-P6 promises a raw-text tab for every dictionary.
    """


#: Kinds that carry no structural meaning and are skipped when walking the tree.
TRIVIA = frozenset({TokenKind.WHITESPACE, TokenKind.COMMENT})

#: Bracket kinds, used for depth tracking when scanning a value.
OPENERS = frozenset({TokenKind.LBRACE, TokenKind.LPAREN, TokenKind.LBRACKET})
CLOSERS = frozenset({TokenKind.RBRACE, TokenKind.RPAREN, TokenKind.RBRACKET})


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    start: int
    """Character offset into the source. ``end`` is ``start + len(text)``."""

    @property
    def end(self) -> int:
        return self.start + len(self.text)

    @property
    def is_trivia(self) -> bool:
        return self.kind in TRIVIA


_PUNCTUATION = {
    "{": TokenKind.LBRACE,
    "}": TokenKind.RBRACE,
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
    ";": TokenKind.SEMICOLON,
}

# Order is significant: earlier alternatives win. The `bad_*` alternatives sit
# directly after their well-formed counterparts so that an unterminated construct
# is reported at its opening delimiter rather than silently decomposing into
# single characters.
#
# The word pattern admits `/` only when it does not begin a comment, because a
# path like `constant/polyMesh` is an ordinary word while `//` and `/*` are not.
_MASTER = re.compile(
    r"""
      (?P<whitespace> [ \t\r\n\f\v]+ )
    | (?P<comment>    // [^\n]* | /\* .*? \*/ )
    | (?P<bad_block>  /\* )
    | (?P<string>     " (?: \\. | [^"\\] )* " )
    | (?P<bad_string> " )
    | (?P<verbatim>   \#\{ .*? \#\} )
    | (?P<bad_verbat> \#\{ )
    | (?P<directive>  \# [ \t]* [A-Za-z_][A-Za-z0-9_]* )
    | (?P<variable>   \$\{ (?: [^{}] | \{ (?: [^{}] | \{[^{}]*\} )* \} )* \}
                    | \$ [A-Za-z0-9_:!./-]+ )
    | (?P<punct>      [{}()\[\];] )
    | (?P<word>       (?: [^ \t\r\n\f\v{}()\[\];"$\#/] | /(?![/*]) )+ )
    | (?P<unknown>    . )
    """,
    re.VERBOSE | re.DOTALL,
)

_GROUP_KINDS = {
    "whitespace": TokenKind.WHITESPACE,
    "comment": TokenKind.COMMENT,
    "string": TokenKind.STRING,
    "verbatim": TokenKind.VERBATIM,
    "directive": TokenKind.DIRECTIVE,
    "variable": TokenKind.VARIABLE,
    "unknown": TokenKind.UNKNOWN,
}

_UNTERMINATED = {
    "bad_block": "block comment",
    "bad_string": "string",
    "bad_verbat": "verbatim block",
}


class LexError(ValueError):
    """An unterminated construct — the only thing the lexer refuses outright.

    Carries a character offset so the caller can report file, line and column
    (E-C02). Unlike an unrecognised character, an unterminated delimiter means the
    rest of the file cannot be tokenised meaningfully at all: everything after it
    would be swallowed into the unclosed region.
    """

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


def tokenize(text: str) -> list[Token]:
    """Split ``text`` into tokens that concatenate back to ``text`` exactly.

    Raises :class:`LexError` only for an unterminated string, block comment or
    verbatim block.
    """
    tokens: list[Token] = []
    append = tokens.append

    for match in _MASTER.finditer(text):
        group = match.lastgroup
        assert group is not None  # the `unknown` fallback matches any character

        if group in _UNTERMINATED:
            raise LexError(f"Unterminated {_UNTERMINATED[group]}", match.start())

        if group == "punct":
            kind = _PUNCTUATION[match.group()]
        elif group == "word":
            kind = TokenKind.WORD
        else:
            kind = _GROUP_KINDS[group]

        append(Token(kind=kind, text=match.group(), start=match.start()))

    # The guarantee everything else is built on. Cheap, and never worth trusting
    # to the test suite alone: a lexer change that dropped a byte would otherwise
    # corrupt a user's case silently, which is the one failure mode §11 calls
    # worse than the tool not existing.
    if sum(len(t.text) for t in tokens) != len(text):
        raise AssertionError(
            "Lexer lost or duplicated input — byte conservation violated. "
            "This is a bug in the tokeniser, not in the input."
        )

    return tokens


def line_and_column(text: str, offset: int) -> tuple[int, int]:
    """Convert a character offset to 1-based line and column, for E-C02 reporting."""
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start + 1
