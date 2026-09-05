"""The mesh panel's transform dialog (FR-P5).

``transformPoints`` was wired to a bare argv and so failed fatally on every case
it was ever pressed on. These tests pin the two halves of the fix: the button
asks before it runs, and what it asks for is what reaches the utility.

The dialog is injected for the same reason the geometry panel's file dialog is —
a modal that blocks until a human answers would hang the suite rather than fail
it, and it sits on the only path to the feature.

Runs offscreen, so no display is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeSession, ScriptedCommand
from foamwb.services.mesh import UTILITIES, Axis, Transform, TransformKind
from foamwb.ui import strings
from foamwb.ui.theme import LIGHT
from foamwb.ui.widgets.mesh_panel import MeshPanel
from foamwb.ui.widgets.transform_dialog import TransformDialog

TRANSFORM_POINTS = next(u for u in UTILITIES if u.name == "transformPoints")


@pytest.fixture
def labels() -> dict[str, str]:
    return {**strings.shell_strings(), **strings.preprocessor_strings()}


@pytest.fixture
def case(tmp_path: Path) -> Path:
    root = tmp_path / "cavity"
    (root / "constant" / "polyMesh").mkdir(parents=True)
    (root / "system").mkdir()
    (root / "constant" / "polyMesh" / "points").write_text("0\n")
    return root


@pytest.fixture
def panel(qtbot, labels, case) -> MeshPanel:
    widget = MeshPanel(LIGHT, labels)
    qtbot.addWidget(widget)
    session = FakeSession({"transformPoints": ScriptedCommand(lines=["End"])})
    widget.set_context(session, case, meshed=True)
    return widget


class TestAskingBeforeRunning:
    def test_the_utility_is_offered_once_a_mesh_exists(self, panel: MeshPanel) -> None:
        assert "transformPoints" in panel.utilities

    def test_the_chosen_operation_reaches_the_command(self, panel: MeshPanel, qtbot) -> None:
        panel.set_dialogs(ask_transform=lambda: Transform.scale(0.001, 0.001, 0.001))
        assert panel.run_utility(TRANSFORM_POINTS)

        qtbot.waitUntil(lambda: bool(panel._session.commands))
        assert panel._session.commands[0][-3:] == (
            "transformPoints",
            "-scale",
            "(0.001 0.001 0.001)",
        )

    def test_cancelling_runs_nothing(self, panel: MeshPanel) -> None:
        panel.set_dialogs(ask_transform=lambda: None)
        assert not panel.run_utility(TRANSFORM_POINTS)
        assert panel._session.commands == []

    def test_cancelling_says_so_rather_than_going_quiet(self, panel: MeshPanel) -> None:
        # Silence here is indistinguishable from a broken button, which is
        # exactly how this was first reported.
        panel.set_dialogs(ask_transform=lambda: None)
        panel.run_utility(TRANSFORM_POINTS)
        assert panel.status_text == panel._labels["transform_cancelled"]

    def test_cancelling_is_not_reported_as_a_failure(self, panel: MeshPanel) -> None:
        # The user changed their mind. Colouring the status line red for that
        # would teach them the panel cannot tell the difference.
        panel.set_dialogs(ask_transform=lambda: None)
        panel.run_utility(TRANSFORM_POINTS)
        assert panel._status_token == "text_muted"

    def test_a_transform_that_moves_nothing_is_declined(self, panel: MeshPanel) -> None:
        # It would rewrite every point and invalidate everything derived from
        # the mesh, in exchange for nothing.
        panel.set_dialogs(ask_transform=lambda: Transform.scale(1, 1, 1))
        assert not panel.run_utility(TRANSFORM_POINTS)
        assert panel._session.commands == []
        assert panel.status_text == panel._labels["transform_identity"]

    def test_a_utility_that_needs_no_operation_is_not_asked_about(
        self, panel: MeshPanel, qtbot
    ) -> None:
        asked = []
        panel.set_dialogs(ask_transform=lambda: asked.append(True) or None)
        check_mesh = next(u for u in UTILITIES if u.name == "checkMesh")
        panel.run_utility(check_mesh)
        assert asked == []


CHECK_MESH_OUTPUT = [
    "Mesh stats",
    "    cells:            2400",
    "Checking geometry...",
    "    Max skewness = 0.8 OK.",
    "Mesh OK.",
    "End",
]


@pytest.fixture
def meshable(tmp_path: Path) -> Path:
    """A case that can be meshed but has not been — the ordinary starting point."""
    root = tmp_path / "wing"
    (root / "system").mkdir(parents=True)
    (root / "constant").mkdir()
    for name in ("blockMeshDict", "surfaceFeatureExtractDict", "snappyHexMeshDict"):
        (root / "system" / name).write_text("x")
    return root


@pytest.fixture
def chain_panel(qtbot, labels, meshable) -> MeshPanel:
    widget = MeshPanel(LIGHT, labels)
    qtbot.addWidget(widget)
    session = FakeSession(
        {
            "blockMesh": ScriptedCommand(lines=["End"]),
            "surfaceFeatureExtract": ScriptedCommand(lines=["End"]),
            "snappyHexMesh": ScriptedCommand(lines=["End"]),
            "checkMesh": ScriptedCommand(lines=CHECK_MESH_OUTPUT),
        }
    )
    widget.set_context(session, meshable, meshed=False)
    return widget


class TestGeneratingInOnePress:
    """FR-P5 — the sequence the application knows, run as one action."""

    def test_the_button_is_offered_on_a_case_that_can_be_meshed(
        self, chain_panel: MeshPanel
    ) -> None:
        assert chain_panel.offers_generate

    def test_it_is_not_offered_when_nothing_would_make_a_mesh(
        self, qtbot, labels, tmp_path
    ) -> None:
        """A primary button that cannot work is worse than no button."""
        bare = tmp_path / "bare"
        (bare / "system").mkdir(parents=True)
        panel = MeshPanel(LIGHT, labels)
        qtbot.addWidget(panel)
        panel.set_context(FakeSession(), bare, meshed=False)
        assert not panel.offers_generate

    def test_one_press_runs_every_stage_in_order(self, chain_panel: MeshPanel, qtbot) -> None:
        assert chain_panel.generate_mesh()
        qtbot.waitUntil(lambda: len(chain_panel._session.commands) == 4, timeout=5000)
        # Located by name rather than by position: the session wraps each argv,
        # and snappyHexMesh carries -overwrite after its own name.
        expected = ["blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "checkMesh"]
        ran = [
            next(t for t in command if t in expected) for command in chain_panel._session.commands
        ]
        assert ran == expected

    def test_the_strip_shows_the_sequence(self, chain_panel: MeshPanel) -> None:
        """Four utilities running into one log need something that says which."""
        assert chain_panel.generate_mesh()
        assert chain_panel.strip_shown

    def test_a_single_utility_gets_no_strip(self, panel: MeshPanel) -> None:
        """One chip beside a status line naming the same utility is a second copy."""
        panel.set_dialogs(ask_transform=lambda: Transform.scale(0.001, 0.001, 0.001))
        assert panel.run_utility(TRANSFORM_POINTS)
        assert not panel.strip_shown

    def test_quality_is_read_from_check_mesh_alone(self, chain_panel: MeshPanel, qtbot) -> None:
        """The figures belong to that stage, not to four utilities' concatenated log.

        Before the chain existed the panel accumulated every line into one list;
        parsing that would hand `parse_check_mesh` blockMesh's output too.
        """
        assert chain_panel.generate_mesh()
        qtbot.waitUntil(lambda: bool(chain_panel.quality_text), timeout=5000)
        assert "2400 cells" in chain_panel.quality_text

    def test_the_mesh_is_announced_once_the_chain_makes_one(
        self, chain_panel: MeshPanel, qtbot
    ) -> None:
        changed = []
        chain_panel.mesh_changed.connect(lambda: changed.append(True))
        assert chain_panel.generate_mesh()
        qtbot.waitUntil(lambda: bool(changed), timeout=5000)

    def test_a_second_press_cannot_start_over_a_running_chain(self, chain_panel: MeshPanel) -> None:
        assert chain_panel.generate_mesh()
        assert not chain_panel.generate_mesh()

    def test_the_failing_stage_is_named_not_the_button(self, qtbot, labels, meshable) -> None:
        """ "Generate mesh failed" leaves the user to find which of four it was."""
        panel = MeshPanel(LIGHT, labels)
        qtbot.addWidget(panel)
        panel.set_context(
            FakeSession(
                {
                    "blockMesh": ScriptedCommand(lines=["End"]),
                    "surfaceFeatureExtract": ScriptedCommand(lines=["End"]),
                    "snappyHexMesh": ScriptedCommand(lines=["boom"], exit_code=1),
                }
            ),
            meshable,
            meshed=False,
        )
        assert panel.generate_mesh()
        qtbot.waitUntil(lambda: "snappyHexMesh" in panel.status_text, timeout=5000)

    def test_the_button_is_disabled_while_the_chain_runs(self, chain_panel: MeshPanel) -> None:
        assert chain_panel.generate_mesh()
        assert not chain_panel._chain_button.isEnabled()


class TestTransformDialog:
    @pytest.fixture
    def dialog(self, qtbot, labels) -> TransformDialog:
        widget = TransformDialog(LIGHT, labels)
        qtbot.addWidget(widget)
        return widget

    def test_it_opens_on_scale_because_units_are_why_people_come_here(
        self, dialog: TransformDialog
    ) -> None:
        assert dialog.kind is TransformKind.SCALE
        assert dialog.transform() == Transform.scale(1, 1, 1)

    def test_a_uniform_scale_follows_the_first_box(self, dialog: TransformDialog) -> None:
        dialog._components[0].setValue(0.001)
        assert dialog.transform() == Transform.scale(0.001, 0.001, 0.001)

    def test_unlinking_lets_the_axes_differ(self, dialog: TransformDialog) -> None:
        dialog._uniform.setChecked(False)
        dialog._components[0].setValue(2)
        assert dialog.transform() == Transform.scale(2, 1, 1)

    def test_switching_operation_resets_to_that_operation_s_resting_value(
        self, dialog: TransformDialog
    ) -> None:
        # Carrying a translation's 0 into a scale would arm a mesh collapse.
        dialog._kind.setCurrentIndex(1)
        assert dialog.transform() == Transform.translate(0, 0, 0)
        dialog._kind.setCurrentIndex(0)
        assert dialog.transform() == Transform.scale(1, 1, 1)

    def test_rotation_reads_its_axis_and_angle(self, dialog: TransformDialog) -> None:
        dialog._kind.setCurrentIndex(2)
        dialog._axis.setCurrentIndex(1)
        dialog._angle.setValue(90)
        assert dialog.transform() == Transform.rotate(Axis.Y, 90)

    def test_a_zero_scale_cannot_be_applied(self, dialog: TransformDialog) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        apply_button = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert apply_button.isEnabled()
        dialog._components[0].setValue(0)
        assert not apply_button.isEnabled()

    def test_a_disabled_apply_says_what_would_re_enable_it(
        self, dialog: TransformDialog, labels
    ) -> None:
        # A dead button with nothing on screen to read is where a user gets
        # stuck: they press it, nothing happens, and there is no next move.
        assert not dialog._blocked.isVisible()
        dialog._components[0].setValue(0)
        assert dialog._blocked.text() == labels["transform_zero_scale"]
        dialog._components[0].setValue(0.001)
        assert dialog._blocked.text() == ""

    def test_applying_closes_the_dialog(self, dialog: TransformDialog) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        dialog._components[0].setValue(0.001)
        dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.transform() == Transform.scale(0.001, 0.001, 0.001)

    def test_every_visible_string_comes_from_the_catalogue(
        self, dialog: TransformDialog, labels
    ) -> None:
        catalogue = set(labels.values())
        assert dialog.windowTitle() in catalogue
        assert dialog._hint.text() in catalogue
        assert dialog._kind.currentText() in catalogue
