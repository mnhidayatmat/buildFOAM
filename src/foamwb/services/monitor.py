"""MonitorService — time series from function-object output (§4.2, DEC-13, FR-S4).

**Why ``.dat`` files and not the log.** DEC-13 makes the injected ``solverInfo``
function object the primary source and log scraping only a fallback. The
function object writes stable columnar output; the log's residual lines change
format between releases and between solvers, and would need a different regex for
every one. The columnar path also works identically in parallel, where the log is
interleaved across ranks.

**The format, as it actually is.** A ``#``-prefixed header block whose last line
names the columns, then tab-separated rows::

    # Solver information
    # Time  U_solver  Ux_initial  Ux_final  Ux_iters  ...  p_converged
    0.005   smoothSolver  1.000000e+00  8.905110e-06  19  ...  true

Columns are **not** uniformly numeric: ``U_solver`` is a solver name and
``U_converged`` is a boolean. A reader that assumed floats would fail on the
first row of every case, so values are parsed per-column and non-numeric ones are
kept as text rather than dropped — the solver name is exactly what a user needs
when asking why a run behaved differently.

Reading is incremental. NFR-P4 gives a 500 ms budget from a ``.dat`` write to the
plot updating, and a run may produce tens of thousands of rows; re-reading the
file each poll would turn a linear cost into a quadratic one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from foamwb.branding import CASE_METADATA_DIR

__all__ = ["MonitorService", "Series", "TimeSeries", "parse_dat"]

#: Residual column suffix. The initial residual is what convergence is judged on:
#: the final residual only says the linear solver converged this timestep, which
#: it almost always did.
INITIAL_RESIDUAL_SUFFIX = "_initial"

_NUMERIC = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


@dataclass(slots=True)
class Series:
    """One named column of values against time."""

    name: str
    times: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.times)

    @property
    def latest(self) -> float | None:
        return self.values[-1] if self.values else None

    @property
    def is_residual(self) -> bool:
        return self.name.endswith(INITIAL_RESIDUAL_SUFFIX)

    @property
    def label(self) -> str:
        """Display name — ``Ux_initial`` reads as ``Ux``."""
        if self.is_residual:
            return self.name[: -len(INITIAL_RESIDUAL_SUFFIX)]
        return self.name


@dataclass(slots=True)
class TimeSeries:
    """Every numeric column from one function object, plus its text columns."""

    source: Path
    series: dict[str, Series] = field(default_factory=dict)
    text_columns: dict[str, str] = field(default_factory=dict)
    """Latest value of each non-numeric column — the linear solver in use, and
    whether the equation reported convergence."""

    @property
    def names(self) -> list[str]:
        return list(self.series)

    @property
    def residuals(self) -> list[Series]:
        """Initial-residual series only, in file order.

        The default plot: FR-S3 requires residuals from ``postProcessing`` and a
        user opening the Run view wants convergence, not twelve columns.
        """
        return [s for s in self.series.values() if s.is_residual]

    @property
    def latest_time(self) -> float | None:
        for series in self.series.values():
            if series.times:
                return series.times[-1]
        return None

    def to_csv(self) -> str:
        """CSV of every numeric series, for FR-S4's export.

        Emitted from the full retained data rather than the decimated plot, so an
        export is never a screenshot of a screenshot (NFR-P5).
        """
        if not self.series:
            return ""
        names = list(self.series)
        rows = [",".join(["Time", *names])]
        # The longest series supplies the time column. Function objects can start
        # reporting a field partway through a run, so the first series is not
        # necessarily the complete one.
        reference = max((s.times for s in self.series.values()), key=len)
        for index, time in enumerate(reference):
            cells = [f"{time:.10g}"]
            for name in names:
                values = self.series[name].values
                cells.append(f"{values[index]:.10g}" if index < len(values) else "")
            rows.append(",".join(cells))
        return "\n".join(rows) + "\n"


def _column_names(header_lines: list[str]) -> list[str]:
    """Column names from the last ``#`` line, which is the one that names them."""
    if not header_lines:
        return []
    return header_lines[-1].lstrip("#").split()


def parse_dat(text: str) -> tuple[list[str], list[list[str]]]:
    """Split function-object output into column names and raw rows."""
    header: list[str] = []
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            header.append(stripped)
            continue
        rows.append(stripped.split())
    return _column_names(header), rows


class MonitorService:
    """Reads ``postProcessing/**/*.dat`` and exposes time series (§4.2).

    One instance per case. Holds the read offset per file so repeated polls are
    incremental.
    """

    def __init__(self, case: Path) -> None:
        self._case = case
        self._offsets: dict[Path, int] = {}
        self._series: dict[Path, TimeSeries] = {}
        # Per instance, not per class: column names belong to one case's files,
        # and a shared dict would leak one case's columns into another's plots.
        self._columns: dict[Path, list[str]] = {}

    @property
    def post_processing_dir(self) -> Path:
        return self._case / "postProcessing"

    def dat_files(self) -> list[Path]:
        """Every function-object output file, newest run directory last.

        A restarted run writes a second time directory beside the first
        (``postProcessing/solverInfo/0`` then ``.../0.5``), so both are read and
        the series continue across the restart — FR-S8 requires a resumed run to
        continue the residual series without a discontinuity.
        """
        if not self.post_processing_dir.is_dir():
            return []
        return sorted(
            path
            for path in self.post_processing_dir.rglob("*.dat")
            if CASE_METADATA_DIR not in path.parts
        )

    def refresh(self) -> dict[str, TimeSeries]:
        """Read what is new since the last call, keyed by function-object name."""
        for path in self.dat_files():
            self._read_increment(path)
        return {self._function_object_name(p): ts for p, ts in self._series.items()}

    def series(self, name: str) -> TimeSeries | None:
        """Time series for one function object, refreshing first."""
        return self.refresh().get(name)

    def _function_object_name(self, path: Path) -> str:
        """``postProcessing/solverInfo/0/solverInfo.dat`` → ``solverInfo``."""
        try:
            relative = path.relative_to(self.post_processing_dir)
        except ValueError:  # pragma: no cover - dat_files only yields descendants
            return path.stem
        return relative.parts[0] if relative.parts else path.stem

    def _read_increment(self, path: Path) -> None:
        """Append rows written since the last read.

        Reopened each time rather than held open: a solver may rotate or rewrite
        the file on restart, and a held handle would keep reading a file that is
        no longer the one on disk. A file that shrank is re-read from the start,
        which is the only safe interpretation of an offset past the end.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return

        offset = self._offsets.get(path, 0)
        if size < offset:
            offset = 0
            self._series.pop(path, None)
        if size == offset:
            return

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            if offset:
                handle.seek(offset)
            chunk = handle.read()
            self._offsets[path] = handle.tell()

        existing = self._series.get(path)
        if existing is None or offset == 0:
            names, rows = parse_dat(chunk)
            # Series are created on demand as numeric values arrive, never
            # pre-created from the column names: `U_solver` and `p_converged` are
            # text, and seeding them here would leave permanently empty series
            # cluttering the plot's series list and the CSV export.
            existing = TimeSeries(source=path)
            self._series[path] = existing
            self._columns[path] = names
        else:
            names = self._columns.get(path, [])
            _, rows = parse_dat(chunk)

        self._append(existing, names, rows)

    @staticmethod
    def _append(target: TimeSeries, names: list[str], rows: list[list[str]]) -> None:
        if not names:
            return
        for row in rows:
            if len(row) != len(names) or not _NUMERIC.match(row[0]):
                # A partially written final line is normal when polling a file the
                # solver is still appending to. Skipping it costs one sample that
                # the next poll will pick up; guessing at it would put a wrong
                # point on a plot the user is reading for convergence.
                continue
            time = float(row[0])
            for name, cell in zip(names[1:], row[1:], strict=True):
                if _NUMERIC.match(cell):
                    series = target.series.setdefault(name, Series(name=name))
                    series.times.append(time)
                    series.values.append(float(cell))
                else:
                    target.text_columns[name] = cell
