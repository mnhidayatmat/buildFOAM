"""The agent interface: a Model Context Protocol server over stdio (DEC-24).

An AI agent — Claude, or any client that speaks MCP — sets up and runs a case
through the same services the window uses. It is a *third view* of the service
layer beside the window and the test suite, and it is Qt-free for the same
reason they are: it runs headless.

Layout:

* :mod:`foamwb.mcp.protocol` — JSON-RPC 2.0 framing and the MCP lifecycle. Knows
  nothing about OpenFOAM.
* :mod:`foamwb.mcp.workbench` — the state an agent's session holds: the
  permitted directories, the runtime session, the runs in flight.
* :mod:`foamwb.mcp.tools` — the tools, declared as data, each a thin call into
  a service.
* :mod:`foamwb.mcp.server` — the entry point.
"""
