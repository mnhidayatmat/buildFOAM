"""Structured logging (NFR-M4).

JSON lines with a **stable event vocabulary**, so that diagnostics bundles
(FR-A4) are machine-analysable rather than a wall of prose. The vocabulary is
the contract: event names are added, never renamed, because a support engineer's
``jq`` filter and the triage tooling both key on them.

Two rules the formatter enforces mechanically:

* One JSON object per line, never multi-line, so a truncated log is still
  parseable up to the truncation point.
* No exception tracebacks in the ``event`` field — a traceback goes in ``error``
  as a string, keeping the event name a closed vocabulary.

Privacy: this module writes to local application logs only. Nothing here is
transmitted. Telemetry (§10.4) is a separate, opt-in, off-by-default channel with
a narrower payload, and it must never simply forward these records — application
logs contain file paths, which telemetry is forbidden to carry.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

__all__ = ["Event", "JsonLinesFormatter", "configure", "get_logger", "log_event"]

LOGGER_ROOT: Final = "foamwb"


class Event(StrEnum):
    """The stable event vocabulary.

    Dotted, lowercase, ``domain.action[.outcome]``. Grouped by the service that
    emits them. Kept deliberately small at M0 and extended milestone by
    milestone; every addition is a vocabulary change and belongs in the same
    review as the code that emits it.
    """

    # Application lifecycle
    APP_START = "app.start"
    APP_STOP = "app.stop"
    APP_CRASH = "app.crash"
    APP_THEME = "app.theme"
    """The user changed the appearance setting (NFR-A4). Recorded because a
    screenshot in a support ticket shows the theme but never says whether the
    user chose it or the desktop did — and a contrast complaint is a different
    bug in each case."""

    # Runtime (RuntimeManager / RuntimeSession)
    RUNTIME_DETECT_BEGIN = "runtime.detect.begin"
    RUNTIME_DETECT_RESULT = "runtime.detect.result"
    RUNTIME_PROVISION_BEGIN = "runtime.provision.begin"
    RUNTIME_PROVISION_STAGE = "runtime.provision.stage"
    RUNTIME_PROVISION_RESULT = "runtime.provision.result"
    RUNTIME_VERIFY_RESULT = "runtime.verify.result"
    RUNTIME_REMOVE_RESULT = "runtime.remove.result"

    # Command execution through a RuntimeSession
    COMMAND_BEGIN = "command.begin"
    COMMAND_END = "command.end"

    # Case lifecycle (CaseService)
    CASE_OPEN = "case.open"
    CASE_CLASSIFY = "case.classify"
    CASE_WRITE = "case.write"
    CASE_VALIDATE_RESULT = "case.validate.result"

    # Run lifecycle (RunController)
    RUN_PLAN_BUILT = "run.plan.built"
    RUN_BEGIN = "run.begin"
    RUN_STAGE_BEGIN = "run.stage.begin"
    RUN_STAGE_END = "run.stage.end"
    RUN_STOP_REQUESTED = "run.stop.requested"
    RUN_END = "run.end"

    # Shell navigation. Useful in a diagnostics bundle: "what was on screen when
    # it failed?" is the first question triage asks.
    UI_VIEW_SHOWN = "ui.view.shown"

    # Anything that surfaced a §9 code to the user
    ERROR_RAISED = "error.raised"


#: Record attributes the stdlib puts on every LogRecord. Anything *not* in this
#: set is treated as a caller-supplied structured field and serialised.
_STANDARD_ATTRS: Final = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonLinesFormatter(logging.Formatter):
    """Render a record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key == "event":
                continue
            payload[key] = value

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        # default=str keeps a stray Path or enum from taking down the log
        # writer; a lost type annotation beats a lost diagnostic.
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure(
    log_directory: Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Install the JSON-lines handler on the package logger.

    Rotation is bounded so that a runaway solver log cannot fill the user's disk
    through the *application* log — E-S07 is about the case directory, and this
    must not become a second way to hit it. The cap also keeps a diagnostics
    bundle under the FR-A4 10 MB budget.

    Idempotent: calling it twice replaces the handlers rather than doubling every
    line, because the setup wizard may reconfigure logging mid-session.
    """
    log_directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_ROOT)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handler = logging.handlers.RotatingFileHandler(
        log_directory / f"{LOGGER_ROOT}.jsonl",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(JsonLinesFormatter())
    logger.addHandler(handler)

    if os.environ.get("FOAMWB_LOG_STDERR"):
        stream = logging.StreamHandler()
        stream.setFormatter(JsonLinesFormatter())
        logger.addHandler(stream)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the package logger."""
    return logging.getLogger(LOGGER_ROOT if name is None else f"{LOGGER_ROOT}.{name}")


def log_event(
    logger: logging.Logger,
    event: Event,
    /,
    *,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Emit one structured record.

    ``event`` is an :class:`Event` member rather than a string so that a typo is
    a static error instead of a silently unqueryable log line.
    """
    if not isinstance(event, Event):
        raise TypeError(
            f"event must be an Event member, got {type(event).__name__}. "
            "The vocabulary is closed by design (NFR-M4)."
        )
    logger.log(level, event.value, extra={"event": event.value, **fields}, exc_info=exc_info)
