"""Product identity and its derived values (NFR-M5, §13.3).

These tests never spell the product name. They assert *relationships* between
the constants, so they keep passing across the rename DEC-03 leaves open — which
is the whole claim NFR-M5 makes.
"""

from __future__ import annotations

import re

from foamwb import branding


class TestConstants:
    def test_app_id_is_safe_in_every_namespace_it_is_used_in(self) -> None:
        # A POSIX path, an NTFS path, a reverse-DNS identifier and a WSL distro
        # name all have to accept it without escaping.
        assert re.fullmatch(r"[a-z][a-z0-9]*", branding.APP_ID)

    def test_display_name_is_non_empty_and_unpadded(self) -> None:
        assert branding.APP_DISPLAY_NAME
        assert branding.APP_DISPLAY_NAME.strip() == branding.APP_DISPLAY_NAME


class TestDerivedValues:
    def test_metadata_dir_is_hidden_and_derived(self) -> None:
        assert f".{branding.APP_ID}" == branding.CASE_METADATA_DIR

    def test_bundle_id_contains_the_app_id(self) -> None:
        assert branding.APP_ID in branding.BUNDLE_ID.split(".")

    def test_content_namespace_tracks_the_app_id(self) -> None:
        assert branding.CONTENT_NAMESPACE == branding.APP_ID

    def test_wsl_distro_name_tracks_the_display_name(self) -> None:
        assert branding.WSL_DISTRO_NAME == branding.APP_DISPLAY_NAME


class TestTradeMarkCompliance:
    """§13.3 — the constraints OpenCFD's guidelines impose."""

    def test_name_is_not_the_forbidden_openfoam_something_construction(self) -> None:
        # The guidelines reject `OpenFOAM <Something>` by name.
        assert not re.match(r"(?i)^openfoam[\s_-]", branding.APP_DISPLAY_NAME)

    def test_tagline_is_a_distinctive_name_plus_a_descriptor(self) -> None:
        assert branding.APP_TAGLINE.startswith(branding.APP_DISPLAY_NAME)
        assert "workbench for OpenFOAM" in branding.APP_TAGLINE

    def test_registered_mark_carried_on_first_prominent_use(self) -> None:
        assert "OpenFOAM®" in branding.APP_TAGLINE

    def test_non_endorsement_notice_names_the_owner_and_the_marks(self) -> None:
        notice = branding.NON_ENDORSEMENT_NOTICE
        assert branding.APP_DISPLAY_NAME in notice
        assert "not approved or endorsed by OpenCFD Limited" in notice
        assert "OPENFOAM®" in notice
        assert "OpenCFD®" in notice


class TestThePublisherIdentity:
    """DEC-03 is settled: the name is kept, and it now reaches public identifiers."""

    def test_the_bundle_id_is_reverse_dns_under_a_namespace_we_control(self) -> None:
        """Notarisation binds this to a developer team and expects it to be
        defensible. An identifier under a GitHub account nobody owns is not."""
        from foamwb.branding import BUNDLE_ID, PUBLISHER_NAMESPACE

        assert BUNDLE_ID.startswith(PUBLISHER_NAMESPACE + ".")
        assert PUBLISHER_NAMESPACE.count(".") >= 2

    def test_the_bundle_id_matches_the_published_repository(self) -> None:
        """The namespace and the homepage must name the same account."""
        import tomllib
        from pathlib import Path

        from foamwb.branding import PUBLISHER_NAMESPACE

        root = Path(__file__).resolve().parent.parent
        with (root / "pyproject.toml").open("rb") as handle:
            homepage = tomllib.load(handle)["project"]["urls"]["Homepage"]

        owner = PUBLISHER_NAMESPACE.rsplit(".", 1)[-1]
        assert f"/{owner}/".lower() in homepage.lower()

    def test_the_publisher_is_not_the_product(self) -> None:
        """Who ships it and what is shipped are renamed for different reasons."""
        from foamwb.branding import APP_ID, PUBLISHER_NAMESPACE

        assert not PUBLISHER_NAMESPACE.endswith(APP_ID)
