"""Focused unit tests for FoamDict.

The corpus gate proves the parser handles real dictionaries; these prove it
handles the *specific constructs* correctly and fails correctly, on inputs small
enough to read. NFR-M2 sets an 80% line-coverage floor on this module because it
is one of the three where a silent defect corrupts user data.
"""

from __future__ import annotations

import pytest

from foamwb.services.foamdict import (
    Document,
    NodeKind,
    ParseError,
    PathError,
    TokenKind,
    tokenize,
)
from foamwb.services.foamdict.lexer import LexError, line_and_column

HEADER = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      testDict;
}
"""


def doc(body: str) -> Document:
    return Document.parse(HEADER + body)


class TestByteConservation:
    @pytest.mark.parametrize(
        "source",
        [
            "",
            "   ",
            "\n\n\n",
            "a 1;",
            "a 1;\r\n",
            "// only a comment",
            "/* block */",
            "key éü中文;",  # NFR-C4: Unicode survives
            "key 'single quotes are just word characters';",
            "\t\v\f mixed \r\n whitespace \t;",
        ],
    )
    def test_every_byte_is_preserved(self, source: str) -> None:
        assert "".join(t.text for t in tokenize(source)) == source

    def test_unrecognised_characters_do_not_raise(self) -> None:
        # A stray byte must still open: refusing would strand the user with no
        # in-app way to fix it, and FR-P6 promises a raw-text tab for every file.
        # A lone '$' is the reachable case — it starts no valid variable name.
        tokens = tokenize("key $ value;")
        assert TokenKind.UNKNOWN in {t.kind for t in tokens}
        assert "".join(t.text for t in tokens) == "key $ value;"

    def test_control_characters_are_absorbed_into_words(self) -> None:
        assert "".join(t.text for t in tokenize("key \x01 value;")) == "key \x01 value;"


class TestLexerConstructs:
    def _kinds(self, source: str) -> list[TokenKind]:
        return [t.kind for t in tokenize(source) if not t.is_trivia]

    def test_line_and_block_comments(self) -> None:
        kinds = [t.kind for t in tokenize("// a\n/* b */") if t.kind is not TokenKind.WHITESPACE]
        assert kinds == [TokenKind.COMMENT, TokenKind.COMMENT]

    def test_slash_in_a_path_is_not_a_comment(self) -> None:
        # `constant/polyMesh` is an ordinary word; only `//` and `/*` start comments.
        assert self._kinds("$FOAM_CASE/system") == [TokenKind.VARIABLE]
        assert self._kinds("a constant/polyMesh;") == [
            TokenKind.WORD,
            TokenKind.WORD,
            TokenKind.SEMICOLON,
        ]

    def test_regex_key_is_a_string(self) -> None:
        assert self._kinds('".*Wall"') == [TokenKind.STRING]

    def test_escaped_quote_inside_a_string(self) -> None:
        assert self._kinds(r'"a \" b"') == [TokenKind.STRING]

    def test_verbatim_block_is_one_opaque_token(self) -> None:
        # Its contents are C++ and must never be read as dictionary syntax — the
        # `#include` and the `;` inside are not ours to interpret.
        tokens = [t for t in tokenize('#{ #include "x.H"; a; #}') if not t.is_trivia]
        assert len(tokens) == 1
        assert tokens[0].kind is TokenKind.VERBATIM

    @pytest.mark.parametrize(
        "source", ["#include", "#codeStream", "#eval", "# include", "#\tinclude"]
    )
    def test_directives_with_and_without_a_space(self, source: str) -> None:
        assert self._kinds(source) == [TokenKind.DIRECTIVE]

    @pytest.mark.parametrize(
        "source",
        ["$var", "${var}", "${var:-default}", "${_${FOAM_EXECUTABLE}}", "$a-SIMPLE"],
    )
    def test_variable_forms(self, source: str) -> None:
        assert self._kinds(source) == [TokenKind.VARIABLE]

    @pytest.mark.parametrize("source", ['"unterminated', "/* unterminated", "#{ unterminated"])
    def test_unterminated_constructs_raise(self, source: str) -> None:
        with pytest.raises(LexError):
            tokenize(source)

    def test_token_offsets_are_contiguous(self) -> None:
        source = "a 1;\n// c\nb (2 3);"
        offset = 0
        for token in tokenize(source):
            assert token.start == offset
            offset = token.end
        assert offset == len(source)

    def test_line_and_column_are_one_based(self) -> None:
        assert line_and_column("abc\ndef", 0) == (1, 1)
        assert line_and_column("abc\ndef", 4) == (2, 1)
        assert line_and_column("abc\ndef", 6) == (2, 3)


class TestStructure:
    def test_reads_scalar_entries(self) -> None:
        d = doc("application simpleFoam;\nendTime 1000;\n")
        assert d.get("application") == "simpleFoam"
        assert d.get("endTime") == "1000"

    def test_reads_nested_dictionaries(self) -> None:
        d = doc("boundaryField { inlet { type fixedValue; value uniform 1; } }")
        assert d.get("boundaryField/inlet/type") == "fixedValue"
        assert d.keys("boundaryField") == ["inlet"]

    def test_regex_keys_resolve_without_their_quotes(self) -> None:
        d = doc('boundaryField { ".*Wall" { type noSlip; } }')
        assert d.get("boundaryField/.*Wall/type") == "noSlip"
        node = d.find("boundaryField/.*Wall")
        assert node is not None and node.keyword_raw == '".*Wall"'

    def test_list_values_are_normalised_not_reformatted(self) -> None:
        d = doc("vertices\n(\n    (0 0 0)\n    (1 0 0)\n);\n")
        assert d.get("vertices") == "( (0 0 0) (1 0 0) )"
        assert d.render() == HEADER + "vertices\n(\n    (0 0 0)\n    (1 0 0)\n);\n"

    def test_dimensions_bracket_syntax(self) -> None:
        assert doc("dimensions [0 1 -1 0 0 0 0];").get("dimensions") == "[0 1 -1 0 0 0 0]"

    def test_semicolon_inside_a_value_does_not_terminate_early(self) -> None:
        d = doc("momentOfInertia #codeStream { code #{ a; b; #}; };\nnext 1;\n")
        assert d.get("next") == "1"

    def test_duplicate_keyword_takes_the_last(self) -> None:
        # Matches OpenFOAM, so the form never shows a value the solver ignores.
        assert doc("a 1;\na 2;\n").get("a") == "2"

    def test_comments_are_not_part_of_a_value(self) -> None:
        assert doc("blocks ( hex /* corner */ (0 1) );").get("blocks") == "( hex (0 1) )"

    def test_missing_path_returns_none(self) -> None:
        assert doc("a 1;").get("nope") is None
        assert not doc("a 1;").has("nope")

    def test_a_dictionary_is_not_a_value(self) -> None:
        assert doc("d { a 1; }").get("d") is None

    def test_keys_on_a_missing_dictionary_raises(self) -> None:
        with pytest.raises(PathError):
            doc("a 1;").keys("nope")


class TestOpaqueRegions:
    def test_directives_are_not_reported_as_keys(self) -> None:
        # A caller enumerating settings must never see `#include` as one.
        d = doc('#include "initialConditions"\na 1;\n')
        assert d.keys() == ["FoamFile", "a"]

    def test_conditional_blocks_leave_their_entries_editable(self) -> None:
        # The entries inside a conditional are real settings; only the #if/#else
        # lines themselves are opaque.
        d = doc("#ifeq 1 1\nversionNo 5;\n#else\nversionNo 6;\n#endif\n")
        assert d.get("versionNo") == "6"
        assert d.render().count("#else") == 1

    def test_macro_inclusion_as_a_body_is_opaque(self) -> None:
        d = doc("relaxationFactors { $relaxationFactors-SIMPLE }\nafter 1;\n")
        assert d.get("after") == "1"

    def test_bare_top_level_list_is_accepted(self) -> None:
        # Cloud position files: a FoamFile header then nothing but a list.
        d = doc("(\n    (0 0 0)\n    (1 1 1)\n)\n")
        assert d.keys() == ["FoamFile"]

    @pytest.mark.parametrize(
        "source",
        [
            '#include "a"\n',
            '#include "a";\n',
            "#inputMode merge;\n",
            "#remove key\n",
            "#message { text here }\n",
        ],
    )
    def test_directive_forms_round_trip(self, source: str) -> None:
        d = doc(source + "after 1;\n")
        assert d.get("after") == "1"
        assert d.render() == HEADER + source + "after 1;\n"


class TestSet:
    def test_replaces_only_the_value(self) -> None:
        d = doc("a     1;   // keep this comment\n")
        d.set("a", "2")
        assert d.render() == HEADER + "a     2;   // keep this comment\n"

    def test_preserves_the_gap_between_keyword_and_value(self) -> None:
        # Column alignment is the author's; a form save must not restyle the file.
        d = doc("application     simpleFoam;\n")
        d.set("application", "icoFoam")
        assert d.render() == HEADER + "application     icoFoam;\n"

    def test_can_set_a_nested_entry(self) -> None:
        d = doc("boundaryField { inlet { type fixedValue; } }")
        d.set("boundaryField/inlet/type", "zeroGradient")
        assert d.get("boundaryField/inlet/type") == "zeroGradient"

    def test_can_set_a_compound_value(self) -> None:
        d = doc("internalField uniform (0 0 0);\n")
        d.set("internalField", "uniform (1 2 3)")
        assert d.render() == HEADER + "internalField uniform (1 2 3);\n"

    def test_missing_entry_raises(self) -> None:
        with pytest.raises(PathError, match="No such entry"):
            doc("a 1;").set("b", "2")

    def test_setting_a_dictionary_raises(self) -> None:
        with pytest.raises(PathError, match="not a value entry"):
            doc("d { a 1; }").set("d", "2")

    @pytest.mark.parametrize("bad", ["1; b 2", "{ a 1; }", "1 }"])
    def test_values_that_would_restructure_the_document_are_refused(self, bad: str) -> None:
        # Checked before the edit, so the message names what the caller supplied
        # rather than describing a parse failure further downstream.
        with pytest.raises(ValueError, match="Cannot set"):
            doc("a 1;").set("a", bad)

    def test_a_refused_set_leaves_the_document_untouched(self) -> None:
        d = doc("a 1;\n")
        before = d.render()
        with pytest.raises(ValueError):
            d.set("a", "1; b 2")
        assert d.render() == before


class TestParseErrors:
    @pytest.mark.parametrize(
        ("source", "fragment"),
        [
            ("d { a 1;", "Unclosed dictionary"),
            ("d { a missing ending }", "missing its ';'"),
            ("a 1;\n}", "Unexpected closing brace"),
            ("d { { a 1; } }", "no keyword before it"),
            ('a "unterminated;', "Unterminated string"),
        ],
    )
    def test_malformed_input_is_rejected_with_a_reason(self, source: str, fragment: str) -> None:
        with pytest.raises(ParseError, match=fragment):
            Document.parse(source)

    def test_error_carries_a_location_for_the_editor(self) -> None:
        # E-C02 must put the cursor on the problem, not report "invalid syntax".
        with pytest.raises(ParseError) as caught:
            Document.parse("a 1;\nb 2;\nc { d 3;")
        assert caught.value.line == 3
        assert caught.value.column >= 1

    def test_non_utf8_bytes_are_reported_as_a_parse_error(self) -> None:
        with pytest.raises(ParseError, match="not valid utf-8"):
            Document.parse_bytes(b"a \xff\xfe;")


class TestEntries:
    def test_yields_paths_depth_first_in_file_order(self) -> None:
        d = doc("a 1;\nd { b 2; e { c 3; } }\n")
        assert [p for p, _ in d.entries()] == [
            "FoamFile/version",
            "FoamFile/format",
            "FoamFile/class",
            "FoamFile/object",
            "a",
            "d/b",
            "d/e/c",
        ]

    def test_only_value_entries_are_yielded(self) -> None:
        d = doc("d { a 1; }")
        assert all(node.kind is NodeKind.ENTRY for _, node in d.entries())

    def test_does_not_descend_into_embedded_code(self) -> None:
        # The entry itself is real and editable; what must not appear is `code`,
        # which lives inside the #codeStream block. That is C++, and offering it
        # for editing would be offering to corrupt the case.
        d = doc("m #codeStream { code #{ int x; #}; };\n")
        paths = [p for p, _ in d.entries() if not p.startswith("FoamFile")]
        assert paths == ["m"]
        assert not any("code" in p for p in paths)

    def test_value_spans_lines_detects_multiline_values(self) -> None:
        d = doc("a 1;\nv\n(\n 0\n);\n")
        by_path = dict(d.entries())
        assert not d.value_spans_lines(by_path["a"])
        assert d.value_spans_lines(by_path["v"])
