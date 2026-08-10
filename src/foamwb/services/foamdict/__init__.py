"""Tolerant OpenFOAM dictionary parser and round-trip-faithful emitter (§4.2).

The M1 gate (§12.2). Round-trip fidelity is the only mechanical guarantee behind
the D4 promise that the application never traps the user and never corrupts a
case, so
this package is proven against the corpus before any feature depends on it.
"""

from foamwb.services.foamdict.document import (
    Document,
    Node,
    NodeKind,
    ParseError,
    PathError,
)
from foamwb.services.foamdict.lexer import LexError, Token, TokenKind, tokenize

__all__ = [
    "Document",
    "LexError",
    "Node",
    "NodeKind",
    "ParseError",
    "PathError",
    "Token",
    "TokenKind",
    "tokenize",
]
