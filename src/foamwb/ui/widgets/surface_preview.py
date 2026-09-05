"""A shaded look at the surface that was just imported (FR-P3).

Deliberately small. NG1 rules out drawing geometry in the sense of CAD authoring
and NG3 rules out replacing ParaView; this does neither. It answers one
question — *is this the thing I meant to import?* — which the bounding box in the
row above it cannot: a box says nothing about whether the wrong body was
exported, whether half the assembly is missing, or whether the surface came out
inside out.

**It also answers "which face is that?"**, because the names of an imported
surface's regions become the patches of the generated mesh, and pointing at a
face on the model is the only way to give one a name that does not require
knowing what the exporter happened to call it. Turning and picking share a mouse
button, so they are told apart by how far the pointer travelled between press and
release — a turn that ends over a face must not also select it.

**All the arithmetic is in :mod:`foamwb.services.preview`.** This widget receives
finished polygons and fills them, which is what keeps the projection testable
without a display and the service layer free of Qt (NFR-M1).

**The file is read once and projected many times.** A drag re-projects the
triangles already in memory; re-reading megabytes off disk per mouse move is the
kind of thing NFR-P3 exists to prevent, in the one place a user is most likely to
be moving something continuously.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from foamwb.services.preview import Facet, Sample, pick, project, read_triangles
from foamwb.ui.theme import Palette

__all__ = ["SurfacePreview"]

#: Tall enough that a typical body is recognisable rather than a smudge, short
#: enough to leave the meshing controls below it on screen without scrolling.
_MINIMUM_HEIGHT = 190

#: How far a drag of one pixel turns the model, in radians. Tuned so a drag
#: across the widget is a little over half a turn — enough to get behind the
#: model in one gesture, slow enough to aim.
_RADIANS_PER_PIXEL = 0.012

#: Where the model is seen from before anyone drags it: a three-quarter view,
#: which shows three faces of a box and so reads as solid immediately. A face-on
#: view is ambiguous between a cube and a square.
_START_YAW = 0.6
_START_PITCH = -1.1

#: How far the pointer may move between press and release and still count as a
#: click rather than a turn.
#:
#: The two gestures share a button, so one of them has to yield. A few pixels of
#: travel is what a deliberate click on a trackpad actually produces, and a
#: threshold of zero would make selection impossible for anyone whose hand moves
#: — while a large one would select a face every time a user let go of a drag.
_CLICK_SLOP = 4.0


class SurfacePreview(QWidget):
    """Draw one imported surface, turnable and — where the faces are known —
    clickable."""

    selection_changed = Signal()
    """The set of picked faces changed, by a click or by being cleared."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._sample: Sample | None = None
        self._name = ""
        self._message = ""
        """What to say instead of the default when there is nothing to draw."""
        self._yaw = _START_YAW
        self._pitch = _START_PITCH
        self._drag_from: QPointF | None = None
        self._press_at: QPointF | None = None
        self._selected: set[int] = set()
        self._hover: int | None = None
        #: What was last painted, which is what a click is tested against.
        #:
        #: Picking has to use the *same* projection the user is looking at.
        #: Re-projecting on click would be correct only as long as nothing about
        #: the view had changed since the paint, and would silently pick the
        #: wrong face the first time that stopped being true.
        self._facets: tuple[Facet, ...] = ()
        #: Face -> region name, so a named face can be drawn as one.
        self._names: dict[int, str] = {}
        self._colours: dict[str, str] = {}

        self.setMouseTracking(True)

        self.setMinimumHeight(_MINIMUM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName(labels["preview_accessible"])
        self.setToolTip(labels["preview_hint"])

    # -- content -----------------------------------------------------------

    def set_surface(self, path: Path | None, name: str = "") -> None:
        """Show a surface file, or nothing. Reading happens here, once."""
        self.set_sample(None if path is None else read_triangles(path), name)

    def set_sample(self, sample: Sample | None, name: str = "", *, message: str = "") -> None:
        """Show triangles someone else read.

        The mesh arrives this way (DEC-23): its boundary is assembled from three
        files by :mod:`foamwb.services.polymesh` and is no more this widget's to
        read than an STL is. ``message`` replaces the empty-state sentence, so a
        mesh that was refused for being too large says *that* rather than
        "nothing to show", which would be true and useless.
        """
        self._name = name
        self._message = message
        self._sample = sample
        # Face ids mean "the nth group found in this file", so they say nothing
        # about a different file. Carrying a selection across would highlight
        # whichever faces of the new model happened to land on the old numbers.
        self._selected.clear()
        self._hover = None
        self._facets = ()
        self._names = {}
        # The view angle is reset with the model rather than kept. A user who
        # turned the last surface upside down and then imported a new one would
        # otherwise be shown the new one upside down, and read that as a fault
        # in the file they just chose.
        self._yaw = _START_YAW
        self._pitch = _START_PITCH
        self.update()

    def clear(self) -> None:
        self.set_surface(None)

    # -- turning it --------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if self._sample is not None and self._sample.triangles:
            self._drag_from = event.position()
            self._press_at = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None:
            self._update_hover(event.position())
            return
        delta = event.position() - self._drag_from
        self._drag_from = event.position()
        self._yaw += delta.x() * _RADIANS_PER_PIXEL
        # Clamped just short of straight down, where the model would flip
        # through itself and the drag would appear to reverse direction.
        limit = math.pi / 2 - 0.01
        self._pitch = max(
            -math.pi + limit, min(-limit, self._pitch - delta.y() * _RADIANS_PER_PIXEL)
        )
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        # A turn that ends over a face must not also select it, so the two are
        # told apart by how far the pointer travelled rather than by which button
        # was used — there is only one button on the hardware this has to work on.
        pressed, self._press_at, self._drag_from = self._press_at, None, None
        if pressed is None:
            return
        travel = event.position() - pressed
        if abs(travel.x()) > _CLICK_SLOP or abs(travel.y()) > _CLICK_SLOP:
            return
        self._click(event)

    def _click(self, event) -> None:
        face = pick(self._facets, event.position().x(), event.position().y())
        if face is None:
            # Clicking the background clears, which is the gesture every list and
            # canvas already has. Without it, deselecting means finding and
            # re-clicking each face, and a mis-click cannot be taken back.
            if self._selected:
                self._selected.clear()
                self.update()
                self.selection_changed.emit()
            return

        # Shift accumulates; a plain click replaces. Naming six faces at once is
        # the common case for a duct, and making every one of them a separate
        # name-and-confirm would be six times the work for one answer.
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._selected.symmetric_difference_update({face})
        else:
            self._selected = {face}
        self.update()
        self.selection_changed.emit()

    def _update_hover(self, position: QPointF) -> None:
        """Light the face under the pointer, so aiming is possible before clicking.

        Without it a user cannot tell what a click will select until after it has
        selected it — and with face groups, what counts as "one face" is the
        thing they most need shown rather than explained.
        """
        face = pick(self._facets, position.x(), position.y())
        if face != self._hover:
            self._hover = face
            self.update()

    def leaveEvent(self, _event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()

    # -- selection ---------------------------------------------------------

    def set_region_names(self, names: dict[int, str], colours: dict[str, str]) -> None:
        """Colour faces by the region they have been given."""
        self._names = dict(names)
        self._colours = dict(colours)
        self.update()

    def clear_selection(self) -> None:
        if self._selected:
            self._selected.clear()
            self.update()
            self.selection_changed.emit()

    # -- drawing -----------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self._palette.bg))
        painter.setPen(QColor(self._palette.border))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self._sample is None or not self._sample.triangles:
            painter.setPen(QColor(self._palette.text_muted))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self._message or self._labels["preview_none"],
            )
            painter.end()
            return

        self._facets = project(
            self._sample.triangles,
            width=self.width(),
            height=self.height(),
            yaw=self._yaw,
            pitch=self._pitch,
            faces=self._sample.faces,
        )
        # Outlined in its *own* fill colour, not a contrasting one. A contrasting
        # edge on twenty thousand triangles covers the fill entirely and the
        # model reads as a grey block, which is why this was NoPen — but NoPen
        # leaves a hairline of background between neighbouring triangles that
        # antialiasing cannot close, and on a mesh, whose faces are split into
        # pairs of triangles, those hairlines draw the diagonals of every cell.
        # A same-colour pen closes the seam and states nothing.
        for facet in self._facets:
            colour = self._shaded(self._base_colour(facet.face), facet.shade)
            painter.setBrush(colour)
            painter.setPen(colour)
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in facet.points]))

        if self._sample.is_partial:
            painter.setPen(QColor(self._palette.text_muted))
            painter.drawText(
                self.rect().adjusted(8, 0, -8, -6),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                self._labels["preview_thinned"].format(
                    f"{len(self._sample.triangles):,}", f"{self._sample.total:,}"
                ),
            )
        painter.end()

    def _base_colour(self, face: int) -> QColor:
        """What colour this face is before the lighting is applied.

        Selection wins over the region name, and the region name over the plain
        accent. That order is what makes "these are the ones I am about to name"
        readable on a model where most faces already carry a name — the opposite
        order would hide the selection inside the colouring.

        Colour is never the only statement (NFR-A2): the selection is also
        counted in words beside the picture, and every named region is listed by
        name. What the colour adds is *which* — a thing a list cannot say about a
        shape.
        """
        if face in self._selected:
            return QColor(self._palette.focus)
        name = self._names.get(face)
        if name and name in self._colours:
            return QColor(self._colours[name])
        if face == self._hover:
            # Halfway to the selection colour: enough to aim by, not enough to be
            # mistaken for a face that has actually been picked.
            return self._blend(QColor(self._palette.accent), QColor(self._palette.focus), 0.4)
        return QColor(self._palette.accent)

    @staticmethod
    def _blend(first: QColor, second: QColor, mix: float) -> QColor:
        return QColor(
            round(first.red() + (second.red() - first.red()) * mix),
            round(first.green() + (second.green() - first.green()) * mix),
            round(first.blue() + (second.blue() - first.blue()) * mix),
        )

    def _shaded(self, base: QColor, shade: float) -> QColor:
        """Darken the accent towards the window background by the lighting.

        Interpolating towards the *background* rather than to black keeps the
        shaded side of the model inside the theme — on the dark palette a fade
        to black would put the model's far side into the window it sits in.
        """
        ground = QColor(self._palette.bg)
        mix = max(0.0, min(1.0, shade))
        return QColor(
            round(ground.red() + (base.red() - ground.red()) * mix),
            round(ground.green() + (base.green() - ground.green()) * mix),
            round(ground.blue() + (base.blue() - ground.blue()) * mix),
        )

    # -- for tests ---------------------------------------------------------

    @property
    def triangle_count(self) -> int:
        return 0 if self._sample is None else len(self._sample.triangles)

    @property
    def showing(self) -> str:
        return self._name

    @property
    def angles(self) -> tuple[float, float]:
        return self._yaw, self._pitch

    @property
    def face_count(self) -> int:
        return 0 if self._sample is None else self._sample.face_count

    @property
    def faces_known(self) -> bool:
        return self._sample is not None and self._sample.faces_known

    @property
    def selected(self) -> tuple[int, ...]:
        return tuple(sorted(self._selected))

    @property
    def hovered(self) -> int | None:
        return self._hover

    def face_at(self, x: float, y: float) -> int | None:
        """Which face is at this point of the last painted frame."""
        return pick(self._facets, x, y)

    def select(self, faces: tuple[int, ...] | list[int]) -> None:
        """Set the selection directly, for tests and for the region list."""
        self._selected = set(faces)
        self.update()
        self.selection_changed.emit()
