"""M6 part 2 — the Library and Post views (§7.6, §7.8).

``isVisibleTo`` rather than ``isVisible`` throughout, as everywhere else in this
suite: the latter is False for every descendant of a window that was never
shown, so a test written the obvious way passes no matter what the widget does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeSession, ScriptedCommand
from foamwb.services.library import ContentItem
from foamwb.services.paraview import ParaViewInstall, ParaViewService
from foamwb.services.post import FUNCTIONS
from foamwb.ui import strings
from foamwb.ui.theme import DARK, LIGHT
from foamwb.ui.views.library import LibraryView, bundled_catalog_path
from foamwb.ui.views.post import PostView


@pytest.fixture
def library_labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.library_strings()}


@pytest.fixture
def post_labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.post_strings()}


@pytest.fixture
def library(qtbot, library_labels) -> LibraryView:
    view = LibraryView(LIGHT, library_labels)
    qtbot.addWidget(view)
    return view


class TestTheLibraryListsSignedContent:
    def test_the_bundled_catalog_loads(self, library) -> None:
        assert library.catalog is not None
        assert library.visible_ids

    def test_every_row_states_its_licence_and_publisher(self, library) -> None:
        for row in library.rows:
            assert row.item.license
            assert row.item.publisher

    def test_a_rejected_catalog_leaves_the_library_empty_not_wrong(
        self, qtbot, library_labels, tmp_path
    ) -> None:
        """E-L01 has no override, so an unverifiable catalog shows nothing.

        Listing the items anyway "because they are probably fine" is exactly the
        behaviour the signature exists to prevent.
        """
        target = tmp_path / "catalog.json"
        target.write_bytes(bundled_catalog_path().read_bytes())  # no .sig beside it

        view = LibraryView(LIGHT, library_labels, catalog_path=target)
        qtbot.addWidget(view)
        assert view.catalog is None
        assert view.visible_ids == []
        assert view.status_text


class TestFiltering:
    def test_free_text_narrows_the_list(self, library) -> None:
        library._search.setText("separation")
        assert library.visible_ids == ["pitzDaily"]

    def test_clearing_the_search_restores_everything(self, library) -> None:
        everything = library.visible_ids
        library._search.setText("separation")
        library._search.setText("")
        assert library.visible_ids == everything

    def test_a_solver_filter_applies(self, library) -> None:
        library._solver.setCurrentIndex(library._solver.findData("interFoam"))
        assert all(library.catalog.by_id(i).solver == "interFoam" for i in library.visible_ids)

    def test_a_search_with_no_matches_says_so(self, library) -> None:
        library._search.setText("zzzz-no-such-case")
        assert library.visible_ids == []
        assert library.status_text == strings.library_strings()["no_matches"]


class TestCompatibilityIsMarkedNotHidden:
    """FR-L1's requirement, and the reason it is worded that way."""

    def test_an_incompatible_item_is_still_listed(self, library) -> None:
        before = library.visible_ids
        library.set_runtime_version("v1912")
        assert library.visible_ids == before

    def test_an_incompatible_item_is_still_installable(self, library) -> None:
        """Refusing would claim more than the catalog knows."""
        library.set_runtime_version("v1912")
        assert all(row.can_install for row in library.rows)

    def test_the_label_changes_with_the_runtime(self, library) -> None:
        library.set_runtime_version("v2512")
        compatible = library.rows[0].compatibility_text
        library.set_runtime_version("v1912")
        assert library.rows[0].compatibility_text != compatible

    def test_no_runtime_is_said_plainly(self, library) -> None:
        library.set_runtime_version(None)
        assert library.rows[0].compatibility_text == strings.library_strings()["compat_no_runtime"]

    def test_an_untested_item_is_not_claimed_compatible(self, qtbot, library_labels) -> None:
        item = ContentItem(
            id="x", name="X", summary="", category="", solver="", payload="", sha256=""
        )
        assert item.compatibility("v2512") == "unknown"


class TestInstallingFromTheView:
    def test_a_successful_install_reports_where_it_went(self, library, tmp_path) -> None:
        library.set_destination(tmp_path / "cases")
        library._install(library.catalog.by_id("cavity"))
        assert "cavity" in library.status_text
        assert (tmp_path / "cases" / "cavity" / "system" / "controlDict").is_file()

    def test_it_announces_the_installed_case(self, library, tmp_path, qtbot) -> None:
        library.set_destination(tmp_path / "cases")
        with qtbot.waitSignal(library.case_installed, timeout=2000) as caught:
            library._install(library.catalog.by_id("cavity"))
        assert Path(caught.args[0]).name == "cavity"

    def test_a_refused_install_names_its_code(self, library, tmp_path) -> None:
        """E-L01 and E-L02 call for different responses from the user."""
        library.set_destination(tmp_path / "cases")
        item = library.catalog.by_id("cavity")
        library._install(item)
        library._install(item)  # the directory now exists
        assert "E-L05" in library.status_text

    def test_installing_without_a_destination_does_nothing(self, library) -> None:
        library.set_destination(None)
        library._install(library.catalog.by_id("cavity"))
        assert "E-" not in library.status_text


class TestPostView:
    def _view(self, qtbot, labels, *, install: ParaViewInstall | None) -> PostView:
        service = ParaViewService()
        service.locate = lambda: install  # type: ignore[method-assign]
        service._launch = lambda argv, cwd: None  # type: ignore[method-assign]
        view = PostView(LIGHT, labels, paraview=service)
        qtbot.addWidget(view)
        return view

    def _case(self, tmp_path: Path) -> Path:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("application icoFoam;\n")
        return case

    def test_a_missing_paraview_is_a_state_not_a_failure(self, qtbot, post_labels) -> None:
        view = self._view(qtbot, post_labels, install=None)
        assert view.shows_missing_banner
        assert not view.can_open

    def test_an_installed_paraview_shows_no_banner(self, qtbot, post_labels, tmp_path) -> None:
        """FR-V1: on a machine that has it, nothing is offered for download."""
        install = ParaViewInstall(executable=tmp_path / "paraview", version="5.13")
        view = self._view(qtbot, post_labels, install=install)
        assert not view.shows_missing_banner

    def test_opening_needs_both_paraview_and_a_case(self, qtbot, post_labels, tmp_path) -> None:
        install = ParaViewInstall(executable=tmp_path / "paraview", version="5.13")
        view = self._view(qtbot, post_labels, install=install)
        assert not view.can_open
        view.set_context(FakeSession({}), self._case(tmp_path))
        assert view.can_open

    def test_mesh_inspection_is_offered_separately(self, qtbot, post_labels, tmp_path) -> None:
        """FR-P8 answers a different question and works before any run."""
        install = ParaViewInstall(executable=tmp_path / "paraview", version="5.13")
        view = self._view(qtbot, post_labels, install=install)
        view.set_context(FakeSession({}), self._case(tmp_path))
        assert view.can_inspect_mesh

    def test_no_case_is_said_plainly(self, qtbot, post_labels) -> None:
        view = self._view(qtbot, post_labels, install=None)
        assert view.status_text == strings.post_strings()["no_case_for_post"]

    def test_a_templated_utility_asks_for_its_argument(self, qtbot, post_labels) -> None:
        view = self._view(qtbot, post_labels, install=None)
        index = [f.needs_argument for f in FUNCTIONS].index(True)
        view._functions.setCurrentIndex(index)
        assert view.argument_visible

    def test_a_plain_utility_does_not(self, qtbot, post_labels) -> None:
        view = self._view(qtbot, post_labels, install=None)
        view._functions.setCurrentIndex(0)
        assert not view.argument_visible

    def test_running_a_utility_streams_into_the_log(self, qtbot, post_labels, tmp_path) -> None:
        view = self._view(qtbot, post_labels, install=None)
        session = FakeSession({"postProcess": ScriptedCommand(lines=["Reading", "End"])})
        view.set_context(session, self._case(tmp_path))
        view._run_utility()
        assert "Reading" in view.log.text

    def test_producing_nothing_is_not_reported_as_failure(
        self, qtbot, post_labels, tmp_path
    ) -> None:
        """`yPlus` on a case with no walls does exactly this."""
        view = self._view(qtbot, post_labels, install=None)
        view.set_context(FakeSession({}), self._case(tmp_path))
        view._run_utility()
        assert "failed" not in view.status_text.lower()

    def test_a_failing_utility_says_so(self, qtbot, post_labels, tmp_path) -> None:
        view = self._view(qtbot, post_labels, install=None)
        session = FakeSession({"postProcess": ScriptedCommand(exit_code=1)})
        view.set_context(session, self._case(tmp_path))
        view._run_utility()
        assert "failed" in view.status_text.lower()

    def test_both_themes_apply(self, qtbot, post_labels) -> None:
        view = self._view(qtbot, post_labels, install=None)
        for palette in (LIGHT, DARK):
            view.set_palette(palette)
        assert True


class TestWiredIntoTheShell:
    def test_both_views_are_real_not_placeholders(self, qtbot) -> None:
        from foamwb.ui.shell import Shell

        shell = Shell(LIGHT)
        qtbot.addWidget(shell)
        assert isinstance(shell.library, LibraryView)
        assert isinstance(shell.post, PostView)

    def test_the_library_follows_the_runtime_version(self, qtbot) -> None:
        """One setter drives the footer and the library, so they cannot disagree."""
        from foamwb.ui.shell import Shell

        shell = Shell(LIGHT)
        qtbot.addWidget(shell)
        shell.set_openfoam_version("v2512")
        assert "v2512" in shell.library.rows[0].compatibility_text
