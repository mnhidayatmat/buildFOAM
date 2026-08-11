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

__all__ = ["nav_labels", "shell_strings", "view_placeholders"]

_CONTEXT = "Shell"


def _(source: str) -> str:
    return QCoreApplication.translate(_CONTEXT, source)


def nav_labels() -> dict[str, str]:
    """Display names for the nav rail, keyed by :data:`~foamwb.ui.navrail.NAV_ITEMS` key."""
    return {
        "hub": _("Hub"),
        "cases": _("Cases"),
        "setup": _("Setup"),
        "run": _("Run"),
        "post": _("Post"),
        "vv": _("V&&V"),  # && escapes the mnemonic ampersand in Qt button text
        "library": _("Library"),
        "guide": _("Guide"),
    }


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
        # Compositions, kept translatable so their parts can be reordered.
        "nav_item": _("{0}  {1}"),
        "nav_tooltip": _("{0}  ({1})"),
    }


def run_strings() -> dict[str, str]:
    """The Run view (§7.5).

    Stop actions name their consequence rather than only their mechanism: "Stop
    Now" means nothing to P1, while "may leave an incomplete result" is the fact
    that decides whether they want it (NFR-A6).
    """
    return {
        "no_plan": _("No run planned yet."),
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
    }


def preprocessor_strings() -> dict[str, str]:
    """The Preprocessor view (§7.4)."""
    return {
        "case_files": _("Case files"),
        "form_tab": _("Form"),
        "form_tab_unavailable": _("Form (not available)"),
        "text_tab": _("Text"),
        "bc_tab": _("Boundary conditions"),
        "raw_text": _("Dictionary text"),
        "validation": _("Validation"),
        "no_case_open_hint": _("Open a case to edit its dictionaries."),
        "no_findings": _("No problems found."),
        "findings_summary": _("{0} to look at, {1} of which will stop a run."),
        "finding": _("{0}  {1} — {2}"),
        "finding_at_line": _("{0}, line {1}"),
        # Text editor
        "save": _("Save"),
        "revert": _("Revert"),
        "no_changes": _("No changes."),
        "unsaved_changes": _("Unsaved changes."),
        "save_blocked": _("Not saved — line {0}: {1}"),
        "not_in_form": _("Also in this file, editable in the Text tab: {0}"),
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


def view_placeholders() -> dict[str, tuple[str, str]]:
    """Title and explanatory body for each view that is not built yet.

    Each names the milestone that will fill it. §7.9's "no dead ends" applies to
    unfinished software as much as to error states: a blank pane tells the user
    nothing, while a sentence about what is coming tells them the app is not
    broken.
    """
    return {
        "cases": (
            _("Cases"),
            _(
                "The case browser and dictionary editors arrive with the "
                "preprocessor. For now, open a case from the Hub."
            ),
        ),
        "setup": (
            _("Setup"),
            _(
                "The setup wizard — system check, runtime provisioning, ParaView "
                "and a verification run — arrives with runtime support."
            ),
        ),
        "run": (
            _("Run"),
            _(
                "The run view shows the plan as a stage strip, streams the solver "
                "log, and plots residuals as the solution converges."
            ),
        ),
        "post": (
            _("Post"),
            _(
                "Postprocessing launches ParaView on the current case, runs the "
                "standard post utilities, and generates the run report."
            ),
        ),
        "vv": (
            _("Verification and validation"),
            _(
                "The turbulence advisor with its y+ audit ships in v1.0. The grid "
                "convergence study and comparison against experimental data "
                "follow in v1.1."
            ),
        ),
        "library": (
            _("Library"),
            _("The content library offers tutorials and example cases to install."),
        ),
        "guide": (
            _("Guide"),
            _("The built-in guide is searchable and works entirely offline."),
        ),
    }
