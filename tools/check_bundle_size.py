"""NFR-P8: the installer stays under 250 MB compressed.

Not a nice-to-have. A naive PySide6 freeze on this machine would carry a
1,164 MB Qt tree, of which QtWebEngineCore alone is 453 MB and the FFmpeg
libraries behind QtMultimedia another 60 MB — so the budget is only met by
actively excluding what the application does not use, and an exclusion list
nobody measures is an exclusion list that quietly stops working.

Run against a built bundle:

    python tools/check_bundle_size.py dist/<App>.app

It measures the *compressed* size, because that is what NFR-P8 budgets and what
a user downloads. It also reports the largest components, so that when the
budget is one day exceeded the next question — what grew? — is already answered.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

#: NFR-P8, in bytes. Excludes ParaView, which is downloaded separately.
BUDGET_BYTES = 250 * 1024**2

#: Modules that must never reappear. Each was excluded for a measured reason, and
#: each is large enough that its return would be felt rather than noticed.
FORBIDDEN = ("QtWebEngineCore", "libavcodec", "libavformat", "QtDesigner")


def _compressed_size(target: Path) -> int:
    """Zip the bundle to a scratch file and measure it.

    Zipped rather than estimated from the file sizes: compression ratios vary
    enormously between a Qt framework and a JSON schema, and a sum of raw sizes
    would be wrong by a factor that changes with the content.
    """
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "bundle.zip"
        if shutil.which("ditto") and target.suffix == ".app":
            # Preserves the bundle structure macOS expects, and is what a real
            # release would use.
            subprocess.run(
                ["ditto", "-c", "-k", "--keepParent", str(target), str(archive)],
                check=True,
                capture_output=True,
            )
        else:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(target.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        bundle.write(path, path.relative_to(target.parent))
        return archive.stat().st_size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="the built .app or dist directory")
    parser.add_argument("--budget-mb", type=float, default=BUDGET_BYTES / 1024**2)
    arguments = parser.parse_args(argv)

    if not arguments.bundle.exists():
        print(f"check_bundle_size: nothing at {arguments.bundle}", file=sys.stderr)
        return 1

    strays = [name for name in FORBIDDEN if any(arguments.bundle.rglob(f"*{name}*"))]

    compressed = _compressed_size(arguments.bundle)
    budget = arguments.budget_mb * 1024**2
    uncompressed = sum(
        p.stat().st_size for p in arguments.bundle.rglob("*") if p.is_file() and not p.is_symlink()
    )

    print(
        f"check_bundle_size: {compressed / 1024**2:.1f} MB compressed "
        f"({uncompressed / 1024**2:.0f} MB on disk), budget "
        f"{arguments.budget_mb:.0f} MB"
    )

    largest = sorted(
        (p for p in arguments.bundle.rglob("*") if p.is_file() and not p.is_symlink()),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )[:5]
    for path in largest:
        print(f"    {path.stat().st_size / 1024**2:6.1f} MB  {path.name}")

    if strays:
        print(
            "\nNFR-P8 violation — an excluded module is back in the bundle:\n  "
            + "\n  ".join(strays)
            + "\n\nCheck the excludes list in packaging/app.spec. These were "
            "excluded for measured reasons and are large enough to matter.",
            file=sys.stderr,
        )
        return 1

    if compressed > budget:
        over = (compressed - budget) / 1024**2
        print(
            f"\nNFR-P8 violation — {over:.1f} MB over the budget. The largest "
            "components are listed above.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
