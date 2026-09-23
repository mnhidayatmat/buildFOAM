"""Entry point for the agent interface (DEC-24).

Started by the MCP client, never by the user directly: the client launches this
as a child process and talks to it over its stdin and stdout. A client
configuration therefore names the command and the directories the agent may
use, e.g.::

    {"command": "<app>-mcp", "args": ["--root", "D:/cases"]}

``--root`` may be given more than once. Without it the agent may use the user's
home directory — a default a person chose by not narrowing it, and one this
module writes to the log so the choice is visible afterwards.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from foamwb import __version__
from foamwb.branding import APP_DISPLAY_NAME, APP_ID
from foamwb.logs import Event, configure, get_logger, log_event
from foamwb.mcp.protocol import Server
from foamwb.mcp.tools import INSTRUCTIONS, build_tools
from foamwb.mcp.workbench import Workbench
from foamwb.paths import log_dir

__all__ = ["build_server", "main"]


def build_server(workbench: Workbench) -> Server:
    return Server(
        build_tools(workbench),
        name=APP_ID,
        version=__version__,
        instructions=INSTRUCTIONS,
    )


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=f"{APP_ID}-mcp",
        description=f"Let an AI agent set up and run OpenFOAM cases through {APP_DISPLAY_NAME}.",
    )
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=[],
        help="A directory the agent may read and write. Repeatable. Default: your home folder.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _arguments(argv)
    configure(log_dir(), level=logging.INFO)
    log = get_logger("mcp.server")

    roots = options.root or [Path.home()]
    workbench = Workbench(roots)
    log_event(
        log,
        Event.MCP_START,
        version=__version__,
        roots=[str(root) for root in workbench.roots],
    )
    try:
        build_server(workbench).serve()
    except KeyboardInterrupt:
        pass
    finally:
        # The pipe closing is the agent's equivalent of the window closing: no
        # solver may outlive it (FR-S10).
        workbench.shutdown()
        log_event(log, Event.MCP_STOP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
