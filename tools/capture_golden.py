#!/usr/bin/env python3
"""Capture §12.3 golden-case reference values.

"Reference values are regenerated only by an explicit, reviewed commit that also
states why. A drift is a defect until proven to be an intended upstream change."

So this is a separate tool, never something the test suite calls. A gate that
could refresh its own expectations would agree with any regression that reached
it. The toolchain fingerprint is written alongside the numbers and is part of the
reference, not metadata about it — the values mean nothing without it.

    python tools/capture_golden.py --tutorials /path/to/tutorials
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT / "tests")]

from foamwb.services.runtime import RuntimeManager  # noqa: E402
from golden import GOLDEN_CASES, measure, prepare, run, toolchain_fingerprint  # noqa: E402

OUTPUT = REPO_ROOT / "tests" / "golden" / "references.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tutorials", required=True, type=Path)
    parser.add_argument("--reason", default="", help="why the references are being regenerated")
    args = parser.parse_args()

    manager = RuntimeManager()
    installations = manager.discover()
    if not installations:
        print("No OpenFOAM installation found", file=sys.stderr)
        return 1
    status = manager.verify(installations[0])
    if not status.is_usable:
        print(f"OpenFOAM not usable: {status.detail}", file=sys.stderr)
        return 1

    fingerprint = toolchain_fingerprint(status.openfoam_version or "unknown")
    print(f"Capturing against {fingerprint}")

    cases: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as scratch:
        for golden in GOLDEN_CASES:
            try:
                case = prepare(golden, args.tutorials, Path(scratch))
            except FileNotFoundError as exc:
                print(f"  skip {golden.name}: {exc}")
                continue
            print(f"  running {golden.name} ...", end="", flush=True)
            run(golden, case, manager, installations[0])
            measurement = measure(golden, case)
            cases[golden.name] = measurement.to_json()
            print(f" t={measurement.final_time} {measurement.l2_norms}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {"toolchain": fingerprint, "reason": args.reason, "cases": cases},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} references to {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
