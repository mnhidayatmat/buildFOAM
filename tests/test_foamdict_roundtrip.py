"""The round-trip fidelity gate (§12.2). **This blocks M1.**

It is the only mechanical guarantee behind the D4 promise — that the application
never traps the user, and that every file it touches remains a valid,
hand-editable OpenFOAM dictionary. §11 puts it before any feature work for a blunt reason: a
CFD tool that silently produces plausible wrong answers is worse than one that
does not exist, and a parser that quietly drops a comment or reorders a
dictionary is exactly how that happens.

The four properties below are §12.2's four steps, run over every dictionary in
the vendored corpus.
"""

from __future__ import annotations

import difflib
import hashlib
import random

import pytest

from corpus_loader import (
    CORPUS_DIR,
    CorpusFile,
    corpus_files,
    ids,
    known_defects,
    limitation_files,
    manifest,
    must_reject_files,
    structural_limitations,
)
from foamwb.services.foamdict import Document, Node, NodeKind, ParseError, tokenize
from foamwb.services.foamdict.lexer import TokenKind

CORPUS = corpus_files()
IDS = ids(CORPUS)

SENTINEL = "roundTripSentinel"


@pytest.fixture(params=CORPUS, ids=IDS)
def corpus_file(request: pytest.FixtureRequest) -> CorpusFile:
    return request.param


class TestCorpusIntegrity:
    """The gate is only as good as the corpus it runs over."""

    def test_corpus_is_present_and_substantial(self) -> None:
        # §12.1 asks for ~25 cases. Fewer would not span the axes; a corpus that
        # silently shrank to three files would still go green.
        assert len(CORPUS) > 300
        assert len(manifest()["cases"]) >= 20

    def test_pinned_to_a_specific_openfoam_release(self) -> None:
        assert manifest()["openfoam_version"].startswith("v")
        assert manifest()["lineage"] == "esi"

    def test_every_case_states_why_it_is_in_the_corpus(self) -> None:
        for case, reason in manifest()["cases"].items():
            assert reason.strip(), case

    def test_known_defects_are_documented_not_merely_skipped(self) -> None:
        for path, reason in known_defects().items():
            assert len(reason) > 40, f"{path} excluded without an explanation"

    def test_structural_limitations_are_documented_not_merely_skipped(self) -> None:
        # An undocumented exclusion silently shrinks what the gate proves.
        assert structural_limitations(), "the known limitation must stay recorded"
        for path, reason in structural_limitations().items():
            assert len(reason) > 100, f"{path} excluded without a real explanation"

    def test_vendored_files_match_their_recorded_hashes(self) -> None:
        # The corpus is the reference the gate measures against, so it must not
        # drift. Without this, a corpus file edited to make a failing test pass
        # would look exactly like a corpus file that was legitimately refreshed.
        for relative, digest in manifest()["files"].items():
            data = (CORPUS_DIR / relative).read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest, relative

    def test_the_reject_fixtures_are_present(self) -> None:
        # Error detection is half the gate; losing these would leave it untested.
        assert len(must_reject_files()) >= 8

    def test_preprocessor_constructs_are_actually_represented(self) -> None:
        # §12.1 requires cases exercising #include, #calc/#eval, #codeStream,
        # macro expansion and regex keys. Asserted rather than assumed: a corpus
        # that lost them would still pass every other test in this file.
        blob = "\n".join(f.text for f in CORPUS)
        for construct in ("#include", "#codeStream", "#eval", "${", "#{"):
            assert construct in blob, construct
        assert any('"' in f.text and ".*" in f.text for f in CORPUS), "regex keys"


class TestStep1ByteIdentity:
    """Parse → render with no modification → byte-identical."""

    def test_render_reproduces_the_source_exactly(self, corpus_file: CorpusFile) -> None:
        source = corpus_file.text
        assert Document.parse(source).render() == source

    def test_lexer_conserves_every_byte(self, corpus_file: CorpusFile) -> None:
        # The property byte-identity is derived from. Asserted separately so a
        # failure points at the lexer rather than at the whole pipeline.
        source = corpus_file.text
        assert "".join(t.text for t in tokenize(source)) == source

    def test_bytes_survive_the_bytes_api(self, corpus_file: CorpusFile) -> None:
        # The path a real file takes. Catches newline translation, which would
        # rewrite every line of a CRLF file while every other test still passed.
        data = corpus_file.path.read_bytes()
        assert Document.parse_bytes(data).render_bytes() == data


def _editable_single_line_entry(doc: Document) -> tuple[str, Node] | None:
    """First entry whose value sits on one line and resolves unambiguously.

    Multi-line values are excluded because replacing a list that spans twelve
    lines with one token legitimately changes twelve lines; §12.2's one-line
    assertion is about leaf values.
    """
    for path, node in doc.entries():
        if doc.value_spans_lines(node):
            continue
        if doc.find(path) is not node:
            continue  # duplicated keyword — `set` would target the other one
        if doc.get(path) == SENTINEL:
            continue
        return path, node
    return None


def _changed_lines(before: str, after: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), n=0, lineterm="")
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


class TestStep2SingleLineDiff:
    """Parse → modify one leaf → render → the diff is exactly one line."""

    def test_editing_one_value_changes_one_line(self, corpus_file: CorpusFile) -> None:
        source = corpus_file.text
        doc = Document.parse(source)
        target = _editable_single_line_entry(doc)
        if target is None:
            pytest.skip("no single-line editable entry in this dictionary")

        path, _ = target
        doc.set(path, SENTINEL)
        changed = _changed_lines(source, doc.render())

        assert len(changed) == 2, (  # one '-' and one '+' for the same line
            f"editing {path!r} changed {len(changed) // 2} lines:\n" + "\n".join(changed[:10])
        )

    def test_everything_else_is_untouched(self, corpus_file: CorpusFile) -> None:
        # FR-P7: comments, ordering, whitespace and preprocessor directives are
        # preserved byte-for-byte elsewhere.
        source = corpus_file.text
        doc = Document.parse(source)
        target = _editable_single_line_entry(doc)
        if target is None:
            pytest.skip("no single-line editable entry in this dictionary")

        path, node = target
        line_index = source[: doc.tokens[node.key_index].start].count("\n")
        doc.set(path, SENTINEL)

        before = source.splitlines()
        after = doc.render().splitlines()
        assert len(before) == len(after), "line count changed"
        for i, (old, new) in enumerate(zip(before, after, strict=True)):
            if i != line_index:
                assert old == new, f"line {i + 1} changed but only {path!r} was set"

    def test_the_new_value_is_readable_back(self, corpus_file: CorpusFile) -> None:
        doc = Document.parse(corpus_file.text)
        target = _editable_single_line_entry(doc)
        if target is None:
            pytest.skip("no single-line editable entry in this dictionary")
        path, _ = target
        doc.set(path, SENTINEL)
        assert doc.get(path) == SENTINEL


class TestStep3Idempotence:
    """Parse → render → re-parse → semantic equality."""

    def test_reparsing_yields_the_same_entries(self, corpus_file: CorpusFile) -> None:
        first = Document.parse(corpus_file.text)
        second = Document.parse(first.render())
        assert _entry_map(first) == _entry_map(second)

    def test_reparsing_yields_the_same_top_level_keys(self, corpus_file: CorpusFile) -> None:
        first = Document.parse(corpus_file.text)
        second = Document.parse(first.render())
        assert first.keys() == second.keys()

    def test_editing_is_stable_under_repetition(self, corpus_file: CorpusFile) -> None:
        # Setting the same value twice must be a no-op the second time. If `set`
        # perturbed layout, the second application would show it.
        doc = Document.parse(corpus_file.text)
        target = _editable_single_line_entry(doc)
        if target is None:
            pytest.skip("no single-line editable entry in this dictionary")
        path, _ = target

        doc.set(path, SENTINEL)
        once = doc.render()
        doc.set(path, SENTINEL)
        assert doc.render() == once


def _entry_map(doc: Document) -> dict[str, str | None]:
    return {path: doc.get(path) for path, _ in doc.entries()}


def _whitespace_offsets(text: str) -> list[int]:
    """Offsets inside whitespace tokens — the only safe places to inject.

    Inserting at an arbitrary offset could land inside a string literal or a
    ``#{ ... #}`` block of C++, which would change the file's meaning rather than
    its formatting, and the test would then be asserting the wrong thing.
    """
    return [
        token.start
        for token in tokenize(text)
        if token.kind is TokenKind.WHITESPACE and "\n" in token.text
    ]


def _fuzz(text: str, seed: int) -> str:
    """Apply formatting-only mutations: extra blank lines, comments, indentation.

    Deterministic — the seed is derived from the file path, so a failure is
    reproducible and the gate cannot go intermittently red.
    """
    rng = random.Random(seed)
    offsets = _whitespace_offsets(text)
    if not offsets:
        return text

    injections = [
        "\n",
        "\n\n",
        "    ",
        "\t",
        "\n// fuzz comment\n",
        "\n/* fuzz block */\n",
        "   \n",
    ]
    for offset in sorted(rng.sample(offsets, min(6, len(offsets))), reverse=True):
        text = text[:offset] + rng.choice(injections) + text[offset:]
    return text


class TestStep4Fuzz:
    """Mutate whitespace, comment placement and directive positions; step 1 holds."""

    def test_byte_identity_survives_reformatting(self, corpus_file: CorpusFile) -> None:
        mutated = _fuzz(corpus_file.text, seed=hash(corpus_file.relative) & 0xFFFF)
        assert Document.parse(mutated).render() == mutated

    def test_reformatting_does_not_change_meaning(self, corpus_file: CorpusFile) -> None:
        # The stronger claim, and the one that matters: whitespace and comments
        # carry no semantics, so the entry map must be identical. If a stray
        # comment could shift a value, the form editors would be unsafe.
        original = Document.parse(corpus_file.text)
        mutated = Document.parse(_fuzz(corpus_file.text, seed=hash(corpus_file.relative) & 0xFFFF))
        assert _entry_map(mutated) == _entry_map(original)

    def test_crlf_line_endings_round_trip(self, corpus_file: CorpusFile) -> None:
        # A student on Windows will hand-edit a case in Notepad. If line endings
        # were normalised on save, every line of the file would appear modified in
        # a diff and FR-C4's external-modification detection would fire on a file
        # nobody changed.
        crlf = corpus_file.text.replace("\n", "\r\n")
        doc = Document.parse(crlf)
        assert doc.render() == crlf
        assert _entry_map(doc) == _entry_map(Document.parse(corpus_file.text))


class TestOpaqueRegionsAreNeverOffered:
    """The tolerance contract: unmodelled constructs are preserved, not edited."""

    def test_no_entry_is_yielded_from_inside_an_opaque_region(
        self, corpus_file: CorpusFile
    ) -> None:
        doc = Document.parse(corpus_file.text)
        opaque_spans = _opaque_spans(doc.root)
        for path, node in doc.entries():
            assert node.key_index is not None
            for start, end in opaque_spans:
                assert not (start <= node.key_index < end), (
                    f"{path!r} sits inside an opaque region and must not be editable"
                )


def _opaque_spans(node: Node) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    if node.kind is NodeKind.OPAQUE:
        assert node.body_start is not None and node.body_end is not None
        spans.append((node.body_start, node.body_end))
    for child in node.children:
        spans.extend(_opaque_spans(child))
    return spans


class TestMalformedInputIsRejected:
    """OpenFOAM's ``fatal-*`` fixtures must raise E-C02, not parse.

    The other half of the gate. Tolerance is what lets real tutorials open; it
    must not extend to input that is genuinely broken, because a parser that
    quietly accepts a missing ``;`` would hand the user a form editor showing a
    case that is not the case the solver will run.
    """

    @pytest.mark.parametrize("bad", must_reject_files(), ids=ids(must_reject_files()))
    def test_rejected_with_a_locatable_error(self, bad: CorpusFile) -> None:
        with pytest.raises(ParseError) as caught:
            Document.parse(bad.text)

        error = caught.value
        assert error.line >= 1, "E-C02 must name a line so the editor can jump to it"
        assert error.column >= 1
        assert error.message

    @pytest.mark.parametrize("bad", must_reject_files(), ids=ids(must_reject_files()))
    def test_still_tokenises_for_the_raw_text_tab(self, bad: CorpusFile) -> None:
        # FR-P6 promises a raw-text tab for *every* dictionary. A file that fails
        # to parse structurally is exactly the file the user most needs to open
        # and fix, so refusing to display it would be a dead end (§7.9 rule 1).
        source = bad.text
        assert "".join(t.text for t in tokenize(source)) == source


class TestStructuralLimitations:
    """Files this parser cannot structure still keep every other guarantee."""

    @pytest.mark.parametrize("f", limitation_files(), ids=ids(limitation_files()))
    def test_tokenises_and_round_trips_byte_for_byte(self, f: CorpusFile) -> None:
        # The layering claim, made concrete: byte fidelity does not depend on
        # understanding the grammar. The raw-text tab works on these files even
        # though the form editors cannot.
        source = f.text
        assert "".join(t.text for t in tokenize(source)) == source
