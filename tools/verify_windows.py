"""Windows verification harness (§12.4, M3).

Run this on the Windows machine. Everything about the WSL bridge has been
written against documentation and tested as pure logic; nothing has ever
executed. This script is what turns that into evidence.

    python tools\\verify_windows.py            # report only, changes nothing
    python tools\\verify_windows.py --run      # also runs a real solver

**Read-only by default.** It inspects, translates, and compares — it does not
install WSL, import a distribution, or write into a case. Provisioning is a
separate decision and a much longer operation, and a verification script that
quietly starts one would be the wrong kind of surprise on a machine you were
only meant to be testing on.

Every check prints what it *expected* as well as what it found, because the
value of this run is in the mismatches, and a bare FAIL tells whoever reads the
output nothing they can act on.
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from foamwb.branding import WSL_DISTRO_NAME  # noqa: E402
from foamwb.services.runtime.wsl import WslSession, wsl_argv  # noqa: E402
from foamwb.services.runtime.wslpath import (  # noqa: E402
    PathOutsideRuntimeError,
    to_host,
    to_runtime,
)

PASS, FAIL, SKIP, INFO = "PASS", "FAIL", "SKIP", "INFO"


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))
        print(f"  [{status:4}] {name}" + (f"\n         {detail}" if detail else ""))

    @property
    def failures(self) -> int:
        return sum(1 for status, _, _ in self.rows if status == FAIL)


def _run(argv: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    # wsl.exe writes UTF-16 on some builds. Decoding leniently and stripping
    # nulls is what makes its output comparable at all.
    raw = done.stdout or done.stderr
    text = (
        raw.decode("utf-16-le", errors="replace")
        if b"\x00" in raw[:8]
        else raw.decode("utf-8", errors="replace")
    )
    return done.returncode, text.replace("\x00", "").strip()


def check_platform(report: Report) -> bool:
    report.add(INFO, f"{platform.system()} {platform.release()} on {platform.machine()}")
    if platform.system() != "Windows":
        report.add(
            SKIP,
            "not Windows",
            "This harness only means anything on the target platform. "
            "Everything below would be inspecting nothing.",
        )
        return False
    return True


def check_wsl(report: Report) -> str | None:
    """Is WSL there, and which distributions does it have?"""
    code, out = _run(["wsl.exe", "--status"])
    if code != 0:
        report.add(FAIL, "wsl.exe --status", f"exit {code}: {out[:200]}")
        return None
    report.add(PASS, "wsl.exe responds", out.splitlines()[0] if out else "")

    code, listing = _run(["wsl.exe", "--list", "--quiet"])
    distros = [d.strip() for d in listing.splitlines() if d.strip()] if code == 0 else []
    report.add(INFO, f"distributions: {', '.join(distros) if distros else 'none'}")

    target = next((d for d in distros if d.lower() == WSL_DISTRO_NAME.lower()), None)
    if target is None:
        report.add(
            SKIP,
            f"the {WSL_DISTRO_NAME} distribution is not present",
            "Everything below that needs it is skipped. Provisioning it is a "
            "separate step this script deliberately does not take.",
        )
        return distros[0] if distros else None
    report.add(PASS, f"{WSL_DISTRO_NAME} distribution present")
    return target


def check_path_translation(report: Report, distro: str) -> None:
    """The claim that has never been tested against a real filesystem.

    Both directions are checked against ``wslpath``, which is WSL's own answer.
    Ours disagreeing with it is the finding.
    """
    samples = [
        Path(r"C:\Users\Public"),
        Path.home(),
        Path(r"C:\Program Files"),
    ]
    for host in samples:
        try:
            ours = to_runtime(host, distro=distro)
        except PathOutsideRuntimeError as exc:
            report.add(FAIL, f"translate {host}", str(exc))
            continue

        code, theirs = _run(["wsl.exe", "-d", distro, "wslpath", "-u", str(host)])
        if code != 0:
            report.add(SKIP, f"wslpath for {host}", f"exit {code}")
            continue

        if str(ours) == theirs:
            report.add(PASS, f"{host}  ->  {ours}")
        else:
            report.add(
                FAIL,
                f"translation differs for {host}",
                f"ours: {ours}\n         wslpath: {theirs}",
            )


def check_unicode_paths(report: Report, distro: str) -> None:
    """NFR-C4 and §12.4's "Unicode + spaces in the case path" row."""
    for name in ("Kes Ujian", "Kes · Ujian", "cases with spaces"):
        host = Path(r"C:\Users\Public") / name
        try:
            there = to_runtime(host, distro=distro)
            back = to_host(there, distro=distro)
        except PathOutsideRuntimeError as exc:
            report.add(FAIL, f"round trip {name!r}", str(exc))
            continue
        if str(back) == str(host):
            report.add(PASS, f"round trip survives {name!r}")
        else:
            report.add(FAIL, f"round trip changed {name!r}", f"{host} -> {there} -> {back}")


def check_command_bridge(report: Report, distro: str) -> None:
    """Does the argv we build actually run, and keep its arguments intact?"""
    argv = wsl_argv(
        ("echo", "one two", "$(whoami)", "kes · ujian"),
        distro=distro,
        bashrc=PurePosixPath("/dev/null"),
    )
    code, out = _run(argv)
    if code != 0:
        report.add(FAIL, "the command bridge", f"exit {code}: {out[:200]}")
        return

    expected = "one two $(whoami) kes · ujian"
    if out == expected:
        report.add(PASS, "arguments survive the bridge", f"got: {out}")
    else:
        report.add(
            FAIL,
            "the bridge altered its arguments",
            f"expected: {expected}\n         got:      {out}",
        )


def check_openfoam(report: Report, distro: str, *, run_solver: bool) -> None:
    code, out = _run(["wsl.exe", "-d", distro, "bash", "-lc", "ls /usr/lib/openfoam 2>/dev/null"])
    if code != 0 or not out:
        report.add(SKIP, "OpenFOAM inside the distribution", "not installed")
        return
    report.add(PASS, "OpenFOAM present", out.replace("\n", " "))

    if not run_solver:
        report.add(INFO, "pass --run to execute a real solver through the session")
        return

    bashrc = f"/usr/lib/openfoam/{out.splitlines()[0]}/etc/bashrc"
    session = WslSession(PurePosixPath(bashrc), distro=distro)
    argv = session.command_for(("blockMesh", "-help"))
    code, out = _run(argv, timeout=120)
    if code == 0:
        report.add(PASS, "a solver command runs through WslSession")
    else:
        report.add(FAIL, "WslSession could not run a command", f"exit {code}: {out[:300]}")


def check_suite(report: Report) -> None:
    """The existing tests, on this platform.

    They are platform-independent by design; running them here is what proves
    that claim rather than assuming it.
    """
    code, out = _run(
        [sys.executable, "-m", "pytest", "-q", "--no-cov", "-x", str(REPO_ROOT / "tests")],
        timeout=900,
    )
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    report.add(PASS if code == 0 else FAIL, "the test suite on Windows", tail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="also execute a real solver command")
    parser.add_argument("--skip-suite", action="store_true", help="do not run pytest")
    arguments = parser.parse_args(argv)

    print("=" * 72)
    print("Windows verification — nothing here installs or modifies anything")
    print("=" * 72)

    report = Report()
    if not check_platform(report):
        return 0

    print("\n-- WSL ---------------------------------------------------------")
    distro = check_wsl(report)

    if distro:
        print("\n-- path translation (FR-V3, NFR-C4) ----------------------------")
        check_path_translation(report, distro)
        check_unicode_paths(report, distro)

        print("\n-- the command bridge (§3.2) -----------------------------------")
        check_command_bridge(report, distro)

        print("\n-- OpenFOAM ----------------------------------------------------")
        check_openfoam(report, distro, run_solver=arguments.run)

    if not arguments.skip_suite:
        print("\n-- test suite --------------------------------------------------")
        check_suite(report)

    print("\n" + "=" * 72)
    counts = {s: sum(1 for st, _, _ in report.rows if st == s) for s in (PASS, FAIL, SKIP)}
    print(f"  {counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped")
    if report.failures:
        print("\n  The failures above are the point of this run. Paste them back.")
    print("=" * 72)
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
