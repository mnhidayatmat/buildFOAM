"""Drawn icons for the ribbon (§7.1, NFR-A3).

**These were Unicode glyphs and that was a mistake.** A glyph is only an icon if
the platform's interface font happens to have it, and several did not: *Outline*
and *Task Page* drew ``▯`` — the replacement box — on macOS, which is to say the
ribbon shipped with tofu in it. Others that did resolve came out at unrelated
weights and optical sizes, because ``⚙`` and ``∿`` and ``▤`` are from different
parts of Unicode drawn by different designers for different purposes, and no
amount of style sheet makes them a set.

So they are drawn here instead: a stroke path per icon in a 0…1 coordinate
space, rendered at the size and colour asked for. That satisfies NFR-A3 by
construction — there is no raster asset to supply at 2x — and it gives the one
thing a borrowed glyph cannot, which is a **consistent stroke weight** across
the whole ribbon. Colour comes from the palette at call time, so the dark theme
needs no second set of artwork.

Nothing here is Ansys's artwork (§13.3). They are the ordinary shapes this kind
of software has used for thirty years — a play triangle, a cube, a grid — drawn
from scratch.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

__all__ = ["ICONS", "ICON_SIZE", "icon_names", "vector_icon"]

#: Logical size of a ribbon icon, in pixels. Large enough to read as an icon
#: rather than a mark, small enough for eight groups across a 1280-pixel window.
ICON_SIZE = 22

#: Rendered at twice the logical size, so a Retina display has real pixels to
#: use and Qt downsamples for the rest. NFR-A3's "no raster below 2x", met by
#: drawing rather than by shipping two files.
_SCALE = 2

#: Stroke width in the 0…1 space. One weight for every icon is the whole point
#: of drawing them: a set that varies in weight reads as clip art.
_STROKE = 0.085

#: A path is a list of instructions in a 0…1 box.
#: ``("m", x, y)`` move, ``("l", x, y)`` line, ``("z",)`` close,
#: ``("c", cx, cy, r)`` circle, ``("r", x, y, w, h)`` rectangle,
#: ``("f",)`` fill what has been drawn so far rather than stroking it.
Instruction = tuple


def _grid(columns: int, rows: int, inset: float = 0.14) -> list[Instruction]:
    """A rectangle ruled into cells — the mesh mark."""
    out: list[Instruction] = [("r", inset, inset, 1 - 2 * inset, 1 - 2 * inset)]
    span = 1 - 2 * inset
    for column in range(1, columns):
        x = inset + span * column / columns
        out += [("m", x, inset), ("l", x, 1 - inset)]
    for row in range(1, rows):
        y = inset + span * row / rows
        out += [("m", inset, y), ("l", 1 - inset, y)]
    return out


def _panel(x: float, y: float, w: float, h: float) -> list[Instruction]:
    """A window with one region filled — the show/hide-a-panel marks."""
    return [("r", 0.1, 0.14, 0.8, 0.72), ("r", x, y, w, h), ("f",)]


#: Every icon the ribbon can ask for. Names are stable identifiers, never shown.
ICONS: dict[str, list[Instruction]] = {
    # -- meshing -----------------------------------------------------------
    "check": [("m", 0.16, 0.53), ("l", 0.40, 0.76), ("l", 0.84, 0.24)],
    "grid": _grid(3, 3),
    "import": [
        ("m", 0.5, 0.12),
        ("l", 0.5, 0.62),
        ("m", 0.29, 0.42),
        ("l", 0.5, 0.63),
        ("l", 0.71, 0.42),
        ("m", 0.16, 0.84),
        ("l", 0.84, 0.84),
    ],
    "inward": [
        ("r", 0.12, 0.12, 0.76, 0.76),
        ("m", 0.26, 0.26),
        ("l", 0.52, 0.52),
        ("m", 0.26, 0.44),
        ("l", 0.26, 0.26),
        ("l", 0.44, 0.26),
    ],
    "sizing": [
        ("r", 0.14, 0.14, 0.72, 0.72),
        ("m", 0.5, 0.14),
        ("l", 0.5, 0.86),
        ("m", 0.14, 0.5),
        ("l", 0.86, 0.5),
        ("r", 0.14, 0.14, 0.36, 0.36),
        ("f",),
    ],
    "boundary": [("r", 0.12, 0.26, 0.76, 0.48)],
    "cube": [
        ("m", 0.5, 0.12),
        ("l", 0.87, 0.31),
        ("l", 0.87, 0.69),
        ("l", 0.5, 0.88),
        ("l", 0.13, 0.69),
        ("l", 0.13, 0.31),
        ("z",),
        ("m", 0.13, 0.31),
        ("l", 0.5, 0.5),
        ("l", 0.87, 0.31),
        ("m", 0.5, 0.5),
        ("l", 0.5, 0.88),
    ],
    # -- physics -----------------------------------------------------------
    "gear": [
        ("c", 0.5, 0.5, 0.20),
        ("m", 0.5, 0.08),
        ("l", 0.5, 0.22),
        ("m", 0.5, 0.78),
        ("l", 0.5, 0.92),
        ("m", 0.08, 0.5),
        ("l", 0.22, 0.5),
        ("m", 0.78, 0.5),
        ("l", 0.92, 0.5),
        ("m", 0.20, 0.20),
        ("l", 0.30, 0.30),
        ("m", 0.70, 0.70),
        ("l", 0.80, 0.80),
        ("m", 0.80, 0.20),
        ("l", 0.70, 0.30),
        ("m", 0.30, 0.70),
        ("l", 0.20, 0.80),
    ],
    "wave": [
        ("m", 0.10, 0.62),
        ("l", 0.26, 0.36),
        ("l", 0.42, 0.62),
        ("l", 0.58, 0.36),
        ("l", 0.74, 0.62),
        ("l", 0.90, 0.36),
    ],
    "layers": [
        ("m", 0.5, 0.14),
        ("l", 0.88, 0.35),
        ("l", 0.5, 0.56),
        ("l", 0.12, 0.35),
        ("z",),
        ("m", 0.12, 0.55),
        ("l", 0.5, 0.76),
        ("l", 0.88, 0.55),
    ],
    "lines": [
        ("m", 0.14, 0.30),
        ("l", 0.86, 0.30),
        ("m", 0.14, 0.50),
        ("l", 0.86, 0.50),
        ("m", 0.14, 0.70),
        ("l", 0.60, 0.70),
    ],
    "table": [
        ("r", 0.12, 0.16, 0.76, 0.68),
        ("m", 0.12, 0.38),
        ("l", 0.88, 0.38),
        ("m", 0.44, 0.38),
        ("l", 0.44, 0.84),
    ],
    # -- solution ----------------------------------------------------------
    "curve": [("m", 0.14, 0.84), ("l", 0.34, 0.40), ("l", 0.58, 0.62), ("l", 0.88, 0.18)],
    "sliders": [
        ("m", 0.12, 0.32),
        ("l", 0.88, 0.32),
        ("m", 0.12, 0.68),
        ("l", 0.88, 0.68),
        ("c", 0.36, 0.32, 0.11),
        ("c", 0.66, 0.68, 0.11),
    ],
    "target": [("c", 0.5, 0.5, 0.36), ("c", 0.5, 0.5, 0.13), ("f",)],
    "refresh": [
        ("m", 0.84, 0.5),
        ("a", 0.5, 0.5, 0.34, 0, 290),
        ("m", 0.62, 0.10),
        ("l", 0.86, 0.18),
        ("l", 0.78, 0.42),
    ],
    "seed": [
        ("r", 0.12, 0.12, 0.76, 0.76),
        ("c", 0.33, 0.33, 0.07),
        ("c", 0.67, 0.33, 0.07),
        ("c", 0.33, 0.67, 0.07),
        ("c", 0.67, 0.67, 0.07),
        ("f",),
    ],
    "clock": [("c", 0.5, 0.5, 0.36), ("m", 0.5, 0.28), ("l", 0.5, 0.52), ("l", 0.70, 0.62)],
    "clipboard": [
        ("r", 0.20, 0.16, 0.60, 0.70),
        ("r", 0.36, 0.08, 0.28, 0.14),
        ("m", 0.32, 0.54),
        ("l", 0.45, 0.67),
        ("l", 0.70, 0.36),
    ],
    "play": [("m", 0.26, 0.14), ("l", 0.84, 0.5), ("l", 0.26, 0.86), ("z",), ("f",)],
    "stop": [("r", 0.22, 0.22, 0.56, 0.56), ("f",)],
    # -- results -----------------------------------------------------------
    "diamond": [("m", 0.5, 0.10), ("l", 0.90, 0.5), ("l", 0.5, 0.90), ("l", 0.10, 0.5), ("z",)],
    "chart": [
        ("m", 0.14, 0.14),
        ("l", 0.14, 0.86),
        ("l", 0.86, 0.86),
        ("m", 0.26, 0.68),
        ("l", 0.44, 0.44),
        ("l", 0.60, 0.58),
        ("l", 0.82, 0.26),
    ],
    "document": [
        ("m", 0.24, 0.10),
        ("l", 0.62, 0.10),
        ("l", 0.78, 0.28),
        ("l", 0.78, 0.90),
        ("l", 0.24, 0.90),
        ("z",),
        ("m", 0.37, 0.46),
        ("l", 0.65, 0.46),
        ("m", 0.37, 0.62),
        ("l", 0.65, 0.62),
    ],
    "export": [
        ("m", 0.5, 0.12),
        ("l", 0.5, 0.62),
        ("m", 0.29, 0.42),
        ("l", 0.5, 0.63),
        ("l", 0.71, 0.42),
        ("m", 0.14, 0.86),
        ("l", 0.86, 0.86),
    ],
    # -- view --------------------------------------------------------------
    "home": [
        ("m", 0.10, 0.50),
        ("l", 0.5, 0.14),
        ("l", 0.90, 0.50),
        ("m", 0.20, 0.44),
        ("l", 0.20, 0.86),
        ("l", 0.80, 0.86),
        ("l", 0.80, 0.44),
    ],
    "panel_left": _panel(0.1, 0.14, 0.28, 0.72),
    "panel_bottom_left": _panel(0.1, 0.58, 0.28, 0.28),
    "panel_bottom": _panel(0.1, 0.62, 0.8, 0.24),
    "sun": [
        ("c", 0.5, 0.5, 0.21),
        ("m", 0.5, 0.06),
        ("l", 0.5, 0.16),
        ("m", 0.5, 0.84),
        ("l", 0.5, 0.94),
        ("m", 0.06, 0.5),
        ("l", 0.16, 0.5),
        ("m", 0.84, 0.5),
        ("l", 0.94, 0.5),
        ("m", 0.16, 0.16),
        ("l", 0.24, 0.24),
        ("m", 0.76, 0.76),
        ("l", 0.84, 0.84),
        ("m", 0.84, 0.16),
        ("l", 0.76, 0.24),
        ("m", 0.24, 0.76),
        ("l", 0.16, 0.84),
    ],
    "moon": [
        ("m", 0.70, 0.16),
        ("a", 0.5, 0.5, 0.38, 58, 244),
        ("a", 0.34, 0.5, 0.38, -58, 116),
        ("z",),
    ],
    "contrast": [("c", 0.5, 0.5, 0.36), ("m", 0.5, 0.14), ("l", 0.5, 0.86)],
    "help": [
        ("c", 0.5, 0.5, 0.37),
        ("m", 0.36, 0.40),
        ("a", 0.5, 0.40, 0.14, 180, -180),
        ("l", 0.5, 0.62),
        ("m", 0.5, 0.74),
        ("l", 0.5, 0.75),
    ],
}


def icon_names() -> Sequence[str]:
    """Every drawing this module can produce. The ribbon's table is checked
    against it, so an action naming an icon that does not exist fails a test
    rather than shipping a blank button."""
    return tuple(ICONS)


def _build(instructions: list[Instruction], size: float) -> tuple[QPainterPath, QPainterPath]:
    """Turn instructions into a path to stroke and a path to fill."""
    stroke, fill = QPainterPath(), QPainterPath()
    target, filling = stroke, False
    for step in instructions:
        if step[0] == "f":
            # Everything drawn so far is a solid, not an outline. Written as a
            # trailing instruction so a shape can be described once and then
            # said to be filled, rather than described twice.
            fill.addPath(stroke)
            stroke = QPainterPath()
            target, filling = stroke, True
            continue
        if step[0] == "m":
            target.moveTo(step[1] * size, step[2] * size)
        elif step[0] == "l":
            target.lineTo(step[1] * size, step[2] * size)
        elif step[0] == "z":
            target.closeSubpath()
        elif step[0] == "c":
            _, x, y, r = step
            target.addEllipse(QPointF(x * size, y * size), r * size, r * size)
        elif step[0] == "r":
            _, x, y, w, h = step
            target.addRect(QRectF(x * size, y * size, w * size, h * size))
        elif step[0] == "a":
            _, x, y, r, start, span = step
            box = QRectF((x - r) * size, (y - r) * size, 2 * r * size, 2 * r * size)
            target.arcTo(box, start, span)
    if filling:
        fill.addPath(stroke)
        return QPainterPath(), fill
    return stroke, fill


@lru_cache(maxsize=512)
def vector_icon(name: str, colour: str, size: int = ICON_SIZE) -> QIcon:
    """The named drawing, in ``colour``.

    Cached: the ribbon asks for every icon again on each palette change, and
    building a path per button per repaint is work with one possible answer.
    """
    instructions = ICONS.get(name)
    pixmap = QPixmap(size * _SCALE, size * _SCALE)
    pixmap.setDevicePixelRatio(_SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    if instructions is None:
        return QIcon(pixmap)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    stroke, fill = _build(instructions, size)

    pen = QPen(QColor(colour))
    pen.setWidthF(_STROKE * size)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(stroke)

    if not fill.isEmpty():
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colour))
        painter.drawPath(fill)
    painter.end()
    return QIcon(pixmap)
