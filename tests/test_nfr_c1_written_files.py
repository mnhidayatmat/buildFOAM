"""NFR-C1 — every file we write is a dictionary OpenFOAM accepts.

The requirement has been unmet since M1, and it is the kind that is easy to
believe without evidence: the round-trip gate proves our *parser* is faithful,
and the schema tests prove our *values* are in range, but neither asks the
question NFR-C1 actually asks — whether OpenFOAM itself will read the result.

Those are different questions. A file can round-trip through our tokeniser
perfectly and still be rejected by the solver, because our parser is deliberately
more tolerant than OpenFOAM's: it accepts constructs it does not understand so
that FR-P7 can promise they survive untouched. Tolerance in a reader is a virtue
and in a writer would be a defect.

So the oracle here is ``foamDictionary``, which is OpenFOAM's own parser. Every
code path that modifies bytes in a user's case is exercised against a real
tutorial and the result handed to it. Exit zero, or the write path is wrong.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import require_runtime_or_skip
from foamwb.services.advisor import load_catalogue, wall_treatments_for
from foamwb.services.apply_turbulence import apply_turbulence, plan_apply
from foamwb.services.case import CaseService
from foamwb.services.foamdict import Document
from foamwb.services.initial import read_initial_fields, set_internal_field
from foamwb.services.regions import apply_patch_type, plan_patch_type
from foamwb.services.runtime.manager import RuntimeManager

pytestmark = pytest.mark.requires_runtime


@pytest.fixture(scope="module")
def runtime():
    manager = RuntimeManager()
    installations = manager.discover()
    if not installations:
        require_runtime_or_skip("no OpenFOAM installation found")
    status = manager.verify(installations[0])
    if not status.is_usable:
        require_runtime_or_skip(f"OpenFOAM present but not usable: {status.detail}")
    return manager, installations[0]


@pytest.fixture(scope="module")
def tutorials(runtime) -> Path:
    manager, installation = runtime
    found = manager.tutorials_dir(installation)
    if found is None or not found.is_dir():
        require_runtime_or_skip("tutorial suite not reachable")
    return found


def _accepts(runtime, case: Path, relative: str) -> tuple[bool, str]:
    """Ask OpenFOAM whether it can read the file. Its answer, not ours."""
    manager, installation = runtime
    session = manager.session_for(installation)
    process = session.run(
        ("foamDictionary", relative),
        cwd=session.to_runtime_path(case),
    )
    output = list(process.lines())
    return process.wait() == 0, "\n".join(output[-12:])


def _copy(tutorials: Path, relative: str, tmp_path: Path) -> Path:
    source = tutorials / relative
    if not (source / "system").is_dir():
        pytest.skip(f"{relative} is not a runnable case in this suite")
    target = tmp_path / source.name
    shutil.copytree(source, target)
    CaseService().restore_initial_conditions(CaseService().open(target))
    return target


CASES = [
    "incompressible/icoFoam/cavity/cavity",
    "incompressible/simpleFoam/pitzDaily",
    "incompressible/pimpleFoam/RAS/TJunction",
]


class TestTheMonitoringFence:
    """FR-S3 writes into controlDict on every run. It is the most-executed
    write path in the application and the one a failure would break hardest."""

    @pytest.mark.parametrize("relative", CASES, ids=lambda r: r.split("/")[-1])
    def test_a_fenced_control_dict_is_accepted(self, runtime, tutorials, tmp_path, relative):
        case_path = _copy(tutorials, relative, tmp_path)
        service = CaseService()
        case = service.open(case_path)
        assert service.enable_monitoring(case)

        accepted, detail = _accepts(runtime, case_path, "system/controlDict")
        assert accepted, f"OpenFOAM rejected our fenced controlDict:\n{detail}"

    def test_the_fence_survives_a_case_that_already_has_functions(
        self, runtime, tutorials, tmp_path
    ):
        """`functions` is a dictionary keyword; two of them is a rejected file.

        This is the failure the single-block composition exists to prevent, and
        only OpenFOAM can confirm it was prevented.
        """
        case_path = _copy(tutorials, "incompressible/pimpleFoam/RAS/TJunction", tmp_path)
        control = case_path / "system" / "controlDict"
        if "functions" not in control.read_text():
            control.write_text(control.read_text() + "\nfunctions\n{\n}\n")

        service = CaseService()
        service.enable_monitoring(service.open(case_path))
        accepted, detail = _accepts(runtime, case_path, "system/controlDict")
        assert accepted, f"the fence produced an unreadable controlDict:\n{detail}"

    def test_removing_the_fence_leaves_it_readable(self, runtime, tutorials, tmp_path):
        case_path = _copy(tutorials, "incompressible/icoFoam/cavity/cavity", tmp_path)
        service = CaseService()
        case = service.open(case_path)
        service.enable_monitoring(case)
        service.disable_monitoring(case)

        accepted, detail = _accepts(runtime, case_path, "system/controlDict")
        assert accepted, detail


class TestEditingThroughTheDocument:
    """Every form save and every property-panel edit goes through Document.set."""

    @pytest.mark.parametrize("relative", CASES, ids=lambda r: r.split("/")[-1])
    def test_a_rewritten_dictionary_is_accepted(self, runtime, tutorials, tmp_path, relative):
        case_path = _copy(tutorials, relative, tmp_path)
        control = case_path / "system" / "controlDict"

        document = Document.parse_bytes(control.read_bytes())
        document.set("endTime", "1.5")
        CaseService().write_dictionary(
            CaseService().open(case_path), control, document.render_bytes()
        )

        accepted, detail = _accepts(runtime, case_path, "system/controlDict")
        assert accepted, detail

    def test_every_system_dictionary_survives_a_no_op_rewrite(self, runtime, tutorials, tmp_path):
        """What a form save does when nothing was changed.

        Byte-identical output is already asserted by §12.2; this asserts the
        stronger practical claim that OpenFOAM still reads what we produced.
        """
        case_path = _copy(tutorials, "incompressible/simpleFoam/pitzDaily", tmp_path)
        for source in sorted((case_path / "system").glob("*")):
            if not source.is_file():
                continue
            document = Document.parse_bytes(source.read_bytes())
            source.write_bytes(document.render_bytes())

            accepted, detail = _accepts(runtime, case_path, f"system/{source.name}")
            assert accepted, f"{source.name} became unreadable:\n{detail}"


class TestTurbulenceChanges:
    """FR-VVT9 writes the turbulence dictionary and boundary conditions."""

    def test_a_model_change_is_accepted(self, runtime, tutorials, tmp_path):
        case_path = _copy(tutorials, "incompressible/simpleFoam/pitzDaily", tmp_path)
        service = CaseService()
        case = service.open(case_path)

        catalogue = load_catalogue()
        model = next(m for m in catalogue.models if m.name == "kOmegaSST")
        treatment = wall_treatments_for(model, catalogue)[0]
        plan = plan_apply(case, model, treatment, dictionary_name="turbulenceProperties")
        if not plan.can_apply:
            pytest.skip(f"nothing to change: {plan.blocked or 'already applied'}")
        apply_turbulence(case, plan, service=service)

        accepted, detail = _accepts(runtime, case_path, "constant/turbulenceProperties")
        assert accepted, detail

        for source in plan.condition_changes:
            relative = source.relative_to(case_path).as_posix()
            accepted, detail = _accepts(runtime, case_path, relative)
            assert accepted, f"{relative} became unreadable:\n{detail}"


class TestInitialConditions:
    """FR-P3 rewrites internalField in a field file."""

    @pytest.mark.parametrize("relative", CASES, ids=lambda r: r.split("/")[-1])
    def test_a_changed_internal_field_is_accepted(self, runtime, tutorials, tmp_path, relative):
        case_path = _copy(tutorials, relative, tmp_path)
        fields = [f for f in read_initial_fields(case_path) if f.is_uniform]
        if not fields:
            pytest.skip("no uniform fields to edit")

        for field in fields[:3]:
            value = "(1 0 0)" if field.is_vector else "0.42"
            assert set_internal_field(field, value)
            relative_path = field.path.relative_to(case_path).as_posix()
            accepted, detail = _accepts(runtime, case_path, relative_path)
            assert accepted, f"{relative_path} became unreadable:\n{detail}"


class TestPatchTypeChanges:
    """FR-P4 splices constant/polyMesh/boundary, a file we did not write."""

    def test_a_changed_patch_type_is_accepted(self, runtime, tutorials, tmp_path):
        case_path = _copy(tutorials, "incompressible/icoFoam/cavity/cavity", tmp_path)

        manager, installation = runtime
        session = manager.session_for(installation)
        mesh = session.run(("blockMesh",), cwd=session.to_runtime_path(case_path))
        list(mesh.lines())
        if mesh.wait() != 0:
            pytest.skip("blockMesh did not produce a mesh")

        change = plan_patch_type(case_path, "movingWall", "patch")
        assert apply_patch_type(case_path, change)

        accepted, detail = _accepts(runtime, case_path, "constant/polyMesh/boundary")
        assert accepted, f"the spliced boundary file became unreadable:\n{detail}"
