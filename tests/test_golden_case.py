"""The §12.3 golden-case regression — the numerical gate.

Two families, kept apart because they are valid under different conditions.

**Editor invariance** runs anywhere OpenFOAM exists. It opens a case, saves a
dictionary through the round-trip machinery without changing any value, runs the
case again, and asserts the functionals are identical. §12.3 calls this "the one
that actually protects users: it proves the *editor* changed nothing numerical,
independently of whether the solver is reproducible."

**Absolute references** compare against numbers captured on a pinned toolchain
and are skipped elsewhere, with the mismatch named. A cross-toolchain comparison
is not a weaker test; it is an invalid one, and letting it fail would teach
people to ignore a red gate.

"Reference values are regenerated only by an explicit, reviewed commit that also
states why. A drift is a defect until proven to be an intended upstream change."
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import require_runtime_or_skip
from foamwb.branding import CASE_METADATA_DIR
from foamwb.services.case import CaseService
from foamwb.services.foamdict import Document
from foamwb.services.runtime import RuntimeManager
from golden import (
    GOLDEN_CASES,
    GoldenCase,
    Measurement,
    measure,
    prepare,
    relative_difference,
    run,
    toolchain_fingerprint,
)

pytestmark = pytest.mark.requires_runtime

REFERENCES = Path(__file__).resolve().parent / "golden" / "references.json"

CASE_IDS = [case.name for case in GOLDEN_CASES]


@pytest.fixture(scope="session")
def runtime():
    manager = RuntimeManager()
    installations = manager.discover()
    if not installations:
        require_runtime_or_skip("no OpenFOAM installation found")
    status = manager.verify(installations[0])
    if not status.is_usable:
        require_runtime_or_skip(f"OpenFOAM not usable: {status.detail}")
    return manager, installations[0], status


@pytest.fixture(scope="session")
def tutorials(runtime) -> Path:
    _manager, installation, _status = runtime
    for candidate in (
        installation.bundle / "tutorials",
        Path("/Volumes") / installation.bundle.stem.replace(".app", "") / "tutorials",
    ):
        if candidate.is_dir():
            return candidate
    require_runtime_or_skip("tutorial suite not reachable")


@pytest.fixture(scope="session")
def references() -> dict:
    if not REFERENCES.exists():
        pytest.skip(
            "No golden references captured. Run:\n"
            "  python tools/capture_golden.py --tutorials <...>/tutorials"
        )
    return json.loads(REFERENCES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("golden", GOLDEN_CASES, ids=CASE_IDS)
class TestEditorInvariance:
    """Valid on any toolchain: two runs on this machine, compared to each other."""

    def test_a_no_op_save_changes_no_number(
        self, golden: GoldenCase, runtime, tutorials, tmp_path
    ) -> None:
        # The row §12.3 says actually protects users. Parse every dictionary and
        # write it straight back — the operation a form save performs when the
        # user changes nothing — then confirm the solution is bit-identical.
        # If the editor perturbed so much as a digit, this is where it shows.
        manager, installation, _status = runtime

        first = prepare(golden, tutorials, tmp_path / "before")
        run(golden, first, manager, installation)
        before = measure(golden, first)

        second = prepare(golden, tutorials, tmp_path / "after")
        rewritten = _rewrite_every_dictionary(second)
        assert rewritten > 0, "no dictionaries were exercised"
        run(golden, second, manager, installation)
        after = measure(golden, second)

        assert after.final_time == before.final_time
        assert after.cell_counts == before.cell_counts
        for name, value in before.l2_norms.items():
            assert after.l2_norms[name] == value, (
                f"{golden.name}: saving {rewritten} dictionaries unchanged moved "
                f"{name} from {value!r} to {after.l2_norms[name]!r}"
            )
        assert after.volume_value == before.volume_value

    def test_the_rewrite_is_byte_identical(
        self, golden: GoldenCase, runtime, tutorials, tmp_path
    ) -> None:
        # Guards the guard: if the rewrite were a no-op because nothing was
        # actually written, the test above would pass while proving nothing.
        case = prepare(golden, tutorials, tmp_path / "fidelity")
        for path in sorted(case.rglob("*")):
            if not _is_dictionary(path):
                continue
            original = path.read_bytes()
            document = Document.parse_bytes(original)
            assert document.render_bytes() == original, path


@pytest.mark.parametrize("golden", GOLDEN_CASES, ids=CASE_IDS)
class TestAbsoluteReferences:
    """Only valid on the toolchain the references were captured on."""

    def test_functionals_match_the_reference(
        self, golden: GoldenCase, runtime, tutorials, references, tmp_path
    ) -> None:
        manager, installation, status = runtime
        expected_toolchain = references["toolchain"]
        actual = toolchain_fingerprint(status.openfoam_version or "unknown")
        if actual != expected_toolchain:
            pytest.skip(
                "Reference values were captured on a different toolchain and "
                "cannot be compared: "
                f"reference {expected_toolchain}, this machine {actual}. "
                "Comparing across toolchains is invalid, not merely lenient."
            )

        if golden.name not in references["cases"]:
            pytest.skip(f"no reference captured for {golden.name}")
        expected = Measurement.from_json(references["cases"][golden.name])

        case = prepare(golden, tutorials, tmp_path)
        run(golden, case, manager, installation)
        actual_measurement = measure(golden, case)

        assert actual_measurement.final_time == expected.final_time
        assert actual_measurement.cell_counts == expected.cell_counts

        for name, reference_value in expected.l2_norms.items():
            difference = relative_difference(actual_measurement.l2_norms[name], reference_value)
            assert difference <= golden.relative_tolerance, (
                f"{golden.name}/{name} drifted by {difference:.3e} "
                f"(tolerance {golden.relative_tolerance:.0e}). A drift is a defect "
                "until proven to be an intended upstream change."
            )

        if expected.volume_value is not None:
            difference = relative_difference(
                actual_measurement.volume_value or 0.0, expected.volume_value
            )
            assert difference <= golden.relative_tolerance, (
                f"{golden.name} volume functional drifted by {difference:.3e}"
            )


@pytest.mark.parametrize("golden", GOLDEN_CASES, ids=CASE_IDS)
class TestMetadataIsNeverLoadBearing:
    """FR-C7 — deleting the metadata directory leaves a case that still runs."""

    def test_runs_after_the_metadata_is_deleted(
        self, golden: GoldenCase, runtime, tutorials, tmp_path
    ) -> None:
        # D4's strongest form, and §12.3's dedicated row. The case must run from a
        # bare invocation with nothing of ours left in it.
        manager, installation, _status = runtime
        case = prepare(golden, tutorials, tmp_path)

        service = CaseService()
        opened = service.open(case)
        service.write_metadata(opened, openfoam_version="unused")
        assert opened.metadata_dir.is_dir()

        shutil.rmtree(opened.metadata_dir)
        assert not (case / CASE_METADATA_DIR).exists()

        run(golden, case, manager, installation)
        assert measure(golden, case).l2_norms


def _is_dictionary(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    parts = set(path.relative_to(path.parents[len(path.parts) - 2]).parts)
    if {"postProcessing", CASE_METADATA_DIR} & set(path.parts):
        return False
    if path.parent.name == "polyMesh" and path.stem in {
        "points",
        "faces",
        "owner",
        "neighbour",
    }:
        return False
    if parts and path.suffix in {".m4", ".obj", ".stl", ".csv", ".dat"}:
        return False
    try:
        head = path.read_bytes()[:2000]
    except OSError:
        return False
    return b"FoamFile" in head and b"\x00" not in head


def _rewrite_every_dictionary(case: Path) -> int:
    """Parse and write back every dictionary, changing nothing.

    Exactly what a form save does when the user opens a file and saves without
    editing — the operation that must be numerically invisible.
    """
    rewritten = 0
    for path in sorted(case.rglob("*")):
        if not _is_dictionary(path):
            continue
        document = Document.parse_bytes(path.read_bytes())
        path.write_bytes(document.render_bytes())
        rewritten += 1
    return rewritten
