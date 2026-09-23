"""Native Windows runtime — OpenFOAM compiled for Windows itself (FR-N).

Some OpenFOAM distributions for Windows are neither WSL nor a container: they
are the ESI sources cross-compiled with MinGW into ordinary ``.exe`` files and
DLLs, with MS-MPI for parallel runs. There is no bash to source an
``etc/bashrc`` into — the ``bin/`` shell scripts ship but cannot run — so the
bridge §3.2 describes does not apply, and this session replaces it.

**The environment is built here, not inherited.** Such installers extend the
*system* ``PATH`` and set ``WM_PROJECT_DIR``, and a program started with those
works. But relying on them means a user who installed two versions runs
whichever the ``PATH`` names first, and one whose installer was interrupted
runs nothing. The session therefore puts its own installation's ``bin`` and
``lib`` first on the ``PATH`` of every child, so the release the footer names is
the release that runs (§7.9 rule 4).

**Which Pstream.** OpenFOAM's inter-process layer is a DLL, and a Windows build
ships two: ``lib/msmpi`` (needs the MS-MPI runtime) and ``lib/dummy`` (serial
only, needs nothing). A parallel stage must have MS-MPI; a serial one uses it
when it is present and the stub when it is not. Without that fallback a
machine lacking MS-MPI could not run even a serial case, and the failure would
be a missing-DLL exit code rather than anything a user could act on.

**Stopping.** Windows console programs have no SIGTERM, and a child with no
console window of its own cannot be sent CTRL+BREAK. *Stop Now* and *Force
Kill* therefore both end the process tree with ``taskkill /T /F``, which also
reaches the MPI ranks ``mpiexec`` started (FR-S10). *Stop & Write* — the
default — is unaffected: it is a trigger file the solver reads, and works here
exactly as it does everywhere else (FR-S5).
"""

from __future__ import annotations

import contextlib
import locale
import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath

from foamwb.codes import ErrorCode
from foamwb.logs import Event, get_logger, log_event
from foamwb.services.runtime.session import Process, RuntimeKind, RuntimeSession

__all__ = [
    "CANARY_UTILITY",
    "STATUS_DLL_NOT_FOUND",
    "UnrepresentablePathError",
    "WindowsNativeProcess",
    "WindowsNativeSession",
    "ansi_code_page",
    "check_representable",
    "find_platform_dir",
    "read_api_version",
    "unpack_tutorials",
]

_log = get_logger("runtime.windows")

#: The exit status Windows gives a program whose DLLs could not be loaded
#: (0xC0000135). Named because it is the commonest way a native build fails —
#: MS-MPI not installed, or a ``lib`` directory missing — and "exit code
#: 3221225781" tells nobody that.
STATUS_DLL_NOT_FOUND = 0xC0000135

#: A utility that every build has and that exits 0 on ``-help`` without a case.
#: Starting it proves the executables and every DLL they need resolve.
CANARY_UTILITY = "blockMesh"

_API = re.compile(r"^\s*api\s*=\s*(\d+)\s*$", re.MULTILINE)

# subprocess flags; absent from the module on other platforms, where this
# session is never constructed but the module must still import (the test suite
# and the services layer are cross-platform).
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_platform_dir(root: Path) -> Path | None:
    """The ``platforms/<arch>`` directory holding this build's executables.

    Found by what it contains rather than by name: the architecture string
    (``linux64MingwDPInt32Opt`` and its siblings) encodes compiler, precision
    and label size, and guessing it would fail the first time a build used
    single precision or 64-bit labels.
    """
    platforms = root / "platforms"
    if not platforms.is_dir():
        return None
    for candidate in sorted(platforms.iterdir()):
        if (candidate / "bin" / f"{CANARY_UTILITY}.exe").is_file():
            return candidate
    return None


def read_api_version(root: Path) -> str | None:
    """The release, as the manifest names it, from ``META-INFO/api-info``.

    Read from the build's own record rather than from the directory name, which
    an installer is free to choose.
    """
    try:
        text = (root / "META-INFO" / "api-info").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _API.search(text)
    return f"v{match.group(1)}" if match else None


def unpack_tutorials(tutorials: Path, cache: Path) -> Path | None:
    """The tutorial tree of a build that ships it zipped, unpacked once.

    Some native Windows builds carry ``tutorials/tutorials.zip`` and no tree —
    14 000 small files are slow to install and slower to uninstall — but every
    consumer of ``FOAM_TUTORIALS`` wants directories: the library, the golden
    gate, a user opening *cavity*. The archive is unpacked into ``cache`` on
    first use and reused after. Extraction goes to a temporary directory that is
    renamed into place, so an interrupted unpack is never mistaken for a
    complete one; and an entry that would land outside the target is refused,
    as the content library refuses one (FR-L3).
    """
    if not tutorials.is_dir():
        return None
    if any(child.is_dir() for child in tutorials.iterdir()):
        return tutorials
    archives = sorted(tutorials.glob("*.zip"))
    if not archives:
        return None
    if cache.is_dir():
        return cache

    staging = cache.with_name(cache.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archives[0]) as bundle:
            for member in bundle.infolist():
                target = (staging / member.filename).resolve()
                if not target.is_relative_to(staging.resolve()):
                    raise ValueError(f"{member.filename} would unpack outside the tutorials")
            bundle.extractall(staging)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        log_event(_log, Event.ERROR_RAISED, where="unpack_tutorials", error=str(exc))
        return None
    staging.replace(cache)
    return cache


class UnrepresentablePathError(OSError):
    """A path the build cannot open, refused before anything starts (E-C18).

    An ``OSError`` because that is what a session raises when it cannot start a
    command, and the controller already turns one into a failed stage; the
    ``code`` attribute lets it name *this* failure rather than a missing solver.
    """

    def __init__(self, path: str, encoding: str) -> None:
        super().__init__(
            f"{path} contains characters outside this computer's code page ({encoding}), "
            "which this OpenFOAM build cannot open. Move or rename the case folder."
        )
        self.code = ErrorCode.PATH_NOT_REPRESENTABLE
        self.path = path


def ansi_code_page() -> str:
    """The encoding narrow-character Windows APIs use in child processes."""
    if os.name == "nt":
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetACP()}"
    return locale.getpreferredencoding(False)


def check_representable(path: str, encoding: str | None = None) -> None:
    """Raise :class:`UnrepresentablePathError` if ``path`` cannot reach the build.

    Measured on the installed build rather than assumed: spaces and accented
    Latin letters run, CJK characters on a Western-European code page make
    ``blockMesh`` exit 1 with no explanation.
    """
    encoding = encoding or ansi_code_page()
    try:
        path.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        raise UnrepresentablePathError(path, encoding) from None


class WindowsNativeProcess(Process):
    """A native Windows command and the process tree it starts."""

    def __init__(self, popen: subprocess.Popen[str], argv: Sequence[str]) -> None:
        self._popen = popen
        self._argv = tuple(argv)

    @property
    def pid(self) -> int | None:
        return self._popen.pid

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode

    @property
    def argv(self) -> tuple[str, ...]:
        return self._argv

    def lines(self) -> Iterator[str]:
        stream = self._popen.stdout
        if stream is None:  # pragma: no cover - always piped by run()
            return
        for line in stream:
            yield line.rstrip("\r\n")
        stream.close()

    def wait(self, timeout: float | None = None) -> int:
        try:
            return self._popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"{self._argv[0]!r} did not exit within {timeout}s") from exc

    def _end_tree(self) -> None:
        """End the process and everything it started, tolerating a race with exit."""
        if self._popen.poll() is not None:
            return
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["taskkill", "/PID", str(self._popen.pid), "/T", "/F"],
                capture_output=True,
                timeout=30,
                check=False,
                creationflags=_CREATE_NO_WINDOW,
            )
        if self._popen.poll() is None:
            # taskkill missing or refused: at least end the root.
            self._popen.kill()

    def terminate(self) -> None:
        """FR-S5's *Stop Now*. Forceful on Windows — see the module docstring."""
        self._end_tree()

    def kill(self) -> None:
        """FR-S5's *Force Kill*."""
        self._end_tree()


class WindowsNativeSession(RuntimeSession):
    """Runs a native Windows OpenFOAM build's executables directly."""

    def __init__(
        self,
        root: Path,
        *,
        platform_dir: Path | None = None,
        version: str | None = None,
        mpi: Mapping[str, str] | None = None,
    ) -> None:
        """``root`` is the installation (``WM_PROJECT_DIR``).

        ``mpi`` is the manifest's ``windows_native.mpiexec`` block: the
        launcher's file name, the variable that locates it, and the runtime DLL
        whose presence means MS-MPI is installed.
        """
        self._root = root
        found = platform_dir or find_platform_dir(root)
        if found is None:
            raise ValueError(
                f"{root} has no platforms/<arch>/bin/{CANARY_UTILITY}.exe; "
                "it is not a native Windows OpenFOAM installation."
            )
        self._platform = found
        self._version = version or read_api_version(root)
        self._mpi = dict(mpi or {})
        self._processes: list[WindowsNativeProcess] = []

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.WINDOWS_NATIVE

    @property
    def root(self) -> Path:
        return self._root

    @property
    def bin_dir(self) -> Path:
        return self._platform / "bin"

    @property
    def lib_dir(self) -> Path:
        return self._platform / "lib"

    @property
    def version(self) -> str | None:
        return self._version

    # -- MPI ---------------------------------------------------------------

    def mpiexec(self) -> str | None:
        """The MPI launcher, or ``None`` when MS-MPI is not installed."""
        name = self._mpi.get("executable", "mpiexec.exe")
        variable = self._mpi.get("bin_variable")
        if variable and (directory := os.environ.get(variable)):
            candidate = Path(directory) / name
            if candidate.is_file():
                return str(candidate)
        return shutil.which(name)

    def has_mpi_runtime(self) -> bool:
        """Whether the MS-MPI runtime DLL can be loaded by a child process."""
        dll = self._mpi.get("runtime_dll")
        if not dll:
            return self.mpiexec() is not None
        system = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32" / dll
        return system.is_file() or shutil.which(dll) is not None

    # -- command construction ----------------------------------------------

    def resolve(self, name: str) -> str:
        """An OpenFOAM program's full path, or ``name`` unchanged if it is not one.

        Resolved rather than left to ``PATH``, so the executable that runs is
        this installation's even when another is earlier on the system path.
        """
        candidate = self.bin_dir / (name if name.lower().endswith(".exe") else f"{name}.exe")
        return str(candidate) if candidate.is_file() else name

    def command_for(self, argv: Sequence[str]) -> tuple[list[str], bool]:
        """The command that reaches the OS, and whether it is an MPI launch.

        A parallel stage arrives as ``mpirun -np N <solver> ... -parallel``
        (:meth:`Stage.render`), which is Open MPI's spelling. MS-MPI's is
        ``mpiexec -n N``, so the launcher and its count are rewritten and the
        rest is kept as it came.
        """
        if not argv:
            raise ValueError("argv must not be empty")
        tokens = list(argv)
        if tokens[0] not in {"mpirun", "mpiexec"}:
            return [self.resolve(tokens[0]), *tokens[1:]], False

        launcher = self.mpiexec()
        if launcher is None:
            raise FileNotFoundError(
                "A parallel run needs Microsoft MPI (mpiexec.exe), which was not found. "
                "Install MS-MPI, or run with one processor."
            )
        rest = tokens[1:]
        count: list[str] = []
        if len(rest) >= 2 and rest[0] in {"-np", "-n"}:
            count, rest = ["-n", rest[1]], rest[2:]
        if not rest:
            raise ValueError("An MPI launch must name the program to run")
        return [launcher, *count, self.resolve(rest[0]), *rest[1:]], True

    def environment(
        self, *, parallel: bool, base: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        """The environment a child runs in: this installation first on ``PATH``."""
        environment = dict(base if base is not None else os.environ)
        pstream = "msmpi" if parallel or self.has_mpi_runtime() else "dummy"
        head = [self.bin_dir, self.lib_dir]
        if (self.lib_dir / pstream).is_dir():
            head.append(self.lib_dir / pstream)
        # Windows environment names are case-insensitive but a dict is not; find
        # whatever spelling of PATH is already there rather than adding a second.
        key = next((k for k in environment if k.upper() == "PATH"), "PATH")
        existing = environment.pop(key, "")
        environment["PATH"] = os.pathsep.join([*map(str, head), *filter(None, [existing])])
        environment["WM_PROJECT_DIR"] = str(self._root)
        environment.setdefault("WM_PROJECT", "OpenFOAM")
        if self._version:
            environment["WM_PROJECT_VERSION"] = self._version
        return environment

    # -- execution ---------------------------------------------------------

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: PurePosixPath | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Process:
        """Start ``argv`` from this installation, as a token list — never a shell."""
        command, parallel = self.command_for(argv)
        if cwd is not None:
            check_representable(str(self.to_host_path(cwd)))
        environment = {**self.environment(parallel=parallel), **(env or {})}

        log_event(_log, Event.COMMAND_BEGIN, argv=list(argv), cwd=str(cwd) if cwd else None)

        popen = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Its own group so the tree can be ended as one (FR-S10), and no
            # console window flashing up over the application for every stage.
            creationflags=_CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW,
        )
        process = WindowsNativeProcess(popen, argv)
        self._processes.append(process)
        return process

    # -- path translation --------------------------------------------------

    def to_runtime_path(self, host_path: Path) -> PurePosixPath:
        """The host path itself, in forward-slash form.

        Windows accepts ``C:/cases/duct`` everywhere it accepts ``C:\\cases\\duct``,
        so the runtime path is the host path and the abstraction's POSIX type
        costs nothing.
        """
        return PurePosixPath(Path(host_path).as_posix())

    def to_host_path(self, runtime_path: PurePosixPath) -> Path:
        return Path(str(runtime_path))

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """End anything still running. Idempotent (NFR-R6)."""
        for process in self._processes:
            if process.returncode is None and process._popen.poll() is None:
                process.kill()
        self._processes.clear()
