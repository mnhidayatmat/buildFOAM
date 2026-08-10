"""Structural view over a tokenised dictionary, and the editing API (§4.2).

The parser's only job is to locate **editable entries**. It is not a complete
OpenFOAM grammar and does not try to be: byte-fidelity is already guaranteed by
the token stream (see :mod:`foamwb.services.foamdict.lexer`), so anything the
parser cannot model is recorded as an opaque region and preserved untouched.

That tolerance is a requirement, not a shortcut. §5.4 says any key present in the
file but absent from the schema is preserved and shown in the raw-text tab, and
D4 says every file stays hand-editable. A parser that rejected
``#ifeq``/``#else``/``#endif``, ``#word``-generated keywords or embedded C++ would
refuse to open real tutorials — the exact cases a student is most likely to be
handed.

What *is* rejected is structural impossibility: an unbalanced brace, an
unterminated string. Those are E-C02, reported with file, line, column and the
offending token, because a file that cannot be tokenised cannot be safely written
back either.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum, auto

from foamwb.services.foamdict.lexer import (
    CLOSERS,
    OPENERS,
    LexError,
    Token,
    TokenKind,
    line_and_column,
    tokenize,
)

__all__ = ["Document", "Node", "NodeKind", "ParseError", "PathError"]


class ParseError(ValueError):
    """A dictionary that cannot be parsed — surfaced to the user as E-C02.

    Carries line, column and the offending text so the raw-text tab can put the
    cursor on the problem rather than reporting "invalid syntax" and leaving the
    user to search a file they did not know existed (§1.2, barrier 3).
    """

    def __init__(self, message: str, *, line: int, column: int, text: str = "") -> None:
        where = f"line {line}, column {column}"
        detail = f"{message} at {text!r} ({where})" if text else f"{message} ({where})"
        super().__init__(detail)
        self.message = message
        self.line = line
        self.column = column
        self.text = text


class PathError(KeyError):
    """A dictionary path that does not resolve."""


class NodeKind(StrEnum):
    ROOT = auto()
    ENTRY = auto()
    """``keyword value;`` — the only kind that can be edited."""

    DICT = auto()
    """``keyword { ... }``."""

    OPAQUE = auto()
    """A region preserved verbatim: a directive, a conditional block, a
    brace group with no keyword. Never edited, never reformatted."""


@dataclass(slots=True)
class Node:
    kind: NodeKind
    keyword: str | None = None
    """Decoded keyword — quotes stripped, so a regex key ``".*Wall"`` resolves as
    ``.*Wall``."""

    keyword_raw: str | None = None
    """Keyword exactly as written, including quotes."""

    key_index: int | None = None
    value_start: int | None = None
    """First token of the value, inclusive. ``None`` for non-entries."""

    value_end: int | None = None
    """One past the last token of the value, exclusive of the terminating ``;``."""

    body_start: int | None = None
    body_end: int | None = None
    """Token span inside a dictionary's braces, exclusive of the braces themselves."""

    children: list[Node] = field(default_factory=list)

    def child(self, keyword: str) -> Node | None:
        """Last child with this keyword.

        Last rather than first because OpenFOAM itself takes the last definition
        when a keyword is repeated; matching that avoids the GUI showing one value
        while the solver uses another.
        """
        for node in reversed(self.children):
            if node.keyword == keyword:
                return node
        return None


class Document:
    """A parsed dictionary that renders back to its exact source."""

    __slots__ = ("_root", "_text", "_tokens")

    def __init__(self, text: str, tokens: list[Token], root: Node) -> None:
        self._text = text
        self._tokens = tokens
        self._root = root

    # -- construction ------------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> Document:
        """Parse dictionary source."""
        try:
            tokens = tokenize(text)
        except LexError as exc:
            line, column = line_and_column(text, exc.offset)
            raise ParseError(str(exc), line=line, column=column) from exc

        root = _Parser(text, tokens).parse()
        return cls(text, tokens, root)

    @classmethod
    def parse_bytes(cls, data: bytes, encoding: str = "utf-8") -> Document:
        """Parse raw file bytes.

        Bytes rather than text because :meth:`str.splitlines` and universal-newline
        decoding both rewrite line endings, and a CRLF file that came back LF would
        fail the byte-identity guarantee on every line. NFR-C4 also requires
        Unicode to survive, so the encoding is explicit rather than locale-derived.
        """
        try:
            return cls.parse(data.decode(encoding))
        except UnicodeDecodeError as exc:
            raise ParseError(f"File is not valid {encoding} text", line=1, column=1) from exc

    # -- reading -----------------------------------------------------------

    @property
    def root(self) -> Node:
        return self._root

    @property
    def tokens(self) -> list[Token]:
        return list(self._tokens)

    def render(self) -> str:
        """Reproduce the document as text.

        For an unmodified document this is byte-identical to the source, by
        construction rather than by effort (§12.2 step 1).
        """
        return "".join(t.text for t in self._tokens)

    def render_bytes(self, encoding: str = "utf-8") -> bytes:
        return self.render().encode(encoding)

    def find(self, path: str) -> Node | None:
        """Resolve a slash-separated path, e.g. ``boundaryField/movingWall/type``.

        Slash-separated to match ``foamDictionary -entry``, so a P4 user's existing
        muscle memory transfers rather than being contradicted.
        """
        node = self._root
        for part in _split_path(path):
            found = node.child(part)
            if found is None:
                return None
            node = found
        return node

    def has(self, path: str) -> bool:
        return self.find(path) is not None

    def get(self, path: str) -> str | None:
        """Value text of an entry, whitespace-normalised, or ``None`` if absent.

        Normalised because callers want the *value* (``uniform (0 0 0)``), not the
        author's column alignment. The document itself keeps the original spacing;
        this is a read-only convenience.
        """
        node = self.find(path)
        if node is None or node.kind is not NodeKind.ENTRY:
            return None
        return self._value_text(node)

    def keys(self, path: str = "") -> list[str]:
        """Keywords directly under ``path``, in file order.

        Opaque regions have no keyword and are omitted, so a caller enumerating
        keys never sees ``#include`` as if it were a setting.
        """
        node = self._root if not path else self.find(path)
        if node is None:
            raise PathError(f"No such dictionary: {path!r}")
        return [c.keyword for c in node.children if c.keyword is not None]

    def entries(self) -> Iterator[tuple[str, Node]]:
        """Yield ``(path, node)`` for every editable entry, in file order.

        The enumeration a form editor needs to answer "what is in this file that
        my schema does not cover?" — §5.4 requires those keys preserved and shown
        in the raw-text tab rather than dropped.

        Opaque regions are not yielded and their interiors are not descended into:
        an entry inside a ``#codeStream`` block is C++, not a setting, and
        offering it for editing would be offering to corrupt the case.
        """

        def walk(node: Node, prefix: str) -> Iterator[tuple[str, Node]]:
            for child in node.children:
                if child.keyword is None:
                    continue
                path = f"{prefix}/{child.keyword}" if prefix else child.keyword
                if child.kind is NodeKind.ENTRY:
                    yield path, child
                elif child.kind is NodeKind.DICT:
                    yield from walk(child, path)

        yield from walk(self._root, "")

    def value_spans_lines(self, node: Node) -> bool:
        """Whether an entry's value occupies more than one line."""
        assert node.value_start is not None and node.value_end is not None
        return any("\n" in t.text for t in self._tokens[node.value_start : node.value_end])

    def _value_text(self, node: Node) -> str:
        assert node.value_start is not None and node.value_end is not None
        # Comments are excluded: a comment sitting inside a block's vertex list is
        # documentation, not data, and folding it into the value would make the
        # same dictionary compare unequal to itself after a purely cosmetic edit.
        raw = "".join(
            t.text
            for t in self._tokens[node.value_start : node.value_end]
            if t.kind is not TokenKind.COMMENT
        )
        return " ".join(raw.split())

    # -- editing -----------------------------------------------------------

    def set(self, path: str, value: str) -> None:
        """Replace the value of an existing entry, touching nothing else.

        The entry's keyword, the whitespace between keyword and value, the
        terminating semicolon, any trailing comment, and every other byte in the
        file are left exactly as they were — so the resulting diff is one line
        (§12.2 step 2).

        Creating entries is deliberately absent: the only thing that needs to
        insert into a user's ``controlDict`` is the GUI-owned function-object
        fence (FR-S3), which lands with the run experience at M5 and has its own
        fencing and disclosure requirements (NFR-C3). A general-purpose insert
        would be the easy way to breach those without noticing.
        """
        node = self.find(path)
        if node is None:
            raise PathError(f"No such entry: {path!r}")
        if node.kind is not NodeKind.ENTRY:
            raise PathError(
                f"{path!r} is a {node.kind.value}, not a value entry; only value entries can be set"
            )

        replacement = value.strip()
        _reject_structural_characters(replacement, path)

        assert node.value_start is not None and node.value_end is not None
        new_tokens = (
            self._tokens[: node.value_start]
            + tokenize(replacement)
            + self._tokens[node.value_end :]
        )

        # Re-lex and re-parse from the rendered text rather than patching the tree
        # in place. Splicing invalidates every token index after the edit, and a
        # stale index is a silent corruption rather than a loud failure. Documents
        # are kilobytes, so correctness wins this trade easily.
        text = "".join(t.text for t in new_tokens)
        rebuilt = Document.parse(text)

        if rebuilt.get(path) != " ".join(replacement.split()):
            raise ValueError(
                f"Setting {path!r} to {value!r} would change the structure of the "
                "document. The value is probably unbalanced or contains a "
                "terminator."
            )

        self._text = rebuilt._text
        self._tokens = rebuilt._tokens
        self._root = rebuilt._root


_FORBIDDEN_IN_VALUE = {";": "a semicolon", "{": "a brace", "}": "a brace"}


def _reject_structural_characters(value: str, path: str) -> None:
    """Refuse a replacement value that would restructure the document.

    Checked before the edit rather than after, so the error names the character
    the caller supplied instead of describing a parse failure downstream.
    """
    for token in tokenize(value):
        if token.kind is TokenKind.SEMICOLON or (
            token.kind in (TokenKind.LBRACE, TokenKind.RBRACE)
        ):
            what = _FORBIDDEN_IN_VALUE[token.text]
            raise ValueError(f"Cannot set {path!r} to a value containing {what}: {value!r}")


def _split_path(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _decode_keyword(token: Token) -> str:
    if token.kind is TokenKind.STRING:
        return token.text[1:-1]
    return token.text


class _Parser:
    """Recursive-descent walk that locates entries and brackets everything else."""

    __slots__ = ("_i", "_text", "_tokens")

    def __init__(self, text: str, tokens: list[Token]) -> None:
        self._text = text
        self._tokens = tokens
        self._i = 0

    # -- helpers -----------------------------------------------------------

    def _skip_trivia(self) -> None:
        while self._i < len(self._tokens) and self._tokens[self._i].is_trivia:
            self._i += 1

    def _peek(self) -> Token | None:
        return self._tokens[self._i] if self._i < len(self._tokens) else None

    def _error(self, message: str, token: Token | None) -> ParseError:
        offset = token.start if token is not None else len(self._text)
        line, column = line_and_column(self._text, offset)
        return ParseError(message, line=line, column=column, text=token.text if token else "")

    # -- entry points ------------------------------------------------------

    def parse(self) -> Node:
        root = Node(kind=NodeKind.ROOT)
        root.body_start = 0
        root.children = self._parse_body(inside_braces=False)
        root.body_end = self._i

        self._skip_trivia()
        if (extra := self._peek()) is not None:
            raise self._error("Unexpected closing brace", extra)
        return root

    def _parse_body(self, *, inside_braces: bool) -> list[Node]:
        nodes: list[Node] = []
        after_directive = False
        while True:
            self._skip_trivia()
            token = self._peek()
            if token is None:
                if inside_braces:
                    raise self._error("Unclosed dictionary — missing '}'", None)
                return nodes

            if token.kind is TokenKind.RBRACE:
                if inside_braces:
                    return nodes
                return nodes  # caller reports it as unexpected

            node = self._parse_node(
                token, after_directive=after_directive, inside_braces=inside_braces
            )
            after_directive = token.kind is TokenKind.DIRECTIVE
            nodes.append(node)

    def _parse_node(self, token: Token, *, after_directive: bool, inside_braces: bool) -> Node:
        if token.kind is TokenKind.DIRECTIVE:
            return self._parse_directive()

        if token.kind is TokenKind.LBRACE:
            # A brace group with no keyword is legitimate in two places: as the
            # body of a keyword a directive produced (`#word "name" { ... }`), and
            # at file scope, where OpenFOAM tolerates a stray pair.
            #
            # Inside a dictionary it is not. This mirrors OpenFOAM's own two
            # fixtures exactly: `missed-ending3.dict` puts a stray `{}` at file
            # scope and upstream accepts it (the name records that its parser
            # *misses* the problem), while `fatal-ending4.dict` puts the same
            # construct inside a dictionary and upstream rejects it.
            #
            # Matching that split matters in both directions. Rejecting the file
            # scope form would refuse a case that runs perfectly well, breaching
            # FR-C2; accepting the nested form would mean accepting a dictionary
            # whose entries silently belong to nothing.
            if inside_braces and not after_directive:
                raise self._error("Unexpected '{' — no keyword before it", token)
            return self._parse_opaque_group(TokenKind.LBRACE, TokenKind.RBRACE)

        if token.kind is TokenKind.LPAREN:
            # A bare top-level list. Several tutorials ship these: a FoamFile
            # header followed by `( ... )` and nothing else — cloud injection
            # positions, for instance. They are valid OpenFOAM files that simply
            # are not dictionaries, and refusing them would make the case
            # un-openable over a file the user never intended to edit.
            return self._parse_opaque_group(TokenKind.LPAREN, TokenKind.RPAREN)

        if token.kind is TokenKind.VARIABLE:
            # Macro inclusion, e.g. `relaxationFactors { $relaxationFactors-SIMPLE }`.
            # The expansion's contents come from elsewhere in the file or from an
            # included one, so there is no value here to edit — only bytes to keep.
            return self._parse_macro_inclusion()

        if token.kind in (TokenKind.WORD, TokenKind.STRING):
            return self._parse_keyed()

        if token.kind is TokenKind.SEMICOLON:
            # A stray terminator. Real files contain them; OpenFOAM tolerates it.
            start = self._i
            self._i += 1
            return Node(kind=NodeKind.OPAQUE, body_start=start, body_end=self._i)

        raise self._error("Unexpected token", token)

    def _parse_keyed(self) -> Node:
        key_index = self._i
        key_token = self._tokens[key_index]
        self._i += 1
        self._skip_trivia()

        following = self._peek()
        if following is not None and following.kind is TokenKind.LBRACE:
            return self._parse_dict(key_index, key_token)
        return self._parse_entry(key_index, key_token)

    def _parse_dict(self, key_index: int, key_token: Token) -> Node:
        open_index = self._i
        self._i += 1  # consume '{'
        children = self._parse_body(inside_braces=True)

        closing = self._peek()
        if closing is None or closing.kind is not TokenKind.RBRACE:
            raise self._error("Unclosed dictionary — missing '}'", self._tokens[open_index])
        body_end = self._i
        self._i += 1  # consume '}'

        # A dictionary may be followed by an optional ';'. Consuming it here keeps
        # it from being parsed as a stray terminator at the parent level.
        self._consume_optional_semicolon()

        return Node(
            kind=NodeKind.DICT,
            keyword=_decode_keyword(key_token),
            keyword_raw=key_token.text,
            key_index=key_index,
            body_start=open_index + 1,
            body_end=body_end,
            children=children,
        )

    def _parse_entry(self, key_index: int, key_token: Token) -> Node:
        value_start = self._i
        depth = 0

        while self._i < len(self._tokens):
            token = self._tokens[self._i]
            if token.kind in OPENERS:
                depth += 1
            elif token.kind in CLOSERS:
                if depth == 0:
                    # Ran into the enclosing dictionary's '}' — the entry is
                    # missing its ';'. Fatal: guessing where the value ended could
                    # silently merge two entries.
                    raise self._error("Entry is missing its ';'", self._tokens[key_index])
                depth -= 1
            elif token.kind is TokenKind.SEMICOLON and depth == 0:
                break
            self._i += 1

        if self._i >= len(self._tokens):
            raise self._error("Entry is missing its ';'", self._tokens[key_index])

        value_end = self._i
        self._i += 1  # consume ';'

        # Trailing trivia belongs to the file's layout, not to the value, so it is
        # excluded from the editable span and therefore survives a `set`.
        while value_end > value_start and self._tokens[value_end - 1].is_trivia:
            value_end -= 1

        return Node(
            kind=NodeKind.ENTRY,
            keyword=_decode_keyword(key_token),
            keyword_raw=key_token.text,
            key_index=key_index,
            value_start=value_start,
            value_end=value_end,
        )

    def _parse_directive(self) -> Node:
        """Consume a directive and its argument as one opaque region.

        Directives are line-oriented unless they take a brace group. Both forms
        appear in the tutorial suite:

            #include "initialConditions"          -- no terminator
            #inputMode merge;                     -- terminated
            #ifeq $WM_PROJECT_VERSION plus        -- conditional, no terminator
            #message { text ${VAR:-unset} }       -- braced argument
            #codeStream { codeInclude #{ ... #}; }

        Conditional directives are *not* modelled as blocks. ``#if`` and its
        siblings each become their own opaque node and the entries between them
        parse normally as siblings, which is what a form editor needs: the entries
        remain visible and editable, and the conditionals around them are
        preserved untouched.
        """
        start = self._i
        self._i += 1  # consume the directive token

        # Look past trivia for a brace, but *rewind* if there is none. Skipping
        # trivia unconditionally would step over the newline that terminates a
        # line-oriented directive, so `#else` would swallow the entry beneath it —
        # and silently, because the bytes still round-trip. The entry would simply
        # vanish from the form editor while remaining in the file.
        after_directive = self._i
        self._skip_trivia()
        following = self._peek()
        if following is not None and following.kind is TokenKind.LBRACE:
            self._consume_balanced(TokenKind.LBRACE, TokenKind.RBRACE)
            self._consume_optional_semicolon()
            return Node(kind=NodeKind.OPAQUE, body_start=start, body_end=self._i)
        self._i = after_directive

        # Scan to a ';' at depth 0, stopping at end of line if none appears first.
        depth = 0
        while self._i < len(self._tokens):
            token = self._tokens[self._i]
            if token.kind in OPENERS:
                depth += 1
            elif token.kind in CLOSERS:
                if depth == 0:
                    break
                depth -= 1
            elif token.kind is TokenKind.SEMICOLON and depth == 0:
                self._i += 1
                break
            elif token.is_trivia and depth == 0 and "\n" in token.text:
                break
            self._i += 1

        return Node(kind=NodeKind.OPAQUE, body_start=start, body_end=self._i)

    def _parse_macro_inclusion(self) -> Node:
        """Consume a ``$variable`` used where an entry would be.

        Distinct from a ``$variable`` in *value* position, which is part of an
        ordinary entry and is scanned by :meth:`_parse_entry`.
        """
        start = self._i
        self._i += 1
        self._skip_trivia()

        following = self._peek()
        if following is not None and following.kind is TokenKind.LBRACE:
            self._consume_balanced(TokenKind.LBRACE, TokenKind.RBRACE)
        self._consume_optional_semicolon()
        return Node(kind=NodeKind.OPAQUE, body_start=start, body_end=self._i)

    def _parse_opaque_group(self, opener: TokenKind, closer: TokenKind) -> Node:
        start = self._i
        self._consume_balanced(opener, closer)
        self._consume_optional_semicolon()
        return Node(kind=NodeKind.OPAQUE, body_start=start, body_end=self._i)

    def _consume_balanced(self, opener: TokenKind, closer: TokenKind) -> None:
        opening = self._tokens[self._i]
        depth = 0
        while self._i < len(self._tokens):
            kind = self._tokens[self._i].kind
            if kind is opener:
                depth += 1
            elif kind is closer:
                depth -= 1
                if depth == 0:
                    self._i += 1
                    return
            self._i += 1
        raise self._error(f"Unclosed {opening.text!r} group", opening)

    def _consume_optional_semicolon(self) -> None:
        saved = self._i
        self._skip_trivia()
        token = self._peek()
        if token is not None and token.kind is TokenKind.SEMICOLON:
            self._i += 1
        else:
            self._i = saved
