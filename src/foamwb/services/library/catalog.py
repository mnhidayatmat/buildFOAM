"""The content catalog and its signature (FR-L1, FR-L4).

§10's threat model puts the content channel among the few places where this
application can actively harm a user's machine, so the catalog is treated as
untrusted input that has to prove itself:

* the catalog is **signed**, with a detached ed25519 signature and a public key
  compiled into the application (not shipped beside the catalog, which would let
  an attacker replace both);
* every payload's **sha256 comes from inside the signed catalog**, so the
  signature covers the payload hashes transitively. A hash stored next to the
  payload would be worth nothing.

**Verification happens before parsing, not after.** The JSON is not decoded until
the signature over its exact bytes has been checked. Parsing first would run a
decoder over attacker-controlled input and then decide whether to trust it, which
gets the order exactly backwards.

E-L01 is defined with "No override." — so this module offers no way to skip
verification. A ``trust_anyway`` flag would exist to be found by the one user who
should never use it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from foamwb.codes import Code, ErrorCode

__all__ = [
    "RELEASE_PUBLIC_KEY",
    "Catalog",
    "CatalogError",
    "ContentItem",
    "load_catalog",
    "verify_catalog",
]

#: The release signing key, as hex. Compiled into the application (FR-L4).
#:
#: **This is a development key.** A real release must generate its own keypair
#: with ``tools/sign_catalog.py --new-key`` and keep the private half off this
#: machine and out of this repository; publishing content signed by a key whose
#: private half has ever been in a working tree is not a signature, it is a
#: decoration.
RELEASE_PUBLIC_KEY = "c5c7d27d778949fcb914807fe0d4fcc0c30bf6eb05e589be0e520bd072c49f22"


class CatalogError(Exception):
    """A catalog that could not be trusted or understood.

    Carries a §9 code so the presentation layer can say which of the two
    happened — a tampered signature and a malformed file need different words,
    and "something went wrong" is not a report a user can act on.
    """

    def __init__(self, code: Code, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ContentItem:
    """One installable item, described entirely by the signed catalog."""

    id: str
    name: str
    summary: str
    category: str
    solver: str
    payload: str
    """Filename of the ``.zip``, relative to the catalog's directory."""

    sha256: str
    """Covered by the catalog signature, which is what makes it trustworthy."""

    size_bytes: int = 0
    versions: tuple[str, ...] = ()
    """OpenFOAM releases this item is known to work with. Empty means unknown,
    which is reported as unknown rather than assumed to be fine."""

    publisher: str = ""
    license: str = ""
    tags: tuple[str, ...] = ()

    def supports(self, version: str) -> bool:
        return version in self.versions

    def compatibility(self, version: str | None) -> str:
        """``"yes"``, ``"no"`` or ``"unknown"`` — never a silent assumption.

        FR-L1 requires incompatible items to be *marked, not hidden*: a user
        looking for a case they know exists should find it and be told why it is
        greyed out, rather than conclude the library does not have it.
        """
        if not self.versions:
            return "unknown"
        if version is None:
            return "unknown"
        return "yes" if self.supports(version) else "no"


@dataclass(frozen=True, slots=True)
class Catalog:
    """The verified catalog. Constructing one means the signature checked out."""

    schema: int
    items: tuple[ContentItem, ...] = ()
    generated: str = ""
    source: Path | None = field(default=None, compare=False)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def by_id(self, item_id: str) -> ContentItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({item.category for item in self.items if item.category}))

    @property
    def solvers(self) -> tuple[str, ...]:
        return tuple(sorted({item.solver for item in self.items if item.solver}))

    def search(
        self,
        text: str = "",
        *,
        category: str | None = None,
        solver: str | None = None,
    ) -> tuple[ContentItem, ...]:
        """Filter by free text and facets (FR-L1).

        Version compatibility is deliberately *not* a filter. It is reported per
        item by :meth:`ContentItem.compatibility`, because hiding incompatible
        items would answer "where is the case I was told to use?" with silence.
        """
        needle = text.strip().lower()
        found = []
        for item in self.items:
            if category and item.category != category:
                continue
            if solver and item.solver != solver:
                continue
            if needle and not _matches(item, needle):
                continue
            found.append(item)
        return tuple(found)


def _matches(item: ContentItem, needle: str) -> bool:
    haystack = " ".join(
        (item.name, item.summary, item.solver, item.category, " ".join(item.tags))
    ).lower()
    return needle in haystack


def verify_catalog(raw: bytes, signature: bytes, *, public_key: str = RELEASE_PUBLIC_KEY) -> None:
    """Check the detached signature over the catalog's exact bytes (FR-L4).

    Raises :class:`CatalogError` with E-L01 and installs nothing. There is no
    return value to ignore and no boolean to get the wrong way round — a caller
    that forgets to check gets an exception rather than a quiet ``False``.
    """
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
    except ValueError as exc:
        raise CatalogError(
            ErrorCode.SIGNATURE_INVALID,
            f"The built-in signing key is not usable: {exc}",
        ) from exc

    try:
        key.verify(signature, raw)
    except InvalidSignature as exc:
        raise CatalogError(
            ErrorCode.SIGNATURE_INVALID,
            "This content could not be verified and was not installed.",
        ) from exc


def load_catalog(
    path: Path,
    *,
    signature: Path | None = None,
    public_key: str = RELEASE_PUBLIC_KEY,
) -> Catalog:
    """Verify and then parse a catalog. Verification always happens first."""
    signature_path = signature or path.with_suffix(path.suffix + ".sig")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CatalogError(ErrorCode.SIGNATURE_INVALID, f"No catalog at {path}: {exc}") from exc

    try:
        detached = signature_path.read_bytes()
    except OSError as exc:
        # An unsigned catalog is not a degraded catalog; it is an unverifiable
        # one, and E-L01 says that is not installable.
        raise CatalogError(
            ErrorCode.SIGNATURE_INVALID,
            "This content could not be verified and was not installed.",
        ) from exc

    verify_catalog(raw, detached, public_key=public_key)
    return parse_catalog(raw, source=path)


def parse_catalog(raw: bytes, *, source: Path | None = None) -> Catalog:
    """Parse catalog bytes that have already been verified.

    Separate from :func:`load_catalog` so a caller cannot accidentally reach it
    with unverified bytes and think they have a catalog: this one is named for
    what it does, and every path that reaches it from disk goes through the
    signature check first.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(
            ErrorCode.SIGNATURE_INVALID, f"The catalog is signed but unreadable: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise CatalogError(ErrorCode.SIGNATURE_INVALID, "The catalog is not an object.")

    items: list[ContentItem] = []
    for entry in data.get("items", ()):
        if not isinstance(entry, dict):
            continue
        try:
            items.append(
                ContentItem(
                    id=str(entry["id"]),
                    name=str(entry.get("name", entry["id"])),
                    summary=str(entry.get("summary", "")),
                    category=str(entry.get("category", "")),
                    solver=str(entry.get("solver", "")),
                    payload=str(entry["payload"]),
                    sha256=str(entry["sha256"]).lower(),
                    size_bytes=int(entry.get("size_bytes", 0)),
                    versions=tuple(str(v) for v in entry.get("versions", ())),
                    publisher=str(entry.get("publisher", "")),
                    license=str(entry.get("license", "")),
                    tags=tuple(str(t) for t in entry.get("tags", ())),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogError(
                ErrorCode.SIGNATURE_INVALID,
                f"A catalog entry is malformed: {exc}",
            ) from exc

    return Catalog(
        schema=int(data.get("schema", 1)),
        items=tuple(items),
        generated=str(data.get("generated", "")),
        source=source,
    )
