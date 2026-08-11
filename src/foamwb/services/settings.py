"""User preferences, persisted to ``config.json`` (§5.3, NFR-A4).

Qt-free like every service, so the preference is a plain value the presentation
layer reads rather than something only a running application can answer. That is
what lets the theme-resolution logic be tested without a display.

**Nothing here may stop the application starting.** A preferences file is written
by an earlier version, edited by hand, truncated by a full disk or synced half-way
by a roaming profile — and none of those are reasons a user should be unable to
open their cases. :meth:`SettingsService.load` therefore never raises: an
unreadable or nonsensical file yields the defaults, and the bad file is left
alone rather than deleted, so the next release can still make sense of it.

Unknown keys are preserved for the same reason in reverse. A user who runs a
newer build, then goes back to this one, must not silently lose the settings the
newer build wrote — this one does not understand them, but it can carry them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from foamwb.logs import get_logger
from foamwb.paths import config_file

__all__ = ["DEFAULT_THEME", "Settings", "SettingsService", "ThemeChoice"]

_log = get_logger("settings")

#: The key theme lives under in ``config.json``.
_THEME_KEY = "theme"


class ThemeChoice(StrEnum):
    """What the user asked for, which is not the same as what gets painted.

    ``SYSTEM`` is a *choice*, not a resolved palette: it means "whatever the
    desktop is doing", and the answer can change while the application is
    running. Collapsing it to light or dark at the point the preference is stored
    would lose the instruction and freeze the window at whatever the desktop
    happened to be when the user chose.
    """

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


#: NFR-A4 describes following the OS by default. This build ships **Light** as
#: the default instead, so a first run looks the same on every machine and in
#: every screenshot in the teaching material. Changing this one name is the whole
#: change needed to go back to :data:`ThemeChoice.SYSTEM`.
DEFAULT_THEME = ThemeChoice.LIGHT


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the user has chosen. One field today; the shape is the point."""

    theme: ThemeChoice = DEFAULT_THEME


def _coerce_theme(raw: object) -> ThemeChoice:
    """Read a stored theme, falling back rather than raising.

    A value this build does not recognise is a value a *newer* build wrote. The
    default is the right answer for it, and refusing to start is not.
    """
    if isinstance(raw, str):
        try:
            return ThemeChoice(raw)
        except ValueError:
            _log.warning("Ignoring unrecognised theme %r in the preferences file", raw)
    return DEFAULT_THEME


class SettingsService:
    """Reads and writes ``config.json``.

    The path is resolved lazily rather than in ``__init__``, because
    :func:`~foamwb.paths.config_file` refuses to answer on an unsupported
    platform — and constructing a settings service is not the moment to find
    that out. Tests pass an explicit path and never touch the user's own file.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path | None:
        """Where settings are stored, or ``None`` if the platform cannot say."""
        if self._path is not None:
            return self._path
        try:
            return config_file()
        except RuntimeError:
            return None

    # -- reading -----------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        """The raw document, or an empty one. Never raises."""
        path = self.path
        if path is None:
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # The ordinary state of a first run, not a problem worth logging.
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            _log.warning("Could not read the preferences file at %s: %s", path, exc)
            return {}
        # A JSON document whose root is a list or a number is not a settings
        # file. Treated as absent rather than picked apart for anything usable.
        return raw if isinstance(raw, dict) else {}

    def load(self) -> Settings:
        """Current preferences, with defaults for anything missing or unreadable."""
        return Settings(theme=_coerce_theme(self._read().get(_THEME_KEY)))

    # -- writing -----------------------------------------------------------

    def save(self, settings: Settings) -> bool:
        """Persist ``settings``, returning whether it reached disk.

        Failure is reported rather than raised. A preference that could not be
        saved is a preference that will not survive a restart, which is worth a
        log line — but it is not worth interrupting whatever the user was doing,
        and the setting is already applied in the running window either way.
        """
        path = self.path
        if path is None:
            return False

        document = self._read()
        document[_THEME_KEY] = settings.theme.value

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomically(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
        except OSError as exc:
            _log.warning("Could not save preferences to %s: %s", path, exc)
            return False
        return True

    def set_theme(self, choice: ThemeChoice) -> Settings:
        """Store a new theme choice and return the settings as they now stand."""
        settings = Settings(theme=choice)
        self.save(settings)
        return settings


def _write_atomically(target: Path, text: str) -> None:
    """Write via a temporary file and rename (NFR-R2).

    The same discipline :mod:`foamwb.services.case` uses for case metadata: a
    crash mid-write must leave the old file, never a truncated one. A settings
    file that half-wrote would be exactly the corrupt input :meth:`load` has to
    tolerate, and not producing it is cheaper than surviving it.
    """
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
