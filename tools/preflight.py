#!/usr/bin/env python3
"""Run every check that must pass before a push.

There is no CI on this project, so this script is the whole safety net. It runs
the same checks in the same order and stops at the first failure, because a
report listing six problems where five are consequences of the first is a worse
report than one.

    uv run python tools/preflight.py            # everything runnable here
    uv run python tools/preflight.py --fast     # skip the tests that need OpenFOAM

**What this cannot check, and no local run can.** The product targets Windows and
macOS (§3.1), and this machine is one of them. The Windows paths in
``foamwb.paths``, the WSL bridge arriving at M3, and the installers at M8 are
exercised here only through monkeypatched tests — which prove the logic and prove
nothing about the platform. §12.4's platform acceptance suite is manual and
gated on release for exactly this reason; it is not a substitute that automation
was going to provide anyway.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    argv: tuple[str, ...]
    why: str
    """One line on what breaks if this is skipped — so a failure explains its own
    stakes rather than sending the reader to the PRD."""

    slow: bool = False


CHECKS: tuple[Check, ...] = (
    Check(
        name="lint",
        argv=("ruff", "check", "."),
        why="style and common errors",
    ),
    Check(
        name="format",
        argv=("ruff", "format", "--check", "."),
        why="formatting drift makes every later diff noisy",
    ),
    Check(
        name="NFR-M1 no Qt in services",
        argv=("python", "tools/check_no_qt.py"),
        why="services must stay testable headlessly and reusable by a CLI",
    ),
    Check(
        name="NFR-M5 product name appears twice",
        argv=("python", "tools/check_branding.py"),
        why="DEC-03 leaves the name open until M8; this keeps reversing it cheap",
    ),
    Check(
        name="NFR-M3 no version literals",
        argv=("python", "tools/check_version_literals.py"),
        why="a new OpenFOAM release must ship as data, not as an app release",
    ),
    Check(
        name="NFR-A5 strings externalised",
        argv=("python", "tools/check_translatable.py"),
        why="finding strings later costs far more than routing them now",
    ),
    Check(
        name="NFR-A2 colours come from the palette",
        argv=("python", "tools/check_palette_only.py"),
        why="a literal does not change with the theme, so it is wrong in one of them",
    ),
    Check(
        name="NFR-R5 works offline",
        argv=("python", "tools/check_offline.py"),
        why="a feature that silently needs the network hangs where it is hardest to diagnose",
    ),
    Check(
        name="§13.5 third-party notices are current",
        argv=("python", "tools/notices.py", "--check"),
        why="shipping someone's code without their notice is easy to avoid and easy to commit",
    ),
    Check(
        name="FR-G2 every error code has a guide page",
        argv=("python", "tools/check_guide_links.py"),
        why="M7's exit criterion: a link that goes nowhere teaches distrust",
    ),
    Check(
        name="tests",
        argv=("pytest", "-q", "--cov"),
        why="§12.2's parser gate and the whole service layer",
    ),
    Check(
        name="numerical gate (§12.3)",
        argv=("pytest", "-m", "requires_runtime", "-q"),
        why="proves a form save changes no number; needs OpenFOAM installed",
        slow=True,
    ),
)


def run(check: Check, *, quiet: bool) -> tuple[bool, float]:
    """Run one check.

    Output streams by default rather than being captured. A captured run shows
    nothing at all while a check hangs, which turns "which test is stuck?" into a
    guessing game — the failure mode this script exists to make cheap.
    """
    started = time.monotonic()
    completed = subprocess.run(
        [*check.argv],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=quiet,
    )
    elapsed = time.monotonic() - started
    if quiet and completed.returncode != 0:
        sys.stdout.write(completed.stdout or "")
        sys.stderr.write(completed.stderr or "")
    return completed.returncode == 0, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip checks that run a real solver",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="hide output from passing checks (hides progress while they run)",
    )
    arguments = parser.parse_args()

    if shutil.which("ruff") is None:
        print("Run this through the project environment: uv run python tools/preflight.py")
        return 1

    checks = [c for c in CHECKS if not (arguments.fast and c.slow)]
    width = max(len(c.name) for c in checks)

    for check in checks:
        print(f"\n=== {check.name} " + "=" * max(0, width - len(check.name)), flush=True)
        passed, elapsed = run(check, quiet=arguments.quiet)
        if not passed:
            print(f"--- {check.name}: FAILED after {elapsed:.1f}s")
            print(f"    this guards: {check.why}")
            return 1
        print(f"--- {check.name}: ok ({elapsed:.1f}s)")

    print("\nAll checks passed.")
    if arguments.fast:
        print("Skipped the solver tests; run without --fast before pushing.")
    print("Not covered here: Windows. See §12.4's manual acceptance suite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
