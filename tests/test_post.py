"""M6 — post-processing utilities and the ParaView launch (FR-V5, FR-P8, FR-V1).

The destinations asserted here were measured against OpenFOAM v2512 rather than
assumed, and the assumption was wrong in an instructive way: ``postProcess -func
'mag(U)'`` writes a *field into each time directory*, ``foamToVTK`` writes into
``VTK/``, and only sampling-style functions write into ``postProcessing/``.
``yPlus`` writes to two of the three. Watching ``postProcessing/`` alone reported
"produced nothing" for work that had just been done.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeSession, ScriptedCommand
from foamwb.branding import CASE_METADATA_DIR
from foamwb.services.paraview import (
    ParaViewInstall,
    ParaViewService,
    ensure_foam_stub,
    foam_stub_path,
    mesh_inspection_script,
)
from foamwb.services.post import FUNCTIONS, PostService, output_roots


def _case(tmp_path: Path) -> Path:
    case = tmp_path / "my case"
    (case / "system").mkdir(parents=True)
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text("application icoFoam;\n")
    return case


class TestCommandsAreTokenLists:
    def test_a_function_renders_as_tokens(self) -> None:
        function = next(f for f in FUNCTIONS if f.key == "mag(U)")
        assert function.argv() == ("postProcess", "-func", "mag(U)")

    def test_a_time_is_passed_as_its_own_token(self) -> None:
        """Never a shell string: a case path with a space must stay one word."""
        function = next(f for f in FUNCTIONS if f.key == "yPlus")
        assert function.argv(time="126.715") == (
            "postProcess",
            "-func",
            "yPlus",
            "-time",
            "126.715",
        )

    def test_a_standalone_utility_is_not_wrapped_in_postprocess(self) -> None:
        function = next(f for f in FUNCTIONS if f.utility == "foamToVTK")
        assert function.argv() == ("foamToVTK",)

    def test_a_templated_function_is_filled_in(self) -> None:
        function = next(f for f in FUNCTIONS if f.needs_argument)
        rendered = function.argv(argument="inlet")
        assert "inlet" in rendered[2]

    def test_a_templated_function_refuses_to_run_empty(self) -> None:
        """Otherwise it would run `patchAverage(name=,...)` and fail obscurely."""
        function = next(f for f in FUNCTIONS if f.needs_argument)
        with pytest.raises(ValueError):
            function.argv()


class TestWhatCountsAsOutput:
    def test_all_three_destinations_are_watched(self, tmp_path) -> None:
        case = _case(tmp_path)
        (case / "0.5").mkdir()
        roots = {p.name for p in output_roots(case)}
        assert {"postProcessing", "VTK", "0.5"} <= roots

    def test_the_zero_directory_counts_as_a_time(self, tmp_path) -> None:
        case = _case(tmp_path)
        assert any(p.name == "0" for p in output_roots(case))

    def test_a_non_numeric_directory_is_not_a_time(self, tmp_path) -> None:
        case = _case(tmp_path)
        assert not any(p.name in {"system", "constant"} for p in output_roots(case))

    def test_new_files_are_reported(self, tmp_path) -> None:
        case = _case(tmp_path)

        class Writing(FakeSession):
            def run(self, argv, *, cwd=None, env=None):
                (case / "postProcessing" / "yPlus").mkdir(parents=True, exist_ok=True)
                (case / "postProcessing" / "yPlus" / "yPlus.dat").write_text("data")
                return super().run(argv, cwd=cwd, env=env)

        result = PostService(Writing({})).run(case, FUNCTIONS[0])
        assert [p.name for p in result.written] == ["yPlus.dat"]
        assert not result.produced_nothing

    def test_producing_nothing_is_reported_as_such_not_as_failure(self, tmp_path) -> None:
        """`yPlus` on a case with no walls succeeds and writes nothing."""
        case = _case(tmp_path)
        result = PostService(FakeSession({})).run(case, FUNCTIONS[0])
        assert result.succeeded
        assert result.produced_nothing

    def test_output_is_streamed_to_the_caller(self, tmp_path) -> None:
        case = _case(tmp_path)
        session = FakeSession({"postProcess": ScriptedCommand(lines=["Reading", "End"])})
        seen: list[str] = []
        PostService(session).run(case, FUNCTIONS[0], on_line=seen.append)
        assert seen == ["Reading", "End"]

    def test_a_failure_is_reported_with_its_exit_code(self, tmp_path) -> None:
        """wallShearStress genuinely fails on a laminar case, and should say so."""
        case = _case(tmp_path)
        session = FakeSession({"postProcess": ScriptedCommand(exit_code=1)})
        result = PostService(session).run(case, FUNCTIONS[0])
        assert not result.succeeded
        assert result.exit_code == 1


class TestTheFoamStub:
    def test_the_stub_is_named_after_the_case(self, tmp_path) -> None:
        case = _case(tmp_path)
        assert foam_stub_path(case).name == "my case.foam"

    def test_it_is_not_rewritten_when_present(self, tmp_path) -> None:
        """Touching it would change the tree hash and trip FR-C4 for nothing."""
        case = _case(tmp_path)
        first = ensure_foam_stub(case)
        first.write_text("marker")
        assert ensure_foam_stub(case).read_text() == "marker"


class TestMeshInspection:
    """FR-P8 — the mesh, at the initial state, with no reader chosen by hand."""

    def test_the_script_names_the_stub(self, tmp_path) -> None:
        case = _case(tmp_path)
        script = mesh_inspection_script(case, foam_stub_path(case))
        assert str(foam_stub_path(case)) in script

    def test_a_path_with_spaces_survives_as_a_python_literal(self, tmp_path) -> None:
        """repr, not quotes-by-hand: the case here is called "my case"."""
        case = _case(tmp_path)
        script = mesh_inspection_script(case, foam_stub_path(case))
        assert "'/" in script or '"/' in script
        compile(script, "<generated>", "exec")

    def test_a_unicode_path_still_compiles(self, tmp_path) -> None:
        case = tmp_path / "kes ujian · 1"
        (case / "system").mkdir(parents=True)
        script = mesh_inspection_script(case, foam_stub_path(case))
        compile(script, "<generated>", "exec")

    def test_it_asks_for_no_fields(self, tmp_path) -> None:
        case = _case(tmp_path)
        assert "CellArrays = []" in mesh_inspection_script(case, foam_stub_path(case))

    def test_it_shows_edges(self, tmp_path) -> None:
        case = _case(tmp_path)
        assert "Surface With Edges" in mesh_inspection_script(case, foam_stub_path(case))

    def test_it_opens_at_the_earliest_time(self, tmp_path) -> None:
        """A case that has run would otherwise open at its last written time."""
        case = _case(tmp_path)
        assert "min(times)" in mesh_inspection_script(case, foam_stub_path(case))


class TestLaunching:
    def _service(self, tmp_path, recorder: list) -> ParaViewService:
        install = ParaViewInstall(executable=tmp_path / "paraview", version="5.13")
        service = ParaViewService()
        service.locate = lambda: install  # type: ignore[method-assign]
        service._launch = lambda argv, cwd: recorder.append(list(argv))  # type: ignore[method-assign]
        return service

    def test_a_normal_open_passes_the_stub(self, tmp_path) -> None:
        case = _case(tmp_path)
        recorded: list = []
        assert self._service(tmp_path, recorded).open_case(case)
        assert str(foam_stub_path(case)) in recorded[0]

    def test_mesh_inspection_passes_a_script_instead(self, tmp_path) -> None:
        """Both would open the case twice in one ParaView session."""
        case = _case(tmp_path)
        recorded: list = []
        self._service(tmp_path, recorded).open_case(case, mesh_only=True)
        argv = recorded[0]
        assert any(a.startswith("--script=") for a in argv)
        assert str(foam_stub_path(case)) not in argv

    def test_the_script_lands_outside_the_case_definition(self, tmp_path) -> None:
        """In the case tree it would make every mesh view look like an edit."""
        case = _case(tmp_path)
        self._service(tmp_path, []).open_case(case, mesh_only=True)
        assert (case / CASE_METADATA_DIR / "paraview" / "inspect-mesh.py").is_file()

    def test_no_paraview_is_a_state_not_an_exception(self, tmp_path) -> None:
        """E-V01 is offered by the caller; raising would take down the view."""
        service = ParaViewService()
        service.locate = lambda: None  # type: ignore[method-assign]
        assert service.open_case(_case(tmp_path)) is False


class TestNoDownloadWhenAlreadyInstalled:
    """FR-V1's acceptance test, stated as a property rather than a screenshot."""

    def test_an_installed_paraview_is_reported_available(self, tmp_path) -> None:
        service = ParaViewService()
        service.locate = lambda: ParaViewInstall(  # type: ignore[method-assign]
            executable=tmp_path / "paraview", version="5.13"
        )
        assert service.is_available

    def test_a_missing_paraview_is_reported_absent(self) -> None:
        service = ParaViewService()
        service.locate = lambda: None  # type: ignore[method-assign]
        assert not service.is_available
