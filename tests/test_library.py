"""M6 — the content library (FR-L1 to FR-L5, §10).

The exit criterion this file exists for: **"A tampered catalog and a tampered
payload are each rejected with no install."** Both are exercised against the
bundled catalog that actually ships, not against a fixture, because a signature
check that works only on test data proves nothing about the release.

The malicious archives are constructed here rather than vendored. A repository
should not contain a zip whose whole purpose is to write outside its destination,
and building them in the test makes the attack legible to the next reader.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from foamwb.codes import ErrorCode
from foamwb.services.library import (
    Catalog,
    CatalogError,
    ContentItem,
    InstallError,
    inspect_archive,
    install_item,
    load_catalog,
    sha256_of,
    verify_catalog,
)
from foamwb.services.library.catalog import parse_catalog

LIBRARY = Path(__file__).resolve().parent.parent / "src" / "foamwb" / "data" / "library"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_catalog(LIBRARY / "catalog.json")


def _zip(path: Path, entries: dict[str, bytes], *, mode: int = 0o644) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, payload in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            bundle.writestr(info, payload)
    return path


def _item_for(archive: Path, **overrides) -> ContentItem:
    fields = {
        "id": "fixture",
        "name": "Fixture",
        "summary": "",
        "category": "test",
        "solver": "icoFoam",
        "payload": archive.name,
        "sha256": sha256_of(archive),
    }
    fields.update(overrides)
    return ContentItem(**fields)


class TestTheBundledCatalogIsSigned:
    """FR-L4 against what actually ships."""

    def test_it_verifies_with_the_compiled_in_key(self, catalog) -> None:
        assert len(catalog) > 0

    def test_every_payload_is_present_and_matches_its_hash(self, catalog) -> None:
        """The signature covers these hashes, so this is the chain of trust."""
        for item in catalog:
            payload = LIBRARY / item.payload
            assert payload.is_file(), f"{item.id} has no payload"
            assert sha256_of(payload) == item.sha256, f"{item.id} hash drifted"

    def test_every_bundled_payload_would_install(self, catalog) -> None:
        """FR-L3 holds for the content we ship, not only for content we reject."""
        for item in catalog:
            plan = inspect_archive(LIBRARY / item.payload)
            assert plan.acceptable, f"{item.id}: {plan.rejections}"

    def test_every_item_declares_a_licence(self, catalog) -> None:
        for item in catalog:
            assert item.license, f"{item.id} ships without a licence"
            assert item.publisher, f"{item.id} ships without a publisher"


class TestATamperedCatalogIsRejected:
    """Half the M6 exit criterion."""

    def test_a_changed_byte_fails_verification(self, tmp_path) -> None:
        raw = (LIBRARY / "catalog.json").read_bytes()
        signature = (LIBRARY / "catalog.json.sig").read_bytes()
        tampered = raw.replace(b'"cavity"', b'"cavlty"', 1)
        assert tampered != raw

        with pytest.raises(CatalogError) as caught:
            verify_catalog(tampered, signature)
        assert caught.value.code is ErrorCode.SIGNATURE_INVALID

    def test_a_tampered_catalog_yields_no_catalog_at_all(self, tmp_path) -> None:
        """Rejection is total: there is no partially trusted catalog."""
        target = tmp_path / "catalog.json"
        target.write_bytes((LIBRARY / "catalog.json").read_bytes().replace(b"cavity", b"pwned"))
        (tmp_path / "catalog.json.sig").write_bytes((LIBRARY / "catalog.json.sig").read_bytes())

        with pytest.raises(CatalogError):
            load_catalog(target)

    def test_a_signature_from_the_wrong_key_fails(self, tmp_path) -> None:
        """An attacker who signs with their own key is still an attacker."""
        attacker = Ed25519PrivateKey.generate()
        raw = (LIBRARY / "catalog.json").read_bytes()

        with pytest.raises(CatalogError) as caught:
            verify_catalog(raw, attacker.sign(raw))
        assert caught.value.code is ErrorCode.SIGNATURE_INVALID

    def test_an_unsigned_catalog_is_not_merely_degraded(self, tmp_path) -> None:
        """E-L01 says no override, so "no signature" cannot mean "load anyway"."""
        target = tmp_path / "catalog.json"
        target.write_bytes((LIBRARY / "catalog.json").read_bytes())

        with pytest.raises(CatalogError) as caught:
            load_catalog(target)
        assert caught.value.code is ErrorCode.SIGNATURE_INVALID

    def test_verification_happens_before_parsing(self, tmp_path) -> None:
        """Unparseable *and* unsigned must fail as unsigned, not as malformed.

        Deciding the JSON is bad first would mean the decoder ran over
        attacker-controlled bytes before anything checked whether to trust them.
        """
        target = tmp_path / "catalog.json"
        target.write_bytes(b"{ this is not json")
        (tmp_path / "catalog.json.sig").write_bytes(b"\x00" * 64)

        with pytest.raises(CatalogError) as caught:
            load_catalog(target)
        assert caught.value.code is ErrorCode.SIGNATURE_INVALID

    def test_a_correctly_signed_catalog_round_trips(self, tmp_path) -> None:
        """The negative tests are only meaningful if the positive one works."""
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        raw = b'{"schema": 1, "items": []}'
        target = tmp_path / "catalog.json"
        target.write_bytes(raw)
        (tmp_path / "catalog.json.sig").write_bytes(key.sign(raw))

        loaded = load_catalog(target, public_key=public.hex())
        assert loaded.schema == 1


class TestATamperedPayloadIsRejected:
    """The other half of the M6 exit criterion."""

    def test_an_appended_byte_fails_the_checksum(self, tmp_path, catalog) -> None:
        item = catalog.by_id("cavity")
        evil = tmp_path / "evil.zip"
        evil.write_bytes((LIBRARY / item.payload).read_bytes() + b"\x00")

        with pytest.raises(InstallError) as caught:
            install_item(item, evil, tmp_path / "cases")
        assert caught.value.code is ErrorCode.CHECKSUM_MISMATCH

    def test_nothing_is_installed_when_the_checksum_fails(self, tmp_path, catalog) -> None:
        item = catalog.by_id("cavity")
        evil = tmp_path / "evil.zip"
        evil.write_bytes((LIBRARY / item.payload).read_bytes() + b"\x00")
        destination = tmp_path / "cases"

        with pytest.raises(InstallError):
            install_item(item, evil, destination)
        assert not destination.exists() or list(destination.iterdir()) == []

    def test_a_substituted_archive_fails_even_though_it_is_valid(self, tmp_path, catalog) -> None:
        """A well-formed archive is not the same as the expected archive."""
        item = catalog.by_id("cavity")
        swapped = _zip(tmp_path / "swap.zip", {"cavity/system/controlDict": b"application evil;"})

        with pytest.raises(InstallError) as caught:
            install_item(item, swapped, tmp_path / "cases")
        assert caught.value.code is ErrorCode.CHECKSUM_MISMATCH


class TestDataOnly:
    """FR-L3 — and every one of these fires on real content, not just malice."""

    def test_an_executable_file_is_refused(self, tmp_path) -> None:
        archive = _zip(tmp_path / "x.zip", {"case/Allrun": b"#!/bin/sh\n"}, mode=0o755)
        plan = inspect_archive(archive)
        assert not plan.acceptable
        assert "executable" in plan.rejections[0].reason

    def test_a_make_directory_is_refused(self, tmp_path) -> None:
        archive = _zip(tmp_path / "m.zip", {"case/Make/files": b"solver.C\n"})
        plan = inspect_archive(archive)
        assert not plan.acceptable
        assert "build" in plan.rejections[0].reason

    def test_a_makefile_anywhere_is_refused(self, tmp_path) -> None:
        archive = _zip(tmp_path / "mk.zip", {"case/system/Makefile": b"all:\n"})
        assert not inspect_archive(archive).acceptable

    def test_installing_a_non_data_package_reports_e_l04(self, tmp_path) -> None:
        archive = _zip(tmp_path / "x.zip", {"case/Allrun": b"#!/bin/sh\n"}, mode=0o755)
        item = _item_for(archive)

        with pytest.raises(InstallError) as caught:
            install_item(item, archive, tmp_path / "cases")
        assert caught.value.code is ErrorCode.PACKAGE_NOT_DATA

    def test_a_plain_case_is_accepted(self, tmp_path) -> None:
        archive = _zip(
            tmp_path / "ok.zip",
            {"case/system/controlDict": b"application icoFoam;\n", "case/0/U": b"x\n"},
        )
        assert inspect_archive(archive).acceptable


class TestPathTraversal:
    """Not named by the PRD, and an installer without it would be unsafe."""

    def test_a_parent_reference_is_refused(self, tmp_path) -> None:
        archive = _zip(tmp_path / "t.zip", {"../escaped.txt": b"pwned"})
        plan = inspect_archive(archive)
        assert not plan.acceptable
        assert "escapes" in plan.rejections[0].reason

    def test_a_deep_parent_reference_is_refused(self, tmp_path) -> None:
        archive = _zip(tmp_path / "t.zip", {"case/../../../.ssh/authorized_keys": b"key"})
        assert not inspect_archive(archive).acceptable

    def test_an_absolute_path_is_refused(self, tmp_path) -> None:
        archive = _zip(tmp_path / "a.zip", {"/etc/passwd": b"root"})
        plan = inspect_archive(archive)
        assert not plan.acceptable
        assert "absolute" in plan.rejections[0].reason

    def test_a_windows_absolute_path_is_refused(self, tmp_path) -> None:
        archive = _zip(tmp_path / "w.zip", {"C:/Windows/system32/x.dll": b"x"})
        assert not inspect_archive(archive).acceptable

    def test_a_symlink_is_refused(self, tmp_path) -> None:
        archive = tmp_path / "s.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            info = zipfile.ZipInfo("case/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, "/etc/passwd")
        plan = inspect_archive(archive)
        assert not plan.acceptable
        assert "symbolic link" in plan.rejections[0].reason

    def test_nothing_escapes_even_when_refused(self, tmp_path) -> None:
        """The refusal is what protects; assert the file never appears."""
        archive = _zip(tmp_path / "t.zip", {"../escaped.txt": b"pwned"})
        destination = tmp_path / "cases"
        with pytest.raises(InstallError):
            install_item(_item_for(archive), archive, destination)
        assert not (tmp_path / "escaped.txt").exists()


class TestInstalling:
    """FR-L2 — one action, and the result opens without further configuration."""

    def test_a_bundled_case_installs(self, tmp_path, catalog) -> None:
        item = catalog.by_id("cavity")
        where = install_item(item, LIBRARY / item.payload, tmp_path / "cases")
        assert where.is_dir()
        assert (where / "system" / "controlDict").is_file()

    def test_the_installed_case_opens(self, tmp_path, catalog) -> None:
        """FR-L2's acceptance test, using the same service a user's open uses."""
        from foamwb.services.case import CaseService

        item = catalog.by_id("cavity")
        where = install_item(item, LIBRARY / item.payload, tmp_path / "cases")
        case = CaseService().open(where)
        assert case.application == "icoFoam"

    def test_the_wrapper_directory_is_unwrapped(self, tmp_path, catalog) -> None:
        """``cases/cavity/cavity`` would be the obvious wrong answer."""
        item = catalog.by_id("cavity")
        where = install_item(item, LIBRARY / item.payload, tmp_path / "cases")
        assert not (where / "cavity").exists()

    def test_an_existing_directory_is_never_overwritten(self, tmp_path, catalog) -> None:
        item = catalog.by_id("cavity")
        destination = tmp_path / "cases"
        install_item(item, LIBRARY / item.payload, destination)
        (destination / "cavity" / "system" / "controlDict").write_text("mine")

        with pytest.raises(InstallError) as caught:
            install_item(item, LIBRARY / item.payload, destination)
        assert caught.value.code is ErrorCode.DESTINATION_EXISTS
        assert (destination / "cavity" / "system" / "controlDict").read_text() == "mine"

    def test_a_unicode_path_with_spaces_works(self, tmp_path, catalog) -> None:
        """§11's exit criterion names this explicitly."""
        item = catalog.by_id("cavity")
        destination = tmp_path / "Kes Saya · ujian"
        where = install_item(item, LIBRARY / item.payload, destination)
        assert where.is_dir()
        assert (where / "system" / "controlDict").is_file()


class TestBrowsing:
    """FR-L1 — searchable and filterable, incompatible items marked not hidden."""

    def test_search_matches_name_and_tags(self, catalog) -> None:
        assert catalog.search("cavity")
        assert catalog.search("separation")

    def test_search_can_filter_by_solver(self, catalog) -> None:
        found = catalog.search(solver="interFoam")
        assert found and all(i.solver == "interFoam" for i in found)

    def test_an_incompatible_item_is_reported_not_removed(self) -> None:
        item = ContentItem(
            id="old",
            name="Old",
            summary="",
            category="",
            solver="icoFoam",
            payload="old.zip",
            sha256="",
            versions=("v1912",),
        )
        catalog = Catalog(schema=1, items=(item,))
        assert catalog.search() == (item,), "an incompatible item must still be listed"
        assert item.compatibility("v2512") == "no"

    def test_unknown_compatibility_is_not_reported_as_yes(self) -> None:
        item = ContentItem(
            id="x", name="X", summary="", category="", solver="", payload="", sha256=""
        )
        assert item.compatibility("v2512") == "unknown"


class TestMalformedCatalogs:
    def test_a_missing_required_field_is_named(self) -> None:
        with pytest.raises(CatalogError):
            parse_catalog(b'{"schema": 1, "items": [{"id": "x"}]}')

    def test_a_non_object_catalog_is_refused(self) -> None:
        with pytest.raises(CatalogError):
            parse_catalog(b"[]")

    def test_an_empty_catalog_is_valid(self) -> None:
        assert len(parse_catalog(b'{"schema": 1, "items": []}')) == 0


class TestTheContentActuallyShips:
    """A catalog in the wheel with no payloads beside it is worse than none.

    The wheel's ``artifacts`` glob once read ``**/*.json``, which would have
    shipped the catalog while silently dropping the signature and every payload.
    Nothing in a source checkout can notice that — the files are simply there —
    so the failure would first appear to a user who installed a release.
    """

    def _artifact_globs(self) -> list[str]:
        import tomllib

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
        return data["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]

    def test_every_data_file_is_covered_by_the_wheel_globs(self) -> None:
        """Judged with pathlib's recursive ``**``, which is hatch's semantics.

        fnmatch is the wrong model here and gives a confidently wrong answer:
        its ``*`` crosses directory separators and its ``**`` means nothing
        special, so it reports files as unshipped that a real build includes.
        """
        root = Path(__file__).resolve().parent.parent
        covered: set[Path] = set()
        for pattern in self._artifact_globs():
            covered.update(path for path in root.glob(pattern) if path.is_file())

        uncovered = [
            path.relative_to(root).as_posix()
            for path in (root / "src" / "foamwb" / "data").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path not in covered
        ]
        assert not uncovered, f"these would not ship in the wheel: {uncovered}"

    def test_the_globs_would_have_caught_the_json_only_rule(self) -> None:
        """The test must be able to fail, or it guards nothing."""
        root = Path(__file__).resolve().parent.parent
        json_only = {p for p in root.glob("src/foamwb/data/**/*.json") if p.is_file()}
        assert (LIBRARY / "catalog.json.sig") not in json_only
        assert (LIBRARY / "cavity.zip") not in json_only

    def test_the_signature_is_one_of_them(self) -> None:
        """The specific file the old glob dropped."""
        assert (LIBRARY / "catalog.json.sig").is_file()
