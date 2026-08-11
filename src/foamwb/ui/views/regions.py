"""The patch editor (FR-P4, E-C04, §7.4).

One table, one action, and a consequences panel — the same shape as the V&V
view's, and for the same reason: this is an edit whose effect reaches beyond the
line it changes, so what else it means is shown *before* it is agreed to rather
than discovered afterwards.

**The consequences are the feature.** Setting a patch to ``empty`` is two
keystrokes and turns a 3D case into an unsolvable one. Setting it to ``wall``
silently enrols it in turbulence wall functions and the y+ audit. Nothing in
OpenFOAM warns about either; the panel is where that warning lives.

**Fields that would have to follow are listed, not rewritten.** A type change
that quietly edited six field files would be a large edit hiding behind a small
one. The list names them and the boundary-condition matrix is where they change,
which keeps one model in charge of one file.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.boundary import Patch, read_boundary
from foamwb.services.regions import SELECTABLE_TYPES, apply_patch_type, plan_patch_type
from foamwb.ui.theme import Palette

__all__ = ["RegionsView"]

_NAME_ROLE = Qt.ItemDataRole.UserRole


class RegionsView(QWidget):
    """Lists the mesh's patches and changes their types, with consequences."""

    patches_changed = Signal()

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._case: Path | None = None
        self._patches: list[Patch] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        heading = QLabel(labels["regions_heading"])
        heading.setProperty("role", "heading")
        outer.addWidget(heading)

        intro = QLabel(labels["regions_intro"])
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        outer.addWidget(intro)

        self._table = QTreeWidget()
        self._table.setColumnCount(4)
        self._table.setHeaderLabels(
            [
                labels["col_patch"],
                labels["col_type"],
                labels["col_faces"],
                labels["col_groups"],
            ]
        )
        self._table.setRootIsDecorated(False)
        self._table.setAccessibleName(labels["regions_heading"])
        self._table.currentItemChanged.connect(self._on_selected)
        outer.addWidget(self._table, stretch=1)

        outer.addWidget(self._build_controls(labels))

        self._consequences = self._build_consequences(labels)
        outer.addWidget(self._consequences)

        self._status = QLabel()
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        self.set_case(None)
        self.set_palette(palette)

    def _build_controls(self, labels: dict[str, str]) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._type = QComboBox()
        self._type.setAccessibleName(labels["col_type"])
        for name in SELECTABLE_TYPES:
            self._type.addItem(name, name)
        self._type.currentIndexChanged.connect(self._preview)
        row.addWidget(self._type)

        self._apply = QPushButton(labels["apply_type"])
        self._apply.clicked.connect(self._apply_type)
        row.addWidget(self._apply)
        row.addStretch(1)
        return bar

    def _build_consequences(self, labels: dict[str, str]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("consequences")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self._consequence_title = QLabel()
        self._consequence_title.setProperty("role", "heading")
        self._consequence_title.setWordWrap(True)
        layout.addWidget(self._consequence_title)

        self._consequence_body = QLabel()
        self._consequence_body.setWordWrap(True)
        layout.addWidget(self._consequence_body)

        self._followers = QLabel()
        self._followers.setWordWrap(True)
        self._followers.setProperty("role", "muted")
        layout.addWidget(self._followers)

        frame.hide()
        return frame

    # -- content -----------------------------------------------------------

    def set_case(self, case: Path | None) -> None:
        self._case = case
        self.refresh()

    def refresh(self) -> None:
        self._table.clear()
        self._consequences.hide()
        self._status.setText("")

        self._patches = read_boundary(self._case) if self._case is not None else []
        if not self._patches:
            self._status.setText(self._labels["no_mesh_yet"])
            self._apply.setEnabled(False)
            self._type.setEnabled(False)
            return

        for patch in self._patches:
            item = QTreeWidgetItem(
                [
                    patch.name,
                    patch.type,
                    self._labels["faces_count"].format(patch.n_faces),
                    " ".join(patch.in_groups),
                ]
            )
            item.setData(0, _NAME_ROLE, patch.name)
            if patch.is_constrained:
                item.setToolTip(1, self._labels["constrained_note"])
            self._table.addTopLevelItem(item)

        for column in range(4):
            self._table.resizeColumnToContents(column)
        self._table.setCurrentItem(self._table.topLevelItem(0))
        self._apply.setEnabled(True)
        self._type.setEnabled(True)

    # -- interaction -------------------------------------------------------

    def _selected_patch(self) -> Patch | None:
        item = self._table.currentItem()
        if item is None:
            return None
        name = item.data(0, _NAME_ROLE)
        return next((p for p in self._patches if p.name == name), None)

    def _on_selected(self, *_args) -> None:
        patch = self._selected_patch()
        if patch is None:
            return
        index = self._type.findData(patch.type)
        if index >= 0:
            self._type.blockSignals(True)
            self._type.setCurrentIndex(index)
            self._type.blockSignals(False)
        self._preview()

    def _preview(self) -> None:
        """Show what the pending change would mean, before it is made."""
        patch = self._selected_patch()
        if patch is None or self._case is None:
            self._consequences.hide()
            return

        wanted = self._type.currentData()
        change = plan_patch_type(self._case, patch.name, wanted)

        if change.is_noop:
            self._consequences.hide()
            return

        self._consequence_title.setText(
            self._labels["consequences_title"].format(patch.name, change.old_type, change.new_type)
        )
        if change.blocked:
            self._consequence_body.setText(change.blocked)
            self._followers.setText("")
        else:
            self._consequence_body.setText("\n".join(f"• {line}" for line in change.consequences))
            if change.fields_needing_update:
                names = ", ".join(sorted(change.fields_needing_update))
                required = next(iter(change.fields_needing_update.values()))
                self._followers.setText(
                    self._labels["fields_must_follow"].format(patch.name)
                    + "\n"
                    + self._labels["fields_list"].format(names, required)
                )
            else:
                self._followers.setText("")

        self._apply.setEnabled(change.can_apply)
        self._consequences.show()

    def _apply_type(self) -> None:
        patch = self._selected_patch()
        if patch is None or self._case is None:
            return

        wanted = self._type.currentData()
        change = plan_patch_type(self._case, patch.name, wanted)

        if change.is_noop:
            self._status.setText(self._labels["no_change"].format(patch.name, wanted))
            return
        if change.blocked:
            self._status.setText(self._labels["change_refused"].format(change.blocked))
            return

        if apply_patch_type(self._case, change):
            # After the refresh, not before: refresh clears the status, so the
            # confirmation set first was never seen — the edit worked and the
            # interface said nothing, which reads as a control that does nothing.
            self.refresh()
            self._status.setText(self._labels["change_applied"].format(patch.name, wanted))
            self.patches_changed.emit()

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._consequences.setStyleSheet(
            f"#consequences {{ background: {palette.surface_alt};"
            f" border: 1px solid {palette.degraded}; border-radius: 6px; }}"
        )

    # -- inspection --------------------------------------------------------

    @property
    def patch_names(self) -> list[str]:
        return [p.name for p in self._patches]

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def shows_consequences(self) -> bool:
        return self._consequences.isVisibleTo(self)

    @property
    def consequence_text(self) -> str:
        return self._consequence_body.text()

    @property
    def followers_text(self) -> str:
        return self._followers.text()

    def choose(self, patch_name: str, new_type: str) -> None:
        """For tests and scripted use: select a patch and a target type."""
        for index in range(self._table.topLevelItemCount()):
            item = self._table.topLevelItem(index)
            if item.data(0, _NAME_ROLE) == patch_name:
                self._table.setCurrentItem(item)
                break
        position = self._type.findData(new_type)
        if position >= 0:
            self._type.setCurrentIndex(position)
