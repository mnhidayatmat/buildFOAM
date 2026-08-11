"""The guide view (FR-G1, FR-G2).

A contents tree, a search box and a reading pane. Nothing about it needs a
network, which is the requirement rather than an implementation detail: §2's
users include a lab machine behind a proxy that blocks everything, and help that
needs the internet is no help on the machine most likely to need it.

**Search narrows as terms are added.** Every term must match, so a second word
makes the list shorter. The alternative — any-term matching — returns more
results for a more specific question, which is the opposite of what the user
asked for.

**A link from an error message lands on the section, not the page.** Arriving at
the top of a nine-section page having clicked "Why this happened" is barely
better than not linking at all.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.guide import Guide, GuidePage, GuideSection, load_guide
from foamwb.ui.theme import Palette

__all__ = ["GuideView"]

_ANCHOR_ROLE = Qt.ItemDataRole.UserRole


class GuideView(QWidget):
    """Reads the bundled guide, with offline search."""

    section_shown = Signal(str)

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        guide: Guide | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._guide = guide if guide is not None else load_guide()
        self._current = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        heading = QLabel(labels["guide_heading"])
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        self._search = QLineEdit()
        self._search.setPlaceholderText(labels["guide_search_placeholder"])
        self._search.setAccessibleName(labels["guide_search"])
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        outer.addWidget(self._search)

        self._status = QLabel(labels["guide_offline_note"])
        self._status.setWordWrap(True)
        self._status.setProperty("role", "muted")
        outer.addWidget(self._status)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._contents = QTreeWidget()
        self._contents.setHeaderHidden(True)
        self._contents.setAccessibleName(labels["guide_contents"])
        self._contents.currentItemChanged.connect(self._on_selected)
        splitter.addWidget(self._contents)

        self._body = QTextBrowser()
        self._body.setOpenExternalLinks(True)
        self._body.setAccessibleName(labels["guide_heading"])
        splitter.addWidget(self._body)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, stretch=1)

        self._show_contents()
        self.set_palette(palette)

    # -- contents ----------------------------------------------------------

    def _show_contents(self) -> None:
        self._contents.clear()
        if not self._guide.pages:
            self._status.setText(self._labels["guide_missing"])
            return

        for page in self._guide.pages:
            parent = QTreeWidgetItem([page.title])
            parent.setData(0, _ANCHOR_ROLE, "")
            for section in page.sections:
                child = QTreeWidgetItem([section.title])
                child.setData(0, _ANCHOR_ROLE, f"{page.name}/{section.anchor}")
                parent.addChild(child)
            self._contents.addTopLevelItem(parent)
        self._contents.expandAll()

    def _show_results(self, query: str, results: list[tuple[GuidePage, GuideSection]]) -> None:
        self._contents.clear()
        for page, section in results:
            item = QTreeWidgetItem(
                [self._labels["guide_result_row"].format(page.title, section.title)]
            )
            item.setData(0, _ANCHOR_ROLE, f"{page.name}/{section.anchor}")
            item.setToolTip(0, section.summary)
            self._contents.addTopLevelItem(item)

        self._status.setText(
            self._labels["guide_results"].format(len(results), query)
            if results
            else self._labels["guide_no_results"].format(query)
        )

    # -- interaction -------------------------------------------------------

    def _on_search(self, text: str) -> None:
        query = text.strip()
        if not query:
            self._status.setText(self._labels["guide_offline_note"])
            self._show_contents()
            return
        self._show_results(query, self._guide.search(query))

    def _on_selected(self, item: QTreeWidgetItem | None, _previous) -> None:
        if item is None:
            return
        anchor = item.data(0, _ANCHOR_ROLE)
        if anchor:
            self.show_anchor(anchor)

    def show_anchor(self, anchor: str) -> bool:
        """Open the section an error message linked to (FR-G2).

        Returns whether it resolved. A caller that gets ``False`` should say the
        guide has no page for this rather than silently showing something else —
        landing the user somewhere unrelated is how a guide loses their trust for
        the rest of the session.
        """
        found = self._guide.resolve(anchor)
        if found is None:
            return False

        _page, section = found
        self._current = anchor
        self._body.setMarkdown(f"# {section.title}\n\n{section.body}\n")
        self.section_shown.emit(anchor)
        return True

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._body.setStyleSheet(
            f"QTextBrowser {{ background: {palette.bg}; color: {palette.text};"
            f" border: 1px solid {palette.border}; padding: 8px; }}"
        )

    # -- inspection --------------------------------------------------------

    @property
    def guide(self) -> Guide:
        return self._guide

    @property
    def current_anchor(self) -> str:
        return self._current

    @property
    def body_text(self) -> str:
        return self._body.toPlainText()

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def result_count(self) -> int:
        return self._contents.topLevelItemCount()

    def search_for(self, query: str) -> None:
        self._search.setText(query)
