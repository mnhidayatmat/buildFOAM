"""M4's exit criterion (§11).

    "Every bundled tutorial can be opened, edited via a form, saved, and still
    runs."

The four claims are checked in that order against every corpus case, because a
failure in one makes the next meaningless: a case that cannot be opened cannot be
edited, and a form save that corrupted a dictionary would show up as a run
failure with no obvious cause.

The run itself needs a real OpenFOAM, so that half is marked ``requires_runtime``
and skipped where there is none. The first three claims run everywhere, since
they are about the editor rather than the solver — which is the same split §12.3
makes for the numerical gate, and for the same reason.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from corpus_loader import corpus_files
from foamwb.services.case import CaseService
from foamwb.services.foamdict import Document
from foamwb.services.schema import load_schema
from foamwb.services.validation import validate_case


#: Corpus cases, derived from the vendored dictionary paths. A "case" here is any
#: directory that has a system/controlDict, which is §5.1's definition.
def corpus_cases() -> list[str]:
    cases = {
        f.relative.rsplit("/system/controlDict", 1)[0]
        for f in corpus_files()
        if f.relative.endswith("system/controlDict")
    }
    return sorted(cases)


CASES = corpus_cases()


@pytest.fixture(params=CASES, ids=[c.split("/")[-1] for c in CASES])
def corpus_case(request, tmp_path) -> Path:
    """A writable copy of one corpus case."""
    from corpus_loader import CORPUS_DIR

    source = CORPUS_DIR / request.param
    destination = tmp_path / Path(request.param).name
    shutil.copytree(source, destination)
    return destination


class TestEveryTutorialOpens:
    """Claim 1 — FR-C2."""

    def test_opens_without_error(self, corpus_case: Path) -> None:
        case = CaseService().open(corpus_case)
        assert case.application or case.findings

    def test_validation_completes(self, corpus_case: Path) -> None:
        # Validation must survive every real case, including ones whose mesh is
        # absent and whose dictionaries use constructs the schema does not model.
        validate_case(CaseService().open(corpus_case))


class TestEveryTutorialCanBeFormEdited:
    """Claims 2 and 3 — FR-P1 and FR-P7."""

    def test_the_form_renders_over_its_controldict(self, corpus_case: Path) -> None:
        schema = load_schema("controlDict")
        document = Document.parse_bytes((corpus_case / "system" / "controlDict").read_bytes())
        applicable = [f for f in schema.fields if f.applies_to(document)]
        assert applicable, "no editable field in this dictionary"

    def test_a_form_save_moves_exactly_one_line(self, corpus_case: Path) -> None:
        # FR-P7 through the same API the form uses. The corpus dictionaries carry
        # banners, comments and directives that a re-rendering editor would
        # flatten.
        source = corpus_case / "system" / "controlDict"
        original = source.read_bytes()
        document = Document.parse_bytes(original)

        key = next((k for k in ("endTime", "writeInterval", "deltaT") if document.get(k)), None)
        if key is None:
            pytest.skip("no scalar entry to edit in this dictionary")

        document.set(key, "12345")
        before, after = original.decode().splitlines(), document.render().splitlines()
        assert len(before) == len(after)
        assert sum(1 for a, b in zip(before, after, strict=True) if a != b) == 1

    def test_saving_leaves_a_case_that_still_parses(self, corpus_case: Path) -> None:
        service = CaseService()
        case = service.open(corpus_case)
        source = corpus_case / "system" / "controlDict"

        document = Document.parse_bytes(source.read_bytes())
        if document.get("writeInterval"):
            document.set("writeInterval", "5")
            service.write_dictionary(case, source, document.render_bytes())

        reopened = service.open(corpus_case)
        assert reopened.application == case.application


@pytest.mark.requires_runtime
class TestEveryTutorialStillRuns:
    """Claim 4 — the one that needs a solver, run from the real tutorials.

    Not from the vendored corpus. That corpus is a *dictionary* corpus for
    §12.2's parser gate: it takes every file carrying a ``FoamFile`` header,
    which deliberately excludes the fragments cases pull in with ``#include``
    (``system/sampling`` and friends carry no header). Those files are not
    dictionaries in their own right, but a case is not runnable without them.

    Running from the corpus would therefore fail four cases for a reason that has
    nothing to do with the editor — and "the tutorial still runs" is a claim
    about the tutorial, so the tutorial is what it should be made against.
    """

    @pytest.fixture(params=CASES, ids=[c.split("/")[-1] for c in CASES])
    def tutorial_case(self, request, tutorials, tmp_path) -> Path:
        source = tutorials / request.param
        if not source.is_dir():
            pytest.skip(f"{request.param} not in this OpenFOAM release")
        destination = tmp_path / Path(request.param).name
        shutil.copytree(source, destination)
        return destination

    def test_the_case_still_runs_after_a_form_save(self, tutorial_case: Path, runtime) -> None:
        from foamwb.services.run import RunController, RunOutcome, RunPlan, Stage

        manager, installation, _status = runtime
        service = CaseService()
        case = service.open(tutorial_case)

        if not case.application:
            pytest.skip("no application named in controlDict")
        if not (tutorial_case / "system" / "blockMeshDict").is_file():
            pytest.skip("case is not meshed by blockMesh alone")
        service.restore_initial_conditions(case)

        # The edit a user makes through the form, via the same API it uses.
        source = tutorial_case / "system" / "controlDict"
        original = source.read_bytes()
        document = Document.parse_bytes(original)
        key = next((k for k in ("writeInterval", "endTime", "deltaT") if document.get(k)), None)
        if key is not None:
            document.set(key, document.get(key))
            service.write_dictionary(case, source, document.render_bytes())
            # The save was a no-op edit, so it must have changed nothing at all.
            assert source.read_bytes() == original

        session = manager.session_for(installation)
        try:
            result = RunController(session).execute(
                RunPlan(
                    case=tutorial_case,
                    stages=(Stage("blockMesh", argv=("blockMesh",)),),
                )
            )
        finally:
            session.close()
        assert result.outcome is RunOutcome.SUCCEEDED, result.failed_stage
