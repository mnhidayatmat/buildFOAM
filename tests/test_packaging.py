"""M8 — uninstall, SBOM and the size budget (FR-A6, NFR-P8, §13.5).

The uninstall tests are the ones that matter. Every other test in this suite
protects a result; these protect a term's worth of someone's simulations from
an uninstaller that was too helpful.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foamwb.services.uninstall import (
    RemovalKind,
    UninstallItem,
    UninstallPlan,
    perform,
    plan_uninstall,
)


def _item(path: Path, kind: RemovalKind, size: int = 0) -> UninstallItem:
    return UninstallItem(path=path, kind=kind, label="x", size_bytes=size, exists=path.exists())


class TestUninstallNeverTouchesUserWork:
    """FR-A6's whole point, and the one failure no reinstall undoes."""

    def test_a_case_directory_is_reported_not_removed(self, tmp_path) -> None:
        cases = tmp_path / "cases"
        (cases / "cavity" / "system").mkdir(parents=True)
        (cases / "cavity" / "system" / "controlDict").write_text("application icoFoam;")

        plan = UninstallPlan(items=[_item(cases, RemovalKind.USER_WORK, 42)])
        assert plan.kept and not plan.removed

        perform(plan)
        assert (cases / "cavity" / "system" / "controlDict").is_file()

    def test_user_work_is_not_even_offered(self, tmp_path) -> None:
        """A destructive default a tired user can accept by pressing Return is
        the same failure with an extra step."""
        cases = tmp_path / "cases"
        cases.mkdir()
        plan = UninstallPlan(items=[_item(cases, RemovalKind.USER_WORK)])
        assert plan.offered == []

    def test_perform_refuses_a_mislabelled_list(self, tmp_path) -> None:
        """The check is repeated here rather than trusted from the caller: this
        function deletes trees."""
        cases = tmp_path / "cases"
        cases.mkdir()
        (cases / "keep.txt").write_text("mine")

        plan = UninstallPlan(items=[_item(cases, RemovalKind.USER_WORK)])
        assert perform(plan) == []
        assert (cases / "keep.txt").is_file()

    def test_the_runtime_is_offered_rather_than_assumed(self, tmp_path) -> None:
        """It may have been there first, and may be shared with other work."""
        runtime = tmp_path / "openfoam"
        runtime.mkdir()
        plan = UninstallPlan(items=[_item(runtime, RemovalKind.RUNTIME, 5_000_000)])
        assert plan.offered
        assert not plan.removed
        perform(plan)
        assert runtime.is_dir()


class TestUninstallRemovesItsOwnState:
    def test_application_state_goes(self, tmp_path) -> None:
        state = tmp_path / "state"
        state.mkdir()
        (state / "config.json").write_text("{}")

        plan = UninstallPlan(items=[_item(state, RemovalKind.APPLICATION_STATE)])
        assert perform(plan) == [state]
        assert not state.exists()

    def test_a_dry_run_removes_nothing(self, tmp_path) -> None:
        state = tmp_path / "state"
        state.mkdir()
        plan = UninstallPlan(items=[_item(state, RemovalKind.APPLICATION_STATE)])
        assert perform(plan, dry_run=True) == [state]
        assert state.is_dir()

    def test_an_absent_path_is_not_reported_as_removed(self, tmp_path) -> None:
        plan = UninstallPlan(items=[_item(tmp_path / "gone", RemovalKind.APPLICATION_STATE)])
        assert plan.removed == []

    def test_a_failure_does_not_stop_the_rest(self, tmp_path) -> None:
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()
        plan = UninstallPlan(
            items=[
                _item(tmp_path / "missing", RemovalKind.APPLICATION_STATE),
                _item(first, RemovalKind.APPLICATION_STATE),
                _item(second, RemovalKind.APPLICATION_STATE),
            ]
        )
        removed = perform(plan)
        assert set(removed) == {first, second}


class TestThePlanIsHonest:
    def test_it_says_what_it_would_free_and_what_it_would_keep(self, tmp_path) -> None:
        state, cases = tmp_path / "state", tmp_path / "cases"
        state.mkdir()
        cases.mkdir()
        plan = UninstallPlan(
            items=[
                _item(state, RemovalKind.APPLICATION_STATE, 1000),
                _item(cases, RemovalKind.USER_WORK, 9000),
            ]
        )
        assert plan.freed_bytes == 1000
        assert plan.retained_bytes == 9000

    def test_planning_removes_nothing(self) -> None:
        """A plan is a description; nothing happens until a caller acts on it."""
        before = plan_uninstall(include_sizes=False)
        after = plan_uninstall(include_sizes=False)
        assert [i.path for i in before.items] == [i.path for i in after.items]

    def test_every_item_is_classified(self) -> None:
        for item in plan_uninstall(include_sizes=False).items:
            assert item.kind in set(RemovalKind)

    def test_the_case_directory_is_classified_as_user_work(self) -> None:
        """Asserted against the real path helpers, not a fixture — a future
        refactor that reclassified it would be caught here."""
        from foamwb import paths

        cases = paths.macos_cases_dir()
        found = next(
            (i for i in plan_uninstall(include_sizes=False).items if i.path == cases), None
        )
        assert found is not None
        assert found.kind is RemovalKind.USER_WORK

    def test_sizes_can_be_skipped(self) -> None:
        """Walking a large case tree costs seconds; a caller may just want paths."""
        assert all(i.size_bytes == 0 for i in plan_uninstall(include_sizes=False).items)


class TestTheSbom:
    def _bom(self) -> dict:
        import subprocess
        import sys

        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(root / "tools" / "sbom.py"), "--version", "1.0.0"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_it_is_valid_cyclonedx(self) -> None:
        bom = self._bom()
        assert bom["bomFormat"] == "CycloneDX"
        assert bom["components"]

    def test_every_component_states_a_licence(self) -> None:
        """§13.5 — procurement asks, and "unstated" is an answer to chase now."""
        for component in self._bom()["components"]:
            name = component["licenses"][0]["license"]["name"]
            assert name and name != "unstated", component["name"]

    def test_the_runtime_dependencies_are_present(self) -> None:
        names = {c["name"] for c in self._bom()["components"]}
        assert {"pyside6", "pyqtgraph", "cryptography"} <= names

    def test_development_tooling_is_absent(self) -> None:
        """Test and lint tools are not in the artefact, so listing them invites
        questions about licences that were never distributed."""
        names = {c["name"] for c in self._bom()["components"]}
        assert not ({"pytest", "ruff", "coverage", "pyinstaller"} & names)

    def test_a_dependency_gated_out_by_a_marker_is_absent(self) -> None:
        """PySide6 requires tomli only below Python 3.11, and this project needs
        3.13 — so it is never in the artefact.

        The first version of the SBOM listed it anyway, because it trusted the
        requirement list rather than asking what was installed. An SBOM is
        believed, so a wrong entry is worse than a missing tool.
        """
        assert "tomli" not in {c["name"] for c in self._bom()["components"]}

    def test_every_component_is_pinned(self) -> None:
        for component in self._bom()["components"]:
            assert component["version"] != "unpinned", component["name"]


class TestThePackagingSpec:
    """NFR-P8 — the exclusion list is a build requirement, not housekeeping."""

    def _spec(self) -> str:
        root = Path(__file__).resolve().parent.parent
        return (root / "packaging" / "app.spec").read_text()

    def test_the_largest_offenders_are_excluded(self) -> None:
        """QtWebEngineCore alone is 453 MB of the 1,164 MB PySide6 ships."""
        spec = self._spec()
        for module in ("QtWebEngineCore", "QtMultimedia", "QtQuick3D", "QtDesigner"):
            assert module in spec, f"{module} is not excluded"

    def test_it_takes_the_name_from_branding(self) -> None:
        """A rename must stay a two-line change (NFR-M5, DEC-03)."""
        spec = self._spec()
        assert "APP_DISPLAY_NAME" in spec
        assert "BUNDLE_ID" in spec

    def test_it_ships_the_data_directory(self) -> None:
        """The manifest, schemas, guide and signed library are read at runtime."""
        assert "foamwb/data" in self._spec()

    def test_signing_is_not_wired_into_the_spec(self) -> None:
        """A spec expecting a signing identity cannot be built by a contributor
        who does not have one."""
        assert "codesign_identity=None" in self._spec()


class TestTheRuntimeCanHoldTheWork:
    """FR-R9 — on Windows the cases are *inside* the thing being removed.

    Cases live on the distro's ext4, inside its VHDX, so `wsl --unregister`
    takes them with it. This is the default layout there, not an edge case: it
    is what DEC-05 and DEC-12 cost together.
    """

    def _windows_shaped_plan(self) -> UninstallPlan:
        return UninstallPlan(
            items=[
                UninstallItem(
                    path=Path("wsl://Distro"),
                    kind=RemovalKind.RUNTIME_HOLDING_WORK,
                    label="d",
                ),
                UninstallItem(
                    path=Path("/tmp/state"), kind=RemovalKind.APPLICATION_STATE, label="s"
                ),
            ]
        )

    def test_such_a_runtime_is_reported_separately(self) -> None:
        plan = self._windows_shaped_plan()
        assert plan.blocked
        assert plan.offered == []

    def test_an_export_is_required_first(self) -> None:
        assert self._windows_shaped_plan().needs_export

    def test_nothing_at_all_is_removed_until_it_happens(self) -> None:
        """Refused rather than warned about: unregister has no undo to offer."""
        assert perform(self._windows_shaped_plan()) == []

    def test_the_block_lifts_once_the_cases_are_out(self) -> None:
        plan = self._windows_shaped_plan()
        plan.cases_exported = True
        assert not plan.needs_export

    def test_it_is_a_state_and_not_a_consent(self) -> None:
        """A user who has decided to uninstall will click through a warning.

        There is deliberately no "proceed anyway": the flag records that the
        export *happened*, which is a fact, not a preference.
        """
        plan = self._windows_shaped_plan()
        assert isinstance(plan.cases_exported, bool)
        assert not plan.cases_exported


class TestLabConfiguration:
    """FR-R7 and FR-R8 — §14's two hundred machines and no admin rights."""

    def _write(self, tmp_path, obj) -> Path:
        path = tmp_path / "lab.json"
        path.write_text(json.dumps(obj))
        return path

    def test_a_pre_provisioned_runtime_is_adopted(self, tmp_path) -> None:
        from foamwb.services.labconfig import adoption_status, load_lab_config

        config = load_lab_config(
            self._write(
                tmp_path,
                {"adopt_runtime": True, "bashrc": "/opt/of/etc/bashrc", "distro": "Lab"},
            )
        )
        assert config.adopt_runtime
        assert adoption_status(config, exists=True).usable

    def test_silent_mode_is_carried(self, tmp_path) -> None:
        from foamwb.services.labconfig import load_lab_config

        assert load_lab_config(self._write(tmp_path, {"silent": True})).silent

    def test_adopting_nothing_is_refused(self, tmp_path) -> None:
        """ "Adopt" with no path is a configuration that cannot be satisfied."""
        from foamwb.services.labconfig import LabConfigError, load_lab_config

        with pytest.raises(LabConfigError):
            load_lab_config(self._write(tmp_path, {"adopt_runtime": True}))

    def test_a_missing_runtime_is_reported_not_worked_around(self, tmp_path) -> None:
        """The same wrong file is on every machine in the room."""
        from foamwb.services.labconfig import adoption_status, load_lab_config

        config = load_lab_config(
            self._write(tmp_path, {"adopt_runtime": True, "bashrc": "/nope/bashrc"})
        )
        status = adoption_status(config, exists=False)
        assert not status.usable
        assert status.code is not None

    @pytest.mark.parametrize(
        "key",
        ["skip_signature_check", "allow_unsigned_content", "disable_verification", "public_key"],
    )
    def test_safety_cannot_be_configured_away(self, tmp_path, key: str) -> None:
        """An administrator installing for two hundred students is exactly the
        person who must not be able to disable verification for them."""
        from foamwb.services.labconfig import LabConfigError, load_lab_config

        with pytest.raises(LabConfigError) as caught:
            load_lab_config(self._write(tmp_path, {key: True}))
        assert caught.value.code.id == "E-L01"

    def test_telemetry_is_off_unless_stated(self, tmp_path) -> None:
        """§7.3 step 1 — opt-in, and never enabled by omission."""
        from foamwb.services.labconfig import load_lab_config

        assert not load_lab_config(self._write(tmp_path, {})).telemetry

    def test_a_malformed_file_names_the_line(self, tmp_path) -> None:
        from foamwb.services.labconfig import LabConfigError, load_lab_config

        path = tmp_path / "lab.json"
        path.write_text("{ truncated")
        with pytest.raises(LabConfigError) as caught:
            load_lab_config(path)
        assert "line" in caught.value.message

    def test_a_missing_file_does_not_fall_back_silently(self, tmp_path) -> None:
        """A managed install that quietly became a manual one would stop two
        hundred machines at the first administrator prompt, without saying why."""
        from foamwb.services.labconfig import LabConfigError, load_lab_config

        with pytest.raises(LabConfigError):
            load_lab_config(tmp_path / "absent.json")
