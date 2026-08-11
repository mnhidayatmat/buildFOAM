"""Live residual and monitor plots (FR-S3, FR-S4, NFR-P4, NFR-P5).

**Log scale is the default, and that is a correctness decision.** Residuals fall
from 1 to 1e-7 over a run. On a linear axis every value below about 1e-2 is
indistinguishable from zero, so the plot would show a line dropping to the axis
and then apparently doing nothing — which is exactly the region where the user is
deciding whether the solution has converged. A linear default would make the plot
worst where it matters most.

**Decimation is bounded but export is not** (NFR-P5). Beyond 50 000 points a
series is drawn decimated, because a plot cannot resolve more pixels than it has
and pushing a million points through the renderer is what makes a live plot
stutter. The full data is retained and CSV export writes all of it (FR-S4) — an
export that silently gave you the screen resolution instead of the data would be
a quiet lie.

Colours come from the palette, not from pyqtgraph's defaults, so the plot obeys
NFR-A2 and NFR-A4 like everything else. Each series also gets a distinct dash
pattern: colour alone cannot carry which line is which for a colourblind reader,
and residual plots routinely show six overlapping series.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.monitor import TimeSeries
from foamwb.ui.theme import Palette

__all__ = ["MAX_PLOTTED_POINTS", "ResidualPlot"]

#: NFR-P5's budget. Beyond this a series is decimated for drawing only.
MAX_PLOTTED_POINTS = 50_000

#: Dash patterns, so a series is identifiable without relying on colour (NFR-A2).
_DASHES: tuple[tuple[int, ...] | None, ...] = (
    None,
    (6, 3),
    (2, 2),
    (8, 3, 2, 3),
    (12, 4),
    (1, 3),
)


class ResidualPlot(QWidget):
    """One function object's series, with per-series toggles and CSV export."""

    export_requested = Signal()

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._toggles: dict[str, QCheckBox] = {}
        self._series: TimeSeries | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        pg.setConfigOptions(antialias=True, background=palette.bg, foreground=palette.text)
        self._plot = pg.PlotWidget()
        self._plot.setLogMode(x=False, y=True)
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("bottom", labels["axis_time"])
        self._plot.setLabel("left", labels["axis_residual"])
        self._plot.addLegend(offset=(-10, 10))
        self._plot.setAccessibleName(labels["residual_plot"])
        layout.addWidget(self._plot, stretch=1)

        self._empty = QLabel(labels["no_monitor_data"])
        self._empty.setProperty("role", "muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._controls = QWidget()
        self._controls_row = QHBoxLayout(self._controls)
        self._controls_row.setContentsMargins(0, 0, 0, 0)
        self._controls_row.setSpacing(10)

        self._log_scale = QCheckBox(labels["log_scale"])
        self._log_scale.setChecked(True)
        self._log_scale.toggled.connect(lambda on: self._plot.setLogMode(x=False, y=on))
        self._controls_row.addWidget(self._log_scale)
        self._controls_row.addStretch(1)

        self._export = QPushButton(labels["export_csv"])
        self._export.clicked.connect(self.export_requested)
        self._export.setEnabled(False)
        self._controls_row.addWidget(self._export)
        layout.addWidget(self._controls)

        self._show_empty(True)

    def _show_empty(self, empty: bool) -> None:
        self._empty.setVisible(empty)
        self._plot.setVisible(not empty)
        self._controls.setVisible(not empty)

    # -- data --------------------------------------------------------------

    def set_series(self, series: TimeSeries) -> None:
        """Replace the plotted data.

        Called on every monitor poll, so it updates existing curves in place
        rather than rebuilding the plot — recreating items would reset the user's
        zoom on every refresh, which makes it impossible to inspect the tail of a
        converging run while it is still running.
        """
        self._series = series
        residuals = series.residuals or list(series.series.values())
        if not residuals:
            self._show_empty(True)
            return

        self._show_empty(False)
        self._export.setEnabled(True)

        for index, item in enumerate(residuals):
            times, values = _decimate(item.times, item.values)
            curve = self._curves.get(item.name)
            if curve is None:
                curve = self._plot.plot(
                    times,
                    values,
                    name=item.label,
                    pen=pg.mkPen(
                        color=_colour_for(self._palette, index),
                        width=2,
                        dash=_DASHES[index % len(_DASHES)],
                    ),
                )
                self._curves[item.name] = curve
                self._add_toggle(item.name, item.label)
            else:
                curve.setData(times, values)
            curve.setVisible(self._toggles[item.name].isChecked())

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette without disturbing the view (NFR-A4).

        pyqtgraph paints its own canvas, so none of this comes from the
        application style sheet — the background, the axes and every pen have to
        be told separately. Pens are reset in place rather than by rebuilding the
        curves, for the same reason :meth:`set_series` updates them in place: new
        items would reset the user's zoom, and someone who changed the theme
        while inspecting the tail of a converging run would lose their place.
        """
        self._palette = palette
        pg.setConfigOptions(background=palette.bg, foreground=palette.text)
        self._plot.setBackground(palette.bg)
        for edge in ("left", "bottom"):
            axis = self._plot.getAxis(edge)
            axis.setPen(palette.text)
            axis.setTextPen(palette.text)

        # Enumerating the dict rather than the series list: insertion order is
        # the order the colours were assigned, so this reproduces exactly the
        # index each curve was originally given.
        for index, curve in enumerate(self._curves.values()):
            curve.setPen(
                pg.mkPen(
                    color=_colour_for(palette, index),
                    width=2,
                    dash=_DASHES[index % len(_DASHES)],
                )
            )

    def _add_toggle(self, name: str, label: str) -> None:
        toggle = QCheckBox(label)
        toggle.setChecked(True)
        toggle.toggled.connect(lambda visible, key=name: self._curves[key].setVisible(visible))
        self._toggles[name] = toggle
        self._controls_row.insertWidget(self._controls_row.count() - 2, toggle)

    def clear(self) -> None:
        for curve in self._curves.values():
            self._plot.removeItem(curve)
        for toggle in self._toggles.values():
            self._controls_row.removeWidget(toggle)
            toggle.deleteLater()
        self._curves.clear()
        self._toggles.clear()
        self._series = None
        self._export.setEnabled(False)
        self._show_empty(True)

    def csv(self) -> str:
        """Full data, never the decimated view (FR-S4, NFR-P5)."""
        return self._series.to_csv() if self._series is not None else ""

    # -- for tests ---------------------------------------------------------

    @property
    def series_names(self) -> list[str]:
        return list(self._curves)

    @property
    def is_log_scale(self) -> bool:
        return self._log_scale.isChecked()

    def toggle(self, name: str) -> QCheckBox:
        return self._toggles[name]

    def curve_visible(self, name: str) -> bool:
        return self._curves[name].isVisible()


def _decimate(times: list[float], values: list[float]) -> tuple[list[float], list[float]]:
    """Thin a series for drawing only, keeping the most recent point.

    Uniform sampling with the last point forced: the newest value is what a user
    watching a live run is reading, and a stride that happened to drop it would
    make the plot lag the log by up to a whole stride.
    """
    if len(times) <= MAX_PLOTTED_POINTS:
        return times, values
    stride = len(times) // MAX_PLOTTED_POINTS + 1
    thinned_times = times[::stride]
    thinned_values = values[::stride]
    if thinned_times[-1] != times[-1]:
        thinned_times.append(times[-1])
        thinned_values.append(values[-1])
    return thinned_times, thinned_values


def _colour_for(palette: Palette, index: int) -> str:
    """Series colours, taken from the palette so themes stay consistent."""
    wheel = (
        palette.accent,
        palette.ready,
        palette.degraded,
        palette.broken,
        palette.text,
        palette.text_muted,
    )
    return wheel[index % len(wheel)]
