"""The content library (§5.6, FR-L1–FR-L5).

Split so that the trust boundary is a file boundary: :mod:`catalog` decides
whether a catalog may be believed, :mod:`install` decides whether a package may
be written to disk. Neither can be used to skip the other.
"""

from foamwb.services.library.catalog import (
    RELEASE_PUBLIC_KEY,
    Catalog,
    CatalogError,
    ContentItem,
    load_catalog,
    verify_catalog,
)
from foamwb.services.library.install import (
    InstallError,
    InstallPlan,
    Rejection,
    inspect_archive,
    install_item,
    sha256_of,
)

__all__ = [
    "RELEASE_PUBLIC_KEY",
    "Catalog",
    "CatalogError",
    "ContentItem",
    "InstallError",
    "InstallPlan",
    "Rejection",
    "inspect_archive",
    "install_item",
    "load_catalog",
    "sha256_of",
    "verify_catalog",
]
