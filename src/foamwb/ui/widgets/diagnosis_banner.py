"""The divergence banner (FR-S6).

Sits above the log and says, in one sentence, that the solution stopped being
physical — while the run is still going. §6.9's argument applies with particular
force here: a diverging run does not look broken. Residuals keep printing, time
keeps advancing, and OpenFOAM says nothing, because it has nothing to say — the
installed libraries contain no divergence message at all.

**It offers the stop, rather than only the news.** The user has just been told
the remaining hours of the run are worthless; making them go and find the stop
control would be an odd place to stop helping. §7.9 rule 3 asks that a finding
carry its remedy.

Hedged findings say so. A ``nan`` is a fact; a high Courant number is a
suspicion, and the banner's title changes accordingly rather than presenting both
with equal confidence.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from foamwb.services.run.diagnosis import Confidence, Diagnosis
from foamwb.ui.theme import Palette

__all__ = ["DiagnosisBanner"]


class DiagnosisBanner(QFrame):
    """One finding about the running solution, with what to do about it."""

    stop_requested = Signal()
    guide_requested = Signal(str)
    """Carries the guide anchor (FR-G2), so the shell decides how to open it."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._diagnosis: Diagnosis | None = None

        self.setObjectName("diagnosisBanner")
        self.setFrameShape(QFrame.Shape.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = QLabel()
        self._title.setProperty("role", "heading")
        header.addWidget(self._title)
        header.addStretch(1)

        self._code = QLabel()
        self._code.setProperty("role", "muted")
        header.addWidget(self._code)
        outer.addLayout(header)

        self._message = QLabel()
        self._message.setWordWrap(True)
        outer.addWidget(self._message)

        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setProperty("role", "muted")
        outer.addWidget(self._detail)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        self._guide = QPushButton(labels["why_this"])
        self._guide.clicked.connect(self._open_guide)
        actions.addWidget(self._guide)

        self._stop = QPushButton(labels["stop_write"])
        self._stop.setToolTip(labels["stop_write_tip"])
        self._stop.clicked.connect(self.stop_requested)
        actions.addWidget(self._stop)

        self._dismiss = QPushButton(labels["dismiss"])
        self._dismiss.clicked.connect(self.clear)
        actions.addWidget(self._dismiss)

        outer.addLayout(actions)

        self.set_palette(palette)
        self.hide()

    # -- content -----------------------------------------------------------

    def show_diagnosis(self, diagnosis: Diagnosis, *, running: bool = True) -> None:
        """Display a finding. ``running`` decides whether a stop is offered."""
        self._diagnosis = diagnosis
        suspected = diagnosis.confidence is Confidence.LIKELY
        self._title.setText(
            self._labels["diverging_suspected"] if suspected else self._labels["diverged_title"]
        )
        self._code.setText(
            self._labels["diagnosis_code"].format(diagnosis.code.id, diagnosis.code.condition)
        )
        self._message.setText(diagnosis.message)

        detail = diagnosis.detail
        if running:
            detail = (
                f"{detail}\n\n{self._labels['diverged_still_running']}"
                if detail
                else self._labels["diverged_still_running"]
            )
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        self._stop.setVisible(running)

        self.set_palette(self._palette)
        self.setAccessibleName(
            self._labels["diagnosis_accessible"].format(self._title.text(), diagnosis.message)
        )
        self.show()

    def clear(self) -> None:
        self._diagnosis = None
        self.hide()

    def _open_guide(self) -> None:
        if self._diagnosis is not None:
            self.guide_requested.emit(self._diagnosis.guide_anchor)

    # -- appearance --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        """Restyle for the current theme.

        The border carries the confidence: ``broken`` for a measured divergence,
        ``degraded`` for a suspected one. Colour is never the only carrier of
        that distinction (NFR-A3) — the title says which it is in words — but
        making them look identical would flatten a difference the user needs.
        """
        self._palette = palette
        suspected = self._diagnosis is not None and self._diagnosis.confidence is Confidence.LIKELY
        edge = palette.degraded if suspected else palette.broken
        self.setStyleSheet(
            f"#diagnosisBanner {{"
            f"  background: {palette.surface_alt};"
            f"  border: 1px solid {edge};"
            f"  border-left: 4px solid {edge};"
            f"  border-radius: 6px;"
            f"}}"
        )

    # -- inspection --------------------------------------------------------

    @property
    def diagnosis(self) -> Diagnosis | None:
        return self._diagnosis

    @property
    def is_showing(self) -> bool:
        """Whether the banner is up.

        ``isVisibleTo`` rather than ``isVisible``: the latter is False for every
        descendant of a window that has never been shown, so a headless test
        would see a hidden banner no matter what this widget did.
        """
        parent = self.parentWidget()
        return self.isVisibleTo(parent) if parent is not None else not self.isHidden()

    @property
    def title_text(self) -> str:
        return self._title.text()

    @property
    def message_text(self) -> str:
        return self._message.text()

    @property
    def offers_stop(self) -> bool:
        return self._stop.isVisibleTo(self)
