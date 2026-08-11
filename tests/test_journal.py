"""NFR-R3 — unsaved edits survive a crash.

The property under test is not "a file gets written". It is that recovery is
*safe*: it never overwrites something newer, never resurrects a buffer the user
abandoned, and never leaves debris in the user's case.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foamwb.services.journal import JournalEntry, JournalService


@pytest.fixture
def case(tmp_path) -> Path:
    root = tmp_path / "cavity"
    (root / "system").mkdir(parents=True)
    (root / "system" / "controlDict").write_text("application icoFoam;\nendTime 0.5;\n")
    return root


@pytest.fixture
def journal(tmp_path) -> JournalService:
    return JournalService(tmp_path / "journal")


class TestTheJournalStaysOutOfTheCase:
    """§5.1 — opening someone else's case must not modify it."""

    def test_recording_writes_nothing_into_the_case(self, journal, case) -> None:
        before = set(case.rglob("*"))
        journal.record(case, "system/controlDict", "edited")
        assert set(case.rglob("*")) == before

    def test_the_users_file_is_untouched(self, journal, case) -> None:
        original = (case / "system" / "controlDict").read_text()
        journal.record(case, "system/controlDict", "something else entirely")
        assert (case / "system" / "controlDict").read_text() == original

    def test_it_lives_in_the_application_directory(self, journal, tmp_path, case) -> None:
        journal.record(case, "system/controlDict", "edited")
        assert list((tmp_path / "journal").glob("*.json"))


class TestRecovery:
    def test_an_unsaved_buffer_comes_back(self, journal, case) -> None:
        journal.record(case, "system/controlDict", "application icoFoam;\nendTime 99;\n")
        recovery = journal.recoveries(case)[0]
        assert recovery.safe
        assert "endTime 99" in recovery.entry.content

    def test_a_file_changed_underneath_is_a_conflict_not_a_write(self, journal, case) -> None:
        """Overwriting a newer file with an older buffer is data loss dressed
        as recovery."""
        journal.record(case, "system/controlDict", "endTime 99;\n")
        (case / "system" / "controlDict").write_text("endTime 7;\n")

        recovery = journal.recoveries(case)[0]
        assert recovery.conflicted
        assert not recovery.safe

    def test_a_buffer_already_on_disk_is_dropped_silently(self, journal, case) -> None:
        """Offering a recovery with nothing to recover trains the user to
        dismiss the dialog."""
        text = "application icoFoam;\nendTime 42;\n"
        journal.record(case, "system/controlDict", text)
        (case / "system" / "controlDict").write_text(text)
        assert journal.recoveries(case) == []

    def test_a_missing_file_is_reported_as_missing(self, journal, case) -> None:
        journal.record(case, "system/controlDict", "edited")
        (case / "system" / "controlDict").unlink()
        recovery = journal.recoveries(case)[0]
        assert recovery.missing
        assert not recovery.safe

    def test_recovery_is_never_applied_automatically(self, journal, case) -> None:
        """The service offers; the user decides. Nothing here writes."""
        journal.record(case, "system/controlDict", "endTime 99;\n")
        journal.recoveries(case)
        assert "endTime 0.5" in (case / "system" / "controlDict").read_text()

    def test_entries_are_scoped_to_their_case(self, journal, case, tmp_path) -> None:
        other = tmp_path / "other"
        (other / "system").mkdir(parents=True)
        (other / "system" / "controlDict").write_text("x")
        journal.record(case, "system/controlDict", "a")
        journal.record(other, "system/controlDict", "b")
        assert len(journal.entries(case)) == 1
        assert len(journal.entries()) == 2


class TestForgetting:
    def test_saving_drops_the_entry(self, journal, case) -> None:
        journal.record(case, "system/controlDict", "edited")
        journal.forget(case, "system/controlDict")
        assert journal.entries(case) == []

    def test_forgetting_something_absent_is_safe(self, journal, case) -> None:
        journal.forget(case, "system/nothing")

    def test_a_whole_case_can_be_dropped(self, journal, case) -> None:
        journal.record(case, "system/controlDict", "a")
        journal.record(case, "system/fvSchemes", "b")
        assert journal.forget_case(case) == 2
        assert journal.entries(case) == []


class TestDamagedJournals:
    """A journal that cannot be trusted must not be offered."""

    def test_a_truncated_entry_is_discarded(self, journal, tmp_path, case) -> None:
        (tmp_path / "journal").mkdir(parents=True, exist_ok=True)
        (tmp_path / "journal" / "junk.json").write_text("{ truncated")
        assert journal.entries() == []

    def test_a_non_object_entry_is_discarded(self, journal, tmp_path) -> None:
        (tmp_path / "journal").mkdir(parents=True, exist_ok=True)
        (tmp_path / "journal" / "list.json").write_text("[]")
        assert journal.entries() == []

    def test_an_entry_with_no_file_is_discarded(self, journal, tmp_path) -> None:
        (tmp_path / "journal").mkdir(parents=True, exist_ok=True)
        (tmp_path / "journal" / "x.json").write_text(json.dumps({"case": "/tmp", "content": "x"}))
        assert journal.entries() == []

    def test_the_write_is_atomic(self, journal, tmp_path, case) -> None:
        """A half-written journal would be offered and would restore a truncated
        file — worse than having none."""
        journal.record(case, "system/controlDict", "edited")
        names = {p.name for p in (tmp_path / "journal").iterdir()}
        assert not any(n.endswith(".tmp") for n in names)

    def test_journalling_never_stops_the_user_editing(self, tmp_path, case) -> None:
        """A disk that cannot take the journal is degraded, not broken."""
        unwritable = JournalService(tmp_path / "nope" / "deep")
        (tmp_path / "nope").write_text("a file, not a directory")
        assert unwritable.record(case, "system/controlDict", "edited") is False


class TestTheEditorRecordsAndClears:
    def _editor(self, qtbot, tmp_path):
        from foamwb.ui import strings
        from foamwb.ui.theme import LIGHT
        from foamwb.ui.widgets.text_editor import TextEditor

        editor = TextEditor(LIGHT, {**strings.shell_strings(), **strings.preprocessor_strings()})
        qtbot.addWidget(editor)
        editor._journal = JournalService(tmp_path / "journal")
        return editor

    def test_a_modified_buffer_is_journalled(self, qtbot, tmp_path, case) -> None:
        editor = self._editor(qtbot, tmp_path)
        editor.set_journal_target(case, "system/controlDict")
        editor.set_content(b"application icoFoam;\n")
        editor._view.setPlainText("application icoFoam;\nendTime 99;\n")
        editor.flush_journal()
        assert editor._journal.recoveries(case)

    def test_saving_clears_it(self, qtbot, tmp_path, case) -> None:
        editor = self._editor(qtbot, tmp_path)
        editor.set_journal_target(case, "system/controlDict")
        editor.set_content(b"application icoFoam;\n")
        editor._view.setPlainText("application icoFoam;\nendTime 99;\n")
        editor.flush_journal()
        assert editor.save()
        assert editor._journal.entries(case) == []

    def test_reverting_clears_it(self, qtbot, tmp_path, case) -> None:
        editor = self._editor(qtbot, tmp_path)
        editor.set_journal_target(case, "system/controlDict")
        editor.set_content(b"application icoFoam;\n")
        editor._view.setPlainText("application icoFoam;\nendTime 99;\n")
        editor.flush_journal()
        editor.revert()
        assert editor._journal.entries(case) == []

    def test_a_refused_save_keeps_the_entry(self, qtbot, tmp_path, case) -> None:
        """The window where writing the file is what fails is exactly when the
        recovery is needed."""
        editor = self._editor(qtbot, tmp_path)
        editor.set_journal_target(case, "system/controlDict")
        editor.set_content(b"application icoFoam;\n")
        editor._view.setPlainText("application icoFoam;\n{ unclosed")
        editor.flush_journal()
        assert not editor.save()
        assert editor._journal.entries(case)

    def test_a_buffer_with_no_target_is_not_journalled(self, qtbot, tmp_path) -> None:
        """A scratch buffer has no file to recover into."""
        editor = self._editor(qtbot, tmp_path)
        editor.set_journal_target(None)
        editor.set_content(b"x")
        editor._view.setPlainText("changed")
        editor.flush_journal()
        assert editor._journal.entries() == []

    def test_typing_does_not_write_per_keystroke(self, qtbot, tmp_path, case) -> None:
        """A disk write in the typing path would be felt at NFR-P3's rates."""
        editor = self._editor(qtbot, tmp_path)
        editor.set_journal_target(case, "system/controlDict")
        editor.set_content(b"application icoFoam;\n")
        for i in range(20):
            editor._view.setPlainText(f"application icoFoam;\nendTime {i};\n")
        assert editor._journal.entries(case) == []


class TestTheEntryItself:
    def test_it_carries_the_baseline_it_was_edited_from(self, journal, case) -> None:
        journal.record(case, "system/controlDict", "edited")
        assert journal.entries(case)[0].baseline

    def test_a_new_file_has_no_baseline(self, journal, case) -> None:
        journal.record(case, "system/brandNew", "content")
        assert journal.entries(case)[0].baseline == ""

    def test_it_round_trips_through_json(self) -> None:
        entry = JournalEntry(case=Path("/c"), relative="system/x", content="y", baseline="z")
        assert JournalEntry.from_json(entry.to_json()) == entry


class TestTheEditorIsWiredToTheCase:
    """The journal is worthless if nothing sets its target."""

    def _preprocessor(self, qtbot, tmp_path):
        from foamwb.services.case import CaseService
        from foamwb.ui import strings
        from foamwb.ui.theme import LIGHT
        from foamwb.ui.views.preprocessor import PreprocessorView

        view = PreprocessorView(
            LIGHT, {**strings.shell_strings(), **strings.preprocessor_strings()}
        )
        qtbot.addWidget(view)
        view.text._journal = JournalService(tmp_path / "journal")
        return view, CaseService()

    def test_opening_a_file_sets_the_target(self, qtbot, tmp_path, case) -> None:
        view, cases = self._preprocessor(qtbot, tmp_path)
        view.set_case(cases.open(case))
        view.open_file(case / "system" / "controlDict")

        view.text._view.setPlainText("application icoFoam;\nendTime 9;\n")
        view.text.flush_journal()
        assert view.text._journal.recoveries(case.resolve())

    def test_a_symlinked_path_does_not_break_opening(self, qtbot, tmp_path, case) -> None:
        """On macOS /tmp is a symlink to /private/tmp, and an unresolved path
        made relative_to raise — journalling must never stop a file opening."""
        view, cases = self._preprocessor(qtbot, tmp_path)
        opened = cases.open(case)
        view.set_case(opened)

        link = tmp_path / "link"
        link.symlink_to(case, target_is_directory=True)
        view.open_file(link / "system" / "controlDict")
        assert view.text.content

    def test_a_file_outside_the_case_is_simply_not_journalled(self, qtbot, tmp_path, case) -> None:
        view, cases = self._preprocessor(qtbot, tmp_path)
        view.set_case(cases.open(case))

        stray = tmp_path / "elsewhere.dict"
        stray.write_text("application icoFoam;\n")
        view.open_file(stray)
        view.text._view.setPlainText("changed")
        view.text.flush_journal()
        assert view.text._journal.entries() == []
