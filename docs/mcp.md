# Connecting an AI agent (MCP)

BuildFOAM includes a [Model Context Protocol](https://modelcontextprotocol.io) server, so Claude — or any agent that speaks MCP — can set up and run OpenFOAM cases through the same services the window uses. Requirements and the reasoning are in PRD §6.10 (FR-AG) and DEC-24.

The server speaks over **stdio only**: the agent's client starts it as a child process. Nothing listens on a network port.

## What you grant

`--root <directory>` names a folder the agent may read and write. Repeat it for more than one. Every path the agent names is resolved and refused if it lands outside these folders, symlinks included. Without `--root` the agent is given your home folder — narrow it.

## Claude Code

```sh
claude mcp add buildfoam -- uv --directory D:/App/Project/buildFOAM run buildfoam-mcp --root D:/cases
```

## Claude Desktop

In `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "buildfoam": {
      "command": "uv",
      "args": ["--directory", "D:/App/Project/buildFOAM", "run", "buildfoam-mcp", "--root", "D:/cases"]
    }
  }
}
```

An installed copy can use the `buildfoam-mcp` script directly as `command`, or `python -m foamwb.mcp`.

## The tools

| Area | Tools |
|---|---|
| Runtime | `runtime_status` |
| Cases | `create_case`, `open_case`, `list_case_files`, `read_case_file`, `write_case_file`, `set_dictionary_entry`, `validate_case` |
| Fields and boundaries | `get_boundary_conditions`, `get_initial_fields`, `set_initial_field`, `restore_initial_conditions` |
| Geometry and mesh | `import_geometry`, `generate_mesh_dictionaries`, `get_mesh_quality` |
| Turbulence | `recommend_turbulence_model`, `apply_turbulence_model` |
| Running | `plan_run`, `start_run`, `get_run_status`, `stop_run`, `list_runs`, `get_residuals` |

A run is asynchronous: `start_run` returns a `run_id` at once and the agent polls `get_run_status` (with `wait_seconds` up to 60). `mode` is `calculate` (everything), `update` (only what is out of date) or `mesh`.

## What the agent cannot do that you could not

- **Edits are byte-faithful.** `set_dictionary_entry` changes one value and leaves every other byte, comment and directive as it was. `write_case_file` refuses text that does not parse, and writes only under `system/`, `constant/` and `0/`.
- **Stopping writes a result.** `stop_run` defaults to *Stop & Write*. `terminate` and `kill` need `confirm=true`, because they can leave a time directory ParaView cannot read.
- **Closing the session stops its runs.** No solver outlives the agent's connection.
- **Everything is logged.** Each call is an `mcp.tool.call` event in the application log, so a diagnostics bundle shows what the agent did.

## A case the window can pick up

The agent writes the same run history and uses the same monitoring as the Run page, so a case an agent has worked on opens in the window with its runs listed and its residuals plotted. The reverse holds as well.

## Runtimes

Runs use whichever runtime the application detects, exactly as the window does: a native macOS or Linux install, the WSL runtime the setup wizard provisions, or a **native Windows OpenFOAM build** (MinGW executables with MS-MPI, found through `WM_PROJECT_DIR` or under `C:/Simulation/OpenFOAM`). `runtime_status` reports which. With none, `start_run` answers **E-R10**; editing, meshing dictionaries, turbulence setup and validation still work.

On a native Windows build, a case folder whose path uses characters outside the system code page (for example Chinese on a Western-European system) cannot be opened by the solver; `start_run` then fails with **E-C18** naming the folder.
