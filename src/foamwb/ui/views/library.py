"""The content library view (§7.8, FR-L1 to FR-L5).

Two decisions carry most of this screen.

**Incompatible items are marked, not hidden** (FR-L1). Filtering them out would
answer "where is the case my lecturer told me to use?" with silence, and a user
who cannot find something concludes the application is broken rather than that
the item is for another release. Compatibility is a *label on the row*, and the
Install button is what changes.

**Verification is stated, not implied.** The catalog's signature is checked
before this view has anything to show, so the heading says so. §7.9 rule 6 asks
that the interface not claim more than it knows — and the converse holds too: a
guarantee the application does provide is worth saying out loud, because it is
the reason a user should be willing to install anything at all.

A failed install is reported with its §9 code and its detail, never as a generic
"install failed". E-L01 and E-L02 mean different things — unverifiable content
versus a payload that does not match — and a user who cannot tell them apart
cannot know whether to retry.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from foamwb.logs import Event, get_logger, log_event
from foamwb.services.library import (
    Catalog,
    CatalogError,
    ContentItem,
    InstallError,
    install_item,
    load_catalog,
)
from foamwb.ui.theme import Palette

__all__ = ["LibraryView"]

_log = get_logger("ui.library")


def bundled_catalog_path() -> Path:
    """The catalog that ships inside the wheel."""
    from foamwb import data

    return Path(data.__file__).parent / "library" / "catalog.json"


class ItemRow(QFrame):
    """One installable case, with everything needed to decide about it."""

    install_requested = Signal(object)

    def __init__(
        self,
        item: ContentItem,
        labels: dict[str, str],
        palette: Palette,
        version: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._labels = labels
        self.setObjectName("libraryItem")
        self.setFrameShape(QFrame.Shape.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(3)

        header = QHBoxLayout()
        self._name = QLabel(item.name)
        self._name.setProperty("role", "heading")
        header.addWidget(self._name)
        header.addStretch(1)

        self._button = QPushButton(labels["install"])
        self._button.clicked.connect(lambda: self.install_requested.emit(item))
        header.addWidget(self._button)
        outer.addLayout(header)

        summary = QLabel(item.summary)
        summary.setWordWrap(True)
        outer.addWidget(summary)

        meta = QLabel(labels["item_meta"].format(item.solver, item.category))
        meta.setProperty("role", "muted")
        outer.addWidget(meta)

        self._compat = QLabel()
        self._compat.setProperty("role", "muted")
        outer.addWidget(self._compat)

        licence = QLabel(labels["licence_line"].format(item.license, item.publisher))
        licence.setProperty("role", "muted")
        outer.addWidget(licence)

        self.set_version(version)
        self.set_palette(palette)

    def set_version(self, version: str | None) -> None:
        """Label the row for the runtime in use, without ever hiding it."""
        verdict = self._item.compatibility(version)
        if version is None:
            text = self._labels["compat_no_runtime"]
        elif verdict == "yes":
            text = self._labels["compat_yes"].format(version)
        elif verdict == "no":
            text = self._labels["compat_no"]
        else:
            text = self._labels["compat_unknown"]
        self._compat.setText(text)

        # Installing an item built for another release is allowed: it usually
        # still runs, and refusing would be a stronger claim than the catalog
        # supports. The label is the warning; the button is not the enforcement.
        self._button.setEnabled(True)
        self.setAccessibleName(self._labels["item_accessible"].format(self._item.name, text))

    def set_palette(self, palette: Palette) -> None:
        self.setStyleSheet(
            f"#libraryItem {{ background: {palette.surface};"
            f" border: 1px solid {palette.border}; border-radius: 6px; }}"
        )

    @property
    def item(self) -> ContentItem:
        return self._item

    @property
    def compatibility_text(self) -> str:
        return self._compat.text()

    @property
    def can_install(self) -> bool:
        return self._button.isEnabled()


class LibraryView(QWidget):
    """Browse, filter and install signed content."""

    case_installed = Signal(Path)

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        catalog_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._catalog: Catalog | None = None
        self._error = ""
        self._version: str | None = None
        self._destination: Path | None = None
        self._rows: list[ItemRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        heading = QLabel(labels["library_heading"])
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        self._intro = QLabel(labels["library_intro"])
        self._intro.setWordWrap(True)
        self._intro.setProperty("role", "muted")
        outer.addWidget(self._intro)

        outer.addWidget(self._build_filters(labels))

        self._status = QLabel()
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list)
        outer.addWidget(self._scroll, stretch=1)

        self.load(catalog_path or bundled_catalog_path())

    def _build_filters(self, labels: dict[str, str]) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText(labels["search_placeholder"])
        self._search.setAccessibleName(labels["search"])
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refresh)
        row.addWidget(self._search, stretch=1)

        self._category = QComboBox()
        self._category.setAccessibleName(labels["all_categories"])
        self._category.currentIndexChanged.connect(self._refresh)
        row.addWidget(self._category)

        self._solver = QComboBox()
        self._solver.setAccessibleName(labels["all_solvers"])
        self._solver.currentIndexChanged.connect(self._refresh)
        row.addWidget(self._solver)
        return bar

    # -- catalog -----------------------------------------------------------

    def load(self, path: Path) -> None:
        """Verify and load a catalog. A failure leaves the view usable and honest."""
        try:
            self._catalog = load_catalog(path)
            self._error = ""
        except CatalogError as exc:
            # The library is empty rather than wrong. Showing unverified items
            # "just to be helpful" is precisely what E-L01 forbids.
            self._catalog = None
            self._error = exc.message
            log_event(_log, Event.ERROR_RAISED, where="library.load", error=exc.code.id)

        self._populate_filters()
        self._refresh()

    def _populate_filters(self) -> None:
        for box, values, everything in (
            (self._category, self._catalog.categories if self._catalog else (), "all_categories"),
            (self._solver, self._catalog.solvers if self._catalog else (), "all_solvers"),
        ):
            box.blockSignals(True)
            box.clear()
            box.addItem(self._labels[everything], "")
            for value in values:
                box.addItem(value, value)
            box.blockSignals(False)

    def set_runtime_version(self, version: str | None) -> None:
        self._version = version
        for row in self._rows:
            row.set_version(version)

    def set_destination(self, destination: Path | None) -> None:
        """Where an install lands — the user's case area."""
        self._destination = destination

    # -- listing -----------------------------------------------------------

    def _refresh(self) -> None:
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []

        if self._catalog is None:
            self._status.setText(self._labels["catalog_unavailable"].format(self._error))
            self._status.show()
            return

        found = self._catalog.search(
            self._search.text(),
            category=self._category.currentData() or None,
            solver=self._solver.currentData() or None,
        )
        if not found:
            self._status.setText(self._labels["no_matches"])
            self._status.show()
            return

        self._status.hide()
        for item in found:
            row = ItemRow(item, self._labels, self._palette, self._version)
            row.install_requested.connect(self._install)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows.append(row)

    # -- installing --------------------------------------------------------

    @Slot(object)
    def _install(self, item: ContentItem) -> None:
        if self._destination is None or self._catalog is None:
            return
        assert self._catalog.source is not None
        payload = self._catalog.source.parent / item.payload

        self._status.setText(self._labels["installing"].format(item.name))
        self._status.show()

        try:
            where = install_item(item, payload, self._destination)
        except InstallError as exc:
            # The code travels with the message: E-L01 and E-L02 call for
            # different responses, and "install failed" tells the user neither.
            self._status.setText(
                self._labels["install_failed_title"].format(item.name)
                + "\n"
                + self._labels["install_failed"].format(exc.message, exc.code.id)
            )
            log_event(_log, Event.ERROR_RAISED, where="library.install", error=exc.code.id)
            return

        self._status.setText(self._labels["installed"].format(item.name, where.name))
        self.case_installed.emit(where)

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        for row in self._rows:
            row.set_palette(palette)

    # -- inspection --------------------------------------------------------

    @property
    def catalog(self) -> Catalog | None:
        return self._catalog

    @property
    def rows(self) -> list[ItemRow]:
        return list(self._rows)

    @property
    def visible_ids(self) -> list[str]:
        return [row.item.id for row in self._rows]

    @property
    def status_text(self) -> str:
        return self._status.text()
