"""Pack content and sign the catalog (FR-L4). Maintainer tool, not shipped.

Deliberately separate from the application: the application only ever
*verifies*. Shipping the ability to sign would mean shipping something that
looks like a key slot, and a verifier that can also sign is one refactor away
from trusting whatever it is handed.

Usage::

    python tools/sign_catalog.py --new-key private.key   # once, then keep it safe
    python tools/sign_catalog.py pack <case-dir> --into src/foamwb/data/library
    python tools/sign_catalog.py sign --key private.key

Packing strips nothing and hides nothing: it *refuses* a case that would fail
FR-L3, so a package that installs is a package that was clean at source. The
alternative — quietly clearing executable bits while packing — would mean the
installer's rules were never really tested against real content.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from foamwb.services.library.install import inspect_archive, sha256_of  # noqa: E402

LIBRARY_DIR = REPO_ROOT / "src" / "foamwb" / "data" / "library"
CATALOG = LIBRARY_DIR / "catalog.json"


def new_key(destination: Path) -> int:
    if destination.exists():
        print(f"refusing to overwrite {destination}", file=sys.stderr)
        return 1

    private = Ed25519PrivateKey.generate()
    destination.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    destination.chmod(stat.S_IRUSR | stat.S_IWUSR)

    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print(f"private key written to {destination} (mode 600) — keep it off this machine")
    print("put this in catalog.py as RELEASE_PUBLIC_KEY:")
    print(f'    RELEASE_PUBLIC_KEY = "{public.hex()}"')
    return 0


def pack(source: Path, into: Path) -> int:
    """Zip a case directory, refusing anything the installer would refuse."""
    if not (source / "system").is_dir():
        print(f"{source} does not look like a case (no system/)", file=sys.stderr)
        return 1

    into.mkdir(parents=True, exist_ok=True)
    archive = into / f"{source.name}.zip"

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(source.parent)
            info = zipfile.ZipInfo(str(relative))
            # Normalised: a data package's timestamps are noise, and reproducible
            # archives make the catalog's hashes reviewable in a diff.
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, path.read_bytes())

    plan = inspect_archive(archive)
    if not plan.acceptable:
        archive.unlink(missing_ok=True)
        print(f"{source.name} cannot be packaged as v1.0 content:", file=sys.stderr)
        for rejection in plan.rejections[:10]:
            print(f"  {rejection.entry or 'archive'}: {rejection.reason}", file=sys.stderr)
        return 1

    print(f"{archive}  ({archive.stat().st_size} bytes, sha256 {sha256_of(archive)})")
    return 0


def sign(key_path: Path, catalog: Path) -> int:
    try:
        private = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
    except (OSError, ValueError) as exc:
        print(f"cannot read the signing key: {exc}", file=sys.stderr)
        return 1

    raw = catalog.read_bytes()
    signature = catalog.with_suffix(catalog.suffix + ".sig")
    signature.write_bytes(private.sign(raw))

    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print(f"signed {catalog.name} -> {signature.name}")
    print(f"public key: {public.hex()}")
    return 0


def refresh(catalog: Path) -> int:
    """Recompute every payload's size and sha256 from the files on disk."""
    data = json.loads(catalog.read_text())
    for entry in data.get("items", ()):
        payload = catalog.parent / entry["payload"]
        if not payload.is_file():
            print(f"missing payload {payload}", file=sys.stderr)
            return 1
        entry["sha256"] = sha256_of(payload)
        entry["size_bytes"] = payload.stat().st_size
    data["generated"] = datetime.now(UTC).strftime("%Y-%m-%d")
    catalog.write_text(json.dumps(data, indent=2) + "\n")
    print(f"refreshed {len(data.get('items', ()))} payload hashes in {catalog.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=False)

    parser.add_argument("--new-key", type=Path, help="generate a signing keypair")
    parser.add_argument("--catalog", type=Path, default=CATALOG)

    pack_parser = sub.add_parser("pack", help="package a case directory")
    pack_parser.add_argument("source", type=Path)
    pack_parser.add_argument("--into", type=Path, default=LIBRARY_DIR)

    sub.add_parser("refresh", help="recompute payload hashes")
    sign_parser = sub.add_parser("sign", help="sign the catalog")
    sign_parser.add_argument("--key", type=Path, required=True)

    arguments = parser.parse_args(argv)

    if arguments.new_key:
        return new_key(arguments.new_key)
    if arguments.command == "pack":
        return pack(arguments.source, arguments.into)
    if arguments.command == "refresh":
        return refresh(arguments.catalog)
    if arguments.command == "sign":
        return sign(arguments.key, arguments.catalog)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
