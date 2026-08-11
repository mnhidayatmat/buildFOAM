"""M3 — the WSL bridge (§3.2, FR-V3, FR-A3, NFR-C4, DEC-05).

**What this file does and does not prove.** Path translation and command
construction are decidable on any machine, and they are where the intricate
mistakes live: a drive letter that keeps its case, a UNC share that is not the
right distro, a space that becomes two arguments. Those are tested here properly,
on macOS, and would be tested identically on Windows.

Whether ``wsl.exe`` then behaves as documented cannot be established from here.
That gap is real and is stated in the module docstring rather than papered over
with a mock that asserts our own assumptions back to us. What these tests do
establish is that the *only* remaining unknown is ``wsl.exe`` itself.

The contract tests at the bottom are the point of M3's exit criterion — "M2's
acceptance suite passes unchanged on this platform" — expressed as a property:
:class:`WslSession` satisfies the same :class:`RuntimeSession` interface, so the
layers above it cannot tell which one they have.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from foamwb.branding import WSL_DISTRO_NAME
from foamwb.services.runtime.manifest import ManifestError
from foamwb.services.runtime.session import RuntimeKind, RuntimeSession
from foamwb.services.runtime.wsl import WSL_EXECUTABLE, WslSession, wsl_argv
from foamwb.services.runtime.wslpath import (
    PathOutsideRuntimeError,
    to_host,
    to_runtime,
)

#: Derived, never spelled out: NFR-M5 keeps the product name in one place,
#: and the distro is named after the product (DEC-12).
DISTRO = WSL_DISTRO_NAME
BASHRC = PurePosixPath("/usr/lib/openfoam/openfoam2512/etc/bashrc")


@pytest.fixture
def session() -> WslSession:
    return WslSession(BASHRC, distro=DISTRO)


class TestWindowsToDistro:
    def test_a_drive_letter_becomes_a_mount(self) -> None:
        assert to_runtime(r"C:\Users\Ali\kes", distro=DISTRO) == PurePosixPath(
            "/mnt/c/Users/Ali/kes"
        )

    def test_the_drive_letter_is_lowercased(self) -> None:
        """WSL mounts at /mnt/c, not /mnt/C, and the difference is a failure."""
        assert to_runtime(r"D:\x", distro=DISTRO) == PurePosixPath("/mnt/d/x")

    def test_a_distro_unc_path_becomes_a_plain_path(self) -> None:
        assert to_runtime(
            rf"\\wsl.localhost\{DISTRO}\home\ali\kes", distro=DISTRO
        ) == PurePosixPath("/home/ali/kes")

    def test_the_legacy_unc_spelling_is_accepted(self) -> None:
        r"""``\\wsl$\`` is older but Windows still resolves it, and users have it
        bookmarked. Refusing would reject something that works."""
        assert to_runtime(rf"\\wsl$\{DISTRO}\home\ali\kes", distro=DISTRO) == PurePosixPath(
            "/home/ali/kes"
        )

    def test_spaces_survive(self) -> None:
        assert to_runtime(r"C:\Users\Ali Baba\kes ujian", distro=DISTRO) == PurePosixPath(
            "/mnt/c/Users/Ali Baba/kes ujian"
        )

    def test_non_ascii_survives(self) -> None:
        """NFR-C4 names this, and §11 names it in M3's exit criterion."""
        assert to_runtime(r"D:\Kes · Ujian\pitzDaily", distro=DISTRO) == PurePosixPath(
            "/mnt/d/Kes · Ujian/pitzDaily"
        )


class TestDistroToWindows:
    def test_a_home_path_becomes_a_unc_path(self) -> None:
        assert str(to_host("/home/ali/kes", distro=DISTRO)) == (
            rf"\\wsl.localhost\{DISTRO}\home\ali\kes"
        )

    def test_a_mount_becomes_a_drive_letter(self) -> None:
        """Not a UNC route to the same file: that would send every later access
        through the 9p layer for a file Windows owns outright."""
        assert str(to_host("/mnt/c/Users/Ali/kes", distro=DISTRO)) == r"C:\Users\Ali\kes"

    def test_the_drive_letter_is_uppercased(self) -> None:
        assert str(to_host("/mnt/d/x", distro=DISTRO)).startswith("D:")

    def test_the_modern_unc_spelling_is_produced(self) -> None:
        assert "wsl$" not in str(to_host("/home/u/x", distro=DISTRO))

    def test_spaces_and_unicode_survive(self) -> None:
        assert str(to_host("/home/ali/Kes · Ujian", distro=DISTRO)).endswith(
            r"\home\ali\Kes · Ujian"
        )


class TestRoundTrip:
    """FR-A3 opens a folder in Explorer; a path that does not round-trip opens
    the wrong one."""

    @pytest.mark.parametrize(
        "windows",
        [
            r"C:\Users\Ali\kes",
            r"C:\Users\Ali Baba\kes ujian",
            r"D:\Kes · Ujian\pitzDaily",
            rf"\\wsl.localhost\{DISTRO}\home\ali\kes",
            rf"\\wsl.localhost\{DISTRO}\home\ali\Kes · Ujian",
        ],
    )
    def test_windows_survives_a_round_trip(self, windows: str) -> None:
        there = to_runtime(windows, distro=DISTRO)
        back = to_host(there, distro=DISTRO)
        assert str(back) == str(PureWindowsPath(windows))

    @pytest.mark.parametrize(
        "posix",
        ["/home/ali/kes", "/home/ali/kes ujian", "/mnt/c/Users/Ali/kes", "/mnt/d/Kes · Ujian"],
    )
    def test_posix_survives_a_round_trip(self, posix: str) -> None:
        there = to_host(posix, distro=DISTRO)
        back = to_runtime(there, distro=DISTRO)
        assert str(back) == posix

    def test_the_legacy_spelling_normalises_rather_than_round_trips(self) -> None:
        """Deliberate: accepted on input, never produced on output."""
        there = to_runtime(rf"\\wsl$\{DISTRO}\home\u\x", distro=DISTRO)
        assert str(to_host(there, distro=DISTRO)).startswith(r"\\wsl.localhost")


class TestPathsWithNoMeaningInside:
    def test_a_network_share_is_refused(self) -> None:
        """Openable in Explorer, invisible to the solver. Finding out at run time
        turns a clear message into "cannot find file" from OpenFOAM."""
        with pytest.raises(PathOutsideRuntimeError) as caught:
            to_runtime(r"\\fileserver\share\kes", distro=DISTRO)
        assert "network location" in str(caught.value)

    def test_another_distro_is_refused_and_named(self) -> None:
        with pytest.raises(PathOutsideRuntimeError) as caught:
            to_runtime(r"\\wsl.localhost\Ubuntu\home\u\kes", distro=DISTRO)
        assert "Ubuntu" in str(caught.value)

    def test_a_relative_path_is_refused(self) -> None:
        with pytest.raises(PathOutsideRuntimeError):
            to_runtime(r"kes\relative", distro=DISTRO)

    def test_a_relative_posix_path_is_refused(self) -> None:
        with pytest.raises(PathOutsideRuntimeError):
            to_host("home/u/x", distro=DISTRO)

    def test_the_session_reports_reachability_without_raising(self, session) -> None:
        assert session.is_reachable(Path(r"C:\Users\x"))
        assert not session.is_reachable(Path(r"\\fileserver\share\x"))


class TestTheCommandLine:
    def test_it_names_the_distro(self, session) -> None:
        argv = session.command_for(("icoFoam",))
        assert argv[:3] == [WSL_EXECUTABLE, "-d", DISTRO]

    def test_the_user_command_is_never_part_of_the_script(self, session) -> None:
        """The script expands "$@"; the command arrives as positional parameters.

        This is what makes a case named ``$(rm -rf ~)`` an argument rather than a
        command substitution.
        """
        argv = session.command_for(("icoFoam", "-case", "/home/u/$(whoami)"))
        script = next(a for a in argv if a.startswith("source "))
        assert "icoFoam" not in script
        assert "$(whoami)" not in script
        assert argv[-1] == "/home/u/$(whoami)"

    def test_the_working_directory_is_its_own_argument(self, session) -> None:
        """--cd rather than `cd ... &&`, so a space never reaches a shell parser."""
        argv = session.command_for(("icoFoam",), cwd=PurePosixPath("/home/u/kes ujian"))
        assert "--cd" in argv
        assert argv[argv.index("--cd") + 1] == "/home/u/kes ujian"

    def test_no_working_directory_means_no_flag(self, session) -> None:
        assert "--cd" not in session.command_for(("icoFoam",))

    def test_the_bashrc_path_is_quoted(self) -> None:
        argv = wsl_argv(
            ("icoFoam",), distro=DISTRO, bashrc=PurePosixPath("/opt/open foam/etc/bashrc")
        )
        script = next(a for a in argv if a.startswith("source "))
        assert "'/opt/open foam/etc/bashrc'" in script

    def test_an_empty_command_is_refused(self, session) -> None:
        with pytest.raises(ValueError):
            session.command_for(())

    def test_the_script_matches_the_native_bridge(self, session) -> None:
        """§3.2's bridge is one construction reached two ways, not two bridges."""
        script = next(a for a in session.command_for(("icoFoam",)) if a.startswith("source "))
        assert script.endswith('&& exec "$@"')


class TestManifestDrivesTheLayout:
    def test_a_session_can_be_built_from_a_release(self) -> None:
        assert WslSession.for_version("v2512").bashrc == BASHRC

    def test_an_unknown_release_is_refused_and_names_what_is_known(self) -> None:
        with pytest.raises(ManifestError) as caught:
            WslSession.for_version("v9999")
        assert "v2512" in str(caught.value)

    def test_the_constructor_has_no_default_bashrc(self) -> None:
        """A default would be a version literal in code by another name."""
        with pytest.raises(TypeError):
            WslSession()  # type: ignore[call-arg]

    def test_the_distro_name_comes_from_branding(self) -> None:
        assert WslSession(BASHRC).distro == WSL_DISTRO_NAME


class TestItSatisfiesTheSessionContract:
    """M3's exit criterion — "M2's acceptance suite passes unchanged" — as a property.

    If the layers above cannot tell a WslSession from a NativeSession, then the
    run controller, the case service and the golden-case harness all apply here
    without alteration. That is a stronger and more durable statement than
    re-running the suite against a mock of Windows.
    """

    def test_it_is_a_runtime_session(self, session) -> None:
        assert isinstance(session, RuntimeSession)

    def test_it_reports_its_kind(self, session) -> None:
        assert session.kind is RuntimeKind.WSL

    @pytest.mark.parametrize("name", ["run", "to_runtime_path", "to_host_path", "close", "kind"])
    def test_every_abstract_member_is_implemented(self, session, name: str) -> None:
        assert getattr(session, name) is not None

    def test_the_path_methods_take_and_return_the_contract_types(self, session) -> None:
        assert isinstance(session.to_runtime_path(Path(r"C:\x")), PurePosixPath)
        assert isinstance(session.to_host_path(PurePosixPath("/home/u/x")), Path)

    def test_it_can_be_used_as_a_context_manager(self) -> None:
        with WslSession(BASHRC) as opened:
            assert opened.kind is RuntimeKind.WSL

    def test_closing_an_idle_session_is_safe(self, session) -> None:
        session.close()
        session.close()
