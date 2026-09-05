"""Glyph icons for the ribbon (NFR-A3).

§7.1 asks for icon-plus-label buttons and NFR-A3 forbids rasterised assets that
are not supplied at 2x. A glyph drawn into a pixmap *at the screen's own device
pixel ratio* satisfies both: it is resolution-independent by construction and
takes its colour from the palette, so a dark theme does not ship a second set of
artwork. Drawn once per glyph and cached, because the ribbon asks for the same
forty icons on every repaint of the palette.

Nothing here is Fluent's artwork. Fluent's icons are its own (§13.3); these are
Unicode glyphs in the interface font.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

__all__ = ["glyph_icon"]

#: Logical size of a ribbon icon. Large enough to read as an icon rather than a
#: character, small enough for eight groups to fit across a 1280-pixel window.
ICON_SIZE = 26

#: Device pixel ratio the pixmap is rendered at. 2x covers every display the
#: application supports without blur; Qt downsamples for 1x screens.
_SCALE = 2


@lru_cache(maxsize=256)
def glyph_icon(glyph: str, colour: str, size: int = ICON_SIZE) -> QIcon:
    """An icon showing ``glyph`` in ``colour``."""
    pixmap = QPixmap(size * _SCALE, size * _SCALE)
    pixmap.setDevicePixelRatio(_SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont()
    font.setPixelSize(int(size * 0.72))
    painter.setFont(font)
    painter.setPen(QColor(colour))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)
