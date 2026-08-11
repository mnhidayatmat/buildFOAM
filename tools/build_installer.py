"""Build the Windows installer (M8).

One command, run on Windows:

    uv run python tools\\build_installer.py

It freezes the application, compiles the NSIS script around it, and writes a
checksum beside the result. The output is a single self-contained ``.exe`` that
can be published anywhere — it downloads nothing at install time.

**The freeze must happen on Windows.** PyInstaller does not cross-compile: it
bundles the interpreter and the extension modules of the machine it runs on, so
a macOS build produces a macOS application whatever the spec says. NSIS *does*
cross-compile, which is why the installer script can be validated from a
developer machine while the payload cannot.

**A checksum is written because this is self-hosted.** A GitHub release page
carries its own integrity signals; a file on a web server carries none. The
sha256 beside the installer is what lets someone verify they received what was
published, and it costs one line to produce.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from foamwb.branding import APP_DISPLAY_NAME, PUBLISHER_NAMESPACE  # noqa: E402

DIST = REPO_ROOT / "dist"
SPEC = REPO_ROOT / "packaging" / "app.spec"
NSI = REPO_ROOT / "packaging" / "installer.nsi"


def _version() -> str:
    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"].get("version", "0.0.0")


def _run(argv: list[str], *, env: dict | None = None) -> int:
    print(f"  $ {' '.join(argv)}")
    return subprocess.run(argv, cwd=REPO_ROOT, env=env, check=False).returncode


def freeze() -> int:
    """PyInstaller, on the platform whose application is being built."""
    if platform.system() != "Windows":
        print(
            "  ! Not Windows. PyInstaller bundles the interpreter of the machine\n"
            "    it runs on, so this would produce a build for the wrong platform.\n"
            "    Run this script on the Windows machine.",
            file=sys.stderr,
        )
        return 1
    return _run([sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean"])


def compile_installer(version: str) -> int:
    """NSIS. Cross-compiles, so this step is checkable from anywhere."""
    makensis = shutil.which("makensis")
    if makensis is None:
        print(
            "  ! makensis not found. Install NSIS from https://nsis.sourceforge.net\n"
            "    (or `brew install makensis` to validate the script off-Windows).",
            file=sys.stderr,
        )
        return 1

    env = dict(os.environ)
    # Homebrew's makensis hard-codes a stub path from its build prefix, which is
    # wrong on any installation that is not in /opt/homebrew.
    if "NSISDIR" not in env:
        guess = Path(makensis).resolve().parent.parent / "share" / "nsis"
        if guess.is_dir():
            env["NSISDIR"] = str(guess)

    return _run(
        [
            makensis,
            f"-DAPP_NAME={APP_DISPLAY_NAME}",
            f"-DAPP_VERSION={version}",
            f"-DAPP_PUBLISHER={PUBLISHER_NAMESPACE.rsplit('.', 1)[-1]}",
            f"-DPAYLOAD_DIR={DIST / APP_DISPLAY_NAME}",
            str(NSI),
        ],
        env=env,
    )


def write_checksum(installer: Path) -> None:
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    target = installer.with_suffix(installer.suffix + ".sha256")
    target.write_text(f"{digest}  {installer.name}\n", encoding="utf-8")
    print(f"  {target.name}: {digest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-freeze", action="store_true", help="reuse an existing dist/")
    parser.add_argument(
        "--check-script",
        action="store_true",
        help="compile the NSIS script against a stub payload, to validate its syntax",
    )
    arguments = parser.parse_args(argv)

    version = _version()
    print(f"Building {APP_DISPLAY_NAME} {version}")

    if arguments.check_script:
        # Validating syntax needs *a* payload directory, not the real one.
        stub = DIST / APP_DISPLAY_NAME
        stub.mkdir(parents=True, exist_ok=True)
        (stub / f"{APP_DISPLAY_NAME}.exe").write_bytes(b"stub")
        print("\n== NSIS script (stub payload) ==")
        return compile_installer(version)

    if not arguments.skip_freeze:
        print("\n== freeze ==")
        if (code := freeze()) != 0:
            return code

    payload = DIST / APP_DISPLAY_NAME
    if not payload.is_dir():
        print(f"  ! no payload at {payload}. Run without --skip-freeze.", file=sys.stderr)
        return 1

    print("\n== installer ==")
    if (code := compile_installer(version)) != 0:
        return code

    installer = DIST / f"{APP_DISPLAY_NAME}-Setup-{version}.exe"
    if not installer.is_file():
        print(f"  ! expected {installer}", file=sys.stderr)
        return 1

    size = installer.stat().st_size / 1024**2
    print(f"\n  {installer}  ({size:.1f} MB)")
    write_checksum(installer)

    print(
        "\nPublish both files together. Silent install for a managed image:\n"
        f"  {installer.name} /S /D=C:\\Program Files\\{APP_DISPLAY_NAME}\n"
        "  (/D must come last and must not be quoted — an NSIS rule, and the\n"
        "   usual reason a silent install lands somewhere unexpected.)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
