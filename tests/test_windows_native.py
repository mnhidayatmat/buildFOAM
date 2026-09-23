"""Native Windows runtime (FR-N): discovery, command construction, execution.

Three layers, each run where it can be:

* **Anywhere** — discovery, version reading, the ``mpirun`` rewrite and the
  environment are pure functions of a directory tree, so they are tested
  against a fabricated installation on every platform.
* **On Windows** — a copy of ``cmd.exe`` stands in for an OpenFOAM executable,
  which proves resolution, environment, streaming and tree-kill against real
  processes without needing OpenFOAM.
* **With a real build** — set ``FOAMWB_WINDOWS_OPENFOAM`` to an installation's
  root and the cavity tutorial runs serially and on two MPI ranks through the
  same :class:`RunController` the Run page uses.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.runtime import RuntimeKind, RuntimeManager, RuntimeState
from foamwb.services.runtime.manifest import load_manifest
from foamwb.services.runtime.windows import (
    STATUS_DLL_NOT_FOUND,
    WindowsNativeSession,
    find_platform_dir,
    read_api_version,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows processes")

ARCH = "someMingwDPInt32Opt"


def _api(version: str) -> str:
    return version.removeprefix("v")


def make_install(root: Path, *, version: str | None = None, pstreams=("msmpi", "dummy")) -> Path:
    """A native Windows installation's layout, with empty files for executables."""
    version = version or load_manifest().default_version
    bin_dir = root / "platforms" / ARCH / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("blockMesh", "icoFoam", "decomposePar"):
        (bin_dir / f"{name}.exe").write_bytes(b"")
    for pstream in pstreams:
        (root / "platforms" / ARCH / "lib" / pstream).mkdir(parents=True)
    (root / "META-INFO").mkdir()
    (root / "META-INFO" / "api-info").write_text(f"api={_api(version)}\npatch=0\n")
    (root / "tutorials").mkdir()
    return root


@pytest.fixture(autouse=True)
def _no_ambient_install(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer machine with a real install must not leak into these tests.
    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)


# -- layout ---------------------------------------------------------------------


class TestLayout:
    def test_platform_dir_is_found_by_content_not_name(self, tmp_path: Path) -> None:
        root = make_install(tmp_path / "OpenFOAM-x")
        (root / "platforms" / "tools").mkdir()
        assert find_platform_dir(root) == root / "platforms" / ARCH

    def test_no_platform_dir(self, tmp_path: Path) -> None:
        assert find_platform_dir(tmp_path) is None

    def test_version_comes_from_meta_info(self, tmp_path: Path) -> None:
        version = load_manifest().default_version
        root = make_install(tmp_path / "renamed-by-installer", version=version)
        assert read_api_version(root) == version

    def test_unreadable_meta_info(self, tmp_path: Path) -> None:
        assert read_api_version(tmp_path) is None

    def test_a_session_refuses_a_directory_that_is_not_an_install(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a native Windows"):
            WindowsNativeSession(tmp_path)


# -- command construction ---------------------------------------------------------


class TestCommands:
    @pytest.fixture
    def session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WindowsNativeSession:
        session = WindowsNativeSession(make_install(tmp_path / "of"))
        monkeypatch.setattr(session, "mpiexec", lambda: "C:/MPI/mpiexec.exe")
        return session

    def test_programs_resolve_to_this_installation(self, session: WindowsNativeSession) -> None:
        command, parallel = session.command_for(["icoFoam", "-case", "x"])
        assert command[0] == str(session.bin_dir / "icoFoam.exe")
        assert command[1:] == ["-case", "x"]
        assert parallel is False

    def test_unknown_programs_are_left_alone(self, session: WindowsNativeSession) -> None:
        assert session.command_for(["cmd", "/c", "dir"])[0] == ["cmd", "/c", "dir"]

    def test_mpirun_becomes_mpiexec(self, session: WindowsNativeSession) -> None:
        command, parallel = session.command_for(["mpirun", "-np", "4", "icoFoam", "-parallel"])
        assert command == [
            "C:/MPI/mpiexec.exe",
            "-n",
            "4",
            str(session.bin_dir / "icoFoam.exe"),
            "-parallel",
        ]
        assert parallel is True

    def test_a_parallel_run_without_mpi_says_so(
        self, session: WindowsNativeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(session, "mpiexec", lambda: None)
        with pytest.raises(FileNotFoundError, match="Microsoft MPI"):
            session.command_for(["mpirun", "-np", "2", "icoFoam", "-parallel"])

    def test_empty_argv(self, session: WindowsNativeSession) -> None:
        with pytest.raises(ValueError):
            session.command_for([])

    def test_this_installation_is_first_on_path(self, session: WindowsNativeSession) -> None:
        env = session.environment(parallel=False, base={"Path": "C:/elsewhere"})
        parts = env["PATH"].split(os.pathsep)
        assert parts[0] == str(session.bin_dir)
        assert parts[1] == str(session.lib_dir)
        assert parts[-1] == "C:/elsewhere"
        # The existing entry is replaced, not duplicated under a second spelling.
        assert "Path" not in env
        assert env["WM_PROJECT_DIR"] == str(session.root)
        assert env["WM_PROJECT_VERSION"] == session.version

    def test_parallel_uses_the_mpi_pstream(self, session: WindowsNativeSession) -> None:
        env = session.environment(parallel=True, base={})
        assert str(session.lib_dir / "msmpi") in env["PATH"].split(os.pathsep)

    def test_serial_without_mpi_uses_the_stub(
        self, session: WindowsNativeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(session, "has_mpi_runtime", lambda: False)
        path = session.environment(parallel=False, base={})["PATH"].split(os.pathsep)
        assert str(session.lib_dir / "dummy") in path
        assert str(session.lib_dir / "msmpi") not in path

    def test_paths_are_the_host_paths(self, session: WindowsNativeSession, tmp_path: Path) -> None:
        runtime = session.to_runtime_path(tmp_path / "a case")
        assert isinstance(runtime, PurePosixPath)
        assert session.to_host_path(runtime) == tmp_path / "a case"
        assert session.kind is RuntimeKind.WINDOWS_NATIVE


# -- discovery ---------------------------------------------------------------------


class TestDiscovery:
    def test_found_under_a_search_root(self, tmp_path: Path) -> None:
        make_install(tmp_path / "roots" / "OpenFOAM-v0001")
        (tmp_path / "roots" / "OpenFOAM-broken").mkdir()
        manager = RuntimeManager(application_dirs=(), windows_roots=(tmp_path / "roots",))
        found = [i for i in manager.discover() if i.is_windows_native]
        assert len(found) == 1
        assert found[0].version == load_manifest().default_version
        assert found[0].platform_dir.name == ARCH

    def test_found_through_wm_project_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = make_install(tmp_path / "anywhere")
        monkeypatch.setenv("WM_PROJECT_DIR", str(root))
        manager = RuntimeManager(application_dirs=(), windows_roots=())
        assert [i.bundle for i in manager.discover() if i.is_windows_native] == [root.resolve()]

    def test_the_same_install_is_listed_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = make_install(tmp_path / "roots" / "OpenFOAM-v0001")
        monkeypatch.setenv("WM_PROJECT_DIR", str(root))
        manager = RuntimeManager(application_dirs=(), windows_roots=(tmp_path / "roots",))
        assert len([i for i in manager.discover() if i.is_windows_native]) == 1

    def test_session_for_a_native_install(self, tmp_path: Path) -> None:
        make_install(tmp_path / "roots" / "OpenFOAM-v0001")
        manager = RuntimeManager(application_dirs=(), windows_roots=(tmp_path / "roots",))
        installation = next(i for i in manager.discover() if i.is_windows_native)
        session = manager.session_for(installation)
        assert isinstance(session, WindowsNativeSession)
        assert session.version == installation.version

    def test_tutorials_without_a_shell(self, tmp_path: Path) -> None:
        make_install(tmp_path / "roots" / "OpenFOAM-v0001")
        manager = RuntimeManager(application_dirs=(), windows_roots=(tmp_path / "roots",))
        installation = next(i for i in manager.discover() if i.is_windows_native)
        assert manager.tutorials_dir(installation) == installation.bundle / "tutorials"


class TestVerify:
    @pytest.fixture
    def installed(self, tmp_path: Path):
        make_install(tmp_path / "roots" / "OpenFOAM-v0001")
        manager = RuntimeManager(application_dirs=(), windows_roots=(tmp_path / "roots",))
        return manager, next(i for i in manager.discover() if i.is_windows_native)

    def _canary(self, monkeypatch: pytest.MonkeyPatch, result) -> None:
        def run_to_completion(self, argv, *, cwd=None, timeout=None):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(WindowsNativeSession, "run_to_completion", run_to_completion)

    def test_ready(self, installed, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, installation = installed
        self._canary(monkeypatch, (0, "Usage: blockMesh [OPTIONS]"))
        status = manager.verify(installation)
        assert status.state is RuntimeState.READY
        assert status.kind is RuntimeKind.WINDOWS_NATIVE
        assert status.openfoam_version == installation.version

    def test_a_missing_dll_is_named(self, installed, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, installation = installed
        self._canary(monkeypatch, (STATUS_DLL_NOT_FOUND, ""))
        status = manager.verify(installation)
        assert status.state is RuntimeState.BROKEN
        assert status.reason is ErrorCode.RUNTIME_BROKEN
        assert "DLL" in status.detail and "MPI" in status.detail

    def test_an_unsupported_release_is_degraded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_install(tmp_path / "old" / "OpenFOAM-v0001", version="v0001")
        manager = RuntimeManager(application_dirs=(), windows_roots=(tmp_path / "old",))
        installation = next(i for i in manager.discover() if i.is_windows_native)
        self._canary(monkeypatch, (0, ""))
        status = manager.verify(installation)
        assert status.state is RuntimeState.DEGRADED
        assert status.reason is ErrorCode.VERSION_MISMATCH
        assert status.is_usable

    def test_a_canary_that_cannot_start(self, installed, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, installation = installed
        self._canary(monkeypatch, OSError("[WinError 193] not a valid Win32 application"))
        assert manager.verify(installation).state is RuntimeState.BROKEN


# -- real processes on Windows --------------------------------------------------------


@windows_only
class TestProcesses:
    @pytest.fixture
    def session(self, tmp_path: Path) -> WindowsNativeSession:
        root = make_install(tmp_path / "of")
        system = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32" / "cmd.exe"
        shutil.copy(system, root / "platforms" / ARCH / "bin" / "fakeFoam.exe")
        return WindowsNativeSession(root)

    def test_runs_with_the_installation_environment(
        self, session: WindowsNativeSession, tmp_path: Path
    ) -> None:
        work = tmp_path / "a case with spaces"
        work.mkdir()
        code, output = session.run_to_completion(
            ["fakeFoam", "/d", "/c", "echo %WM_PROJECT_DIR%& cd"],
            cwd=session.to_runtime_path(work),
            timeout=60,
        )
        lines = output.splitlines()
        assert code == 0
        assert lines[0] == str(session.root)
        assert Path(lines[1]) == work

    def test_kill_ends_the_tree(self, session: WindowsNativeSession) -> None:
        process = session.run(["fakeFoam", "/d", "/c", "ping -n 120 127.0.0.1 >nul"])
        time.sleep(1)
        started = time.monotonic()
        process.kill()
        process.wait(timeout=30)
        assert time.monotonic() - started < 30
        assert process.returncode is not None

    def test_close_reaps_what_is_running(self, session: WindowsNativeSession) -> None:
        process = session.run(["fakeFoam", "/d", "/c", "ping -n 120 127.0.0.1 >nul"])
        session.close()
        process.wait(timeout=30)
        assert process.returncode is not None


# -- a real native OpenFOAM build -------------------------------------------------------

REAL_ROOT = os.environ.get("FOAMWB_WINDOWS_OPENFOAM")


@windows_only
@pytest.mark.requires_runtime
@pytest.mark.skipif(not REAL_ROOT, reason="set FOAMWB_WINDOWS_OPENFOAM to a native build's root")
def test_cavity_serial_and_parallel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from foamwb.services.case import CaseService
    from foamwb.services.run import RunController, build_plan

    root = Path(REAL_ROOT)
    monkeypatch.setenv("WM_PROJECT_DIR", str(root))
    manager = RuntimeManager(application_dirs=(), windows_roots=())
    installation = next(i for i in manager.discover() if i.is_windows_native)
    assert manager.verify(installation).is_usable

    case_dir = tmp_path / "cavity"
    tutorials = root / "tutorials"
    source = tutorials / "incompressible" / "icoFoam" / "cavity" / "cavity"
    if source.is_dir():
        shutil.copytree(source, case_dir)
    else:
        archive = next(tutorials.glob("*.zip"))
        marker = "incompressible/icoFoam/cavity/cavity/"
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if marker in name and not name.endswith("/"):
                    target = case_dir / name.split(marker, 1)[1]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(name))
    (case_dir / "system" / "decomposeParDict").write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\n"
        "numberOfSubdomains 2;\nmethod simple;\ncoeffs { n (2 1 1); }\n",
        encoding="utf-8",
    )

    cases = CaseService()
    session = manager.session_for(installation)
    for n_procs in (1, 2):
        case = cases.open(case_dir)
        result = RunController(session).execute(build_plan(case, n_procs=n_procs))
        assert result.succeeded, [(s.name, s.state, s.detail) for s in result.stages]
        assert cases.open(case_dir).latest_time not in (None, "0")
    session.close()


class TestPathsTheBuildCannotOpen:
    """E-C18: measured on a real build — accents run, other scripts do not."""

    def test_latin_accents_pass_on_a_western_code_page(self) -> None:
        from foamwb.services.runtime.windows import check_representable

        check_representable("C:/cases/föö bär", "cp1252")

    def test_another_script_is_refused_with_its_code(self) -> None:
        from foamwb.services.runtime.windows import UnrepresentablePathError, check_representable

        with pytest.raises(UnrepresentablePathError) as caught:
            check_representable("C:/cases/模拟", "cp1252")
        assert caught.value.code is ErrorCode.PATH_NOT_REPRESENTABLE
        assert "模拟" in str(caught.value)

    def test_the_run_fails_before_starting_and_names_the_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from foamwb.services.run import RunController
        from foamwb.services.run.plan import RunPlan, Stage, StageState
        from foamwb.services.runtime import windows

        monkeypatch.setattr(windows, "ansi_code_page", lambda: "cp1252")
        session = WindowsNativeSession(make_install(tmp_path / "of"))
        started = []
        monkeypatch.setattr(windows.subprocess, "Popen", lambda *a, **k: started.append(a))
        case = tmp_path / "模拟"
        case.mkdir()
        result = RunController(session).execute(
            RunPlan(case=case, stages=(Stage("blockMesh", argv=("blockMesh",)),))
        )
        stage = result.stages[0]
        assert stage.state is StageState.FAILED
        assert stage.reason is ErrorCode.PATH_NOT_REPRESENTABLE
        assert started == []
