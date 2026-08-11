"""Boundary matrix, schema layer and validation (FR-P1, FR-P4, FR-C3, §5.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from foamwb.codes import ErrorCode
from foamwb.services.boundary import PatchType, read_boundary
from foamwb.services.boundary_matrix import read_matrix
from foamwb.services.case import CaseService
from foamwb.services.foamdict import Document
from foamwb.services.schema import (
    FieldKind,
    SchemaError,
    available_schemas,
    load_schema,
    parse_schema,
    validate_document,
)
from foamwb.services.validation import validate_case

BOUNDARY = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       polyBoundaryMesh;
    object      boundary;
}
3
(
    movingWall
    {
        type            wall;
        inGroups        1(wall);
        nFaces          20;
        startFace       760;
    }
    fixedWalls
    {
        type            wall;
        nFaces          60;
        startFace       780;
    }
    frontAndBack
    {
        type            empty;
        nFaces          800;
        startFace       840;
    }
)
"""

CONTROL_DICT = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}
application     icoFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         0.5;
deltaT          0.005;
writeControl    timeStep;
writeInterval   20;
"""


def field_file(conditions: dict[str, str]) -> str:
    entries = "\n".join(
        f"    {patch}\n    {{\n        type            {kind};\n    }}"
        for patch, kind in conditions.items()
    )
    return (
        "FoamFile\n{\n    version 2.0;\n    format ascii;\n"
        "    class volScalarField;\n    object p;\n}\n"
        "dimensions      [0 2 -2 0 0 0 0];\n"
        "internalField   uniform 0;\n"
        f"boundaryField\n{{\n{entries}\n}}\n"
    )


def make_case(root: Path, *, fields: dict[str, dict[str, str]] | None = None) -> Path:
    case = root / "cavity"
    (case / "system").mkdir(parents=True)
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "0").mkdir(parents=True)
    (case / "system" / "controlDict").write_text(CONTROL_DICT)
    (case / "constant" / "polyMesh" / "boundary").write_text(BOUNDARY)

    default = {
        "U": {"movingWall": "fixedValue", "fixedWalls": "noSlip", "frontAndBack": "empty"},
        "p": {".*": "zeroGradient", "frontAndBack": "empty"},
    }
    for name, conditions in (fields or default).items():
        (case / "0" / name).write_text(field_file(conditions))
    return case


class TestBoundaryReader:
    """FR-P4's input — the counted-list form the parser now understands."""

    def test_reads_patches_in_file_order(self, tmp_path) -> None:
        case = make_case(tmp_path)
        assert [p.name for p in read_boundary(case)] == [
            "movingWall",
            "fixedWalls",
            "frontAndBack",
        ]

    def test_reads_type_and_face_count(self, tmp_path) -> None:
        patch = read_boundary(make_case(tmp_path))[0]
        assert patch.type == PatchType.WALL
        assert patch.n_faces == 20
        assert patch.in_groups == ("wall",)

    def test_constrained_types_name_their_required_condition(self, tmp_path) -> None:
        # E-C04: a 2D case whose front and back carry a real condition is
        # silently solving a different problem.
        patches = {p.name: p for p in read_boundary(make_case(tmp_path))}
        assert patches["frontAndBack"].required_condition == "empty"
        assert patches["movingWall"].required_condition is None

    def test_an_unmeshed_case_yields_no_patches(self, tmp_path) -> None:
        # The ordinary state of a fresh import, not a fault.
        (tmp_path / "system").mkdir(parents=True)
        assert read_boundary(tmp_path) == []

    def test_processor_patches_are_excluded(self, tmp_path) -> None:
        # decomposePar's artefacts are not part of the case the user wrote.
        case = make_case(tmp_path)
        boundary = case / "constant" / "polyMesh" / "boundary"
        boundary.write_text(
            boundary.read_text().replace(
                "    frontAndBack\n    {\n        type            empty;",
                "    procBoundary0to1\n    {\n        type            processor;",
            )
        )
        assert "procBoundary0to1" not in [p.name for p in read_boundary(case)]

    def test_the_boundary_file_round_trips(self, tmp_path) -> None:
        # A counted list is opaque to the structural parser, but byte fidelity is
        # unconditional — it is a property of the token stream.
        case = make_case(tmp_path)
        source = (case / "constant" / "polyMesh" / "boundary").read_bytes()
        assert Document.parse_bytes(source).render_bytes() == source


class TestBoundaryMatrix:
    """FR-P4 — every patch shown for every field."""

    def test_covers_every_patch_and_field(self, tmp_path) -> None:
        matrix = read_matrix(CaseService().open(make_case(tmp_path)))
        assert len(matrix.patches) == 3
        assert matrix.fields == ["U", "p"]
        assert len(matrix.cells) == 6

    def test_reports_the_condition_in_force(self, tmp_path) -> None:
        matrix = read_matrix(CaseService().open(make_case(tmp_path)))
        assert matrix.cell("movingWall", "U").condition == "fixedValue"

    def test_a_regex_key_covers_matching_patches(self, tmp_path) -> None:
        # ".*" is how real cases set a default, and a matrix that showed those
        # cells as missing would report errors that are not there.
        matrix = read_matrix(CaseService().open(make_case(tmp_path)))
        cell = matrix.cell("movingWall", "p")
        assert cell.condition == "zeroGradient"
        assert cell.is_default
        assert cell.matched_by == ".*"

    def test_an_explicit_entry_is_not_marked_as_a_default(self, tmp_path) -> None:
        matrix = read_matrix(CaseService().open(make_case(tmp_path)))
        assert not matrix.cell("movingWall", "U").is_default

    def test_the_last_matching_key_wins(self, tmp_path) -> None:
        # OpenFOAM applies the last match, so a later ".*" overrides an earlier
        # explicit entry. Showing the first would show a value the solver ignores.
        case = make_case(
            tmp_path,
            fields={"p": {"movingWall": "fixedValue", ".*": "zeroGradient"}},
        )
        matrix = read_matrix(CaseService().open(case))
        assert matrix.cell("movingWall", "p").condition == "zeroGradient"

    def test_a_missing_entry_is_reported_with_the_patch_and_field(self, tmp_path) -> None:
        # FR-C3's acceptance criterion, and §1.2's most common beginner failure.
        case = make_case(
            tmp_path,
            fields={"p": {"movingWall": "zeroGradient", "frontAndBack": "empty"}},
        )
        matrix = read_matrix(CaseService().open(case))
        finding = next(f for f in matrix.findings if f.code is ErrorCode.MISSING_BOUNDARY_FIELD)
        assert "fixedWalls" in finding.detail
        assert finding.file.name == "p"
        assert matrix.cell("fixedWalls", "p").is_missing

    def test_a_constrained_patch_with_the_wrong_condition_is_reported(self, tmp_path) -> None:
        case = make_case(tmp_path, fields={"p": {".*": "zeroGradient"}})
        matrix = read_matrix(CaseService().open(case))
        finding = next(f for f in matrix.findings if f.code is ErrorCode.PATCH_BC_INCOMPATIBLE)
        assert "frontAndBack" in finding.detail
        assert "empty" in finding.detail

    def test_a_valid_case_produces_no_findings(self, tmp_path) -> None:
        assert read_matrix(CaseService().open(make_case(tmp_path))).findings == []

    def test_an_unparseable_field_still_appears_as_a_column(self, tmp_path) -> None:
        # Hiding it would make the matrix disagree with the file tree beside it.
        case = make_case(tmp_path)
        (case / "0" / "broken").write_text("boundaryField {\n")
        matrix = read_matrix(CaseService().open(case))
        assert "broken" in matrix.fields
        assert any(f.code is ErrorCode.PARSE_ERROR for f in matrix.findings)

    def test_an_unmeshed_case_says_so_rather_than_erroring(self, tmp_path) -> None:
        case = make_case(tmp_path)
        (case / "constant" / "polyMesh" / "boundary").unlink()
        matrix = read_matrix(CaseService().open(case))
        assert not matrix.is_meshed
        assert matrix.findings == []


class TestSchema:
    """§5.4 — form editors are driven by data."""

    def test_the_bundled_controldict_schema_loads(self) -> None:
        schema = load_schema("controlDict")
        assert schema is not None
        assert schema.file == Path("system/controlDict")
        assert "application" in schema.keys

    def test_a_missing_schema_is_not_an_error(self) -> None:
        # Most dictionaries have no schema and are edited in the raw-text tab,
        # which FR-P6 provides for every file.
        assert load_schema("noSuchDictionary") is None

    def test_every_bundled_schema_parses(self) -> None:
        for name in available_schemas():
            assert load_schema(name) is not None

    def test_every_corpus_controldict_validates_clean(self) -> None:
        # The strongest statement available about the schema: it agrees with 23
        # real dictionaries written by OpenFOAM's own authors. A schema that
        # flagged valid tutorials would teach users to ignore the panel.
        from corpus_loader import corpus_files

        schema = load_schema("controlDict")
        assert schema is not None
        checked = 0
        for corpus_file in corpus_files():
            if not corpus_file.relative.endswith("system/controlDict"):
                continue
            checked += 1
            document = Document.parse(corpus_file.text)
            assert validate_document(schema, document, corpus_file.path) == []
        assert checked > 15

    def test_unknown_keys_are_reported_not_rejected(self) -> None:
        # §5.4: preserved untouched and shown in the raw-text tab.
        schema = load_schema("controlDict")
        document = Document.parse(CONTROL_DICT + "libs (myLib);\nfunctions { }\n")
        assert set(schema.unknown_keys(document)) == {"libs", "functions"}
        assert validate_document(schema, document, Path("controlDict")) == []

    @pytest.mark.parametrize(
        ("kind", "value", "ok"),
        [
            (FieldKind.SCALAR, "0.005", True),
            (FieldKind.SCALAR, "1e-6", True),
            (FieldKind.SCALAR, "abc", False),
            (FieldKind.INTEGER, "20", True),
            (FieldKind.INTEGER, "2.5", False),
            (FieldKind.BOOL, "yes", True),
            (FieldKind.BOOL, "true", True),
            (FieldKind.BOOL, "maybe", False),
            (FieldKind.WORD, "icoFoam", True),
            (FieldKind.WORD, "two words", False),
        ],
    )
    def test_field_checking(self, kind: FieldKind, value: str, ok: bool) -> None:
        from foamwb.services.schema import Field

        assert (Field(key="k", kind=kind).check(value) is None) is ok

    def test_a_range_violation_explains_itself(self) -> None:
        # The message is shown in the form, so it must say what to do.
        from foamwb.services.schema import Field

        field = Field(key="deltaT", kind=FieldKind.SCALAR, minimum=0, exclusive_minimum=True)
        assert "greater than 0" in field.check("0")
        assert field.check("0.001") is None

    def test_dependent_fields_are_skipped_when_inapplicable(self) -> None:
        # maxCo matters only with adjustTimeStep on. Demanding it otherwise would
        # report an error about a value the case never reads.
        schema = load_schema("controlDict")
        document = Document.parse(CONTROL_DICT)
        assert validate_document(schema, document, Path("controlDict")) == []

    def test_a_required_field_that_is_absent_is_reported(self) -> None:
        schema = load_schema("controlDict")
        document = Document.parse(CONTROL_DICT.replace("deltaT          0.005;\n", ""))
        findings = validate_document(schema, document, Path("controlDict"))
        assert any("deltaT" in f.detail for f in findings)

    def test_a_bad_enum_value_names_the_alternatives(self) -> None:
        schema = load_schema("controlDict")
        document = Document.parse(
            CONTROL_DICT.replace("writeControl    timeStep;", "writeControl    someday;")
        )
        finding = validate_document(schema, document, Path("controlDict"))[0]
        assert "timeStep" in finding.detail

    @pytest.mark.parametrize(
        "raw",
        ['{"schema": 99, "file": "x", "fields": []}', "{ not json", '{"schema": 1}'],
    )
    def test_an_unusable_schema_is_refused(self, raw: str) -> None:
        with pytest.raises((SchemaError, KeyError)):
            parse_schema("bad", raw)


class TestValidation:
    """FR-C3 and §7.4's panel."""

    def test_a_valid_case_is_runnable(self, tmp_path) -> None:
        assert validate_case(CaseService().open(make_case(tmp_path))).is_runnable

    def test_findings_are_ordered_worst_first(self, tmp_path) -> None:
        case = make_case(tmp_path, fields={"p": {".*": "zeroGradient"}})
        validation = validate_case(CaseService().open(case))
        severities = [int(f.severity) for f in validation.findings]
        assert severities == sorted(severities, reverse=True)

    def test_a_blocking_finding_makes_the_case_not_runnable(self, tmp_path) -> None:
        case = make_case(tmp_path, fields={"p": {"movingWall": "zeroGradient"}})
        validation = validate_case(CaseService().open(case))
        assert not validation.is_runnable
        assert validation.blocking

    def test_the_matrix_is_available_alongside_the_findings(self, tmp_path) -> None:
        # §7.4 shows both, and recomputing the matrix for the panel would let the
        # two disagree about the same case.
        validation = validate_case(CaseService().open(make_case(tmp_path)))
        assert validation.matrix.is_meshed

    def test_validation_never_prevents_opening(self, tmp_path) -> None:
        # FR-C2 and §7.9 rule 1: a case that refused to open until it was valid
        # could not be fixed in the application.
        case = make_case(tmp_path, fields={"p": {}})
        opened = CaseService().open(case)
        assert opened.application == "icoFoam"
        assert validate_case(opened).blocking
