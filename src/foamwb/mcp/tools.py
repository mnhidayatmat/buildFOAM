"""The tools an agent can call, declared as data (DEC-24).

Each tool is a thin call into a service the window already uses, so an agent
gets the same guarantees a person does and none the window does not give:

* **Byte-faithful edits** (FR-P7). ``set_dictionary_entry`` goes through
  :meth:`Document.set`, so a changed value is a one-line diff and every comment
  survives. ``write_case_file`` refuses text that does not parse (E-C02).
* **The plan is visible before it runs** (FR-S1). ``plan_run`` returns the
  stages ``start_run`` would execute, and ``start_run`` returns them again.
* **Stopping is not killing** (FR-S5, DEC-14). ``stop_run`` defaults to *Stop &
  Write*; the two signals need ``confirm``, which is the agent's version of the
  dialog the Run page shows before them (§7.9 rule 5).
* **Codes, not prose** (§9). Every failure a service reports carries its code
  and guide anchor into the result, so an agent's transcript is supportable.

The tools that write are marked destructive or not in their annotations, which
is what a client uses to decide whether to ask the person before calling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from foamwb.branding import APP_DISPLAY_NAME
from foamwb.codes import Code
from foamwb.mcp.protocol import Tool, ToolError, ToolResult
from foamwb.mcp.workbench import Workbench
from foamwb.services import advisor
from foamwb.services.apply_turbulence import apply_turbulence, current_choice, plan_apply
from foamwb.services.boundary_matrix import read_matrix
from foamwb.services.case import Case, Finding, is_definition_file
from foamwb.services.foamdict.document import Document, ParseError, PathError
from foamwb.services.freshness import assess
from foamwb.services.geometry import GeometryError, existing_surfaces, import_geometry
from foamwb.services.initial import read_initial_fields, set_internal_field
from foamwb.services.mesh import mesh_plan, parse_check_mesh
from foamwb.services.monitor import MonitorService
from foamwb.services.newcase import NewCaseError, create_case
from foamwb.services.run import RunPlan, StageState, StopMode, build_plan, build_update_plan
from foamwb.services.run.job import RunJob
from foamwb.services.runtime.manifest import load_manifest
from foamwb.services.snappy import FlowRegion, MeshSettings, SnappyError, plan_mesh
from foamwb.services.snappy import write_dictionaries as write_mesh_dictionaries
from foamwb.services.validation import validate_case

__all__ = ["INSTRUCTIONS", "build_tools"]

#: Largest file ``read_case_file`` returns whole. Mesh files run to gigabytes and
#: an agent's context does not; past this the tail is returned instead.
MAX_READ_BYTES = 256 * 1024

#: Longest a single ``get_run_status`` may block. Long enough to save an agent
#: most of its polling, short enough that a stop request is never queued behind
#: a wait for a minute.
MAX_WAIT_SECONDS = 60

INSTRUCTIONS = (
    f"{APP_DISPLAY_NAME} sets up and runs OpenFOAM cases. Typical order: "
    "runtime_status; create_case or open_case; import_geometry and "
    "generate_mesh_dictionaries (or write a blockMeshDict with write_case_file); "
    "start_run with mode=mesh, then get_mesh_quality; get_boundary_conditions and "
    "set_dictionary_entry / write_case_file for the 0/ fields; "
    "recommend_turbulence_model and apply_turbulence_model; validate_case; "
    "plan_run; start_run; get_run_status (with wait_seconds) until it finishes; "
    "get_residuals. Runs are asynchronous: start_run returns a run_id at once. "
    "Every file stays an ordinary OpenFOAM dictionary the user can open by hand. "
    "Stop runs with stop_run mode=write unless the user asks otherwise."
)


# -- serialisation -------------------------------------------------------------


def _relative(case: Path, path: Path) -> str:
    try:
        return path.relative_to(case).as_posix()
    except ValueError:
        return str(path)


def _code(code: Code | None) -> dict[str, str] | None:
    if code is None:
        return None
    return {"id": code.id, "condition": code.condition, "guide": code.guide_anchor}


def _finding(case: Path, finding: Finding) -> dict[str, Any]:
    return {
        "code": finding.code.id,
        "severity": finding.severity.name.lower(),
        "blocks_run": finding.blocks_run,
        "file": _relative(case, finding.file),
        "line": finding.line,
        "column": finding.column,
        "detail": finding.detail or finding.code.condition,
        "guide": finding.code.guide_anchor,
    }


def _plan(plan: RunPlan) -> list[dict[str, Any]]:
    states = plan.stage_states()
    active = set(plan.active_stages())
    return [
        {
            "stage": stage.name,
            "command": " ".join(stage.render(plan.n_procs)) if stage in active else None,
            "state": states[stage.name].value,
        }
        for stage in plan.stages
    ]


def _raise_coded(exc: Exception) -> None:
    """Turn a service's coded exception into a ToolError carrying the code."""
    code: Code | None = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    raise ToolError(
        message,
        code=code.id if code else None,
        guide=code.guide_anchor if code else None,
    ) from exc


def _turbulence_dictionary(workbench: Workbench) -> str:
    """The lineage's name for the turbulence dictionary (NFR-M3, DEC-15)."""
    manifest = load_manifest()
    version = workbench.openfoam_version
    release = (
        manifest.release(version)
        if version and manifest.supports(version)
        else manifest.default_release()
    )
    return release.dictionary("turbulence")


# -- the tools -----------------------------------------------------------------


_CASE = {"type": "string", "description": "Case directory (absolute, or relative to the root)."}


def build_tools(wb: Workbench) -> list[Tool]:
    """Every tool, bound to one workbench."""

    # -- runtime ---------------------------------------------------------------

    def runtime_status(args: dict[str, Any]) -> ToolResult:
        status = wb.runtime_status(refresh=bool(args.get("refresh")))
        data = {
            "state": status.state.value,
            "usable": status.is_usable,
            "openfoam_version": status.openfoam_version,
            "kind": status.kind.value if status.kind else None,
            "reason": _code(status.reason),
            "detail": status.detail,
            "permitted_directories": [str(root) for root in wb.roots],
        }
        summary = (
            f"OpenFOAM {status.openfoam_version} is {status.state.value}."
            if status.is_usable
            else f"No usable runtime ({status.reason.id if status.reason else status.state})."
        )
        return ToolResult(data, summary)

    # -- cases -----------------------------------------------------------------

    def create(args: dict[str, Any]) -> ToolResult:
        parent = wb.resolve(args.get("parent") or str(wb.roots[0]), must_exist=False)
        parent.mkdir(parents=True, exist_ok=True)
        try:
            made = create_case(
                parent, args["name"], application=args.get("application") or "simpleFoam"
            )
        except NewCaseError as exc:
            _raise_coded(exc)
        return ToolResult(
            {
                "case": str(made.path),
                "application": made.application,
                "written": [p.as_posix() for p in made.written],
            },
            f"Created {made.path.name}. It has no mesh yet.",
        )

    def open_case(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        freshness = assess(case.path)
        metadata = case.metadata
        runs = [run.to_json() for run in (metadata.runs if metadata else [])][-5:]
        data = {
            "case": str(case.path),
            "name": case.name,
            "classification": case.classification.value,
            "application": case.application,
            "time_directories": case.time_directories(),
            "latest_time": case.latest_time,
            "needs_initial_conditions": wb.cases.needs_initial_conditions(case),
            "has_mesh": freshness.has_mesh,
            "mesh_stale_because": freshness.mesh_stale_because or None,
            "has_results": freshness.has_results,
            "results_stale_because": freshness.results_stale_because or None,
            "surfaces": [s.name for s in existing_surfaces(case.path)],
            "findings": [_finding(case.path, f) for f in case.findings],
            "recent_runs": runs,
        }
        return ToolResult(data, f"{case.name}: {case.application or 'no solver named'}.")

    def list_files(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        files = [_relative(case.path, p) for p in wb.cases.dictionary_files(case)]
        return ToolResult({"case": str(case.path), "files": files})

    def read_file(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        target = wb.case_file(case, args["file"])
        data = target.read_bytes()
        truncated = len(data) > MAX_READ_BYTES
        if truncated:
            data = data[-MAX_READ_BYTES:]
        return ToolResult(
            {
                "file": _relative(case.path, target),
                "truncated": truncated,
                "content": data.decode("utf-8", errors="replace"),
            }
        )

    def write_file(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        target = wb.case_file(case, args["file"], must_exist=False)
        if not is_definition_file(case.path, target):
            raise ToolError(
                f"{args['file']} is not part of the case definition. Only files under "
                "system/, constant/ and 0/ can be written; results are the solver's."
            )
        content = args["content"]
        try:
            Document.parse(content)
        except ParseError as exc:
            raise ToolError(
                f"{args['file']} was not written because it does not parse: {exc}",
                code="E-C02",
                guide="cases/parse-error",
            ) from exc
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        wb.cases.write_dictionary(case, target, content.encode("utf-8"))
        verb = "Replaced" if existed else "Created"
        return ToolResult({"file": _relative(case.path, target), "created": not existed}, verb)

    def set_entries(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        target = wb.case_file(case, args["file"])
        entries = args["entries"]
        if not entries or not all(isinstance(v, str | int | float) for v in entries.values()):
            raise ToolError("entries must map entry paths to values, e.g. {'endTime': '500'}.")
        try:
            document = Document.parse_bytes(target.read_bytes())
        except ParseError as exc:
            raise ToolError(str(exc), code="E-C02", guide="cases/parse-error") from exc

        changed: dict[str, dict[str, str | None]] = {}
        for path, value in entries.items():
            before = document.get(path)
            try:
                document.set(path, str(value))
            except PathError as exc:
                raise ToolError(
                    f"{exc.args[0]} in {args['file']}. set_dictionary_entry changes existing "
                    "entries only; use write_case_file to add one."
                ) from exc
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if before != document.get(path):
                changed[path] = {"from": before, "to": document.get(path)}

        if changed:
            wb.cases.write_dictionary(case, target, document.render_bytes())
        return ToolResult(
            {"file": _relative(case.path, target), "changed": changed},
            f"Changed {len(changed)} entr{'y' if len(changed) == 1 else 'ies'}.",
        )

    def validate(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        result = validate_case(case)
        findings = [_finding(case.path, f) for f in result.findings]
        verdict = "runnable" if result.is_runnable else f"{len(result.blocking)} blocking"
        return ToolResult(
            {"runnable": result.is_runnable, "findings": findings},
            f"{case.name}: {verdict}, {len(findings)} finding(s).",
        )

    def boundary_conditions(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        matrix = read_matrix(case)
        patches = [
            {
                "name": patch.name,
                "type": patch.type,
                "required_condition": patch.required_condition,
            }
            for patch in matrix.patches
        ]
        cells = {
            patch.name: {
                field_name: (
                    {"type": cell.condition, "matched_by": cell.matched_by}
                    if (cell := matrix.cell(patch.name, field_name)) and not cell.is_missing
                    else None
                )
                for field_name in matrix.fields
            }
            for patch in matrix.patches
        }
        return ToolResult(
            {
                "meshed": matrix.is_meshed,
                "fields": matrix.fields,
                "patches": patches,
                "conditions": cells,
                "missing": [{"patch": c.patch, "field": c.field_name} for c in matrix.missing()],
                "findings": [_finding(case.path, f) for f in matrix.findings],
            },
            "No mesh yet: patches come from the mesh."
            if not matrix.is_meshed
            else f"{len(patches)} patches x {len(matrix.fields)} fields.",
        )

    def initial_fields(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        fields = read_initial_fields(case.path)
        return ToolResult(
            {
                "fields": [
                    {
                        "name": f.name,
                        "class": f.class_name,
                        "dimensions": f.dimensions,
                        "unit": f.unit,
                        "internal_field": f.internal_field,
                    }
                    for f in fields
                ]
            }
        )

    def set_initial(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        fields = {f.name: f for f in read_initial_fields(case.path)}
        field = fields.get(args["field"])
        if field is None:
            raise ToolError(
                f"{case.name} has no initial field {args['field']}. "
                f"It has: {', '.join(sorted(fields)) or 'none'}."
            )
        changed = set_internal_field(field, args["value"])
        if changed and case.metadata is not None:
            # An application-initiated change, so the metadata must follow it;
            # otherwise the next open would call it an outside edit (FR-C4).
            wb.cases.write_metadata(case)
        return ToolResult({"field": field.name, "changed": changed})

    def restore_initial(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        restored = wb.cases.restore_initial_conditions(case)
        return ToolResult(
            {"restored": restored},
            "Copied 0.orig to 0." if restored else "Nothing to restore.",
        )

    # -- geometry and meshing --------------------------------------------------

    def geometry(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        source = wb.resolve(args["source"])
        try:
            surface = import_geometry(case.path, source)
        except GeometryError as exc:
            _raise_coded(exc)
        return ToolResult(
            {
                "surface": _relative(case.path, surface.path),
                "format": surface.surface_format.value,
                "triangles": surface.triangles,
                "regions": list(surface.solids),
                "bounds": surface.bounds,
                "size": surface.size,
            },
            f"Imported {surface.name}: {surface.triangles} triangles.",
        )

    def mesh_dictionaries(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        location = args.get("location_in_mesh")
        if location is not None and (
            len(location) != 3 or not all(isinstance(v, int | float) for v in location)
        ):
            raise ToolError("location_in_mesh must be three numbers.")
        settings = MeshSettings(
            region=FlowRegion(args.get("region") or FlowRegion.EXTERNAL.value),
            refinement_min=args.get("refinement_min", 2),
            refinement_max=args.get("refinement_max", 3),
            background_cells=args.get("background_cells", 40),
            padding=args.get("padding", 2.0),
            location_in_mesh=tuple(location) if location else None,
        ).normalised()
        try:
            plan = plan_mesh(case.path, settings)
            if args.get("preview"):
                written: tuple[Path, ...] = ()
            else:
                written = write_mesh_dictionaries(
                    case.path, plan, replace_existing=bool(args.get("replace_existing"))
                )
        except SnappyError as exc:
            _raise_coded(exc)
        if written and case.metadata is not None:
            wb.cases.write_metadata(case)
        return ToolResult(
            {
                "written": [p.as_posix() for p in written],
                "domain_min": plan.low,
                "domain_max": plan.high,
                "background_cells": plan.cells,
                "background_cell_count": plan.background_cell_count,
                "location_in_mesh": plan.location_in_mesh,
                "existing": [p.as_posix() for p in plan.existing],
            },
            "Preview only; nothing written."
            if args.get("preview")
            else f"Wrote {len(written)} meshing dictionaries.",
        )

    def mesh_quality(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        logs = case.metadata_dir / "logs"
        found = sorted(logs.glob("r-*/log.checkMesh")) if logs.is_dir() else []
        if not found:
            raise ToolError(f"{case.name} has no checkMesh output yet. Run start_run mode=mesh.")
        quality = parse_check_mesh(found[-1].read_text(encoding="utf-8", errors="replace"))
        return ToolResult(
            {
                "run": found[-1].parent.name,
                "verdict": quality.verdict.value,
                "cells": quality.cells,
                "mesh_ok": quality.mesh_ok,
                "failed_checks": quality.failed_checks,
                "metrics": [
                    {
                        "name": m.name,
                        "value": m.value,
                        "verdict": m.verdict.value,
                        "threshold": m.threshold,
                        "detail": m.detail,
                    }
                    for m in quality.metrics
                ],
            },
            f"Mesh quality: {quality.verdict.value}.",
        )

    # -- turbulence ------------------------------------------------------------

    def recommend(args: dict[str, Any]) -> ToolResult:
        answers = advisor.Answers(**{key: value for key, value in args.items() if key != "limit"})
        manifest = load_manifest()
        version = wb.openfoam_version
        shortlist = advisor.recommend(
            answers,
            version=version,
            supported_versions=manifest.versions,
            limit=args.get("limit", 5),
        )
        catalogue = advisor.load_catalogue()
        return ToolResult(
            {
                "recommendations": [
                    {
                        "model": entry.name,
                        "family": entry.model.family,
                        "score": round(entry.score, 3),
                        "relative_cost": entry.model.cost,
                        "good_at": entry.model.good_at,
                        "fails_at": entry.model.fails_at,
                        "reasons": list(entry.reasons),
                        "caveats": list(entry.caveats),
                        "wall_treatments": [
                            {"key": t.key, "label": t.label, "target_y_plus": t.target_y_plus}
                            for t in advisor.wall_treatments_for(entry.model, catalogue)
                        ],
                    }
                    for entry in shortlist
                ]
            },
            "A ranked shortlist with trade-offs, not a single answer (FR-VVT2).",
        )

    def apply_model(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        catalogue = advisor.load_catalogue()
        model = catalogue.model(args["model"])
        if model is None:
            raise ToolError(
                f"Unknown turbulence model {args['model']}. Known: {', '.join(catalogue.names)}."
            )
        treatment = catalogue.treatment(args["wall_treatment"])
        if treatment is None:
            allowed = ", ".join(t.key for t in advisor.wall_treatments_for(model, catalogue))
            raise ToolError(f"Unknown wall treatment. {model.name} accepts: {allowed}.")
        dictionary = _turbulence_dictionary(wb)
        plan = plan_apply(case, model, treatment, dictionary_name=dictionary)
        if plan.blocked:
            raise ToolError(plan.blocked)

        planned = {
            "model_changes": plan.model_changes,
            "condition_changes": {
                _relative(case.path, path): changes
                for path, changes in plan.condition_changes.items()
            },
            "previous_model": plan.current_model,
        }
        if args.get("preview"):
            return ToolResult({"preview": True, **planned}, "Preview only; nothing written.")

        result = apply_turbulence(case, plan, service=wb.cases)
        name, block = current_choice(case, dictionary_name=dictionary)
        return ToolResult(
            {
                **planned,
                "written": [_relative(case.path, p) for p in result.written],
                "skipped": result.skipped,
                "now": {"model": name, "block": block},
            },
            f"Applied {model.name} with {treatment.label.lower()}.",
        )

    # -- running ---------------------------------------------------------------

    def _plan_for(case: Case, mode: str) -> RunPlan:
        if mode == "mesh":
            try:
                return mesh_plan(case.path)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        try:
            if mode == "update":
                return build_update_plan(case, assess(case.path))
            return build_plan(case)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    def plan_run(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        plan = _plan_for(case, args.get("mode") or "calculate")
        return ToolResult({"case": str(case.path), "stages": _plan(plan)})

    def start_run(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        mode = args.get("mode") or "calculate"
        session = wb.session()

        if mode != "mesh":
            # Most tutorials ship 0.orig and no 0; the window restores it on
            # open, and a run started here must not fail on a good case.
            wb.cases.restore_initial_conditions(case)
            if not args.get("ignore_validation"):
                blocking = validate_case(case).blocking
                if blocking:
                    raise ToolError(
                        f"{case.name} has {len(blocking)} blocking finding(s); fix them or "
                        "pass ignore_validation. First: "
                        + "; ".join(
                            f"{f.code.id} {_relative(case.path, f.file)}" for f in blocking[:3]
                        ),
                        code=blocking[0].code.id,
                        guide=blocking[0].code.guide_anchor,
                    )

        plan = _plan_for(case, mode)
        if all(state is StageState.SKIPPED for state in plan.stage_states().values()):
            return ToolResult(
                {"started": False, "stages": _plan(plan)}, "Everything is up to date."
            )

        job = RunJob(session, plan, cases=wb.cases)
        wb.add_job(job)
        return ToolResult(
            {
                "started": True,
                "run_id": job.run_id,
                "case": str(case.path),
                "stages": _plan(plan),
                "log_dir": str(job.log_dir),
            },
            f"Started {job.run_id}. Poll get_run_status.",
        )

    def run_status(args: dict[str, Any]) -> ToolResult:
        case = wb.resolve(args["case"]) if args.get("case") else None
        job = wb.job(args["run_id"], case)
        wait = min(max(args.get("wait_seconds", 0), 0), MAX_WAIT_SECONDS)
        if wait:
            job.wait(wait)
        state = job.snapshot()
        result = state.result
        data: dict[str, Any] = {
            "run_id": state.run_id,
            "case": str(state.case),
            "running": state.running,
            "current_stage": state.current_stage,
            "stages": {name: s.value for name, s in state.stages.items()},
            "lines_seen": state.lines_seen,
            "started": state.started.isoformat(timespec="seconds"),
            "finished": state.finished.isoformat(timespec="seconds") if state.finished else None,
            "log_dir": str(state.log_dir),
            "error": state.error,
            "diagnosis": (
                {
                    "message": state.diagnosis.message,
                    "code": state.diagnosis.code.id,
                    "time": state.diagnosis.time,
                    "evidence": state.diagnosis.detail,
                    "guide": state.diagnosis.guide_anchor,
                }
                if state.diagnosis
                else None
            ),
            "tail": job.tail(args.get("tail_lines", 30)),
        }
        if result is not None:
            data["outcome"] = result.outcome.value
            data["wall_seconds"] = round(result.wall_seconds, 3)
            data["stage_results"] = [
                {
                    "stage": s.name,
                    "state": s.state.value,
                    "exit_code": s.exit_code,
                    "wall_seconds": round(s.wall_seconds, 3),
                    "reason": _code(s.reason),
                    "detail": s.detail,
                    "diagnosis": s.diagnosis.message if s.diagnosis else None,
                }
                for s in result.stages
            ]
        if state.running:
            summary = f"{state.run_id} running {state.current_stage or ''}".rstrip() + "."
        elif result is not None:
            summary = f"{state.run_id} {result.outcome.value}."
        else:
            summary = f"{state.run_id} ended with an error."
        return ToolResult(data, summary)

    def stop(args: dict[str, Any]) -> ToolResult:
        case = wb.resolve(args["case"]) if args.get("case") else None
        job = wb.job(args["run_id"], case)
        mode = StopMode(args.get("mode") or StopMode.WRITE.value)
        if mode is not StopMode.WRITE and not args.get("confirm"):
            raise ToolError(
                f"Stopping with {mode.value} can leave a partial time directory that "
                "ParaView and a restart cannot read. Pass confirm=true if the user wants "
                "that; otherwise use mode=write, which writes a complete one."
            )
        if not job.is_running:
            return ToolResult({"delivered": False}, f"{job.run_id} is not running.")
        delivered = job.stop(mode)
        return ToolResult(
            {"delivered": delivered, "mode": mode.value},
            "Stop requested; the solver writes and exits at the end of the current step."
            if mode is StopMode.WRITE
            else f"Sent {mode.value}.",
        )

    def list_runs(_args: dict[str, Any]) -> ToolResult:
        runs = []
        for job in wb.jobs():
            state = job.snapshot()
            runs.append(
                {
                    "run_id": state.run_id,
                    "case": str(state.case),
                    "running": state.running,
                    "outcome": state.result.outcome.value if state.result else None,
                }
            )
        return ToolResult({"runs": runs})

    def residuals(args: dict[str, Any]) -> ToolResult:
        case = wb.open_case(args["case"])
        points = max(0, args.get("history_points", 0))
        data = MonitorService(case.path).refresh()
        if not data:
            raise ToolError(
                f"{case.name} has no postProcessing output yet. Residuals appear once a "
                "run started here or in the window has written its first step."
            )
        sources = {}
        for name, series in data.items():
            ordered = series.residuals + [s for s in series.series.values() if not s.is_residual]
            sources[name] = {
                "latest_time": series.latest_time,
                "text": series.text_columns,
                "series": {
                    s.name: {
                        "residual": s.is_residual,
                        "latest": s.latest,
                        "samples": len(s),
                        **(
                            {"times": s.times[-points:], "values": s.values[-points:]}
                            if points
                            else {}
                        ),
                    }
                    for s in ordered
                },
            }
        return ToolResult({"sources": sources})

    return [
        Tool(
            "runtime_status",
            "Runtime status",
            "Detect the OpenFOAM installation and report whether runs are possible, its "
            "version, and the directories this server may touch.",
            runtime_status,
            {"refresh": {"type": "boolean", "description": "Detect again rather than reuse."}},
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "create_case",
            "Create case",
            "Create an empty case (system/, constant/, 0/ with p and U). It has no mesh.",
            create,
            {
                "name": {"type": "string", "description": "Folder name for the case."},
                "parent": {"type": "string", "description": "Directory to create it in."},
                "application": {"type": "string", "description": "Solver, e.g. simpleFoam."},
            },
            required=("name",),
        ),
        Tool(
            "open_case",
            "Open case",
            "Summarise a case: solver, time directories, whether the mesh and results "
            "are current, imported surfaces, findings and recent runs.",
            open_case,
            {"case": _CASE},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "list_case_files",
            "List case files",
            "List the dictionaries that define the case (system/, constant/, 0/).",
            list_files,
            {"case": _CASE},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "read_case_file",
            "Read case file",
            "Return a file's text, path relative to the case. Large files return their tail.",
            read_file,
            {"case": _CASE, "file": {"type": "string", "description": "e.g. system/controlDict"}},
            required=("case", "file"),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "write_case_file",
            "Write case file",
            "Create or replace a dictionary under system/, constant/ or 0/. Rejected unless "
            "it parses. Prefer set_dictionary_entry for changing values in an existing file.",
            write_file,
            {
                "case": _CASE,
                "file": {"type": "string", "description": "Path relative to the case."},
                "content": {"type": "string", "description": "Complete file text."},
            },
            required=("case", "file", "content"),
            destructive=True,
            idempotent=True,
        ),
        Tool(
            "set_dictionary_entry",
            "Set dictionary entries",
            "Change existing entries in a dictionary, leaving every other byte untouched. "
            "Paths are slash-separated, e.g. 'endTime', 'boundaryField/inlet/value', "
            "'RAS/model'.",
            set_entries,
            {
                "case": _CASE,
                "file": {"type": "string", "description": "Path relative to the case."},
                "entries": {
                    "type": "object",
                    "description": "Entry path -> new value, e.g. {'deltaT': '0.001'}.",
                },
            },
            required=("case", "file", "entries"),
            destructive=True,
            idempotent=True,
        ),
        Tool(
            "validate_case",
            "Validate case",
            "Check the case and list findings with severity, file, line and §9 code. "
            "Blocking findings stop start_run.",
            validate,
            {"case": _CASE},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "get_boundary_conditions",
            "Boundary conditions",
            "The patch x field matrix: each patch's type and each field's condition on it, "
            "with missing entries listed. Needs a mesh.",
            boundary_conditions,
            {"case": _CASE},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "get_initial_fields",
            "Initial fields",
            "Every field in 0/ with its dimensions and internal value.",
            initial_fields,
            {"case": _CASE},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "set_initial_field",
            "Set initial field",
            "Set a field's uniform internal value, e.g. value '(10 0 0)' for U or '0' for p.",
            set_initial,
            {
                "case": _CASE,
                "field": {"type": "string"},
                "value": {"type": "string"},
            },
            required=("case", "field", "value"),
            destructive=True,
            idempotent=True,
        ),
        Tool(
            "restore_initial_conditions",
            "Restore 0 from 0.orig",
            "Copy 0.orig to 0 when the case has no 0, as a tutorial's Allrun does.",
            restore_initial,
            {"case": _CASE},
            required=("case",),
            idempotent=True,
        ),
        Tool(
            "import_geometry",
            "Import geometry",
            "Copy an STL or OBJ (or convert a STEP/IGES) into constant/triSurface and "
            "describe it: triangles, named regions, bounds.",
            geometry,
            {"case": _CASE, "source": {"type": "string", "description": "Surface file."}},
            required=("case", "source"),
        ),
        Tool(
            "generate_mesh_dictionaries",
            "Generate meshing dictionaries",
            "Write blockMeshDict and snappyHexMeshDict around the imported surfaces. "
            "Use preview=true to see the domain and cell count first.",
            mesh_dictionaries,
            {
                "case": _CASE,
                "region": {"type": "string", "enum": [r.value for r in FlowRegion]},
                "refinement_min": {"type": "integer"},
                "refinement_max": {"type": "integer"},
                "background_cells": {
                    "type": "integer",
                    "description": "Cells along the longest axis.",
                },
                "padding": {"type": "number", "description": "External domain size multiple."},
                "location_in_mesh": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "A point inside the fluid, [x, y, z].",
                },
                "replace_existing": {"type": "boolean"},
                "preview": {"type": "boolean"},
            },
            required=("case",),
            destructive=True,
        ),
        Tool(
            "get_mesh_quality",
            "Mesh quality",
            "checkMesh's figures from the latest run that meshed, with a pass/warn/fail "
            "verdict per metric.",
            mesh_quality,
            {"case": _CASE},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "recommend_turbulence_model",
            "Recommend turbulence model",
            "Rank turbulence models for the flow described, each with reasons, trade-offs "
            "and the wall treatments it permits.",
            recommend,
            {
                "external": {"type": "boolean"},
                "separation": {"type": "boolean"},
                "adverse_pressure_gradient": {"type": "boolean"},
                "swirl": {"type": "boolean"},
                "transition": {"type": "boolean"},
                "buoyancy": {"type": "boolean"},
                "unsteady": {"type": "boolean"},
                "scale_resolving": {"type": "boolean"},
                "compressible": {"type": "boolean"},
                "resolve_near_wall": {"type": "boolean"},
                "compute": {"type": "string", "enum": [c.value for c in advisor.Compute]},
                "limit": {"type": "integer"},
            },
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "apply_turbulence_model",
            "Apply turbulence model",
            "Set the turbulence model and write the matching wall conditions across 0/, "
            "consistently. preview=true shows the changes without writing.",
            apply_model,
            {
                "case": _CASE,
                "model": {"type": "string", "description": "e.g. kOmegaSST"},
                "wall_treatment": {"type": "string", "description": "A key from recommend."},
                "preview": {"type": "boolean"},
            },
            required=("case", "model", "wall_treatment"),
            destructive=True,
            idempotent=True,
        ),
        Tool(
            "plan_run",
            "Plan run",
            "The stages start_run would execute, without running anything. mode: "
            "calculate (everything), update (only what is out of date), mesh (meshing only).",
            plan_run,
            {"case": _CASE, "mode": {"type": "string", "enum": ["calculate", "update", "mesh"]}},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "start_run",
            "Start run",
            "Start meshing or the solver in the background and return a run_id at once. "
            "Refuses a case with blocking findings unless ignore_validation is set.",
            start_run,
            {
                "case": _CASE,
                "mode": {"type": "string", "enum": ["calculate", "update", "mesh"]},
                "ignore_validation": {"type": "boolean"},
            },
            required=("case",),
        ),
        Tool(
            "get_run_status",
            "Run status",
            "Progress of a run: stage states, outcome, diagnosis and the last lines of "
            f"output. wait_seconds (up to {MAX_WAIT_SECONDS}) blocks until it finishes or "
            "the time passes.",
            run_status,
            {
                "run_id": {"type": "string"},
                "case": _CASE,
                "wait_seconds": {"type": "number"},
                "tail_lines": {"type": "integer"},
            },
            required=("run_id",),
            read_only=True,
        ),
        Tool(
            "stop_run",
            "Stop run",
            "Stop a run. mode=write (default) writes a complete time directory and exits; "
            "terminate and kill need confirm=true because they can leave a partial one.",
            stop,
            {
                "run_id": {"type": "string"},
                "case": _CASE,
                "mode": {"type": "string", "enum": [m.value for m in StopMode]},
                "confirm": {"type": "boolean"},
            },
            required=("run_id",),
            destructive=True,
        ),
        Tool(
            "list_runs",
            "List runs",
            "Runs started by this server and whether they are still going.",
            list_runs,
            read_only=True,
            idempotent=True,
        ),
        Tool(
            "get_residuals",
            "Residuals",
            "Monitored series from postProcessing: latest residual per equation and any "
            "forces or probes. history_points returns the last N samples too.",
            residuals,
            {"case": _CASE, "history_points": {"type": "integer"}},
            required=("case",),
            read_only=True,
            idempotent=True,
        ),
    ]
