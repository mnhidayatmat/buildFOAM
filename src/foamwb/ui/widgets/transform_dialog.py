"""Asking what ``transformPoints`` should do, before it is run (FR-P5).

``transformPoints`` is the only utility in §6.3's list that cannot be run bare:
it parses its arguments, finds no operation, and exits fatally. A button wired
straight to it therefore offers nothing but a failure — the same defect as
offering ``snappyHexMesh`` to a case with no dictionary, which
:func:`~foamwb.services.mesh.available_utilities` already refuses to do.

**The dialog exists because the operation is the user's, not ours.** There is no
sensible default: a mesh does not know whether it is in the wrong units, at the
wrong origin, or facing the wrong way. Guessing one would be worse than asking,
because the transform is applied to a mesh that took minutes to build and its
inverse is not always obvious afterwards.

**Three operations, not the utility's full set.** ``-rotate`` between two
vectors, ``-yawPitchRoll`` and ``-cylToCart`` all take arguments that a user must
already understand the convention for; a field nobody can fill in is worse than
one that is not there. Scale, translate and rotate-about-an-axis cover what a
mesh actually needs after import: wrong units, wrong origin, wrong orientation.

**Scale defaults to uniform** because the case that brings people here is
millimetres, and typing ``0.001`` into three boxes is three chances to typo a
mesh into an aspect ratio nobody will diagnose. The three values stay visible
rather than being hidden behind the checkbox, so what will be sent is what is on
screen.

Modal, and therefore injectable: ``MeshPanel.set_dialogs`` replaces it wholesale
in tests, because a dialog that blocks until a human answers is otherwise the one
path no test can take.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.mesh import Axis, Transform, TransformKind
from foamwb.ui.theme import Palette

__all__ = ["TransformDialog", "ask_for_transform"]

#: Enough decimals for a millimetre expressed in metres, which is the smallest
#: figure anyone types here in practice.
_DECIMALS = 6

#: Wide enough for a geometry in millimetres and a scale factor that undoes it,
#: bounded so a stray keystroke cannot ask for a mesh the size of a solar system.
_LIMIT = 1.0e6

_KINDS: tuple[tuple[TransformKind, str, str], ...] = (
    (TransformKind.SCALE, "transform_scale", "transform_scale_hint"),
    (TransformKind.TRANSLATE, "transform_translate", "transform_translate_hint"),
    (TransformKind.ROTATE, "transform_rotate", "transform_rotate_hint"),
)

_AXES: tuple[tuple[Axis, str], ...] = (
    (Axis.X, "transform_axis_x"),
    (Axis.Y, "transform_axis_y"),
    (Axis.Z, "transform_axis_z"),
)

#: What each operation means when it has not been touched: a scale that changes
#: nothing is 1, a translation that changes nothing is 0. Switching operation
#: resets to these, because carrying a translation's 0 across into a scale would
#: silently arm the collapse that :attr:`Transform.is_degenerate` exists to catch.
_RESTING_VALUE: dict[TransformKind, float] = {
    TransformKind.SCALE: 1.0,
    TransformKind.TRANSLATE: 0.0,
}


class TransformDialog(QDialog):
    """Collect one ``transformPoints`` operation."""

    def __init__(
        self, palette: Palette, labels: dict[str, str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._labels = labels
        self.setWindowTitle(labels["transform_title"])

        layout = QVBoxLayout(self)

        chooser = QFormLayout()
        self._kind = QComboBox()
        for kind, label_key, _hint_key in _KINDS:
            self._kind.addItem(labels[label_key], kind.value)
        chooser.addRow(labels["transform_operation"], self._kind)
        layout.addLayout(chooser)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_vector_page())
        self._pages.addWidget(self._build_rotate_page())
        layout.addWidget(self._pages)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        # A disabled button with no stated reason is a dead end: the user clicks
        # it, nothing happens, and there is nothing on screen to read. This line
        # appears only when Apply is off, and says what would re-enable it.
        self._blocked = QLabel()
        self._blocked.setWordWrap(True)
        self._blocked.setStyleSheet(f"color: {palette.broken};")
        self._blocked.setVisible(False)
        layout.addWidget(self._blocked)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # The standard buttons carry Qt's own translations, which are not this
        # application's catalogue and would leave one dialog in a second voice.
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(labels["transform_apply"])
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            labels["transform_cancel"]
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._kind.currentIndexChanged.connect(self._on_kind_changed)
        self._on_kind_changed()

    # -- construction ------------------------------------------------------

    def _build_vector_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._components = tuple(self._spin_box() for _ in range(3))
        for box, key in zip(
            self._components, ("transform_x", "transform_y", "transform_z"), strict=True
        ):
            form.addRow(self._labels[key], box)

        self._uniform = QCheckBox(self._labels["transform_uniform"])
        self._uniform.setChecked(True)
        form.addRow(self._uniform)

        self._uniform.toggled.connect(self._follow_first_component)
        self._components[0].valueChanged.connect(self._follow_first_component)
        return page

    def _build_rotate_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._axis = QComboBox()
        for axis, label_key in _AXES:
            self._axis.addItem(self._labels[label_key], axis.value)
        form.addRow(self._labels["transform_axis"], self._axis)

        self._angle = QDoubleSpinBox()
        self._angle.setDecimals(3)
        # A full turn either way. More is expressible but means the same thing,
        # and a box that accepts 3600 invites the reader to wonder whether it is
        # ten turns or a typo.
        self._angle.setRange(-360.0, 360.0)
        form.addRow(self._labels["transform_angle"], self._angle)
        return page

    def _spin_box(self) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setDecimals(_DECIMALS)
        box.setRange(-_LIMIT, _LIMIT)
        box.valueChanged.connect(self._refresh_apply)
        return box

    # -- behaviour ---------------------------------------------------------

    @property
    def kind(self) -> TransformKind:
        return TransformKind(self._kind.currentData())

    def _on_kind_changed(self, _index: int = -1) -> None:
        kind = self.kind
        rotating = kind is TransformKind.ROTATE
        self._pages.setCurrentIndex(1 if rotating else 0)
        self._uniform.setVisible(kind is TransformKind.SCALE)

        if not rotating:
            resting = _RESTING_VALUE[kind]
            for box in self._components:
                box.blockSignals(True)
                box.setValue(resting)
                box.blockSignals(False)

        hint_key = next(key for candidate, _label, key in _KINDS if candidate is kind)
        self._hint.setText(self._labels[hint_key])
        self._follow_first_component()
        self._refresh_apply()

    def _follow_first_component(self, _value: object = None) -> None:
        """Drive Y and Z from X while the scale is uniform."""
        linked = self._uniform.isChecked() and self.kind is TransformKind.SCALE
        for box in self._components[1:]:
            box.setEnabled(not linked)
            if linked:
                box.blockSignals(True)
                box.setValue(self._components[0].value())
                box.blockSignals(False)
        self._refresh_apply()

    def _refresh_apply(self, _value: object = None) -> None:
        """A transform that would flatten the mesh cannot be applied at all."""
        blocked = self.transform().is_degenerate
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not blocked)
        self._blocked.setText(self._labels["transform_zero_scale"] if blocked else "")
        self._blocked.setVisible(blocked)

    def transform(self) -> Transform:
        """What the fields currently say."""
        if self.kind is TransformKind.ROTATE:
            return Transform.rotate(Axis(self._axis.currentData()), self._angle.value())
        x, y, z = (box.value() for box in self._components)
        if self.kind is TransformKind.SCALE:
            return Transform.scale(x, y, z)
        return Transform.translate(x, y, z)


def ask_for_transform(
    palette: Palette, labels: dict[str, str], parent: QWidget | None = None
) -> Transform | None:
    """Put the dialog up. ``None`` means cancelled, and nothing should run."""
    dialog = TransformDialog(palette, labels, parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.transform()
    return None
