"""The user-visible string catalogue (NFR-A5).

"All user-visible strings externalised for translation **from M1**. English ships
in v1.0; Bahasa Melayu in v1.1. Retrofitting i18n later is expensive — the
extraction discipline starts immediately."

Every string goes through :func:`QCoreApplication.translate`, which
``pyside6-lupdate`` extracts into a ``.ts`` catalogue. Collecting them here rather
than scattering ``tr()`` calls through the widgets buys three things:

* Widgets take their text as an argument, so they can be constructed in a test
  with fixed strings and asserted against without depending on the locale.
* M7's pseudo-locale pass — accented, 40%-expanded strings, checking for
  truncation — can be driven by substituting one dictionary.
* The set of user-visible text is enumerable, so "did we translate everything?"
  is a question with an answer rather than a code review.

Placeholders are positional (``{0}``) rather than named, because a translator
reordering a sentence must be able to move them, and some languages need to.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from foamwb.branding import APP_DISPLAY_NAME

__all__ = ["shell_strings", "view_placeholders"]

_CONTEXT = "Shell"


def _(source: str) -> str:
    return QCoreApplication.translate(_CONTEXT, source)


def shell_strings() -> dict[str, str]:
    """Hub and shell chrome."""
    return {
        "window_title": APP_DISPLAY_NAME,
        "hub_heading": _("Welcome to {0}").format(APP_DISPLAY_NAME),
        "recent_cases": _("Recent cases"),
        "no_recent_cases": _(
            "No cases yet. Create one, open an existing OpenFOAM case folder, "
            "or install a tutorial from the Library."
        ),
        "never_run": _("never run"),
        "run_succeeded": _("completed"),
        "run_failed": _("failed"),
        "go_to_setup": _("Go to Setup"),
        "action_new_case": _("New Case"),
        "action_open_case": _("Open Case"),
        "action_library": _("Library"),
        "action_guide": _("Guide"),
        "action_case_folder": _("Case Folder"),
        "action_settings": _("Settings"),
        "toggle_nav_rail": _("Collapse navigation"),
        "choose_case": _("Choose an OpenFOAM case folder"),
        "not_a_case_title": _("That folder is not an OpenFOAM case"),
        "case_opened": _("Opened {0}"),
        "cannot_plan_title": _("This case cannot be run yet"),
        "restored_initial": _(
            "Copied 0.orig to 0, as this case ships its initial conditions that way."
        ),
        "no_runtime_title": _("OpenFOAM is not ready"),
        "no_runtime_body": _(
            "A case can be opened, but running one needs a working OpenFOAM. Setup will install it."
        ),
        "run_state_running": _("running"),
        "up_to_date": _("Everything is up to date."),
        "update_running": _("Updating {0}: {1}."),
        # The window title: case, then its solver in brackets, the way Fluent
        # titles its window with the case's solver settings.
        "title_with_case": _("{0} — {1}"),
        "title_with_solver": _("{0} [{1}] — {2}"),
        "recent_menu": _("Recent Cases"),
        "no_recent_menu": _("No recent cases"),
        # Creating a case (FR-C1)
        "new_case_where": _("Choose where to create the case"),
        "new_case_name_title": _("New case"),
        "new_case_name_prompt": _("Name for the new case folder:"),
        "new_case_default": _("case"),
        "new_case_failed_title": _("The case could not be created"),
        "new_case_failed": _("{0}  ({1})"),
        # Revealing the case folder
        "no_case_open_title": _("No case is open"),
        "no_case_open_body": _("Open or create a case first, and this will show you its folder."),
        "reveal_failed_title": _("The folder could not be opened"),
        "reveal_failed_body": _(
            "The case is at {0}, but this computer's file manager could not be started."
        ),
        # Compositions, kept translatable so their parts can be reordered.
        "nav_item": _("{0}  {1}"),
        "nav_tooltip": _("{0}  ({1})"),
    }


def messages_strings() -> dict[str, str]:
    """The Messages tab of the console dock (§7.4, FR-C3).

    Its own catalogue because two things show findings — the pane and, through
    it, the Check Case document — and one copy of each sentence is what stops a
    translator being asked the same question twice.
    """
    return {
        "messages": _("Messages"),
        "validation": _("Validation"),
        "no_case_open_hint": _("Open a case to edit its dictionaries."),
        "no_findings": _("No problems found."),
        "findings_summary": _("{0} to look at, {1} of which will stop a run."),
        "finding": _("{0}  {1} — {2}"),
        "finding_at_line": _("{0}, line {1}"),
    }


def log_pane_strings() -> dict[str, str]:
    """Strings owned by the log pane itself.

    Shared, because the Run view and the meshing panel both embed one. Kept as
    its own function rather than copied into both catalogues: two copies would
    drift, and a translator would be asked to translate the same sentence twice.
    """
    return {
        "log": _("Solver log"),
        "search_log": _("Search the log"),
        "find_next": _("Find next"),
        "jump_to_error": _("Jump to error"),
        "follow_output": _("Follow output"),
        "log_status": _("{0} lines, {1} flagged"),
    }


def stage_strip_strings() -> dict[str, str]:
    """The stage strip's vocabulary (§7.5).

    Its own catalogue because the strip is no longer only the Run view's: the
    mesh panel shows one too, now that generating a mesh is a sequence rather
    than four separate presses. Shared rather than copied — the same words
    duplicated under two keys would reach a translator as two questions with one
    right answer, and would drift the first time one of them was edited.
    """
    return {
        "no_plan": _("No run planned yet."),
        # Stage states, so the strip reads in words as well as glyphs (NFR-A2).
        "stage_pending": _("waiting"),
        "stage_running": _("running"),
        "stage_succeeded": _("done"),
        "stage_failed": _("failed"),
        "stage_skipped": _("skipped"),
        "stage_cancelled": _("stopped"),
        # Compositions, translatable so a right-to-left locale can reorder them.
        "stage_chip": _("{0}  {1}"),
        "stage_accessible": _("{0}: {1}"),
    }


def run_strings() -> dict[str, str]:
    """The Run view (§7.5).

    Stop actions name their consequence rather than only their mechanism: "Stop
    Now" means nothing to P1, while "may leave an incomplete result" is the fact
    that decides whether they want it (NFR-A6).
    """
    return {
        **log_pane_strings(),
        **stage_strip_strings(),
        "no_case_for_run": _("Open a case to run it."),
        "ready_to_run": _("{0} is ready to run."),
        "run": _("Run"),
        "log": _("Solver log"),
        "monitors": _("Monitors"),
        "residuals": _("Residuals"),
        "search_log": _("Search the log"),
        "find_next": _("Find next"),
        "jump_to_error": _("Jump to error"),
        "follow_output": _("Follow output"),
        "log_status": _("{0} lines, {1} flagged"),
        "axis_time": _("Time"),
        "axis_residual": _("Initial residual"),
        "residual_plot": _("Residual plot"),
        "no_monitor_data": _("Residuals appear here once the solver starts writing them."),
        "log_scale": _("Log scale"),
        "export_csv": _("Export CSV"),
        "exported_csv": _("Exported to {0}."),
        "running_stage": _("Running {0}…"),
        "run_succeeded": _("Finished in {0:.1f} s."),
        "run_failed": _("Run failed after {0:.1f} s."),
        "run_stopped": _("Stopped after {0:.1f} s."),
        "run_failed_at": _("Run failed at {0} ({1})."),
        "run_error": _("The run could not start: {0}"),
        # The three-level stop (FR-S5, DEC-14).
        "stop_write": _("Stop && Write"),
        "stop_write_tip": _(
            "Ask the solver to write the current time and stop cleanly. "
            "The result stays complete and can be reloaded."
        ),
        "stop_now": _("Stop Now"),
        "stop_now_tip": _("Signal the solver to quit. The last write may be incomplete."),
        "stop_kill": _("Force Kill"),
        "stop_kill_tip": _("End the process immediately. Anything being written is lost."),
        "stopping_write": _("Asking the solver to write and stop…"),
        "stopping_terminate": _("Stopping the solver…"),
        "stopping_kill": _("Ending the solver…"),
        "confirm_stop_title": _("Stop this run?"),
        "confirm_terminate": _(
            "Stopping now can leave an incomplete final result, which ParaView "
            "may not be able to open.\n\nStop & Write finishes the current step "
            "first and is usually what you want."
        ),
        "confirm_kill": _(
            "Force Kill ends the solver immediately. Anything it was writing at "
            "that moment is lost, and the case may need cleaning before it can "
            "run again.\n\nUse this only if the solver has stopped responding."
        ),
        # Divergence (FR-S6). The banner states the finding; the guide link and
        # the stop button are beside it, because a user who has just been told
        # their run is worthless wants to end it, not go hunting for the control.
        "diverging_title": _("Solution diverging"),
        "diverged_title": _("Solution diverged"),
        "diverging_suspected": _("Possible problem"),
        "why_this": _("Why this happened"),
        "dismiss": _("Dismiss"),
        "diagnosis_code": _("{0} · {1}"),
        # A composition, so a right-to-left locale can reorder it (NFR-A5).
        "diagnosis_accessible": _("{0}: {1}"),
        "diverged_still_running": _(
            "The run is still going. Nothing after this point is meaningful, so "
            "stopping now saves the remaining machine time."
        ),
        # Run history (FR-S7).
        "history": _("History"),
        "history_empty": _("Runs of this case will be listed here."),
        "history_columns": _("When,Outcome,Stages,Duration,Final time"),
        "history_outcome_succeeded": _("finished"),
        "history_outcome_failed": _("failed"),
        "history_outcome_stopped": _("stopped"),
        "history_duration": _("{0:.0f} s"),
        "history_procs": _("{0} cores"),
    }


def property_strings() -> dict[str, str]:
    """The settings page — scFLOW's Parameter / Value / Unit."""
    return {
        "properties": _("Properties"),
        "column_parameter": _("Parameter"),
        "column_value": _("Value"),
        "column_unit": _("Unit"),
        "no_properties": _("This step has no settings of its own."),
        "property_source": _("From {0}"),
        "group_row": _("{0}   ·   {1}"),
    }


def preprocessor_strings() -> dict[str, str]:
    """The Preprocessor view (§7.4)."""
    return {
        # The mesh panel embeds a log pane, so it needs its vocabulary too.
        **log_pane_strings(),
        # The initial-conditions editor is one of this view's tabs rather than a
        # view of its own. Merged here rather than at each construction site so
        # that "which catalogues does the preprocessor need?" has one answer —
        # three call sites each remembering a second merge is three chances to
        # forget, and forgetting raises a KeyError at construction.
        **initial_strings(),
        # The settings page is one of this view's pages too.
        **property_strings(),
        # Generating a mesh is a sequence, and the mesh panel shows it in the
        # same strip the Run view uses.
        **stage_strip_strings(),
        "stop_now": _("Stop Now"),
        "case_files": _("Case files"),
        # Naming the faces of an imported surface (FR-P3). The names typed here
        # become the patches of the generated mesh, which is why the hint says
        # what a face *is* rather than only how to pick one — a user who does not
        # know that a curved side counts as one face cannot predict the result.
        "region_pick": _("Turn the model with a drag. Click a face to select it — {0} in all."),
        "region_selected": _("{0} of {1} faces selected. Shift-click to add more."),
        "region_too_large": _("This surface is too large to identify faces in."),
        "region_name_label": _("Region name"),
        "region_name_placeholder": _("Name for the selected faces"),
        "region_name_apply": _("Name faces"),
        "region_name_invalid": _("A region name needs a letter to start with."),
        "region_name_cleaned": _("Named {1}: OpenFOAM cannot use {0} as a patch name."),
        "region_named": _("{1} faces named {0}. Written to {2}."),
        "region_row": _("{0}  ({1} faces)"),
        "region_list": _("Named regions"),
        # Geometry (FR-P3)
        "geometry_tab": _("Geometry"),
        "geometry_heading": _("Surfaces"),
        "geometry_intro": _(
            "Surfaces in constant/triSurface, which snappyHexMesh meshes around. "
            "STL and OBJ are used directly; STEP and IGES are converted on import."
        ),
        # The imported surface, drawn (FR-P3). Not a viewer: it answers "is this
        # the body I meant?", which a bounding box cannot.
        "preview_accessible": _("Preview of the selected surface"),
        "preview_hint": _("Drag to turn the model."),
        "preview_none": _("Nothing to show."),
        # Keyed by Unavailable's own values, so a reason added to that enum
        # without a sentence here fails a test rather than a user's window.
        "mesh_no_mesh": _("No mesh yet. Generate one and it appears here."),
        "mesh_too_large": _(
            "This mesh is too large to preview here. Open it in ParaView from Results."
        ),
        "mesh_unreadable": _(
            "This mesh could not be read. It may be in binary format, which "
            "ParaView opens and this preview does not."
        ),
        "mesh_patches": _("{0} patches, {1} of {2} boundary faces drawn"),
        "mesh_patches_whole": _("{0} patches, {1} boundary faces"),
        "preview_thinned": _("Showing {0} of {1} triangles."),
        "geometry_import": _("Import Geometry…"),
        "geometry_none": _("No geometry imported yet."),
        "geometry_filter": _(
            "Geometry (*.stl *.obj *.step *.stp *.iges *.igs *.brep);;All files (*)"
        ),
        "geometry_choose": _("Choose a geometry file"),
        # Two entries rather than one, because a surface can legitimately hold a
        # single triangle and "1 triangles" is the kind of slip that makes an
        # application look unfinished. Two catalogue keys keep the choice in the
        # widget where the count is known, and keep both forms translatable.
        "geometry_summary": _("{0} — {1} triangles"),
        "geometry_summary_one": _("{0} — 1 triangle"),
        "geometry_unreadable_row": _("{0} — could not be read"),
        "geometry_bounds": _("Size {0} x {1} x {2}"),
        "geometry_regions": _("Regions: {0}"),
        "geometry_imported": _("Imported {0}."),
        "geometry_converting": _("Converting {0}. This can take a few minutes."),
        "geometry_failed": _("{0}  ({1})"),
        "geometry_binary": _("binary"),
        "geometry_ascii": _("text"),
        "geometry_converter": _("CAD converter: {0}"),
        "geometry_converter_none": _(
            "No CAD converter found, so STEP and IGES cannot be converted. "
            "Install Gmsh, or export STL from your CAD package."
        ),
        "geometry_remove": _("Remove"),
        "geometry_removed": _("Removed {0}."),
        # Building a mesh around the imported geometry (FR-P3)
        "mesh_from_geometry": _("Mesh around this geometry"),
        "flow_region": _("Flow is"),
        "flow_external": _("Around the body (external)"),
        "flow_internal": _("Through the body (internal)"),
        "flow_region_help": _(
            "This decides which side of the surface the fluid is on. Getting it "
            "wrong is the usual reason a mesh comes out empty or inside out."
        ),
        "refinement_levels": _("Surface refinement"),
        "refinement_range": _("{0} to {1}"),
        "background_cells": _("Background cells (longest axis)"),
        "domain_summary": _("Domain {0} x {1} x {2}, {3} background cells before refinement."),
        "generate_mesh_dicts": _("Generate Mesh Settings"),
        "replace_mesh_dicts": _("Replace Mesh Settings"),
        "mesh_dicts_written": _("Wrote blockMeshDict and snappyHexMeshDict. Mesh tab is next."),
        "mesh_dicts_exist": _("This case already has {0}. Generating would replace it."),
        "mesh_dicts_failed": _("{0}  ({1})"),
        "confirm_replace_title": _("Replace the meshing dictionaries?"),
        "confirm_replace_body": _(
            "{0} will be overwritten. If you tuned it by hand, copy it somewhere "
            "else first — this cannot be undone."
        ),
        "form_tab": _("Form"),
        "form_tab_unavailable": _("Form (not available)"),
        "text_tab": _("Text"),
        "bc_tab": _("Boundary conditions"),
        "initial_tab": _("Initial conditions"),
        "raw_text": _("Dictionary text"),
        **messages_strings(),
        # Text editor
        "save": _("Save"),
        "revert": _("Revert"),
        "no_changes": _("No changes."),
        "unsaved_changes": _("Unsaved changes."),
        "save_blocked": _("Not saved — line {0}: {1}"),
        "not_in_form": _("Also in this file, editable in the Text tab: {0}"),
        "partly_in_form": _("These have further settings in the Text tab: {0}"),
        # Boundary-condition matrix
        "bc_matrix": _("Boundary conditions by patch and field"),
        "mesh_needed": _("This case has no mesh yet. Generate one to see its patches."),
        "matrix_summary": _("{0} patches x {1} fields, {2} without a condition."),
        "patch_header": _("{0}  ({1})"),
        "cell_missing": _("not set"),
        "cell_missing_tip": _("{0} has no entry in {1}, so the solver has nothing to apply there."),
        "cell_default_tip": _("Supplied by the pattern {0}, not written for this patch."),
        "cell_accessible": _("{0}, {1}: {2}"),
        "apply_to_all": _("Apply to all"),
        "for_field": _("patches, for"),
        "apply": _("Apply"),
        # Meshing utilities (FR-P5, FR-P9)
        "mesh_tab": _("Mesh"),
        "mesh_needs_runtime": _("Meshing needs a working OpenFOAM. Set one up first."),
        # One press for the whole sequence. Named for the outcome rather than for
        # the utilities, because the outcome is what the user wants and the
        # utilities are what the application knows.
        "generate_mesh": _("Generate mesh"),
        "generate_mesh_tip": _("Run every meshing step this case needs, in order."),
        "nothing_to_mesh": _("This case has no meshing dictionary, so there is nothing to run."),
        "utility_running": _("Running {0}…"),
        "utility_ok": _("{0} finished."),
        "utility_failed": _("{0} did not finish. {1}"),
        "utility_error": _("The utility could not start: {0}"),
        "quality_cells": _("{0} cells"),
        "quality_metric": _("{0} {1} ({2})"),
        # transformPoints asks what to do before it runs (FR-P5)
        "transform_title": _("Transform the mesh"),
        "transform_operation": _("Operation"),
        "transform_scale": _("Scale"),
        "transform_translate": _("Translate"),
        "transform_rotate": _("Rotate"),
        "transform_uniform": _("Same factor on every axis"),
        "transform_axis": _("Axis"),
        "transform_axis_x": _("X"),
        "transform_axis_y": _("Y"),
        "transform_axis_z": _("Z"),
        "transform_angle": _("Angle"),
        "transform_x": _("X"),
        "transform_y": _("Y"),
        "transform_z": _("Z"),
        "transform_scale_hint": _(
            "Multiplies every point coordinate. A mesh drawn in millimetres "
            "becomes metres at 0.001."
        ),
        "transform_translate_hint": _("Moves every point by this vector, in metres."),
        "transform_rotate_hint": _(
            "Turns the mesh about the chosen axis through the origin. "
            "Degrees, anticlockwise seen from the positive end of the axis."
        ),
        "transform_apply": _("Apply"),
        "transform_cancel": _("Cancel"),
        "transform_identity": _("That would move nothing, so the mesh was left alone."),
        "transform_cancelled": _("No transform applied."),
        "transform_zero_scale": _(
            "A factor of zero would flatten the mesh. Every axis needs a "
            "non-zero factor before this can be applied."
        ),
    }


def vandv_strings() -> dict[str, str]:
    """The V&V view (§7.7).

    Questions are phrased as things a user can answer about their own problem,
    not as model jargon. "Does the flow separate?" is answerable by someone who
    has seen the geometry; "do you need a realizable stress tensor?" is not, and
    a questionnaire that asked it would be a quiz rather than an aid.
    """
    return {
        "vv_no_case": _("Open a case to configure its turbulence modelling."),
        "vv_provenance": _("{0}  ·  OpenFOAM {1}  ·  currently {2}"),
        "vv_unknown_version": _("version unknown"),
        "vv_no_model": _("no turbulence model set"),
        # Tabs
        "vv_turbulence_tab": _("Turbulence"),
        "vv_mesh_study_tab": _("Mesh study"),
        "vv_validation_tab": _("Validation"),
        "vv_mesh_study_title": _("Grid convergence study"),
        "vv_mesh_study_body": _(
            "Generates a family of systematically refined meshes, runs them as "
            "one batch, and produces the GCI table a journal will ask for — with "
            "its convergence class and the assumptions it rests on. Ships in the "
            "next release."
        ),
        "vv_validation_title": _("Validation against experiment"),
        "vv_validation_body": _(
            "Imports measured data, samples the solution at the same locations, "
            "and reports the comparison error against its combined uncertainty. "
            "It will never print the word 'validated' as a verdict: that "
            "judgement depends on the application and belongs to you. Ships in "
            "the next release."
        ),
        # Questionnaire
        "vv_questionnaire": _("About your flow"),
        "vv_questionnaire_note": _(
            "Answer what you know. Anything left unticked is treated as 'no', "
            "and the shortlist still explains itself."
        ),
        "q_external_flow": _("Flow around a body, not through a duct"),
        "q_external_flow_help": _("External aerodynamics rather than internal, confined flow."),
        "q_separation": _("The flow separates from a surface"),
        "q_separation_help": _(
            "A recirculation or wake behind a step, a bluff body, or a stalled aerofoil."
        ),
        "q_adverse_pressure": _("Pressure rises along the flow"),
        "q_adverse_pressure_help": _(
            "A diffuser, a rear-facing curve, anything decelerating the flow near a wall."
        ),
        "q_swirl": _("The flow swirls or curves strongly"),
        "q_swirl_help": _("Cyclones, bends, anything with strong streamline curvature."),
        "q_transition": _("Laminar-to-turbulent transition matters"),
        "q_transition_help": _("The answer depends on where the boundary layer becomes turbulent."),
        "q_buoyancy": _("Buoyancy drives the flow"),
        "q_buoyancy_help": _("Natural convection, or a strongly heated or stratified flow."),
        "q_unsteady": _("The result changes over time"),
        "q_unsteady_help": _("Vortex shedding, a transient event, or a moving boundary."),
        "q_scale_resolving": _("Resolve the turbulent structures, not just their average"),
        "q_scale_resolving_help": _(
            "Choose this only if you need the eddies themselves — it costs "
            "orders of magnitude more than modelling them."
        ),
        "q_compressible": _("Compressibility matters"),
        "q_compressible_help": _("Roughly Mach 0.3 and above, or with significant heat release."),
        "q_resolve_near_wall": _("Mesh into the viscous sublayer (y+ ≈ 1)"),
        "q_resolve_near_wall_help": _(
            "Needed for heat transfer and separation onset. Far more cells near every wall."
        ),
        "q_compute": _("Compute available"),
        "compute_laptop": _("A laptop"),
        "compute_workstation": _("A workstation"),
        "compute_cluster": _("A cluster"),
        # Shortlist
        "vv_shortlist": _("Suggested models"),
        "vv_shortlist_note": _(
            "Ranked, never decided for you. Each entry says where it is strong "
            "and where it is known to fail."
        ),
        "vv_entry_head": _("{0}   ({1})"),
        "vv_good_at": _("Good at: {0}"),
        "vv_fails_at": _("Known to fail: {0}"),
        "vv_cost": _("Cost: {0}"),
        "cost_1": _("low"),
        "cost_2": _("moderate"),
        "cost_3": _("high"),
        "cost_4": _("very high"),
        "vv_because": _("+ {0}"),
        "vv_but": _("− {0}"),
        "vv_current": _("This case currently uses {0}, ranked {1} here — {2}"),
        "vv_current_unknown": _("This case uses {0}, which is not in the catalogue."),
        "vv_no_factor": _("nothing in your answers distinguishes it either way"),
        # Coupled consequences
        "vv_consequences": _("What that implies"),
        "vv_wall_treatment": _("Wall treatment"),
        "vv_velocity": _("Reference velocity (m/s)"),
        "vv_length": _("Reference length (m)"),
        "vv_viscosity": _("Kinematic viscosity (m²/s)"),
        "vv_intensity": _("Turbulence intensity (%)"),
        "vv_target": _("Target y+: {0}–{1}, aiming at {2}"),
        "vv_first_cell": _("First cell height: {0} m"),
        "vv_layers": _("Inflation layers to cover 2% of the reference length: {0}"),
        "vv_reynolds": _("Reynolds number: {0}"),
        "vv_inlet": _("Inlet {0} = {1}          {2}"),
        "vv_caveat": _("From {0}. {1}"),
        "vv_apply": _("Apply to this case"),
        "vv_applied": _("Applied {0}. Changed: {1}"),
        # Audit
        "vv_audit": _("y+ after the last run"),
        "vv_audit_none": _(
            "No y+ data yet. Run the case with the y+ audit enabled to see where "
            "the mesh actually landed."
        ),
        "vv_audit_no_walls": _("This case has no wall patches to audit."),
        "vv_audit_summary": _("Overall: {0}. Patches needing attention: {1}"),
        "vv_patch": _("Patch"),
        "vv_min": _("min y+"),
        "vv_max": _("max y+"),
        "vv_verdict": _("Verdict"),
        "verdict_pass": _("within band"),
        "verdict_warn": _("check"),
        "verdict_fail": _("outside the model's assumptions"),
    }


def runtime_banner_message(state: str, code: str | None) -> str:
    """Banner text for a non-ready runtime (§7.2).

    Plain language with no jargon (NFR-A6). The §9 code is appended rather than
    substituted for the explanation: it exists so a support conversation can start
    from a code, not so the user has to decode one.
    """
    messages = {
        "missing": _(
            "OpenFOAM is not installed yet. Setup will install everything needed "
            "to run a simulation on this computer."
        ),
        "broken": _("OpenFOAM is installed but is not working. Setup can repair or reinstall it."),
        "degraded": _(
            "OpenFOAM is working, but not in its preferred configuration. "
            "Simulations will still run."
        ),
    }
    text = messages.get(state, _("The runtime state could not be determined."))
    return f"{text}  ({code})" if code else text


def workflow_strings() -> dict[str, str]:
    """The outline and the task page (§7.2, DEC-21).

    Node names are Fluent's where OpenFOAM has the same thing: *Boundary
    Conditions* rather than ``0/``, *Methods* rather than ``fvSchemes``. The file
    is named underneath, in the task page, so the user learns the mapping
    instead of having to know it first.
    """
    return {
        "workflow": _("Outline View"),
        "outline_filter": _("Filter the outline"),
        "case_tree": _("Case"),
        # The nodes, in order.
        "step.workflow": _("Workflow"),
        "step.workflow.import": _("Import Geometry"),
        "step.workflow.describe": _("Describe Geometry"),
        "step.workflow.sizing": _("Add Local Sizing"),
        "step.workflow.boundaries": _("Update Boundaries"),
        "step.workflow.volume": _("Generate the Volume Mesh"),
        "step.setup": _("Setup"),
        "step.setup.general": _("General"),
        "step.setup.models": _("Models"),
        "step.setup.materials": _("Materials"),
        "step.setup.boundary": _("Boundary Conditions"),
        "step.setup.reference": _("Reference Values"),
        "step.solution": _("Solution"),
        "step.solution.methods": _("Methods"),
        "step.solution.controls": _("Controls"),
        "step.solution.monitors": _("Monitors"),
        "step.solution.initialization": _("Initialization"),
        "step.solution.activities": _("Calculation Activities"),
        "step.solution.check": _("Check Case"),
        "step.solution.run": _("Run Calculation"),
        "step.results": _("Results"),
        "step.results.graphics": _("Graphics"),
        "step.results.plots": _("Plots"),
        "step.results.reports": _("Reports"),
        "step.files": _("Files"),
        "step.files.case": _("Case Files"),
        # What each node is for, shown as the task page's caption. One sentence.
        "hint.workflow.import": _("Import the surface the mesh will be built around."),
        "hint.workflow.describe": _(
            "Say which side of the surface the fluid is on, and how finely to resolve it."
        ),
        "hint.workflow.sizing": _("Block structure and refinement, from blockMeshDict."),
        "hint.workflow.boundaries": _("The named patches the boundary conditions attach to."),
        "hint.workflow.volume": _("Run blockMesh, then checkMesh to see whether it is usable."),
        "hint.setup.general": _("The solver, and the time span it runs over."),
        "hint.setup.models": _("The turbulence model, from the turbulence dictionary."),
        "hint.setup.materials": _("Viscosity and density, from the transport dictionary."),
        "hint.setup.boundary": _("Every patch and every field, as a matrix."),
        "hint.setup.reference": _("Flow speed, length and target y+ for the turbulence advisor."),
        "hint.solution.methods": _("Discretisation schemes, from fvSchemes."),
        "hint.solution.controls": _("Linear solvers and relaxation, from fvSolution."),
        "hint.solution.monitors": _("Residuals, forces and probes written during the run."),
        "hint.solution.initialization": _("The starting field values, from the 0 directory."),
        "hint.solution.activities": _("How often, and in what form, results are written."),
        "hint.solution.check": _("Check the case is complete and consistent before running it."),
        "hint.solution.run": _("Run the solver, with the console and residuals live."),
        "hint.results.graphics": _("Show the mesh here, or open the result in ParaView."),
        "hint.results.plots": _("The residual history of the last run."),
        "hint.results.reports": _("Post utilities, and the turbulence and y+ audit."),
        "hint.files.case": _("Every file in the case, as it is on disk."),
        # Node states (NFR-A2: never colour alone).
        "state.done": _("done"),
        "state.available": _("ready"),
        "state.stale": _("out of date"),
        "state.blocked": _("not yet"),
        "state.locked": _("locked"),
        # Names the file that did it, because "needs updating" and "you edited
        # system/blockMeshDict after building the mesh" are the same fact and
        # only one of them can be acted on.
        "stale_because": _("{0} changed since this was last run. Update to bring it up to date."),
        "next_step": _("Next: {0}"),
        "step_row_state": _("{0}  {1} — {2}"),
        "workflow_progress": _("{0} of {1} done"),
        "workflow_progress_none": _("Open a case to begin."),
        "nothing_outstanding": _("Every required step is done."),
        # Fluent's mode switch. Once a mesh exists the meshing workflow greys
        # out and this brings it back.
        "return_to_mesh": _("Switch to Meshing"),
        "locked_explains": _("The mesh is built. Switch to Meshing to change it."),
        "blocked_no_case": _("Open a case first."),
        "blocked_no_mesh": _("Generate the mesh first."),
        **property_strings(),
        "step_accessible": _("{0}, {1}"),
        "step_row": _("{0}  {1}"),
        # The task page beside the outline.
        "task_page": _("Task Page"),
        "task_page_none": _("Select a node in the outline."),
    }


def ribbon_strings() -> dict[str, str]:
    """The ribbon (§7.1, DEC-21): tabs, groups and the actions in them.

    Fluent's tab names, and Fluent's grouping where the application has the
    same action. Actions it does not have — user-defined functions, parametric
    design — are absent rather than greyed, because a permanently dead button
    is the dead end §7.9 rule 1 forbids.
    """
    return {
        "tab.file": _("File"),
        "tab.domain": _("Domain"),
        "tab.physics": _("Physics"),
        "tab.solution": _("Solution"),
        "tab.results": _("Results"),
        "tab.view": _("View"),
        "tab.help": _("Help"),
        "group.mesh": _("Mesh"),
        "group.geometry": _("Geometry"),
        "group.sizing": _("Sizing"),
        "group.zones": _("Zones"),
        "group.generate": _("Generate"),
        "group.solver": _("Solver"),
        "group.models": _("Models"),
        "group.materials": _("Materials"),
        "group.reference": _("Reference"),
        "group.methods": _("Methods"),
        "group.controls": _("Controls"),
        "group.monitors": _("Monitors"),
        "group.initialization": _("Initialization"),
        "group.activities": _("Activities"),
        "group.run": _("Run Calculation"),
        "group.graphics": _("Graphics"),
        "group.plots": _("Plots"),
        "group.reports": _("Reports"),
        "group.export": _("Export"),
        "group.display": _("Display"),
        "group.layout": _("Layout"),
        "group.appearance": _("Appearance"),
        "action.new_case": _("New Case…"),
        "action.open_case": _("Open Case…"),
        "action.import_geometry": _("Import"),
        "action.import_geometry_menu": _("Import Geometry…"),
        "action.case_files": _("Case Files"),
        "action.library": _("Library…"),
        "action.case_folder": _("Case Folder"),
        "action.settings": _("Settings…"),
        "action.exit": _("Exit"),
        "action.check_mesh": _("Check"),
        "action.display_mesh": _("Display"),
        "action.describe_geometry": _("Describe"),
        "action.local_sizing": _("Local Sizing"),
        "action.update_boundaries": _("Boundaries"),
        "action.volume_mesh": _("Volume Mesh"),
        "action.general": _("General"),
        "action.models": _("Models"),
        "action.materials": _("Materials"),
        "action.boundary_conditions": _("Boundaries"),
        "action.reference_values": _("Reference Values"),
        "action.methods": _("Methods"),
        "action.controls": _("Controls"),
        "action.monitors": _("Monitors"),
        "action.initialization": _("Initialize"),
        "action.activities": _("Autosave"),
        "action.check_case": _("Check Case"),
        "action.update": _("Update"),
        "action.calculate": _("Calculate"),
        # && escapes the mnemonic ampersand in Qt button text.
        "action.stop_write": _("Stop && Write"),
        "action.graphics": _("Mesh"),
        "action.paraview": _("ParaView"),
        "action.residuals": _("Residuals"),
        "action.reports": _("Reports"),
        "action.export_csv": _("Residuals CSV"),
        "action.fit_view": _("Fit"),
        "action.reset_view": _("Reset View"),
        "action.toggle_outline": _("Outline"),
        "action.toggle_task_page": _("Task Page"),
        "action.toggle_console": _("Console"),
        "action.theme_light": _("Light"),
        "action.theme_dark": _("Dark"),
        "action.theme_system": _("System"),
        "action.guide": _("Guide"),
        # Tooltips carry the shortcut, so the keyboard route is discoverable.
        "tip.with_shortcut": _("{0}  ({1})"),
        "tip.new_case": _("Create an empty case folder"),
        "tip.open_case": _("Open an existing OpenFOAM case folder"),
        "tip.import_geometry": _("Import an STL, OBJ, STEP or IGES surface"),
        "tip.check_mesh": _("Run checkMesh and report the quality figures"),
        "tip.display_mesh": _("Show the surface and mesh in the graphics window"),
        "tip.volume_mesh": _("Run the meshing utilities in order"),
        "tip.check_case": _("Validate the case before running it"),
        "tip.update": _("Run whatever is out of date — meshing first if the mesh needs it"),
        "tip.calculate": _("Run the solver"),
        "tip.stop_write": _("Stop at the next write, leaving a complete result"),
        "tip.paraview": _("Open the result in ParaView"),
        "tip.export_csv": _("Write the residual history beside the case"),
        "tip.reset_view": _("Return the graphics window to the default view"),
        "tip.toggle_outline": _("Show or hide the outline"),
        "tip.toggle_task_page": _("Show or hide the task page"),
        "tip.toggle_console": _("Show or hide the console"),
        "tip.guide": _("Open the built-in guide"),
    }


def console_strings() -> dict[str, str]:
    """The console dock under the graphics window (§7.5, DEC-21)."""
    return {
        **log_pane_strings(),
        **messages_strings(),
        "console": _("Console"),
        "console_collapse": _("Collapse the console"),
        "console_expand": _("Expand the console"),
    }


def graphics_strings() -> dict[str, str]:
    """The graphics window's document tabs (DEC-21)."""
    return {
        "graphics_window": _("Graphics window"),
        "doc.start": _("Start"),
        "doc.geometry": _("Geometry"),
        "doc.mesh": _("Mesh"),
        "doc.residuals": _("Scaled Residuals"),
        "doc.boundary": _("Boundary Conditions"),
        "doc.files": _("Case Files"),
        "doc.vv": _("Turbulence and y+"),
        "doc.verify": _("Check Case"),
        "doc.library": _("Library"),
        "doc.guide": _("Guide"),
        "doc.setup": _("Setup"),
    }


def regions_strings() -> dict[str, str]:
    """The patch editor (FR-P4, E-C04)."""
    return {
        "regions_heading": _("Regions and patches"),
        "regions_intro": _(
            "The named surfaces of the mesh. A patch's type decides which "
            "boundary conditions are legal on it, so changing one changes the "
            "physics as well as the label."
        ),
        "no_mesh_yet": _("This case has no mesh yet. Generate one to see its patches."),
        "col_patch": _("Patch"),
        "col_type": _("Type"),
        "col_faces": _("Faces"),
        "col_groups": _("Groups"),
        "faces_count": _("{0}"),
        "apply_type": _("Change type"),
        "consequences_title": _("Changing {0} from {1} to {2}"),
        "fields_must_follow": _("These fields would need their condition on {0} changed:"),
        "fields_list": _("{0} — each to {1}"),
        "change_applied": _("{0} is now {1}."),
        "change_refused": _("{0}"),
        "no_change": _("{0} is already {1}."),
        "constrained_note": _("Set by the geometry — its condition is not a choice."),
        "cancel": _("Cancel"),
    }


def initial_strings() -> dict[str, str]:
    """The initial-conditions editor (FR-P3)."""
    return {
        "initial_heading": _("Initial conditions"),
        "initial_intro": _(
            "The values every cell starts from, before the first time step. "
            "Boundary values are set in Boundary conditions."
        ),
        "no_fields": _("This case has no initial-condition files."),
        "col_field": _("Field"),
        "col_internal": _("Internal field"),
        "col_dimensions": _("Units"),
        "nonuniform_note": _("Set per cell — edit this one in the Text tab."),
        "unreadable_field": _("This file could not be read. Open it in the Text tab."),
        "field_updated": _("{0} now starts at {1}."),
        "field_unchanged": _("{0} is unchanged."),
        "vector_hint": _("Three components, e.g. (1 0 0)."),
        "scalar_hint": _("A single number."),
        "source_note": _("From {0}"),
    }


def verify_strings() -> dict[str, str]:
    """The setup check (FR-C3, §7.3 step 8's spirit, before the run).

    The wording is careful about what a clean check does and does not mean. It
    means nothing contradicts itself; it does not mean the case is right. §6.9's
    whole argument is that a plausible wrong answer is the failure mode that
    matters, and a green tick that implied correctness would be exactly that.
    """
    return {
        "verify_heading": _("Check setup"),
        "verify_intro": _(
            "Looks for the mistakes that stop a case running or make it run as "
            "something other than what you meant."
        ),
        "verify_now": _("Check again"),
        "verify_no_case": _("Open a case to check it."),
        "verify_clean": _("Nothing inconsistent found."),
        "verify_clean_caveat": _(
            "This checks that the case does not contradict itself. It cannot "
            "tell you whether the physics is right for your problem — that is "
            "what Verification is for."
        ),
        "verify_blocked": _("{0} would stop this case running."),
        "verify_warnings": _("{0} worth looking at."),
        "verify_ready": _("This case can run."),
        "verify_not_ready": _("This case cannot run yet."),
        "col_severity": _("Severity"),
        "col_where": _("Where"),
        "col_problem": _("Problem"),
        "col_code": _("Code"),
        "at_line": _("{0}:{1}"),
        "sev_fatal": _("blocks the run"),
        "sev_error": _("blocks the run"),
        "sev_warning": _("worth checking"),
        "sev_info": _("note"),
        "open_the_file": _("Open the file"),
    }


def guide_strings() -> dict[str, str]:
    """The guide (FR-G1, FR-G2)."""
    return {
        "guide_heading": _("Guide"),
        "guide_search": _("Search the guide"),
        "guide_search_placeholder": _("Search"),
        "guide_contents": _("Contents"),
        "guide_no_results": _("Nothing found for {0}."),
        "guide_results": _("{0} results for {1}"),
        "guide_offline_note": _("The guide is part of the application and works offline."),
        "guide_missing": _("The guide could not be loaded."),
        "guide_result_row": _("{0} — {1}"),
    }


def library_strings() -> dict[str, str]:
    """The content library (§7.8, FR-L1 to FR-L5).

    The refusal messages are the important ones here. A user whose install was
    rejected has been told something alarming, and §9's E-L01 wording is
    deliberate: it says what happened and that nothing was installed, without
    speculating about who did it.
    """
    return {
        "library_heading": _("Library"),
        "library_intro": _(
            "Cases you can install and run straight away. Everything here is "
            "signed and checked before anything is written to your machine."
        ),
        "search": _("Search"),
        "search_placeholder": _("Search cases"),
        "all_categories": _("All categories"),
        "all_solvers": _("All solvers"),
        "install": _("Install"),
        "installing": _("Installing {0}…"),
        "installed": _("Installed {0} to {1}."),
        "open_installed": _("Open it"),
        "no_matches": _("Nothing matches that search."),
        "item_meta": _("{0}  ·  {1}"),
        "item_size": _("{0} KB"),
        "licence_line": _("{0}, from {1}"),
        # Version compatibility (FR-L1): marked, never hidden.
        "compat_yes": _("Works with {0}"),
        "compat_no": _("Built for a different OpenFOAM release"),
        "compat_unknown": _("Not tested against your OpenFOAM"),
        "compat_no_runtime": _("Install OpenFOAM to see whether this fits"),
        # Failures (§9).
        "catalog_unavailable": _("The library could not be opened: {0}"),
        "install_failed_title": _("{0} was not installed"),
        "install_failed": _("{0}  ({1})"),
        "verified_note": _("Verified · {0}"),
        # A composition, so a translator can reorder it (NFR-A5).
        "item_accessible": _("{0}. {1}"),
    }


def post_strings() -> dict[str, str]:
    """The Post view (§7.6, FR-V1, FR-V2, FR-V5, FR-P8)."""
    return {
        **log_pane_strings(),
        "post_heading": _("Post-processing"),
        "no_case_for_post": _("Open a case to work with its results."),
        "open_in_paraview": _("Open in ParaView"),
        "inspect_mesh": _("Inspect mesh"),
        "inspect_mesh_tip": _("Opens the mesh on its own, with edges shown and no results loaded."),
        "paraview_missing": _("ParaView was not found on this machine."),
        "paraview_missing_detail": _(
            "Post-processing opens results in ParaView. Setup can install it, or "
            "you can point at an existing copy."
        ),
        "paraview_found": _("ParaView {0}"),
        "paraview_opened": _("Opening {0} in ParaView…"),
        "utilities": _("Utilities"),
        "run_utility": _("Run"),
        "utility_argument": _("Patch or field name"),
        "running_utility": _("Running {0}…"),
        "utility_wrote": _("{0} wrote {1} files."),
        "utility_wrote_nothing": _("{0} finished and produced no new files."),
        "utility_failed": _("{0} failed. The log below says why."),
        "results_at": _("Latest result: {0}"),
        "no_results_yet": _("This case has no results yet. Run it first."),
    }


def view_placeholders() -> dict[str, tuple[str, str]]:
    """Title and explanatory body for each document that is not built yet.

    Each names the milestone that will fill it. §7.9's "no dead ends" applies to
    unfinished software as much as to error states: a blank pane tells the user
    nothing, while a sentence about what is coming tells them the app is not
    broken.
    """
    return {
        "setup": (
            _("Setup"),
            _(
                "The setup wizard — system check, runtime provisioning, ParaView "
                "and a verification run — arrives with runtime support."
            ),
        ),
    }
