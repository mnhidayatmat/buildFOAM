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
        # Compositions, kept translatable so their parts can be reordered.
        "nav_item": _("{0}  {1}"),
        "nav_tooltip": _("{0}  ({1})"),
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
