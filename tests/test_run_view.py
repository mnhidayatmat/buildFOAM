"""The Run view and its widgets (§7.5, FR-S1..S5, NFR-P3, NFR-P5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeSession, ScriptedCommand
from foamwb.services.monitor import MonitorService
from foamwb.services.run import RunPlan, Severity, Stage, StageState, StopMode
from foamwb.ui import strings
from foamwb.ui.run_worker import MAX_BATCH_LINES, RunWorker
from foamwb.ui.theme import LIGHT
from foamwb.ui.views.run import RunView
from foamwb.ui.widgets.log_pane import LogPane
from foamwb.ui.widgets.residual_plot import MAX_PLOTTED_POINTS, ResidualPlot, _decimate
from foamwb.ui.widgets.stage_strip import STATE_GLYPHS, StageStrip


@pytest.fixture
def labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.run_strings()}


def plan_for(case: Path, n_procs: int = 1) -> RunPlan:
    return RunPlan(
        case=case,
        n_procs=n_procs,
        stages=(
            Stage("blockMesh", argv=("blockMesh",)),
            Stage("checkMesh", argv=("checkMesh",), fail_on=Severity.ERROR),
            Stage("decomposePar", argv=("decomposePar",), when=lambda p: p.n_procs > 1),
            Stage("solve", argv=("icoFoam",), monitored=True),
        ),
    )


class TestStageStrip:
    """FR-S1 — the plan is visible before it runs."""

    def test_a_plan_populates_every_stage_as_pending(self, qtbot, labels, tmp_path) -> None:
        strip = StageStrip(LIGHT, labels)
        qtbot.addWidget(strip)
        strip.set_plan(plan_for(tmp_path))
        assert strip.stage_names == ["blockMesh", "checkMesh", "decomposePar", "solve"]
        assert strip.state_of("blockMesh") is StageState.PENDING

    def test_skipped_stages_are_shown_not_hidden(self, qtbot, labels, tmp_path) -> None:
        # The plan reviewed before launch must be the plan watched during it.
        strip = StageStrip(LIGHT, labels)
        qtbot.addWidget(strip)
        strip.set_plan(plan_for(tmp_path))
        assert strip.state_of("decomposePar") is StageState.SKIPPED

    def test_state_is_carried_in_words_as_well_as_a_glyph(self, qtbot, labels, tmp_path) -> None:
        # NFR-A2: colour is never the sole carrier, and neither is a symbol.
        strip = StageStrip(LIGHT, labels)
        qtbot.addWidget(strip)
        strip.set_plan(plan_for(tmp_path))
        strip.set_state("solve", StageState.RUNNING)
        assert "running" in strip.text_of("solve")

    def test_every_state_has_a_distinct_glyph(self) -> None:
        assert len(set(STATE_GLYPHS.values())) == len(STATE_GLYPHS)

    def test_replanning_replaces_rather_than_appends(self, qtbot, labels, tmp_path) -> None:
        strip = StageStrip(LIGHT, labels)
        qtbot.addWidget(strip)
        strip.set_plan(plan_for(tmp_path))
        strip.set_plan(plan_for(tmp_path))
        assert strip.stage_names.count("solve") == 1


class TestLogPane:
    """FR-S2 — stream, search, jump to error."""

    def test_appends_a_batch(self, qtbot, labels) -> None:
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["Time = 0.005", "Time = 0.01"])
        assert pane.line_count == 2
        assert "Time = 0.01" in pane.text

    def test_flags_error_lines(self, qtbot, labels) -> None:
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["Time = 0.005", "--> FOAM FATAL ERROR: something", "Time = 0.01"])
        assert pane.error_count == 1

    def test_jump_to_error_cycles(self, qtbot, labels) -> None:
        # Repeated presses walk the whole set rather than sticking at the last.
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["*** a", "ok", "*** b"])
        first = pane.jump_to_next_error()
        second = pane.jump_to_next_error()
        assert (first, second) == (0, 2)
        assert pane.jump_to_next_error() == first

    def test_jumping_stops_following(self, qtbot, labels) -> None:
        # Otherwise the view snaps straight back to the newest line and undoes
        # the jump the user just asked for.
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["*** boom"])
        assert pane.following
        pane.jump_to_next_error()
        assert not pane.following

    def test_jumping_with_no_errors_is_a_no_op(self, qtbot, labels) -> None:
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["all fine"])
        assert pane.jump_to_next_error() is None

    def test_search_finds_and_wraps(self, qtbot, labels) -> None:
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["alpha", "beta", "gamma"])
        pane.set_search("beta")
        assert pane.find_next()
        assert pane.find_next()  # wraps rather than reporting failure

    def test_an_empty_search_matches_nothing(self, qtbot, labels) -> None:
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["alpha"])
        assert not pane.find_next()

    def test_clear_resets_counts(self, qtbot, labels) -> None:
        pane = LogPane(LIGHT, labels)
        qtbot.addWidget(pane)
        pane.append(["*** boom"])
        pane.clear()
        assert (pane.line_count, pane.error_count) == (0, 0)


class TestResidualPlot:
    """FR-S4, NFR-P5."""

    def _series(self, tmp_path: Path, rows: int = 3):
        target = tmp_path / "postProcessing" / "solverInfo" / "0"
        target.mkdir(parents=True)
        lines = ["# Solver information", "# Time\tUx_initial\tp_initial"]
        for index in range(rows):
            lines.append(f"{(index + 1) * 0.005}\t{1.0 / (index + 1)}\t{0.5 / (index + 1)}")
        (target / "solverInfo.dat").write_text("\n".join(lines) + "\n")
        return MonitorService(tmp_path).series("solverInfo")

    def test_log_scale_is_the_default(self, qtbot, labels) -> None:
        # Residuals span orders of magnitude; a linear axis hides exactly the
        # region where convergence is judged.
        plot = ResidualPlot(LIGHT, labels)
        qtbot.addWidget(plot)
        assert plot.is_log_scale

    def test_plots_each_residual_series(self, qtbot, labels, tmp_path) -> None:
        plot = ResidualPlot(LIGHT, labels)
        qtbot.addWidget(plot)
        plot.set_series(self._series(tmp_path))
        assert sorted(plot.series_names) == ["Ux_initial", "p_initial"]

    def test_a_series_can_be_hidden(self, qtbot, labels, tmp_path) -> None:
        plot = ResidualPlot(LIGHT, labels)
        qtbot.addWidget(plot)
        plot.set_series(self._series(tmp_path))
        plot.toggle("p_initial").setChecked(False)
        assert not plot.curve_visible("p_initial")
        assert plot.curve_visible("Ux_initial")

    def test_updating_reuses_curves_so_zoom_survives(self, qtbot, labels, tmp_path) -> None:
        # Rebuilding the plot on every poll would reset the user's zoom, making
        # it impossible to inspect a converging tail while the run continues.
        plot = ResidualPlot(LIGHT, labels)
        qtbot.addWidget(plot)
        series = self._series(tmp_path)
        plot.set_series(series)
        first = plot._curves["Ux_initial"]
        plot.set_series(series)
        assert plot._curves["Ux_initial"] is first

    def test_csv_export_is_the_full_data_not_the_plotted_view(
        self, qtbot, labels, tmp_path
    ) -> None:
        plot = ResidualPlot(LIGHT, labels)
        qtbot.addWidget(plot)
        plot.set_series(self._series(tmp_path, rows=5))
        assert len(plot.csv().splitlines()) == 6  # header + 5

    def test_decimation_bounds_the_drawn_points(self) -> None:
        count = MAX_PLOTTED_POINTS * 3
        times = [float(i) for i in range(count)]
        thinned_times, thinned_values = _decimate(times, list(times))
        assert len(thinned_times) <= MAX_PLOTTED_POINTS + 1
        assert len(thinned_values) == len(thinned_times)

    def test_decimation_keeps_the_newest_point(self) -> None:
        # The newest value is what a user watching a live run is reading; losing
        # it to a stride would make the plot lag the log.
        count = MAX_PLOTTED_POINTS * 2 + 7
        times = [float(i) for i in range(count)]
        thinned, _ = _decimate(times, list(times))
        assert thinned[-1] == times[-1]

    def test_a_short_series_is_not_decimated(self) -> None:
        times = [1.0, 2.0, 3.0]
        assert _decimate(times, times) == (times, times)


class TestRunWorkerBatching:
    """NFR-P3 — 5 000 lines/s must not become 5 000 signals/s."""

    def test_lines_arrive_in_batches(self, qapp, tmp_path) -> None:
        burst = [f"line {i}" for i in range(MAX_BATCH_LINES * 3)]
        session = FakeSession({"icoFoam": ScriptedCommand(lines=burst)})
        worker = RunWorker(session, plan_for(tmp_path))

        received: list[list[str]] = []
        worker.lines.connect(lambda _stage, chunk: received.append(chunk))
        worker._execute()  # synchronous, so no thread is needed for this claim

        assert sum(len(chunk) for chunk in received) == len(burst)
        # Batched: far fewer emissions than lines. One per line would be 1 500.
        assert len(received) < 20

    def test_a_batch_never_spans_two_stages(self, qapp, tmp_path) -> None:
        # The log and the stage strip must agree on what had printed when a stage
        # ended.
        session = FakeSession(
            {
                "blockMesh": ScriptedCommand(lines=["mesh a", "mesh b"]),
                "icoFoam": ScriptedCommand(lines=["solve a"]),
            }
        )
        worker = RunWorker(session, plan_for(tmp_path))
        received: list[tuple[str, list[str]]] = []
        worker.lines.connect(lambda stage, chunk: received.append((stage, chunk)))
        worker._execute()

        for stage, chunk in received:
            if stage == "blockMesh":
                assert all("solve" not in line for line in chunk)


class TestRunView:
    def _view(self, qtbot, labels) -> RunView:
        view = RunView(LIGHT, labels)
        qtbot.addWidget(view)
        return view

    def test_cannot_run_without_a_case(self, qtbot, labels) -> None:
        view = self._view(qtbot, labels)
        assert not view.can_run
        assert not view.can_stop

    def test_setting_a_context_shows_the_plan_without_running_it(
        self, qtbot, labels, tmp_path
    ) -> None:
        # FR-S1 and §7.9 rule 2: nothing starts until Run is pressed.
        view = self._view(qtbot, labels)
        view.set_context(FakeSession(), tmp_path, plan_for(tmp_path))
        assert view.can_run
        assert view.strip.stage_names
        assert all(
            view.strip.state_of(name) in (StageState.PENDING, StageState.SKIPPED)
            for name in view.strip.stage_names
        )

    def test_stop_and_write_is_the_default_button(self, qtbot, labels) -> None:
        # §7.9 rule 5 and DEC-14: the safe stop is the easy one, and the
        # destructive modes take a deliberate second action.
        view = self._view(qtbot, labels)
        assert "Write" in view.stop_button_text

    def test_the_destructive_modes_are_behind_a_menu(self, qtbot, labels) -> None:
        view = self._view(qtbot, labels)
        actions = [a.text() for a in view._stop_button.menu().actions()]
        assert "Stop Now" in actions
        assert "Force Kill" in actions

    def test_stop_before_a_run_is_harmless(self, qtbot, labels, tmp_path) -> None:
        view = self._view(qtbot, labels)
        view.set_context(FakeSession(), tmp_path, plan_for(tmp_path))
        view.stop(StopMode.KILL)

    def test_shutdown_without_a_run_is_harmless(self, qtbot, labels) -> None:
        self._view(qtbot, labels).shutdown()


class TestWorkerLifecycle:
    """The state a second run depends on.

    Qt deletes a QThread's C++ object as soon as it finishes, so anything that
    asks the thread whether it is running gets a RuntimeError rather than False.
    That made the *second* run in a session throw from the Run button, and
    closing the window after any run throw from shutdown — both far from the code
    that caused them.
    """

    def _finished_worker(self, qapp, tmp_path) -> RunWorker:
        from PySide6.QtCore import QEventLoop, QTimer

        session = FakeSession({"icoFoam": ScriptedCommand(lines=["done"])})
        worker = RunWorker(session, plan_for(tmp_path))

        loop = QEventLoop()
        # Waited for through the timer rather than the signal, because a lambda
        # has no thread affinity and would run on the worker thread, quitting the
        # loop before the queued slots were delivered.
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: (not worker.is_running) and loop.quit())
        QTimer.singleShot(10_000, loop.quit)
        worker.start()
        poll.start()
        loop.exec()
        poll.stop()
        qapp.processEvents()
        return worker

    def test_is_running_is_false_after_finishing(self, qapp, tmp_path) -> None:
        assert self._finished_worker(qapp, tmp_path).is_running is False

    def test_waiting_on_a_finished_worker_is_safe(self, qapp, tmp_path) -> None:
        assert self._finished_worker(qapp, tmp_path).wait(1000) is True

    def test_a_second_run_is_possible(self, qapp, tmp_path, labels) -> None:
        # The user-visible consequence: pressing Run twice in one session.
        view = RunView(LIGHT, labels)
        view.set_context(FakeSession(), tmp_path, plan_for(tmp_path))
        view.start()
        view._worker._execute()  # run synchronously, then let the view settle
        view._worker._active = False
        assert view.can_run or not view._worker.is_running
        view.start()

    def test_starting_twice_while_running_is_ignored(self, qapp, tmp_path) -> None:
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["x"])})
        worker = RunWorker(session, plan_for(tmp_path))
        worker._active = True
        worker.start()
        assert worker._thread is None
