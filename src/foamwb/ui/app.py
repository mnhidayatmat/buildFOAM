"""Application entry point.

Lives in the presentation layer because it constructs a ``QApplication``; a
``foamwb/__main__.py`` would put a Qt import outside ``ui/`` and breach NFR-M1.

NFR-P1 gives cold start to an interactive Hub a 3-second budget on the reference
machine, which is why nothing here touches the filesystem beyond opening the log
and nothing blocks on runtime detection. Detection is deliberately *not* run
before the window appears: probing for OpenFOAM can take seconds on a cold WSL
distribution, and a splash screen that hides an empty window is still an empty
window. The shell opens immediately in its honest "not detected yet" state and is
updated when the answer arrives.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from foamwb import __version__
from foamwb.branding import APP_DISPLAY_NAME, APP_ID
from foamwb.logs import Event, configure, get_logger, log_event
from foamwb.paths import log_dir
from foamwb.ui.probe import RuntimeProbe
from foamwb.ui.shell import Shell
from foamwb.ui.theme import DARK, LIGHT, Palette, stylesheet

__all__ = ["main"]


def palette_for_scheme(application: QApplication) -> Palette:
    """Pick the palette matching the OS appearance (NFR-A4).

    Qt reports the system colour scheme directly on 6.5+, so light and dark follow
    the OS setting without the app owning a preference the user has already
    expressed elsewhere.
    """
    hints = application.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None and scheme() == Qt.ColorScheme.Dark:
        return DARK
    return LIGHT


def build_application(argv: list[str] | None = None) -> tuple[QApplication, Shell]:
    """Construct the application and its shell, without entering the event loop.

    Split out from :func:`main` so a test can build the real window, assert
    against it, and tear it down without the process blocking forever in
    ``exec()``.
    """
    # Must precede construction of the QGuiApplication — Qt warns and ignores it
    # otherwise, so a fractional-scaling display would round to whole factors and
    # the UI would be subtly the wrong size at 125% and 150% (NFR-A3).
    if QApplication.instance() is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    application = QApplication.instance() or QApplication(argv or sys.argv)
    assert isinstance(application, QApplication)

    application.setApplicationName(APP_DISPLAY_NAME)
    application.setApplicationVersion(__version__)
    application.setOrganizationDomain(f"{APP_ID}.local")

    palette = palette_for_scheme(application)
    application.setStyleSheet(stylesheet(palette))

    shell = Shell(palette)
    return application, shell


def main(argv: list[str] | None = None) -> int:
    configure(log_dir(), level=logging.INFO)
    log = get_logger("ui.app")
    log_event(log, Event.APP_START, version=__version__)

    application, shell = build_application(argv)
    shell.show()

    # Detection starts only after the window is up, so the three-second budget
    # buys an interactive Hub rather than a probe the user did not ask for. The
    # footer corrects itself when the answer arrives (FR-A2 allows one second for
    # that, measured from the state change, not from launch).
    probe = RuntimeProbe()
    probe.finished.connect(shell.apply_runtime_status)
    probe.start()

    try:
        code = application.exec()
    finally:
        probe.stop()
        # Logged in a finally block so an abnormal exit still records that the
        # session ended, which is what makes a truncated diagnostics bundle
        # distinguishable from a crash (FR-A4, FR-A7).
        log_event(log, Event.APP_STOP)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
