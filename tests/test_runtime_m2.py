"""Manifest, detection and the canary (§3.4, FR-R1, FR-R5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.runtime import RuntimeKind, RuntimeState
from foamwb.services.runtime.manager import Installation, RuntimeManager
from foamwb.services.runtime.manifest import (
    ManifestError,
    load_manifest,
    parse_manifest,
)


@pytest.fixture
def manifest():
    return load_manifest()


class TestManifest:
    def test_ships_with_the_application(self, manifest) -> None:
        # §3.4: the manifest is bundled so a first launch works offline, and
        # updates ship over the content channel on top of it.
        assert manifest.versions
        assert manifest.lineage == "esi"

    def test_default_is_installable(self, manifest) -> None:
        # A default that is not among the releases would have the wizard open by
        # offering a version it cannot install.
        assert manifest.supports(manifest.default_version)

    def test_versions_are_newest_first(self, manifest) -> None:
        # Sorted rather than file-ordered, so adopting the first candidate adopts
        # the newest one even if a release was appended in the wrong place.
        assert list(manifest.versions) == sorted(manifest.versions, reverse=True)

    def test_supports_a_rolling_window(self, manifest) -> None:
        # §3.4: the current release and the previous two.
        assert len(manifest.versions) >= 3
        assert manifest.minimum_supported in manifest.versions

    def test_every_release_names_both_platforms(self, manifest) -> None:
        for version in manifest.versions:
            release = manifest.release(version)
            assert release.platform("windows") is not None, version
            assert release.platform("macos") is not None, version

    def test_every_release_maps_the_dictionary_roles(self, manifest) -> None:
        # DEC-15: the indirection that keeps Foundation support additive. A
        # release missing these would force a caller to hard-code a filename.
        for version in manifest.versions:
            release = manifest.release(version)
            assert "transport" in release.dictionary_roles
            assert "turbulence" in release.dictionary_roles
            assert release.dictionary("transport")
            assert release.dictionary("turbulence")

    def test_dictionary_lookup_is_by_role_not_filename(self, manifest) -> None:
        release = manifest.default_release()
        with pytest.raises(ManifestError, match="no dictionary for role"):
            release.dictionary("nonexistent-role")

    def test_macos_entries_describe_the_bundle_layout(self, manifest) -> None:
        # The tap ships a cask whose payload is an app bundle, not the formula
        # §3.3 assumed. Detection needs the bundle name and the launcher path.
        for version in manifest.versions:
            spec = manifest.release(version).platform("macos")
            assert spec.app_name, version
            assert spec.launcher, version
            assert spec.architectures, version

    def test_unknown_release_names_what_is_available(self, manifest) -> None:
        with pytest.raises(ManifestError, match="knows"):
            manifest.release("v9999")

    def test_at_least_one_release_is_verified(self, manifest) -> None:
        # "We packaged this" and "we ran this" are different claims — the same
        # distinction FR-R5 polices for installations.
        assert any(manifest.release(v).verified for v in manifest.versions)


class TestManifestValidation:
    def test_rejects_an_unreadable_schema(self) -> None:
        # A newer manifest arriving over the content channel must be refused
        # loudly, not half-understood: it ships independently of the app (§15.1).
        with pytest.raises(ManifestError, match="schema"):
            parse_manifest(json.dumps({"schema": 99, "releases": {}}))

    def test_rejects_malformed_json(self) -> None:
        with pytest.raises(ManifestError, match="not valid JSON"):
            parse_manifest("{ not json")

    @pytest.mark.parametrize("missing", ["lineage", "default", "minimum_supported", "releases"])
    def test_rejects_a_missing_required_key(self, missing: str) -> None:
        raw = {
            "schema": 1,
            "lineage": "esi",
            "default": "v0000",
            "minimum_supported": "v0000",
            "releases": {"v0000": {}},
        }
        del raw[missing]
        with pytest.raises(ManifestError):
            parse_manifest(json.dumps(raw))

    def test_rejects_a_default_that_is_not_a_release(self) -> None:
        with pytest.raises(ManifestError, match="not among its releases"):
            parse_manifest(
                json.dumps(
                    {
                        "schema": 1,
                        "lineage": "esi",
                        "default": "v0001",
                        "minimum_supported": "v0000",
                        "releases": {"v0000": {}},
                    }
                )
            )


def _bundle(root: Path, name: str, *, launcher: bool = True) -> Path:
    bundle = root / f"{name}.app"
    target = bundle / "Contents" / "Resources" / "etc"
    target.mkdir(parents=True)
    if launcher:
        (target / "openfoam").write_text("#!/bin/sh\nexit 0\n")
    return bundle


class TestDiscovery:
    """FR-R1 — detect before proposing to install anything."""

    def test_finds_a_bundle(self, tmp_path) -> None:
        _bundle(tmp_path, "OpenFOAM-v2512")
        found = RuntimeManager(application_dirs=(tmp_path,)).discover()
        assert len(found) == 1
        assert found[0].version == "v2512"

    def test_returns_newest_first(self, tmp_path) -> None:
        # Adopting the first candidate should adopt the best one.
        for name in ("OpenFOAM-v2506", "OpenFOAM-v2606", "OpenFOAM-v2512"):
            _bundle(tmp_path, name)
        found = RuntimeManager(application_dirs=(tmp_path,)).discover()
        assert [i.version for i in found] == ["v2606", "v2512", "v2506"]

    def test_ignores_a_bundle_without_a_launcher(self, tmp_path) -> None:
        # A leftover directory is not an installation, and offering to adopt it
        # would put the user in a broken state they did not choose.
        _bundle(tmp_path, "OpenFOAM-v2512", launcher=False)
        assert RuntimeManager(application_dirs=(tmp_path,)).discover() == []

    def test_ignores_unrelated_applications(self, tmp_path) -> None:
        (tmp_path / "Safari.app").mkdir()
        assert RuntimeManager(application_dirs=(tmp_path,)).discover() == []

    def test_missing_directory_is_not_an_error(self, tmp_path) -> None:
        # ~/Applications does not exist on most machines.
        manager = RuntimeManager(application_dirs=(tmp_path / "nope",))
        assert manager.discover() == []

    def test_adopts_an_already_sourced_environment(self, tmp_path, monkeypatch) -> None:
        # A lab image or a user launching from a configured shell (FR-R8).
        project = tmp_path / "OpenFOAM-vLab"
        (project / "etc").mkdir(parents=True)
        (project / "etc" / "openfoam").write_text("#!/bin/sh\n")
        monkeypatch.setenv("WM_PROJECT_DIR", str(project))
        monkeypatch.setenv("WM_PROJECT_VERSION", "v2512")

        found = RuntimeManager(application_dirs=(tmp_path / "none",)).discover()
        assert [i.version for i in found] == ["v2512"]

    def test_discovery_runs_nothing(self, tmp_path) -> None:
        # Safe to call during the wizard's system check: a bundle whose launcher
        # would fail is still discovered, because proving it works is verify()'s
        # job and costs a subprocess.
        bundle = _bundle(tmp_path, "OpenFOAM-v2512")
        (bundle / "Contents" / "Resources" / "etc" / "openfoam").write_text("exit 1")
        assert RuntimeManager(application_dirs=(tmp_path,)).discover()


class TestVerification:
    """FR-R5 — installed and works are different claims."""

    def _install(self, tmp_path: Path, script: str) -> Installation:
        bundle = _bundle(tmp_path, "OpenFOAM-v2512")
        launcher = bundle / "Contents" / "Resources" / "etc" / "openfoam"
        launcher.write_text(script)
        launcher.chmod(0o755)
        return Installation(launcher=launcher, bundle=bundle, version="v2512")

    def test_a_working_canary_reports_ready(self, tmp_path) -> None:
        install = self._install(tmp_path, "#!/bin/sh\necho v2512\n")
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(install)
        assert status.state is RuntimeState.READY
        assert status.openfoam_version == "v2512"
        assert status.kind is RuntimeKind.NATIVE

    def test_a_failing_canary_reports_broken_not_ready(self, tmp_path) -> None:
        # The whole point of FR-R5. A corrupted install that reported ready would
        # send the user into a lab session with a machine that cannot run.
        install = self._install(
            tmp_path, "#!/bin/sh\necho 'dyld: library not loaded' >&2\nexit 1\n"
        )
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(install)
        assert status.state is RuntimeState.BROKEN
        assert not status.is_usable
        assert status.reason is ErrorCode.RUNTIME_BROKEN
        assert "dyld" in status.detail

    def test_exit_zero_without_a_version_is_broken(self, tmp_path) -> None:
        # A launcher that succeeds but reports nothing has not proved anything.
        install = self._install(tmp_path, "#!/bin/sh\nexit 0\n")
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(install)
        assert status.state is RuntimeState.BROKEN

    def test_an_unsupported_version_is_degraded_not_broken(self, tmp_path) -> None:
        # It runs; it is just outside the rolling support window (§3.4). Calling
        # it broken would be false, and refusing to use it would be a dead end.
        install = self._install(tmp_path, "#!/bin/sh\necho v1806\n")
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(install)
        assert status.state is RuntimeState.DEGRADED
        assert status.is_usable
        assert status.reason is ErrorCode.VERSION_MISMATCH
        assert "v1806" in status.detail

    def test_a_missing_launcher_is_broken(self, tmp_path) -> None:
        install = Installation(launcher=tmp_path / "gone", bundle=tmp_path)
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(install)
        assert status.state is RuntimeState.BROKEN

    def test_a_slow_canary_is_degraded_not_broken(self, tmp_path) -> None:
        # The bundle mounts a disk image on first use, so a slow answer is far
        # more likely to be a cold mount than a corrupt install. Reporting broken
        # would send the user to reinstall something that works.
        install = self._install(tmp_path, "#!/bin/sh\nsleep 5\necho v2512\n")
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(install, timeout=0.3)
        assert status.state is RuntimeState.DEGRADED
        assert "did not answer" in status.detail

    def test_version_is_read_from_output_not_the_bundle_name(self, tmp_path) -> None:
        # A renamed or copied bundle would otherwise report a version it does not
        # contain, and every schema lookup after that would be wrong.
        bundle = _bundle(tmp_path, "OpenFOAM-v2606")
        launcher = bundle / "Contents" / "Resources" / "etc" / "openfoam"
        launcher.write_text("#!/bin/sh\necho v2512\n")
        launcher.chmod(0o755)
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(
            Installation(launcher=launcher, bundle=bundle, version="v2606")
        )
        assert status.openfoam_version == "v2512"

    def test_mount_chatter_does_not_confuse_the_parser(self, tmp_path) -> None:
        # The launcher prints mount progress to the same stream as the canary.
        install = self._install(
            tmp_path,
            "#!/bin/sh\necho 'Mounting OpenFOAM volume...'\necho 'done'\necho v2512\n",
        )
        status = RuntimeManager(application_dirs=(tmp_path,)).verify(install)
        assert status.openfoam_version == "v2512"


class TestDetect:
    def test_no_installation_reports_missing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
        status = RuntimeManager(application_dirs=(tmp_path,)).detect()
        assert status.state is RuntimeState.MISSING
        assert status.reason is ErrorCode.NOT_PROVISIONED

    def test_a_broken_install_does_not_mask_a_working_one(self, tmp_path, monkeypatch) -> None:
        # Newest-first ordering means the broken v2606 is tried first. Stopping
        # there would report a perfectly usable machine as broken.
        monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
        for name, script in (
            ("OpenFOAM-v2606", "#!/bin/sh\nexit 1\n"),
            ("OpenFOAM-v2512", "#!/bin/sh\necho v2512\n"),
        ):
            bundle = _bundle(tmp_path, name)
            launcher = bundle / "Contents" / "Resources" / "etc" / "openfoam"
            launcher.write_text(script)
            launcher.chmod(0o755)

        status = RuntimeManager(application_dirs=(tmp_path,)).detect()
        assert status.state is RuntimeState.READY
        assert status.openfoam_version == "v2512"

    def test_all_broken_reports_the_first_failure(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("WM_PROJECT_DIR", raising=False)
        bundle = _bundle(tmp_path, "OpenFOAM-v2512")
        launcher = bundle / "Contents" / "Resources" / "etc" / "openfoam"
        launcher.write_text("#!/bin/sh\nexit 1\n")
        launcher.chmod(0o755)
        status = RuntimeManager(application_dirs=(tmp_path,)).detect()
        assert status.state is RuntimeState.BROKEN
        assert not status.is_usable


class TestSessionModes:
    """Two entry points, because installations differ (§3.2, §3.3)."""

    def test_a_launcher_is_invoked_directly(self, tmp_path) -> None:
        from foamwb.services.runtime.native import NativeSession

        launcher = tmp_path / "openfoam"
        launcher.write_text('#!/bin/sh\nexec "$@"\n')
        launcher.chmod(0o755)
        session = NativeSession(launcher)
        code, output = session.run_to_completion(["echo", "hello"], timeout=30)
        session.close()
        assert code == 0
        assert output.strip() == "hello"

    def test_a_bashrc_is_sourced_before_the_command(self, tmp_path) -> None:
        # The Debian packages that serve Linux and the WSL distribution ship
        # etc/bashrc without a wrapper. This is §3.2's command bridge, and it is
        # what WslSession needs at M3.
        from foamwb.services.runtime.native import NativeSession

        bashrc = tmp_path / "bashrc"
        bashrc.write_text("export WM_PROJECT_VERSION=vTEST\n")
        session = NativeSession(bashrc=bashrc)
        code, output = session.run_to_completion(
            ["bash", "-c", "echo $WM_PROJECT_VERSION"], timeout=30
        )
        session.close()
        assert code == 0
        assert output.strip() == "vTEST"

    def test_arguments_are_never_reparsed_by_the_shell(self, tmp_path) -> None:
        # NFR-C4: a case directory with a space, a quote or a $ must stay one
        # argument. The command is expanded with "$@", so the shell never sees it.
        from foamwb.services.runtime.native import NativeSession

        bashrc = tmp_path / "bashrc"
        bashrc.write_text("export MARKER=expanded\n")
        session = NativeSession(bashrc=bashrc)
        code, output = session.run_to_completion(["echo", "a b", "c$MARKER", "d'e"], timeout=30)
        session.close()
        assert code == 0
        assert output.strip() == "a b c$MARKER d'e"

    def test_a_bashrc_path_with_spaces_survives(self, tmp_path) -> None:
        from foamwb.services.runtime.native import NativeSession

        directory = tmp_path / "my openfoam"
        directory.mkdir()
        bashrc = directory / "bashrc"
        bashrc.write_text("export WM_PROJECT_VERSION=vTEST\n")
        session = NativeSession(bashrc=bashrc)
        code, output = session.run_to_completion(
            ["bash", "-c", "echo $WM_PROJECT_VERSION"], timeout=30
        )
        session.close()
        assert code == 0
        assert output.strip() == "vTEST"

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"launcher": Path("/a"), "bashrc": Path("/b")}],
    )
    def test_exactly_one_entry_point_is_required(self, kwargs) -> None:
        # A session with neither would run every solver outside the OpenFOAM
        # environment, which looks like a broken installation rather than a
        # misconfigured session.
        from foamwb.services.runtime.native import NativeSession

        with pytest.raises(ValueError, match="exactly one"):
            NativeSession(**kwargs)


class TestLinuxDiscovery:
    """The layout that serves the CI runner and, at M3, the WSL distribution."""

    def _linux_root(self, manifest) -> tuple[str, str]:
        version = manifest.versions[0]
        spec = manifest.release(version).platform("linux")
        return version, spec.get("root")

    def test_the_manifest_declares_a_linux_layout(self, manifest) -> None:
        # Without this the gate finds no runtime in CI, skips every test, and
        # reports green having verified nothing.
        for version in manifest.versions:
            spec = manifest.release(version).platform("linux")
            assert spec is not None, version
            assert spec.get("root"), version
            assert spec.bashrc, version

    def test_a_bashrc_only_installation_is_found(self, tmp_path) -> None:
        # The Debian package ships etc/bashrc and no wrapper. Requiring the
        # wrapper is exactly why the first CI run found nothing and every gate
        # skipped itself.
        from foamwb.services.runtime.manifest import parse_manifest

        root = tmp_path / "openfoam"
        (root / "etc").mkdir(parents=True)
        (root / "etc" / "bashrc").write_text("export WM_PROJECT_VERSION=v0000\n")

        manifest = parse_manifest(
            json.dumps(
                {
                    "schema": 1,
                    "lineage": "esi",
                    "default": "v0000",
                    "minimum_supported": "v0000",
                    "releases": {
                        "v0000": {
                            "linux": {
                                "root": str(root),
                                "launcher": "etc/openfoam",
                                "bashrc": str(root / "etc" / "bashrc"),
                            }
                        }
                    },
                }
            )
        )

        found = RuntimeManager(manifest, application_dirs=(tmp_path / "none",)).discover()
        assert len(found) == 1
        assert found[0].launcher is None
        assert found[0].bashrc == root / "etc" / "bashrc"

    def test_a_wrapper_is_preferred_when_both_exist(self, tmp_path) -> None:
        from foamwb.services.runtime.manifest import parse_manifest

        root = tmp_path / "openfoam"
        (root / "etc").mkdir(parents=True)
        (root / "etc" / "bashrc").write_text("x\n")
        (root / "etc" / "openfoam").write_text("#!/bin/sh\n")

        manifest = parse_manifest(
            json.dumps(
                {
                    "schema": 1,
                    "lineage": "esi",
                    "default": "v0000",
                    "minimum_supported": "v0000",
                    "releases": {
                        "v0000": {
                            "linux": {
                                "root": str(root),
                                "launcher": "etc/openfoam",
                                "bashrc": str(root / "etc" / "bashrc"),
                            }
                        }
                    },
                }
            )
        )
        found = RuntimeManager(manifest, application_dirs=(tmp_path / "none",)).discover()
        assert found[0].launcher is not None
        assert found[0].bashrc is None
