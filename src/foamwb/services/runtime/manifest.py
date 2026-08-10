"""The runtime manifest (§3.4) — the only place OpenFOAM versions exist.

"No OpenFOAM version number appears anywhere in application code." Everything
version- or lineage-specific is read from ``data/runtime-manifest.json`` through
this module, which buys two things the PRD is explicit about:

* A new ESI release is supported by shipping a manifest update over the content
  channel, without an application release (§15.1).
* The Foundation lineage stays *additive* rather than a fork of every call site
  (DEC-15, NG5). Its dictionary names differ — ``physicalProperties`` and
  ``momentumTransport`` where ESI has ``transportProperties`` and
  ``turbulenceProperties`` — and that divergence is what NG5 defers. Routing every
  lookup through :meth:`Release.dictionary` now is what keeps it a data change.

Enforced by ``tools/check_version_literals.py``, which fails the build on a
version identifier or a lineage-specific dictionary name anywhere in ``src``
outside the data directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

__all__ = ["Manifest", "PlatformSpec", "Release", "load_manifest"]

_MANIFEST_RESOURCE = "runtime-manifest.json"


class ManifestError(ValueError):
    """The manifest is missing, malformed, or of an unsupported schema."""


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    """How one release is packaged on one platform."""

    raw: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    @property
    def app_name(self) -> str | None:
        """macOS bundle name, e.g. the directory under ``/Applications``."""
        return self.raw.get("app_name")

    @property
    def launcher(self) -> str | None:
        """Path to the environment launcher, relative to the bundle."""
        return self.raw.get("launcher")

    @property
    def bashrc(self) -> str | None:
        """Absolute path to ``etc/bashrc`` inside the runtime (Windows/WSL)."""
        return self.raw.get("bashrc")

    @property
    def architectures(self) -> tuple[str, ...]:
        return tuple(self.raw.get("arch", ()))

    @property
    def minimum_macos(self) -> str | None:
        return self.raw.get("min_macos")


@dataclass(frozen=True, slots=True)
class Release:
    """One OpenFOAM release the application knows how to drive."""

    version: str
    raw: dict[str, Any]

    @property
    def verified(self) -> bool:
        """Whether this entry has been exercised against a real installation.

        Recorded rather than assumed: the difference between "we packaged this"
        and "we ran this" is exactly the difference FR-R5 exists to police.
        """
        return bool(self.raw.get("verified", False))

    def platform(self, name: str) -> PlatformSpec | None:
        spec = self.raw.get(name)
        return PlatformSpec(spec) if spec else None

    def dictionary(self, role: str) -> str:
        """Filename for a dictionary role, e.g. ``transport`` or ``turbulence``.

        The indirection DEC-15 depends on. A caller asks for the *role*; which
        filename that means is the manifest's business, and differs between
        lineages.
        """
        names = self.raw.get("dictionaries", {})
        if role not in names:
            raise ManifestError(
                f"Release {self.version} defines no dictionary for role {role!r}. "
                f"Known roles: {sorted(names)}"
            )
        return names[role]

    @property
    def dictionary_roles(self) -> tuple[str, ...]:
        return tuple(sorted(self.raw.get("dictionaries", {})))


@dataclass(frozen=True, slots=True)
class Manifest:
    """Every release the application knows about, plus the support policy."""

    raw: dict[str, Any]

    @property
    def lineage(self) -> str:
        """``esi`` or ``foundation``. v1.x ships ESI only (NG5)."""
        return self.raw["lineage"]

    @property
    def default_version(self) -> str:
        return self.raw["default"]

    @property
    def minimum_supported(self) -> str:
        return self.raw["minimum_supported"]

    @property
    def versions(self) -> tuple[str, ...]:
        """Supported versions, newest first.

        Sorted by the ``vYYMM`` scheme rather than by dictionary order, so the
        ordering survives someone appending a release to the wrong place in the
        file.
        """
        return tuple(sorted(self.raw["releases"], reverse=True))

    def release(self, version: str) -> Release:
        try:
            return Release(version=version, raw=self.raw["releases"][version])
        except KeyError:
            raise ManifestError(
                f"Unknown OpenFOAM release {version!r}. "
                f"This manifest knows: {', '.join(self.versions)}"
            ) from None

    def supports(self, version: str) -> bool:
        return version in self.raw["releases"]

    def default_release(self) -> Release:
        return self.release(self.default_version)


def _validate(raw: dict[str, Any]) -> None:
    if raw.get("schema") != 1:
        raise ManifestError(
            f"Unsupported manifest schema {raw.get('schema')!r}; this build reads schema 1. "
            "A newer manifest needs a newer application."
        )
    for key in ("lineage", "default", "minimum_supported", "releases"):
        if key not in raw:
            raise ManifestError(f"Manifest is missing required key {key!r}")
    if raw["default"] not in raw["releases"]:
        raise ManifestError(
            f"Manifest default {raw['default']!r} is not among its releases — "
            "the application would start by asking for a version it cannot install."
        )


def parse_manifest(text: str) -> Manifest:
    """Parse manifest JSON, rejecting a schema this build cannot read."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Manifest is not valid JSON: {exc}") from exc
    _validate(raw)
    return Manifest(raw=raw)


@cache
def load_manifest(path: Path | None = None) -> Manifest:
    """Load the manifest, preferring a cached update over the bundled copy.

    ``path`` overrides both, for tests and for the lab-image config (FR-R8).
    Cached because it is read on every schema lookup and never changes within a
    session; a manifest update takes effect at next launch, which is also when
    the application would want to re-verify the runtime anyway.
    """
    if path is not None:
        return parse_manifest(path.read_text(encoding="utf-8"))
    source = resources.files("foamwb.data").joinpath(_MANIFEST_RESOURCE)
    return parse_manifest(source.read_text(encoding="utf-8"))
