"""The four regions the Fluent-shaped window added (§7.1, DEC-21).

The shell's own tests exercise these through the window, which is the right
level for "pressing Calculate runs the solver". These are the properties that
only show up when each piece is on its own: that the ribbon is a faithful
rendering of its declared table, that a stack refuses an unknown name instead
of silently showing the wrong thing, and that folding the console leaves
something to unfold it with.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QWidget

from foamwb.ui import strings
from foamwb.ui.icons import ICON_SIZE, glyph_icon
from foamwb.ui.ribbon import FILE_MENU, RIBBON_TABS, Ribbon
from foamwb.ui.theme import DARK, LIGHT
from foamwb.ui.widgets.console_dock import ConsoleDock
from foamwb.ui.widgets.graphics_window import GraphicsWindow
from foamwb.ui.widgets.task_page import TaskPage


@pytest.fixture
def labels() -> dict[str, str]:
    return {
        **strings.shell_strings(),
        **strings.ribbon_strings(),
        **strings.workflow_strings(),
        **strings.console_strings(),
        **strings.graphics_strings(),
    }


@pytest.fixture
def ribbon(qtbot, labels) -> Ribbon:
    widget = Ribbon(LIGHT, labels)
    qtbot.addWidget(widget)
    return widget


class TestTheRibbonRendersItsTable:
    """Tabs, groups and actions are data; the widget only draws them."""

    def test_every_declared_tab_is_built(self, ribbon: Ribbon) -> None:
        assert ribbon.tab_keys == [tab.key for tab in RIBBON_TABS]

    def test_every_declared_action_gets_a_button(self, ribbon: Ribbon) -> None:
        for tab in RIBBON_TABS:
            for group in tab.groups:
                for action in group.actions:
                    assert ribbon.button(action.key) is not None

    def test_every_group_is_captioned(self, ribbon: Ribbon, labels) -> None:
        """The caption under the buttons is what makes a ribbon a ribbon rather
        than a toolbar: it names the kind of thing the buttons above it do."""
        captions = {
            label.text()
            for label in ribbon.findChildren(QLabel)
            if label.property("role") == "ribbonCaption"
        }
        for tab in RIBBON_TABS:
            for group in tab.groups:
                assert labels[f"group.{group.key}"] in captions

    def test_every_group_key_has_a_label(self, labels) -> None:
        for tab in RIBBON_TABS:
            for group in tab.groups:
                assert labels[f"group.{group.key}"].strip()

    def test_the_file_menu_is_built_in_order(self, ribbon: Ribbon) -> None:
        assert ribbon.menu_keys == [k for k in FILE_MENU if k not in (None, "recent")]

    def test_pressing_a_button_emits_its_key(self, ribbon: Ribbon, qtbot) -> None:
        with qtbot.waitSignal(ribbon.action_triggered) as caught:
            ribbon.trigger("calculate")
        assert caught.args == ["calculate"]

    def test_a_disabled_action_emits_nothing(self, ribbon: Ribbon) -> None:
        """A shortcut must not reach past a button the shell has switched off."""
        seen: list[str] = []
        ribbon.action_triggered.connect(seen.append)
        ribbon.set_enabled("calculate", False, reason="no mesh")
        ribbon.trigger("calculate")
        assert seen == []

    def test_a_disabled_action_explains_itself(self, ribbon: Ribbon) -> None:
        ribbon.set_enabled("calculate", False, reason="Generate the mesh first.")
        assert ribbon.tooltip_of("calculate") == "Generate the mesh first."

    def test_re_enabling_restores_the_tooltip_with_its_shortcut(self, ribbon: Ribbon) -> None:
        original = ribbon.tooltip_of("calculate")
        ribbon.set_enabled("calculate", False, reason="Generate the mesh first.")
        ribbon.set_enabled("calculate", True)
        assert ribbon.tooltip_of("calculate") == original
        assert "Ctrl+R" in original

    def test_an_unknown_key_is_ignored_rather_than_raising(self, ribbon: Ribbon) -> None:
        """The shell disables actions by name; a typo must not crash the window."""
        ribbon.set_enabled("nonesuch", False)
        ribbon.trigger("nonesuch")

    def test_showing_an_unknown_tab_changes_nothing(self, ribbon: Ribbon) -> None:
        ribbon.show_tab("physics")
        ribbon.show_tab("nonesuch")
        assert ribbon.current_tab == "physics"

    def test_the_recent_menu_starts_empty_and_says_so(self, ribbon: Ribbon) -> None:
        entries = ribbon._recent.actions()
        assert len(entries) == 1 and not entries[0].isEnabled()

    def test_a_recent_entry_emits_its_path(self, ribbon: Ribbon, qtbot) -> None:
        ribbon.set_recent(["/cases/pitzDaily"])
        with qtbot.waitSignal(ribbon.recent_requested) as caught:
            ribbon._recent.actions()[0].trigger()
        assert caught.args == ["/cases/pitzDaily"]

    def test_setting_the_recent_list_replaces_it(self, ribbon: Ribbon) -> None:
        ribbon.set_recent(["/a", "/b"])
        ribbon.set_recent(["/c"])
        assert [a.text() for a in ribbon._recent.actions()] == ["/c"]

    def test_every_button_carries_an_icon(self, ribbon: Ribbon) -> None:
        for tab in RIBBON_TABS:
            for group in tab.groups:
                for action in group.actions:
                    assert not ribbon.button(action.key).icon().isNull(), action.key

    def test_the_icons_follow_the_palette(self, ribbon: Ribbon) -> None:
        """NFR-A4 — a dark theme must not ship a second set of artwork."""
        before = ribbon.button("calculate").icon().cacheKey()
        ribbon.set_palette(DARK)
        assert ribbon.button("calculate").icon().cacheKey() != before


class TestGlyphIcons:
    """NFR-A3 — resolution-independent by construction, not a bitmap."""

    def test_it_produces_an_icon(self) -> None:
        assert isinstance(glyph_icon("▶", "#000000"), QIcon)

    def test_it_is_rendered_above_the_logical_size(self) -> None:
        """A 1x pixmap would blur on every display the application supports.

        Asked for at the logical size, ``QIcon`` hands back a 1x copy — the
        question worth asking is what it actually *has*, which is what it scales
        from on a Retina display.
        """
        available = glyph_icon("▶", "#000000").availableSizes()
        assert available and available[0].width() >= ICON_SIZE * 2

    def test_the_same_request_is_cached(self) -> None:
        """The ribbon asks for forty icons on every repaint of the palette."""
        assert glyph_icon("▶", "#000000") is glyph_icon("▶", "#000000")

    def test_a_different_colour_is_a_different_icon(self) -> None:
        assert glyph_icon("▶", "#000000") is not glyph_icon("▶", "#ffffff")


class TestTheTaskPage:
    @pytest.fixture
    def page(self, qtbot, labels) -> TaskPage:
        widget = TaskPage(labels)
        qtbot.addWidget(widget)
        widget.add_page("settings", QWidget())
        widget.add_page("run", QWidget())
        return widget

    def test_it_starts_on_the_empty_page(self, page: TaskPage) -> None:
        assert page.current == ""

    def test_a_page_can_be_reached_by_name(self, page: TaskPage) -> None:
        assert page.show_page("run", title="Run Calculation")
        assert page.current == "run"
        assert page.title_text == "Run Calculation"

    def test_an_unknown_name_changes_nothing(self, page: TaskPage) -> None:
        page.show_page("settings")
        assert not page.show_page("nonesuch")
        assert page.current == "settings"

    def test_a_caption_appears_only_when_there_is_one(self, page: TaskPage) -> None:
        page.show_page("run", title="Run", caption="Run the solver.")
        assert page.caption_text == "Run the solver."
        page.show_page("settings", title="General")
        assert not page.caption_text

    def test_the_empty_page_is_not_offered_as_a_destination(self, page: TaskPage) -> None:
        assert page.pages == ["settings", "run"]

    def test_a_long_caption_is_given_the_height_it_needs(self, page: TaskPage) -> None:
        """A wrapped label reports a single-line hint, and a layout with no
        spare room grants exactly that — which clipped every caption longer
        than the column mid-word, losing the half that says what to do."""
        page.resize(240, 400)
        page.show()
        page.show_page(
            "run",
            title="Run Calculation",
            caption=(
                "Run blockMesh, then checkMesh to see whether the mesh it "
                "produced is usable before the solver is started on it."
            ),
        )
        caption = page._caption
        assert caption.height() >= caption.heightForWidth(caption.width())
        assert caption.height() > caption.fontMetrics().height()

    def test_a_page_with_no_caption_takes_no_height(self, page: TaskPage) -> None:
        page.resize(240, 400)
        page.show()
        page.show_page("settings", title="General")
        assert page._caption.height() == 0


class TestTheGraphicsWindow:
    @pytest.fixture
    def graphics(self, qtbot, labels) -> GraphicsWindow:
        widget = GraphicsWindow(labels)
        qtbot.addWidget(widget)
        widget.add_document("mesh", QWidget())
        widget.add_document("residuals", QWidget())
        return widget

    def test_documents_are_named_from_the_catalogue(self, graphics, labels) -> None:
        assert graphics.title_of("residuals") == labels["doc.residuals"]

    def test_a_document_can_be_raised_by_name(self, graphics: GraphicsWindow) -> None:
        assert graphics.show_document("residuals")
        assert graphics.current == "residuals"

    def test_an_unknown_name_changes_nothing(self, graphics: GraphicsWindow) -> None:
        graphics.show_document("mesh")
        assert not graphics.show_document("nonesuch")
        assert graphics.current == "mesh"

    def test_the_first_document_is_the_one_shown(self, graphics: GraphicsWindow) -> None:
        assert graphics.current == "mesh"


class TestTheConsoleDock:
    @pytest.fixture
    def dock(self, qtbot, labels) -> ConsoleDock:
        widget = ConsoleDock(labels, QWidget(), QWidget())
        qtbot.addWidget(widget)
        return widget

    def test_it_opens_on_the_transcript(self, dock: ConsoleDock) -> None:
        assert dock.current_tab == "console"
        assert not dock.collapsed

    def test_showing_messages_switches_tab(self, dock: ConsoleDock) -> None:
        dock.show_messages()
        assert dock.current_tab == "messages"

    def test_folding_leaves_the_header_behind(self, dock: ConsoleDock, qtbot) -> None:
        """A dock that folded away entirely would have nothing to unfold it."""
        dock.show()
        dock.set_collapsed(True)
        assert dock.collapsed
        assert dock._toggle.isVisible()
        assert not dock._tabs.isVisible()

    def test_showing_a_tab_unfolds_it(self, dock: ConsoleDock) -> None:
        """A run starting must not write into a dock nobody can see."""
        dock.set_collapsed(True)
        dock.show_console()
        assert not dock.collapsed

    def test_the_state_is_carried_in_words(self, dock: ConsoleDock) -> None:
        """NFR-A2 — the ▾/▴ glyph is not the only statement of the state."""
        collapsed_label = dock._toggle.accessibleName()
        dock.set_collapsed(True)
        assert dock._toggle.accessibleName() != collapsed_label
        assert dock._toggle.accessibleName().strip()

    def test_folding_twice_reports_once(self, dock: ConsoleDock) -> None:
        seen: list[bool] = []
        dock.collapsed_changed.connect(seen.append)
        dock.set_collapsed(True)
        dock.set_collapsed(True)
        assert seen == [True]
