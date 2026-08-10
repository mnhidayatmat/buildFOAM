"""The CI guards themselves (NFR-M1, NFR-M3, NFR-M5).

Three architectural promises in this project are enforced by a script rather
than by a type system, which makes the scripts load-bearing: if one quietly
stops detecting violations, the promise decays silently and is only discovered
when someone tries to collect on it — at a rename, at a Foundation-lineage port,
or at the first attempt to run a service headlessly.

So each guard is checked twice: that it passes on the tree as it stands, and
that it still *fails* on a synthetic violation.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import check_branding
import check_no_qt
import check_version_literals

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "script",
    ["check_no_qt.py", "check_branding.py", "check_version_literals.py"],
)
def test_guard_passes_on_the_current_tree(script: str) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{script} failed:\n{result.stdout}\n{result.stderr}"


class TestNoQtGuard:
    """NFR-M1 — Qt outside the presentation layer."""

    @pytest.mark.parametrize(
        "source",
        [
            "import PySide6",
            "from PySide6.QtCore import Signal",
            "import PySide6.QtWidgets as widgets",
            "from PyQt6 import QtCore",
            "import qtpy",
            "import shiboken6",
        ],
    )
    def test_detects_a_forbidden_import(self, source: str) -> None:
        roots = {root for _, root in check_no_qt._imported_roots(ast.parse(source))}
        assert roots & check_no_qt.FORBIDDEN_ROOTS

    def test_detects_an_import_nested_inside_a_function(self) -> None:
        # A deferred import is the most tempting way to breach the rule, and a
        # line-oriented grep of the module header would miss it.
        source = "def build():\n    from PySide6.QtWidgets import QWidget\n    return QWidget\n"
        roots = {root for _, root in check_no_qt._imported_roots(ast.parse(source))}
        assert "PySide6" in roots

    @pytest.mark.parametrize(
        "source",
        [
            '"""Mentions PySide6 in a docstring."""',
            "# PySide6 belongs in foamwb.ui\nimport json",
            "SIGNAL_DOC = 'see PySide6 docs'",
        ],
    )
    def test_does_not_flag_prose(self, source: str) -> None:
        # AST-based rather than grep, so documenting the rule is not a breach.
        roots = {root for _, root in check_no_qt._imported_roots(ast.parse(source))}
        assert not roots & check_no_qt.FORBIDDEN_ROOTS

    def test_relative_imports_are_not_treated_as_third_party(self) -> None:
        roots = {root for _, root in check_no_qt._imported_roots(ast.parse("from . import ui"))}
        assert not roots

    def test_ui_subtree_is_the_only_exemption(self) -> None:
        assert check_no_qt.QT_ALLOWED == (check_no_qt.PACKAGE_ROOT / "ui",)


class TestBrandingGuard:
    """NFR-M5 — the product name appears exactly twice."""

    def test_reads_the_name_out_of_the_branding_module(self) -> None:
        # Hard-coding it here would make this file a third occurrence and would
        # stop the guard working across the rename DEC-03 leaves open.
        terms = check_branding._terms()
        assert terms
        assert all(t == t.lower() for t in terms)

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('APP_ID = "widget"', {"widget"}),
            ('APP_ID: Final = "widget"', {"widget"}),
            ("APP_DISPLAY_NAME = 'Widget'", {"widget"}),
            ('APP_ID: Final = "a"\nAPP_DISPLAY_NAME: Final = "B"', {"a", "b"}),
        ],
    )
    def test_constant_pattern_handles_the_declaration_forms(
        self, source: str, expected: set[str]
    ) -> None:
        found = {m.group("value").lower() for m in check_branding._CONSTANT.finditer(source)}
        assert found == expected

    def test_pattern_ignores_derived_f_strings(self) -> None:
        # `CASE_METADATA_DIR = f".{APP_ID}"` must not be read as a literal name.
        source = 'APP_ID: Final = "widget"\nCASE_METADATA_DIR = f".{APP_ID}"\n'
        found = {m.group("value").lower() for m in check_branding._CONSTANT.finditer(source)}
        assert found == {"widget"}

    def test_expects_one_literal_per_constant(self) -> None:
        assert check_branding.EXPECTED_OCCURRENCES == 2

    def test_scans_all_three_code_roots(self) -> None:
        assert set(check_branding.SCANNED_ROOTS) == {"src", "tests", "tools"}


class TestVersionLiteralGuard:
    """NFR-M3 — version and lineage knowledge lives only in data."""

    @pytest.mark.parametrize(
        "line",
        [
            'BASHRC = "/usr/lib/openfoam/openfoam2606/etc/bashrc"',
            'DEFAULT = "v2506"',
            'PACKAGE = "openfoam2512-default"',
            'TRANSPORT = "transportProperties"',
            'TURBULENCE = "turbulenceProperties"',
            # The Foundation lineage's names are equally forbidden — hard-coding
            # either side is what would make DEC-15's additive design a fork.
            'TRANSPORT = "physicalProperties"',
            'TURBULENCE = "momentumTransport"',
        ],
    )
    def test_detects_a_literal(self, line: str) -> None:
        assert any(p.search(line) for p, _ in check_version_literals.PATTERNS)

    @pytest.mark.parametrize(
        "line",
        [
            'name = manifest.dictionaries["transport"]',
            "version = manifest.default",
            "schema = load_schema(version)",
            'APP_VERSION = "1.0.0"',
        ],
    )
    def test_does_not_flag_manifest_driven_lookups(self, line: str) -> None:
        assert not any(p.search(line) for p, _ in check_version_literals.PATTERNS)

    def test_data_directory_is_exempt(self) -> None:
        # The manifest and the declarative schemas are *supposed* to name
        # versions and dictionaries; that is the design (§3.4, §5.4).
        data_dir = check_version_literals.PACKAGE_ROOT / "data"
        assert check_version_literals._is_exempt(data_dir / "runtime-manifest.json")
        assert not check_version_literals._is_exempt(
            check_version_literals.PACKAGE_ROOT / "services" / "case.py"
        )
