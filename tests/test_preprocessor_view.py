"""The Preprocessor view and its editors (§7.4, FR-P1, FR-P6, FR-P7, DEC-07)."""

from __future__ import annotations

import pytest

from foamwb.services.case import CaseService
from foamwb.services.foamdict import Document
from foamwb.services.schema import load_schema
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT
from foamwb.ui.views.preprocessor import PreprocessorView
from foamwb.ui.widgets.form_editor import FormEditor
from foamwb.ui.widgets.text_editor import TextEditor
from test_preprocessor import CONTROL_DICT, make_case


@pytest.fixture
def labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.preprocessor_strings()}


@pytest.fixture
def view(qtbot, labels) -> PreprocessorView:
    widget = PreprocessorView(LIGHT, labels)
    qtbot.addWidget(widget)
    return widget


class TestTextEditor:
    """FR-P6 — a raw-text tab for every dictionary."""

    def _editor(self, qtbot, labels) -> TextEditor:
        editor = TextEditor(LIGHT, labels)
        qtbot.addWidget(editor)
        editor.set_content(CONTROL_DICT.encode())
        return editor

    def test_loads_a_dictionary_verbatim(self, qtbot, labels) -> None:
        assert self._editor(qtbot, labels).text == CONTROL_DICT

    def test_saving_is_disabled_until_something_changes(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels)
        assert not editor.can_save
        editor.set_text(CONTROL_DICT + "\nlibs (x);\n")
        assert editor.can_save

    def test_a_valid_edit_saves_exactly_what_is_shown(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels)
        saved: list[bytes] = []
        editor.saved.connect(saved.append)
        editor.set_text(CONTROL_DICT.replace("endTime         0.5;", "endTime         2;"))
        assert editor.save()
        assert saved[0] == editor.content

    def test_invalid_syntax_blocks_the_save(self, qtbot, labels) -> None:
        # FR-P6's acceptance criterion. Writing a file the parser cannot read
        # would leave the case broken *and* unopenable in the application that
        # broke it.
        editor = self._editor(qtbot, labels)
        saved: list[bytes] = []
        editor.saved.connect(saved.append)
        editor.set_text(CONTROL_DICT + "\nbroken {\n")
        assert not editor.save()
        assert saved == []

    def test_a_blocked_save_reports_the_line(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels)
        # A stray closing brace, which is an error on the line it appears on.
        # `b wrong here` would *not* do: a multi-word value is legal, and the
        # parser is right to accept it.
        editor.set_text("a 1;\nb } 2;\nc 3;\n")
        editor.save()
        assert "line" in editor.status_text.lower()
        assert "2" in editor.status_text

    def test_a_blocked_save_moves_the_cursor_to_the_problem(self, qtbot, labels) -> None:
        # The value of a line-accurate error is arriving at the line; making the
        # user scroll to it themselves wastes the accuracy.
        editor = self._editor(qtbot, labels)
        editor.set_text("a 1;\nb } 2;\nc 3;\n")
        editor.save()
        assert editor.cursor_line == 2

    def test_revert_restores_the_original(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels)
        editor.set_text("nonsense")
        editor.revert()
        assert editor.text == CONTROL_DICT
        assert not editor.can_save

    def test_any_file_can_be_opened_even_if_it_does_not_parse(self, qtbot, labels) -> None:
        # FR-P6 says *every* dictionary. The file a user most needs to open is
        # the broken one.
        editor = TextEditor(LIGHT, labels)
        qtbot.addWidget(editor)
        editor.set_content(b"boundaryField {\n")
        assert editor.text == "boundaryField {\n"
        assert editor.validate() is not None


class TestFormEditor:
    """FR-P1 and FR-P7."""

    def _editor(self, qtbot, labels, source: str = CONTROL_DICT) -> FormEditor:
        editor = FormEditor(LIGHT, labels)
        qtbot.addWidget(editor)
        editor.set_document(load_schema("controlDict"), Document.parse(source))
        return editor

    def test_renders_the_schema_fields(self, qtbot, labels) -> None:
        assert "application" in self._editor(qtbot, labels).keys

    def test_inapplicable_fields_are_not_offered(self, qtbot, labels) -> None:
        # maxCo means nothing with adjustTimeStep off; offering it would invite
        # an edit with no effect.
        assert "maxCo" not in self._editor(qtbot, labels).keys

    def test_a_dependent_field_appears_when_it_applies(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels, CONTROL_DICT + "adjustTimeStep yes;\nmaxCo 0.9;\n")
        assert "maxCo" in editor.keys

    def test_validation_runs_on_entry(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels)
        editor.set_value("deltaT", "-1")
        assert "greater than 0" in editor.error_of("deltaT")
        assert not editor.can_save

    def test_a_valid_edit_enables_saving(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels)
        editor.set_value("endTime", "2")
        assert editor.can_save
        assert editor.error_of("endTime") == ""

    def test_saving_changes_only_the_edited_entry(self, qtbot, labels) -> None:
        # FR-P7, and the guarantee that makes forms and the text tab safe
        # together (DEC-07).
        editor = self._editor(qtbot, labels)
        saved: list[bytes] = []
        editor.saved.connect(saved.append)
        editor.set_value("endTime", "2")
        assert editor.save()

        before, after = CONTROL_DICT.splitlines(), saved[0].decode().splitlines()
        assert len(before) == len(after)
        differing = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        assert len(differing) == 1
        assert "endTime" in after[differing[0]]

    def test_an_unchanged_boolean_is_not_rewritten(self, qtbot, labels) -> None:
        # A checkbox cannot report which spelling the file used, so comparing
        # strings would make every boolean look edited — and saving one field
        # would silently convert every other boolean in the file.
        source = CONTROL_DICT + "runTimeModifiable true;\nwriteCompression off;\n"
        editor = self._editor(qtbot, labels, source)
        editor.set_value("endTime", "2")
        assert set(editor.changes) == {"endTime"}

    def test_a_genuinely_changed_boolean_is_written(self, qtbot, labels) -> None:
        source = CONTROL_DICT + "runTimeModifiable true;\n"
        editor = self._editor(qtbot, labels, source)
        editor.set_value("runTimeModifiable", "no")
        assert "runTimeModifiable" in editor.changes

    def test_a_no_op_save_writes_nothing(self, qtbot, labels) -> None:
        editor = self._editor(qtbot, labels)
        assert editor.changes == {}
        assert not editor.save()

    def test_unknown_keys_are_named_not_hidden(self, qtbot, labels) -> None:
        # §5.4: preserved and shown in the raw-text tab. A user who cannot find
        # `functions` should be told where it is, not left wondering.
        editor = self._editor(qtbot, labels, CONTROL_DICT + "functions { }\n")
        assert "functions" in editor.unknown_text

    def test_an_out_of_schema_enum_value_is_shown_not_replaced(self, qtbot, labels) -> None:
        # Silently substituting the first legal value would change the case
        # without the user asking.
        source = CONTROL_DICT.replace("writeControl    timeStep;", "writeControl    odd;")
        editor = self._editor(qtbot, labels, source)
        assert editor.value_of("writeControl") == "odd"


class TestPreprocessorView:
    """§7.4's three regions."""

    def test_lists_the_real_file_tree(self, view, tmp_path) -> None:
        # Real filenames: a user told their case contains system/controlDict must
        # find that file on disk under that name.
        view.set_case(CaseService().open(make_case(tmp_path)))
        names = [p.name for p in view.tree_files]
        assert "controlDict" in names
        assert "boundary" in names

    def test_opens_on_a_dictionary_the_form_can_edit(self, view, tmp_path) -> None:
        # Otherwise a case opens on constant/polyMesh/boundary, which is
        # generated data and the least useful thing to land on.
        view.set_case(CaseService().open(make_case(tmp_path)))
        assert view.current_file.name == "controlDict"
        assert view.form_available

    def test_a_file_with_no_schema_still_opens_in_the_text_tab(self, view, tmp_path) -> None:
        # DEC-07 and FR-P6: every dictionary is editable as text.
        case = make_case(tmp_path)
        view.set_case(CaseService().open(case))
        view.open_file(case / "constant" / "polyMesh" / "boundary")
        assert not view.form_available
        assert "movingWall" in view.text.text

    def test_the_validation_panel_lists_findings(self, view, tmp_path) -> None:
        case = make_case(tmp_path, fields={"p": {"movingWall": "zeroGradient"}})
        view.set_case(CaseService().open(case))
        assert view.finding_count > 0
        assert "stop a run" in view.summary_text

    def test_a_clean_case_says_so(self, view, tmp_path) -> None:
        view.set_case(CaseService().open(make_case(tmp_path)))
        assert view.finding_count == 0
        assert "No problems" in view.summary_text

    def test_activating_a_finding_opens_its_file(self, view, tmp_path) -> None:
        # §7.4: each finding is clickable to the offending line.
        case = make_case(tmp_path, fields={"p": {"movingWall": "zeroGradient"}})
        view.set_case(CaseService().open(case))
        view.activate_finding(0)
        assert view.current_file.name == "p"

    def test_saving_through_the_form_writes_the_file(self, view, tmp_path) -> None:
        case = make_case(tmp_path)
        view.set_case(CaseService().open(case))
        view.form.set_value("endTime", "3")
        view.form.save()
        assert "endTime         3;" in (case / "system" / "controlDict").read_text()

    def test_saving_re_runs_validation(self, view, tmp_path) -> None:
        # A panel that could drift from the files beside it would be believed.
        case = make_case(tmp_path, fields={"p": {"movingWall": "zeroGradient"}})
        view.set_case(CaseService().open(case))
        assert view.finding_count > 0

        target = case / "0" / "p"
        text = target.read_text().replace(
            "    movingWall\n    {\n        type            zeroGradient;\n    }",
            "    movingWall\n    {\n        type            zeroGradient;\n    }\n"
            "    fixedWalls\n    {\n        type            zeroGradient;\n    }\n"
            "    frontAndBack\n    {\n        type            empty;\n    }",
        )
        view.open_file(target)
        view.text.set_text(text)
        view.text.save()
        assert view.finding_count == 0

    def test_the_bulk_action_updates_every_patch_of_a_type(self, view, tmp_path) -> None:
        # §7.4: "because that is what the work actually is".
        case = make_case(tmp_path)
        view.set_case(CaseService().open(case))
        view.matrix.request_bulk("wall", "U", "slip")

        document = Document.parse_bytes((case / "0" / "U").read_bytes())
        assert document.get("boundaryField/movingWall/type") == "slip"
        assert document.get("boundaryField/fixedWalls/type") == "slip"
        # The constrained patch is untouched: its condition is dictated by the
        # geometry, and the bulk action targets one patch type at a time.
        assert document.get("boundaryField/frontAndBack/type") == "empty"

    def test_the_bulk_action_preserves_the_rest_of_the_file(self, view, tmp_path) -> None:
        case = make_case(tmp_path)
        view.set_case(CaseService().open(case))
        before = (case / "0" / "U").read_text().splitlines()
        view.matrix.request_bulk("wall", "U", "slip")
        after = (case / "0" / "U").read_text().splitlines()
        assert len(before) == len(after)
        assert sum(1 for a, b in zip(before, after, strict=True) if a != b) == 2

    def test_an_unmeshed_case_says_the_mesh_is_needed(self, view, tmp_path) -> None:
        case = make_case(tmp_path)
        (case / "constant" / "polyMesh" / "boundary").unlink()
        view.set_case(CaseService().open(case))
        assert "mesh" in view.matrix.notice_text.lower()
        assert not view.matrix.bulk_visible


class TestRoundTripAfterFormEdits:
    """FR-P7 over the corpus, not just one fixture."""

    def test_a_form_save_leaves_every_other_byte_alone(self, qtbot, labels) -> None:
        # The corpus dictionaries carry comments, banners and directives that a
        # naive editor would flatten. Editing one value must move one line.
        from corpus_loader import corpus_files

        schema = load_schema("controlDict")
        checked = 0
        for corpus_file in corpus_files():
            if not corpus_file.relative.endswith("system/controlDict"):
                continue
            document = Document.parse(corpus_file.text)

            editor = FormEditor(LIGHT, labels)
            qtbot.addWidget(editor)
            editor.set_document(schema, document)
            if "endTime" not in editor.keys:
                # One corpus case uses `stopAt nextWrite`, so endTime does not
                # apply and the form correctly does not offer it.
                continue
            editor.set_value("endTime", "12345")

            saved: list[bytes] = []
            editor.saved.connect(saved.append)
            assert editor.save()

            before = corpus_file.text.splitlines()
            after = saved[0].decode().splitlines()
            assert len(before) == len(after), corpus_file.relative
            differing = sum(1 for a, b in zip(before, after, strict=True) if a != b)
            assert differing == 1, f"{corpus_file.relative} changed {differing} lines"
            checked += 1

        assert checked > 15
