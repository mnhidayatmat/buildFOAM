"""The persistent status footer (FR-A2, §7.1).

"The status footer never lies" is §7.9's fourth interaction principle, and it is
the reason this widget renders from a :class:`RuntimeStatus` value rather than
from strings its callers assemble. A caller cannot forget to update it, and it
cannot show *ready* while holding an error code, because
:class:`~foamwb.services.runtime.status.RuntimeStatus` refuses to be constructed
that way (FR-R2).

The runtime indicator is a button, not a label: §7.1 requires clicking it to jump
to Setup. That also makes it keyboard-reachable, which a label would not be
(NFR-A1).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from foamwb.services.runtime import RuntimeStatus
from foamwb.ui.theme import Palette, status_glyph

__all__ = ["StatusFooter"]


class StatusFooter(QFrame):
    """Always-visible strip: runtime state, OpenFOAM version, case, run state."""

    setup_requested = Signal()
    """Emitted when the user activates the runtime indicator (§7.1)."""

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusFooter")
        self._palette = palette

        self._indicator = QToolButton()
        self._indicator.setObjectName("runtimeIndicator")
        self._indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self._indicator.clicked.connect(self.setup_requested)
        self._indicator.setToolTip(self.tr("Go to Setup"))

        self._version = QLabel()
        self._case = QLabel()
        self._run_state = QLabel()
        for label in (self._version, self._case, self._run_state):
            label.setProperty("role", "muted")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 12, 4)
        layout.setSpacing(10)
        layout.addWidget(self._indicator)
        layout.addWidget(self._separator())
        layout.addWidget(self._version)
        layout.addWidget(self._separator())
        layout.addWidget(self._case)
        layout.addStretch(1)
        layout.addWidget(self._run_state)

        self.set_case(None)
        self.set_run_state(None)

    def _separator(self) -> QLabel:
        dot = QLabel("·")
        dot.setProperty("role", "muted")
        return dot

    # -- state -------------------------------------------------------------

    def set_runtime_status(self, status: RuntimeStatus) -> None:
        """Render a runtime status.

        Colour, glyph *and* text all change together — NFR-A2 forbids colour as
        the sole carrier of meaning, so this reads correctly in greyscale and to a
        colourblind user. A non-ready state also shows its §9 code, because that
        is what turns a support conversation into something that starts from a
        code rather than a screenshot.
        """
        state = status.state.value
        labels = {
            "ready": self.tr("Runtime ready"),
            "degraded": self.tr("Runtime degraded"),
            "missing": self.tr("Runtime not installed"),
            "broken": self.tr("Runtime broken"),
        }
        text = labels.get(state, self.tr("Runtime unknown"))
        if status.reason is not None:
            text = f"{text} ({status.reason.id})"

        # A format string rather than an f-string, so a right-to-left locale can
        # put the glyph after the label (NFR-A5).
        self._indicator.setText(self.tr("{0}  {1}").format(status_glyph(state), text))
        colour = getattr(self._palette, state, self._palette.text_muted)
        self._indicator.setStyleSheet(f"#runtimeIndicator {{ color: {colour}; }}")

        # The accessible name carries the same information as the glyph, so a
        # screen reader is not told to interpret a bullet character.
        self._indicator.setAccessibleName(text)

    def set_openfoam_version(self, version: str | None) -> None:
        # Never a literal in code — the version comes from the runtime manifest
        # via the canary command (NFR-M3, FR-R5).
        self._version.setText(
            self.tr("OpenFOAM {0}").format(version) if version else self.tr("No OpenFOAM detected")
        )

    def set_case(self, case_name: str | None) -> None:
        self._case.setText(case_name if case_name else self.tr("No case open"))

    def set_run_state(self, run_state: str | None) -> None:
        self._run_state.setText(run_state if run_state else self.tr("idle"))

    # -- for tests ---------------------------------------------------------

    @property
    def runtime_text(self) -> str:
        return self._indicator.text()

    @property
    def version_text(self) -> str:
        return self._version.text()

    @property
    def case_text(self) -> str:
        return self._case.text()

    @property
    def run_state_text(self) -> str:
        return self._run_state.text()
