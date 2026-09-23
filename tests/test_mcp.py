"""The agent interface (DEC-24): protocol, confinement, and a run end to end.

Driven through :meth:`Server.handle_message` — the same entry the stdio loop
uses — so what is tested is what a client receives, not what a handler
returned before serialisation. Runs execute against :class:`FakeSession`, and
the one subprocess test proves the real entry point speaks only JSON on stdout
and never imports Qt.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fakes import FakeSession, ScriptedCommand
from foamwb.branding import APP_ID, CASE_METADATA_DIR, CASE_METADATA_FILE
from foamwb.mcp.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    Server,
    Tool,
    ToolResult,
)
from foamwb.mcp.server import build_server
from foamwb.mcp.workbench import Workbench
from foamwb.services.run.history import latest_written_time, next_run_id

# -- helpers --------------------------------------------------------------------


class Client:
    """A minimal MCP client over :meth:`Server.handle_message`."""

    def __init__(self, server: Server) -> None:
        self.server = server
        self._id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        message = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            message["params"] = params
        reply = self.server.handle_message(message)
        assert reply is not None
        # Round-trip through JSON, as the stream does, so a value that would not
        # serialise fails here rather than in a client.
        return json.loads(json.dumps(reply))

    def call(self, tool: str, **arguments: object) -> dict:
        reply = self.request("tools/call", {"name": tool, "arguments": arguments})
        assert "result" in reply, reply
        return reply["result"]

    def ok(self, tool: str, **arguments: object) -> dict:
        result = self.call(tool, **arguments)
        assert not result["isError"], result["content"][0]["text"]
        return result["structuredContent"]

    def refused(self, tool: str, **arguments: object) -> str:
        result = self.call(tool, **arguments)
        assert result["isError"], result
        return result["content"][0]["text"]


@pytest.fixture
def session() -> FakeSession:
    return FakeSession(
        {
            "checkMesh": ScriptedCommand(lines=["Mesh OK."]),
            "simpleFoam": ScriptedCommand(lines=["Time = 1", "Time = 2", "End"]),
        }
    )


@pytest.fixture
def client(tmp_path: Path, session: FakeSession) -> Client:
    workbench = Workbench([tmp_path / "work"], session=session)
    (tmp_path / "work").mkdir()
    return Client(build_server(workbench))


@pytest.fixture
def case(client: Client) -> str:
    return client.ok("create_case", name="duct")["case"]


# -- protocol -------------------------------------------------------------------


class TestLifecycle:
    def test_initialize_echoes_a_supported_version(self, client: Client) -> None:
        for version in SUPPORTED_PROTOCOL_VERSIONS:
            reply = client.request("initialize", {"protocolVersion": version})
            assert reply["result"]["protocolVersion"] == version

    def test_initialize_offers_the_newest_for_an_unknown_version(self, client: Client) -> None:
        reply = client.request("initialize", {"protocolVersion": "1999-01-01"})
        assert reply["result"]["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]

    def test_initialize_declares_tools_and_names_the_server(self, client: Client) -> None:
        result = client.request("initialize", {"protocolVersion": "2025-06-18"})["result"]
        assert result["capabilities"] == {"tools": {"listChanged": False}}
        assert result["serverInfo"]["name"] == APP_ID
        assert "start_run" in result["instructions"]

    def test_ping(self, client: Client) -> None:
        assert client.request("ping")["result"] == {}

    def test_notifications_are_never_answered(self, client: Client) -> None:
        for method in ("notifications/initialized", "notifications/cancelled", "no/such"):
            assert client.server.handle_message({"jsonrpc": "2.0", "method": method}) is None

    def test_unknown_method(self, client: Client) -> None:
        assert client.request("resources/list")["error"]["code"] == METHOD_NOT_FOUND

    def test_malformed_input(self, client: Client) -> None:
        assert client.server.handle_line(b"{not json")["error"]["code"] == PARSE_ERROR
        assert client.server.handle_line(b'{"id": 1}')["error"]["code"] == INVALID_REQUEST
        assert client.server.handle_line(b"[]")["error"]["code"] == INVALID_REQUEST

    def test_a_batch_is_answered_as_a_batch(self, client: Client) -> None:
        line = json.dumps(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ]
        )
        replies = client.server.handle_line(line)
        assert [r["id"] for r in replies] == [1, 2]

    def test_serve_writes_one_json_object_per_line(self, client: Client) -> None:
        stdin = io.BytesIO(
            b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n'
            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        )
        stdout = io.BytesIO()
        client.server.serve(stdin, stdout)
        lines = stdout.getvalue().splitlines()
        assert [json.loads(line)["id"] for line in lines] == [1, 2]


class TestToolDeclarations:
    def test_every_tool_is_well_formed(self, client: Client) -> None:
        tools = client.request("tools/list")["result"]["tools"]
        names = [tool["name"] for tool in tools]
        assert len(names) == len(set(names))
        for tool in tools:
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert set(schema["required"]) <= set(schema["properties"]), tool["name"]
            assert tool["description"]
            annotations = tool["annotations"]
            assert annotations["openWorldHint"] is False
            # A tool cannot both only read and destroy.
            assert not (annotations["readOnlyHint"] and annotations["destructiveHint"])

    def test_writing_tools_are_not_marked_read_only(self, client: Client) -> None:
        tools = {t["name"]: t for t in client.request("tools/list")["result"]["tools"]}
        for name in ("write_case_file", "set_dictionary_entry", "start_run", "stop_run"):
            assert tools[name]["annotations"]["readOnlyHint"] is False

    def test_unknown_tool_is_a_protocol_error(self, client: Client) -> None:
        reply = client.request("tools/call", {"name": "format_disk", "arguments": {}})
        assert reply["error"]["code"] == INVALID_PARAMS

    def test_arguments_are_checked_against_the_schema(self, client: Client) -> None:
        assert "Missing required" in client.refused("open_case")
        assert "Unknown argument" in client.refused("open_case", case="x", colour="red")
        assert "type string" in client.refused("open_case", case=3)
        assert "one of" in client.refused("plan_run", case="x", mode="fast")

    def test_a_boolean_is_not_an_integer(self, client: Client) -> None:
        assert "type integer" in client.refused("get_residuals", case="duct", history_points=True)

    def test_a_handler_error_becomes_an_internal_error_not_a_crash(self) -> None:
        def boom(_args: dict) -> ToolResult:
            raise RuntimeError("kaboom")

        server = Server([Tool("boom", "Boom", "Raises.", boom)], name="t", version="0")
        reply = server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "boom"}}
        )
        assert reply["error"]["code"] == -32603


# -- confinement ----------------------------------------------------------------


class TestConfinement:
    def test_a_path_outside_the_roots_is_refused(self, client: Client, tmp_path: Path) -> None:
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        assert "outside the directories" in client.refused("open_case", case=str(outside))

    def test_dot_dot_cannot_climb_out(self, client: Client) -> None:
        assert "outside the directories" in client.refused("open_case", case="../..")

    def test_a_file_outside_the_case_is_refused(self, client: Client, case: str) -> None:
        text = client.refused("read_case_file", case=case, file="../../secret.txt")
        assert "outside the case" in text

    def test_relative_paths_land_in_the_first_root(self, client: Client, tmp_path: Path) -> None:
        made = client.ok("create_case", name="pipe")
        assert Path(made["case"]) == (tmp_path / "work" / "pipe").resolve()

    def test_a_symlink_is_judged_by_where_it_leads(self, client: Client, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere"
        target.mkdir()
        link = tmp_path / "work" / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks need privileges on this platform")
        assert "outside the directories" in client.refused("open_case", case=str(link))

    def test_a_workbench_needs_a_root(self) -> None:
        with pytest.raises(ValueError):
            Workbench([])


# -- editing ---------------------------------------------------------------------


class TestEditing:
    def test_create_then_open(self, client: Client, case: str) -> None:
        summary = client.ok("open_case", case=case)
        assert summary["application"] == "simpleFoam"
        assert summary["has_mesh"] is False
        assert "system/controlDict" in client.ok("list_case_files", case=case)["files"]

    def test_create_refuses_to_overwrite(self, client: Client, case: str) -> None:
        assert "E-C13" in client.refused("create_case", name="duct")

    def test_set_entry_changes_one_line_only(self, client: Client, case: str) -> None:
        control = Path(case) / "system" / "controlDict"
        before = control.read_text(encoding="utf-8").splitlines()

        changed = client.ok(
            "set_dictionary_entry", case=case, file="system/controlDict", entries={"endTime": 250}
        )["changed"]

        after = control.read_text(encoding="utf-8").splitlines()
        assert changed["endTime"]["to"] == "250"
        assert len(before) == len(after)
        assert sum(1 for a, b in zip(before, after, strict=True) if a != b) == 1

    def test_set_entry_does_not_create_entries(self, client: Client, case: str) -> None:
        text = client.refused(
            "set_dictionary_entry", case=case, file="system/controlDict", entries={"nope": "1"}
        )
        assert "write_case_file" in text

    def test_set_entry_refuses_a_structural_value(self, client: Client, case: str) -> None:
        client.refused(
            "set_dictionary_entry",
            case=case,
            file="system/controlDict",
            entries={"endTime": "1; application icoFoam"},
        )

    def test_an_edit_is_not_mistaken_for_an_outside_change(self, client: Client, case: str) -> None:
        client.ok(
            "set_dictionary_entry", case=case, file="system/controlDict", entries={"endTime": 5}
        )
        assert client.ok("open_case", case=case)["classification"] != "modified"

    def test_write_refuses_text_that_does_not_parse(self, client: Client, case: str) -> None:
        text = client.refused(
            "write_case_file", case=case, file="constant/transportProperties", content="nu {"
        )
        assert text.startswith("E-C02")
        assert not (Path(case) / "constant" / "transportProperties").exists()

    def test_write_refuses_results_and_metadata(self, client: Client, case: str) -> None:
        for file in ("postProcessing/x", f"{CASE_METADATA_DIR}/{CASE_METADATA_FILE}", "100/U"):
            assert "not part of the case definition" in client.refused(
                "write_case_file", case=case, file=file, content="a 1;"
            )

    def test_write_creates_a_dictionary(self, client: Client, case: str) -> None:
        result = client.ok(
            "write_case_file",
            case=case,
            file="constant/transportProperties",
            content="transportModel Newtonian;\nnu 1e-05;\n",
        )
        assert result["created"] is True
        read = client.ok("read_case_file", case=case, file="constant/transportProperties")
        assert "nu 1e-05;" in read["content"]

    def test_initial_field(self, client: Client, case: str) -> None:
        assert client.ok("set_initial_field", case=case, field="U", value="(10 0 0)")["changed"]
        fields = {f["name"]: f for f in client.ok("get_initial_fields", case=case)["fields"]}
        assert fields["U"]["internal_field"] == "uniform (10 0 0)"
        assert "has no initial field" in client.refused(
            "set_initial_field", case=case, field="T", value="300"
        )

    def test_boundary_conditions_without_a_mesh(self, client: Client, case: str) -> None:
        matrix = client.ok("get_boundary_conditions", case=case)
        assert matrix["meshed"] is False

    def test_turbulence_shortlist_has_trade_offs(self, client: Client) -> None:
        shortlist = client.ok("recommend_turbulence_model", separation=True)["recommendations"]
        assert len(shortlist) >= 2
        assert all(entry["wall_treatments"] for entry in shortlist)

    def test_unknown_turbulence_model(self, client: Client, case: str) -> None:
        assert "Unknown turbulence model" in client.refused(
            "apply_turbulence_model", case=case, model="magic", wall_treatment="x"
        )


# -- running ---------------------------------------------------------------------


class TestRunning:
    def test_plan_is_shown_before_it_runs(self, client: Client, case: str, session) -> None:
        stages = client.ok("plan_run", case=case)["stages"]
        assert [s["stage"] for s in stages] == ["checkMesh", "solve"]
        assert session.commands == []

    def test_a_run_end_to_end(self, client: Client, case: str, session) -> None:
        started = client.ok("start_run", case=case, ignore_validation=True)
        assert started["started"] is True
        run_id = started["run_id"]

        status = client.ok("get_run_status", run_id=run_id, wait_seconds=30)
        assert status["running"] is False
        assert status["outcome"] == "succeeded"
        assert "End" in status["tail"]
        assert session.ran("simpleFoam")

        # The history the window reads (FR-S7), written by the same code.
        metadata = json.loads(
            (Path(case) / CASE_METADATA_DIR / CASE_METADATA_FILE).read_text(encoding="utf-8")
        )
        assert [run["id"] for run in metadata["runs"]] == [run_id]
        assert (Path(case) / CASE_METADATA_DIR / "logs" / run_id / "log.solve").is_file()
        assert client.ok("list_runs")["runs"][0]["outcome"] == "succeeded"

    def test_monitoring_is_installed_at_launch(self, client: Client, case: str) -> None:
        run_id = client.ok("start_run", case=case, ignore_validation=True)["run_id"]
        client.ok("get_run_status", run_id=run_id, wait_seconds=30)
        control = (Path(case) / "system" / "controlDict").read_text(encoding="utf-8")
        assert "solverInfo" in control

    def test_blocking_findings_stop_a_run(self, client: Client, case: str) -> None:
        # The fresh case has no mesh; whether that blocks depends on validation,
        # so construct something that certainly does: an unparseable field.
        (Path(case) / "0" / "U").write_text("FoamFile {", encoding="utf-8")
        assert "blocking" in client.refused("start_run", case=case)

    def test_a_failed_stage_carries_its_code(self, client: Client, case: str, session) -> None:
        session.script("simpleFoam", ScriptedCommand(lines=["--> FOAM FATAL ERROR"], exit_code=1))
        run_id = client.ok("start_run", case=case, ignore_validation=True)["run_id"]
        status = client.ok("get_run_status", run_id=run_id, wait_seconds=30)
        assert status["outcome"] == "failed"
        failed = next(s for s in status["stage_results"] if s["state"] == "failed")
        assert failed["reason"]["id"].startswith("E-S")

    def test_signals_need_confirmation(self, client: Client, case: str) -> None:
        run_id = client.ok("start_run", case=case, ignore_validation=True)["run_id"]
        assert "confirm=true" in client.refused("stop_run", run_id=run_id, mode="kill")
        client.ok("get_run_status", run_id=run_id, wait_seconds=30)
        assert client.ok("stop_run", run_id=run_id)["delivered"] is False

    def test_an_unknown_run(self, client: Client) -> None:
        assert "No run r-0099" in client.refused("get_run_status", run_id="r-0099")

    def test_residuals_before_any_output(self, client: Client, case: str) -> None:
        assert "no postProcessing output" in client.refused("get_residuals", case=case)

    def test_residuals_are_read_from_post_processing(self, client: Client, case: str) -> None:
        dat = Path(case) / "postProcessing" / "solverInfo" / "0" / "solverInfo.dat"
        dat.parent.mkdir(parents=True)
        dat.write_text(
            "# Solver information\n# Time\tUx_initial\tp_initial\n1\t0.5\t0.9\n2\t0.1\t0.3\n",
            encoding="utf-8",
        )
        sources = client.ok("get_residuals", case=case, history_points=2)["sources"]
        series = next(iter(sources.values()))["series"]
        assert series["p_initial"]["latest"] == pytest.approx(0.3)
        assert series["p_initial"]["values"] == [0.9, 0.3]

    def test_no_runtime_is_a_coded_refusal(self, tmp_path: Path) -> None:
        from foamwb.services.runtime import RuntimeManager

        class Nothing(RuntimeManager):
            def discover(self):
                return []

        root = tmp_path / "w"
        root.mkdir()
        client = Client(build_server(Workbench([root], manager_factory=Nothing)))
        case = client.ok("create_case", name="c")["case"]
        assert client.refused("start_run", case=case, ignore_validation=True).startswith("E-R10")


class TestHistory:
    def test_run_ids_continue_from_the_directory(self, tmp_path: Path) -> None:
        assert next_run_id(tmp_path) == "r-0001"
        (tmp_path / CASE_METADATA_DIR / "logs" / "r-0001").mkdir(parents=True)
        (tmp_path / CASE_METADATA_DIR / "logs" / "r-0003").mkdir()
        assert next_run_id(tmp_path) == "r-0002"
        assert next_run_id(None) == "r-0001"

    def test_latest_time_is_numeric_not_lexical(self, tmp_path: Path) -> None:
        for name in ("0", "9", "10", "constant"):
            (tmp_path / name).mkdir()
        assert latest_written_time(tmp_path) == "10"


# -- the real entry point ---------------------------------------------------------


def test_the_entry_point_speaks_only_json_and_never_imports_qt(tmp_path: Path) -> None:
    probe = (
        "import runpy, sys\n"
        "sys.argv = ['mcp', '--root', sys.argv[1]]\n"
        "try:\n"
        "    runpy.run_module('foamwb.mcp', run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n"
        "assert not [m for m in sys.modules if m.startswith('PySide6')], 'Qt was imported'\n"
    )
    requests = (
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}\n'
        b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path)],
        input=requests,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    replies = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert replies[1]["result"]["tools"]
