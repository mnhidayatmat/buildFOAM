"""JSON-RPC 2.0 over stdio, and the MCP lifecycle (DEC-24).

Hand-written rather than taken from the MCP SDK. The SDK brings an HTTP stack,
an async runtime and a validation library — tens of megabytes against NFR-P8's
installer budget — to serve a transport that is one JSON object per line on
stdin and stdout. The stdio transport is small enough to state completely, and
this module is that statement.

**No socket, ever.** The server speaks only over the pipes of the process that
launched it, so §10.1's "no listening sockets" and NFR-R5's offline guarantee
both still hold, and ``tools/check_offline.py`` keeps them holding. An agent
reaches the workbench only by being the program that started it.

**stdout belongs to the protocol.** One stray ``print`` corrupts the stream and
the client disconnects without saying why, so nothing here writes to stdout
except :meth:`Server._send`, and logging goes to the log file (and to stderr
when asked).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import IO, Any

from foamwb.logs import Event, get_logger, log_event

__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "RpcError",
    "Server",
    "Tool",
    "ToolError",
    "ToolResult",
]

_log = get_logger("mcp.protocol")

#: Newest first. A client asking for one of these gets it back; a client asking
#: for anything else is offered the newest, and decides for itself whether it
#: can continue — which is how the specification says negotiation works.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """A protocol-level failure, answered as a JSON-RPC ``error``."""

    def __init__(self, code: int, message: str, data: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class ToolError(Exception):
    """A tool that ran and could not do what was asked.

    Answered as a *result* with ``isError`` rather than as a protocol error, as
    MCP requires: the agent should read the reason and try something else, and
    a protocol error tells it only that the call was malformed.

    ``code`` is a §9 identifier where one applies, so an agent's transcript
    carries the same code a person would quote to support.
    """

    def __init__(self, message: str, *, code: str | None = None, guide: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.guide = guide


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool hands back: a structured payload and a sentence about it."""

    data: dict[str, Any]
    summary: str = ""


@dataclass(frozen=True, slots=True)
class Tool:
    """One tool, declared as data — the ribbon's pattern (``ui/ribbon.py``).

    The declaration is what ``tools/list`` sends, so the description an agent
    reads and the handler that runs cannot come from two places.
    """

    name: str
    title: str
    description: str
    handler: Callable[[dict[str, Any]], ToolResult]
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
                # Every tool acts on this machine's files and runtime, never on
                # the network (§10.1).
                "openWorldHint": False,
            },
        }


class Server:
    """Dispatches JSON-RPC messages to the MCP methods and the tools."""

    def __init__(
        self,
        tools: Iterable[Tool],
        *,
        name: str,
        version: str,
        instructions: str = "",
    ) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._name = name
        self._version = version
        self._instructions = instructions
        self._out: IO[bytes] | None = None
        self.protocol_version: str | None = None

    @property
    def tools(self) -> dict[str, Tool]:
        return dict(self._tools)

    # -- transport ---------------------------------------------------------

    def serve(self, stdin: IO[bytes] | None = None, stdout: IO[bytes] | None = None) -> None:
        """Read messages until end of input, answering each as it arrives."""
        source = stdin or sys.stdin.buffer
        self._out = stdout or sys.stdout.buffer
        for raw in source:
            line = raw.strip()
            if not line:
                continue
            reply = self.handle_line(line)
            if reply is not None:
                self._send(reply)

    def _send(self, message: object) -> None:
        assert self._out is not None
        # ensure_ascii keeps the stream 7-bit, so a Windows console code page can
        # never be the reason a case path with a non-ASCII name arrives mangled.
        self._out.write(json.dumps(message, ensure_ascii=True).encode("ascii") + b"\n")
        self._out.flush()

    def handle_line(self, line: bytes | str) -> object | None:
        """Answer one line of input. ``None`` when nothing is owed."""
        try:
            message = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            return _error(None, RpcError(PARSE_ERROR, f"Not valid JSON: {exc}"))

        if isinstance(message, list):
            # Batches were removed from the protocol in 2025-06-18 but are
            # harmless to accept, and an older client may still send one.
            if not message:
                return _error(None, RpcError(INVALID_REQUEST, "Empty batch"))
            replies = [r for r in (self.handle_message(m) for m in message) if r is not None]
            return replies or None
        return self.handle_message(message)

    def handle_message(self, message: object) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, RpcError(INVALID_REQUEST, "Not a JSON-RPC 2.0 message"))

        method = message.get("method")
        request_id = message.get("id")
        is_notification = "id" not in message

        if not isinstance(method, str):
            # A response to something we sent. The server sends no requests, so
            # there is nothing to match it to.
            return None

        params = message.get("params") or {}
        try:
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            result = self._dispatch(method, params)
        except RpcError as exc:
            return None if is_notification else _error(request_id, exc)
        except Exception as exc:
            log_event(_log, Event.ERROR_RAISED, where=f"mcp.{method}", error=str(exc))
            if is_notification:
                return None
            return _error(request_id, RpcError(INTERNAL_ERROR, f"Internal error: {exc}"))

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    # -- methods -----------------------------------------------------------

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.describe() for tool in self._tools.values()]}
        if method == "tools/call":
            return self._call_tool(params)
        if method.startswith("notifications/"):
            # initialized, cancelled, roots/list_changed: nothing to do. A call
            # in flight cannot be cancelled mid-handler; a long run is stopped
            # with the stop_run tool, which is the graceful route anyway.
            return {}
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        self.protocol_version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        client = params.get("clientInfo") or {}
        log_event(
            _log,
            Event.MCP_INITIALIZE,
            client=client.get("name"),
            client_version=client.get("version"),
            protocol=self.protocol_version,
        )
        result: dict[str, Any] = {
            "protocolVersion": self.protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self._name, "version": self._version},
        }
        if self._instructions:
            result["instructions"] = self._instructions
        return result

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")

        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")

        log_event(_log, Event.MCP_TOOL_CALL, tool=tool.name)
        try:
            _check_arguments(tool, arguments)
            outcome = tool.handler(arguments)
        except ToolError as exc:
            log_event(_log, Event.MCP_TOOL_ERROR, tool=tool.name, code=exc.code, error=exc.message)
            error = {"message": exc.message, "code": exc.code, "guide": exc.guide}
            text = f"{exc.code}: {exc.message}" if exc.code else exc.message
            return {
                "content": [{"type": "text", "text": text}],
                "structuredContent": {"error": error},
                "isError": True,
            }

        body = json.dumps(outcome.data, indent=2, ensure_ascii=False, default=str)
        text = f"{outcome.summary}\n\n{body}" if outcome.summary else body
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": json.loads(json.dumps(outcome.data, default=str)),
            "isError": False,
        }


_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _check_arguments(tool: Tool, arguments: dict[str, Any]) -> None:
    """Reject arguments the schema does not allow, naming the one at fault.

    A reported ToolError rather than a protocol error, so the agent sees which
    argument to fix. Only the schema features the tools actually use are
    checked: required keys, unknown keys, primitive types and enums.
    """
    missing = [key for key in tool.required if key not in arguments]
    if missing:
        raise ToolError(f"Missing required argument(s): {', '.join(missing)}")

    unknown = sorted(set(arguments) - set(tool.properties))
    if unknown:
        raise ToolError(
            f"Unknown argument(s): {', '.join(unknown)}. "
            f"Accepted: {', '.join(sorted(tool.properties)) or 'none'}."
        )

    for key, value in arguments.items():
        schema = tool.properties[key]
        expected = schema.get("type")
        python_type = _JSON_TYPES.get(expected) if isinstance(expected, str) else None
        # bool is an int in Python and must not satisfy "integer" or "number".
        if python_type is not None and (
            not isinstance(value, python_type)
            or (isinstance(value, bool) and expected in {"integer", "number"})
        ):
            raise ToolError(f"Argument {key!r} must be of type {expected}.")
        if "enum" in schema and value not in schema["enum"]:
            raise ToolError(
                f"Argument {key!r} must be one of: {', '.join(map(str, schema['enum']))}."
            )


def _error(request_id: object, exc: RpcError) -> dict[str, Any]:
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.data is not None:
        error["data"] = exc.data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}
