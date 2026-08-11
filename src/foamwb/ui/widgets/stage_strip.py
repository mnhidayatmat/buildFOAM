"""The run plan as a horizontal stage strip (§7.5, FR-S1).

FR-S1 requires the plan to be displayed *before* launch, and §7.9 rule 2 forbids
hidden work — so the strip is populated from the plan the moment one is built,
with every stage visible and pending. Watching it fill in is how a user knows
what the application is doing and what it will do next.

Skipped stages are shown, not hidden. A serial plan skips ``decomposePar`` and
``reconstructPar``, and dropping them would mean the plan reviewed before launch
is not the plan watched during it.

State is carried by a glyph and a text label as well as colour (NFR-A2), which is
what keeps the strip readable in a screenshot attached to a support ticket.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from foamwb.services.run import RunPlan, StageState
from foamwb.ui.theme import Palette

__all__ = ["STATE_GLYPHS", "StageStrip"]

#: Distinct *shapes*, so the strip does not depend on colour vision or on colour
#: surviving a screenshot (NFR-A2).
STATE_GLYPHS: dict[StageState, str] = {
    StageState.PENDING: "○",
    StageState.RUNNING: "◐",
    StageState.SUCCEEDED: "●",
    StageState.FAILED: "✕",
    StageState.SKIPPED: "/",
    StageState.CANCELLED: "◼",
}


class StageStrip(QFrame):
    """One chip per stage, left to right in plan order."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stageStrip")
        self._palette = palette
        self._labels = labels
        self._chips: dict[str, _StageChip] = {}

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(8)

        self._empty = QLabel(labels["no_plan"])
        self._empty.setProperty("role", "muted")
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)

    def set_plan(self, plan: RunPlan) -> None:
        """Show a plan before it runs, every stage pending or skipped."""
        self._clear()
        self._empty.setVisible(False)

        for name, state in plan.stage_states().items():
            chip = _StageChip(name, self._palette, self._labels)
            chip.set_state(state)
            self._chips[name] = chip
            self._layout.insertWidget(self._layout.count() - 1, chip)

    def set_state(self, stage: str, state: StageState) -> None:
        chip = self._chips.get(stage)
        if chip is not None:
            chip.set_state(state)

    def clear(self) -> None:
        self._clear()
        self._empty.setVisible(True)

    def _clear(self) -> None:
        for chip in self._chips.values():
            self._layout.removeWidget(chip)
            chip.deleteLater()
        self._chips.clear()

    # -- for tests ---------------------------------------------------------

    @property
    def stage_names(self) -> list[str]:
        return list(self._chips)

    def state_of(self, stage: str) -> StageState | None:
        chip = self._chips.get(stage)
        return chip.state if chip is not None else None

    def text_of(self, stage: str) -> str:
        return self._chips[stage].text()


class _StageChip(QFrame):
    """One stage: glyph, name, and its state in words."""

    def __init__(self, name: str, palette: Palette, labels: dict[str, str]) -> None:
        super().__init__()
        self.setObjectName("stageChip")
        self._name = name
        self._palette = palette
        self._labels = labels
        self._state = StageState.PENDING

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(1)

        self._title = QLabel(name)
        self._title.setProperty("role", "subheading")
        self._status = QLabel()
        self._status.setProperty("role", "muted")

        layout.addWidget(self._title)
        layout.addWidget(self._status)

    def set_state(self, state: StageState) -> None:
        self._state = state
        label = self._labels[f"stage_{state.value}"]
        self._status.setText(self._labels["stage_chip"].format(STATE_GLYPHS[state], label))
        self._status.setStyleSheet(f"color: {self._colour_for(state)};")
        # The whole chip announces itself, so a screen reader reads "solve,
        # running" rather than a bullet followed by a word.
        self.setAccessibleName(self._labels["stage_accessible"].format(self._name, label))

    def _colour_for(self, state: StageState) -> str:
        return {
            StageState.PENDING: self._palette.text_muted,
            StageState.RUNNING: self._palette.accent,
            StageState.SUCCEEDED: self._palette.ready,
            StageState.FAILED: self._palette.broken,
            StageState.SKIPPED: self._palette.text_muted,
            StageState.CANCELLED: self._palette.degraded,
        }[state]

    @property
    def state(self) -> StageState:
        return self._state

    def text(self) -> str:
        return self._status.text()
