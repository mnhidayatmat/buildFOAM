"""NFR-P7 — the application does nothing when it is doing nothing.

Measured at 0.30–0.35% against a 1% budget. That number is not what this file
asserts, because it would flake on a loaded machine and a flaky test teaches
whoever sees it to press rerun.

What is asserted is the *cause*. Idle CPU in a Qt application is repeating
timers, and a timer left running after the work it served has finished is both
the usual defect and a deterministic thing to check. If nothing is scheduled,
nothing can burn.

This matters more than a percentage suggests. A laptop is the machine a student
runs this on, a poll every 250 ms prevents the CPU from idling down, and the
user has no way to attribute a flat battery to a simulation they finished an
hour ago.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer

from fakes import FakeSession, ScriptedCommand
from foamwb.services.case import CaseService
from foamwb.services.run import build_plan
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT


def _active_timers(widget) -> list[str]:
    """Every repeating timer still scheduled beneath a widget.

    Single-shot timers are excluded: one that is pending will fire once and stop,
    which is a bounded cost rather than a permanent drain.
    """
    return [
        f"{type(t.parent()).__name__}.{t.objectName() or 'timer'} @{t.interval()}ms"
        for t in widget.findChildren(QTimer)
        if t.isActive() and not t.isSingleShot()
    ]


@pytest.fixture
def case(tmp_path) -> Path:
    root = tmp_path / "cavity"
    (root / "system").mkdir(parents=True)
    (root / "constant").mkdir()
    (root / "0").mkdir()
    (root / "system" / "controlDict").write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
        "application     icoFoam;\nstartFrom startTime;\nstartTime 0;\nstopAt endTime;\n"
        "endTime 0.5;\ndeltaT 0.005;\nwriteControl timeStep;\nwriteInterval 20;\n"
    )
    return root


class TestNothingIsScheduledWhenNothingIsHappening:
    def test_a_freshly_built_shell_schedules_nothing(self, qtbot) -> None:
        from foamwb.ui.shell import Shell

        shell = Shell(LIGHT)
        qtbot.addWidget(shell)
        assert _active_timers(shell) == []

    def test_opening_a_case_schedules_nothing(self, qtbot, case) -> None:
        """Reading a case is work that finishes. Nothing should still be polling
        afterwards."""
        from foamwb.ui.shell import Shell

        shell = Shell(LIGHT)
        qtbot.addWidget(shell)
        shell.set_dialogs(report=lambda *a: None)
        shell.open_case(case)
        assert _active_timers(shell) == []

    def test_the_monitor_poll_stops_when_the_run_does(self, qtbot, case) -> None:
        """The one repeating timer in the application, and the one that would
        otherwise outlive its purpose."""
        from foamwb.ui.views.run import RunView

        view = RunView(LIGHT, {**strings.shell_strings(), **strings.run_strings()})
        qtbot.addWidget(view)
        session = FakeSession({"icoFoam": ScriptedCommand(lines=["Time = 1", "End"])})
        view.set_context(session, case, build_plan(CaseService().open(case)))

        assert _active_timers(view) == []
        view.start()
        assert _active_timers(view), "the monitor poll should run *during* a run"

        qtbot.waitUntil(lambda: not view._worker.is_running, timeout=10_000)
        qtbot.waitUntil(lambda: _active_timers(view) == [], timeout=5_000)

    def test_the_journal_timer_is_single_shot(self, qtbot) -> None:
        """It coalesces typing; it must not become a heartbeat."""
        from foamwb.ui.widgets.text_editor import TextEditor

        editor = TextEditor(LIGHT, {**strings.shell_strings(), **strings.preprocessor_strings()})
        qtbot.addWidget(editor)
        assert editor._journal_timer.isSingleShot()
        assert _active_timers(editor) == []


class TestTheCheckWouldNoticeALeak:
    """A check that cannot fail guards nothing."""

    def test_a_repeating_timer_is_reported(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        qtbot.addWidget(widget)
        leaked = QTimer(widget)
        leaked.setInterval(250)
        leaked.start()
        assert _active_timers(widget)

    def test_a_single_shot_is_not(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        qtbot.addWidget(widget)
        pending = QTimer(widget)
        pending.setSingleShot(True)
        pending.start(5_000)
        assert _active_timers(widget) == []
