"""Which palette to paint, given the user's choice and the desktop (NFR-A4).

Its own module because two callers need the same answer and neither can own it.
:mod:`foamwb.ui.app` needs a palette *before* the shell exists, to style the
application; :class:`~foamwb.ui.shell.Shell` needs one *after*, every time the
user changes the setting or the desktop changes underneath them. Putting the
mapping in either would mean the other imported it, and the shell importing the
entry point is a cycle.

It also cannot live in :mod:`foamwb.ui.theme`, which is deliberately free of Qt
so the WCAG contrast check runs without a display or a ``QApplication``. Asking
the desktop what it is doing is unavoidably a Qt question, so it is asked here
and the palettes stay plain data.

**Light is the fallback whenever the answer is unavailable.** Older Qt has no
``colorScheme()``, and a headless session has no desktop to ask. A light UI on a
dark desktop is merely jarring; a dark UI on a light desktop can be unreadable,
because the platform paints its own light background behind anything the style
sheet does not cover.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from foamwb.services.settings import ThemeChoice
from foamwb.ui.theme import DARK, LIGHT, Palette

__all__ = ["palette_for_scheme", "resolve_palette", "system_is_dark"]


def system_is_dark(application: QGuiApplication | None = None) -> bool:
    """Whether the desktop is currently in dark mode.

    ``getattr`` rather than a version check: Qt gained ``colorScheme()`` in 6.5
    and the project floor is 6.9, but the probe costs nothing and keeps a
    downgraded environment rendering a legible window instead of raising on
    startup.
    """
    application = application or QGuiApplication.instance()
    if application is None:
        return False
    hints = application.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    return scheme is not None and scheme() == Qt.ColorScheme.Dark


def palette_for_scheme(application: QGuiApplication | None = None) -> Palette:
    """The palette the *desktop* implies, ignoring any stored preference."""
    return DARK if system_is_dark(application) else LIGHT


def resolve_palette(
    choice: ThemeChoice,
    application: QGuiApplication | None = None,
) -> Palette:
    """The palette to paint for a choice.

    An explicit Light or Dark is honoured even when it disagrees with the
    desktop — that disagreement is the entire reason the setting exists, and a
    toggle that quietly deferred to the OS would be a toggle that does nothing
    for the user who most wanted it.
    """
    if choice is ThemeChoice.LIGHT:
        return LIGHT
    if choice is ThemeChoice.DARK:
        return DARK
    return palette_for_scheme(application)
