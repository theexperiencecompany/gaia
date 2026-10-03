"""Unit tests for scripts/sandbox_bridge.py."""

import json
from pathlib import Path

import pytest
from scripts.sandbox_bridge import (
    BRIDGE_CONFIG_PATH,
    DEFAULT_ALLOWED_SERVERS,
    EXEC_MAX_OUTPUT_BYTES,
    FRAME_EXEC_EXIT,
    FRAME_EXEC_STDERR,
    FRAME_EXEC_STDOUT,
    FRAME_HELLO,
    FRAME_MCP_ERROR,
    FRAME_MCP_OPENED,
    FRAME_PONG,
    SANDBOX_TOKEN_AUDIENCE,
    Bridge,
    BridgeConfig,
    ExecResult,
    ExecRunner,
    Frame,
    _truncate_outputs,
    build_auth_header,
    load_bridge_config,
    run_exec_command,
    sandbox_ws_url,
)

pytestmark = pytest.mark.unit


def _bridge(servers: list[str] | None = None, runner: ExecRunner | None = None) -> Bridge:
    config = BridgeConfig(allowed_servers=list(servers) if servers is not None else ["splitwise"])
    return Bridge(config, exec_runner=runner)


class TestFrameRoundTrip:
    def test_full_frame_survives_encode_decode(self) -> None:
        frame = Frame(
            t="mcp.open",
            sid="s1",
            server="splitwise",
            data='{"jsonrpc":"2.0"}',
            pod="pod-a",
            command="echo hi",
            cwd="/workspace",
            code=0,
            key="splitwise",
        )
        assert Frame.decode(frame.encode()) == frame

    def test_unset_fields_dropped_on_wire(self) -> None:
        assert json.loads(Frame(t="ping").encode()) == {"t": "ping"}

    def test_servers_list_round_trip(self) -> None:
        frame = Frame(t=FRAME_HELLO, servers=["splitwise"])
        assert Frame.decode(frame.encode()) == frame

    def test_garbage_is_value_error(self) -> None:
        with pytest.raises(ValueError):
            Frame.decode("not json{")

    def test_non_object_is_value_error(self) -> None:
        with pytest.raises(ValueError):
            Frame.decode("[1, 2]")

    def test_missing_t_is_value_error(self) -> None:
        with pytest.raises(ValueError):
            Frame.decode("{}")

    def test_non_string_t_is_value_error(self) -> None:
        with pytest.raises(ValueError):
            Frame.decode('{"t": 5}')


class TestAllowlist:
    def test_missing_file_means_splitwise_only(self, tmp_path: Path) -> None:
        config = load_bridge_config(tmp_path / "absent.json")
        assert config.allowed_servers == list(DEFAULT_ALLOWED_SERVERS)
        assert DEFAULT_ALLOWED_SERVERS == ("splitwise",)

    def test_valid_file_loads_servers(self, tmp_path: Path) -> None:
        path = tmp_path / "bridge.json"
        path.write_text(json.dumps({"allowed_servers": ["splitwise"]}))
        assert load_bridge_config(path).allowed_servers == ["splitwise"]

    def test_malformed_json_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "bridge.json"
        path.write_text("{nope")
        with pytest.raises(ValueError):
            load_bridge_config(path)

    def test_wrong_shape_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "bridge.json"
        path.write_text(json.dumps({"servers": ["splitwise"]}))
        with pytest.raises(ValueError):
            load_bridge_config(path)

    def test_non_string_entries_fail_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "bridge.json"
        path.write_text(json.dumps({"allowed_servers": ["splitwise", 7]}))
        with pytest.raises(ValueError):
            load_bridge_config(path)

    def test_default_path_constant(self) -> None:
        assert BRIDGE_CONFIG_PATH == "/workspace/.gaia/bridge.json"


class TestDispatch:
    def test_ping_replies_pong(self) -> None:
        assert _bridge().handle_raw('{"t": "ping"}') == [Frame(t=FRAME_PONG)]

    def test_unknown_frame_type_yields_nothing(self) -> None:
        assert _bridge().handle_raw('{"t": "nope"}') == []

    def test_malformed_line_yields_nothing(self) -> None:
        assert _bridge().handle_raw("{{{") == []

    def test_open_allowlisted_server(self) -> None:
        replies = _bridge().handle_frame(
            Frame(t="mcp.open", sid="s1", server="splitwise", pod="pod-a")
        )
        assert replies == [Frame(t=FRAME_MCP_OPENED, sid="s1", pod="pod-a")]

    def test_open_denied_server_names_it(self) -> None:
        replies = _bridge().handle_frame(Frame(t="mcp.open", sid="s1", server="evil", pod="pod-a"))
        assert replies == [
            Frame(
                t=FRAME_MCP_ERROR,
                sid="s1",
                pod="pod-a",
                error="Unknown server 'evil'",
            )
        ]

    def test_open_needs_sid_and_server(self) -> None:
        assert _bridge().handle_frame(Frame(t="mcp.open", sid="s1")) == []
        assert _bridge().handle_frame(Frame(t="mcp.open", server="splitwise")) == []

    def test_msg_to_open_session_accepted_silently(self) -> None:
        bridge = _bridge()
        bridge.handle_frame(Frame(t="mcp.open", sid="s1", server="splitwise"))
        assert bridge.handle_frame(Frame(t="mcp.msg", sid="s1", data="{}")) == []

    def test_msg_to_unknown_session_fails_fast(self) -> None:
        replies = _bridge().handle_frame(Frame(t="mcp.msg", sid="ghost", data="{}", pod="pod-a"))
        assert replies == [
            Frame(
                t=FRAME_MCP_ERROR,
                sid="ghost",
                pod="pod-a",
                error="Unknown session 'ghost'",
            )
        ]

    def test_close_drops_session(self) -> None:
        bridge = _bridge()
        bridge.handle_frame(Frame(t="mcp.open", sid="s1", server="splitwise"))
        bridge.handle_frame(Frame(t="mcp.close", sid="s1"))
        replies = bridge.handle_frame(Frame(t="mcp.msg", sid="s1", data="{}"))
        assert replies[0].t == FRAME_MCP_ERROR

    def test_hello_advertises_allowlist(self) -> None:
        bridge = _bridge(servers=["splitwise"])
        assert bridge.hello_frame() == Frame(t=FRAME_HELLO, servers=["splitwise"])

    def test_revoke_stops_bridge(self) -> None:
        bridge = _bridge()
        assert bridge.handle_frame(Frame(t="revoke")) == []
        assert bridge.stopped is True

    def test_server_remove_closes_allowlist(self) -> None:
        bridge = _bridge(servers=["splitwise"])
        assert bridge.handle_frame(Frame(t="server.remove", key="splitwise")) == []
        replies = bridge.handle_frame(Frame(t="mcp.open", sid="s1", server="splitwise"))
        assert replies[0].t == FRAME_MCP_ERROR
        assert bridge.hello_frame().servers == []


class TestExecShaping:
    def test_exec_open_shapes_stream_frames(self) -> None:
        def fake_runner(command: str, cwd: str | None) -> ExecResult:
            assert command == "echo hi"
            assert cwd is None
            return ExecResult(stdout="hi\n", stderr="warn\n", code=0)

        replies = _bridge(runner=fake_runner).handle_frame(
            Frame(t="exec.open", sid="e1", command="echo hi", pod="pod-a")
        )
        assert replies == [
            Frame(t=FRAME_EXEC_STDOUT, sid="e1", pod="pod-a", data="hi\n"),
            Frame(t=FRAME_EXEC_STDERR, sid="e1", pod="pod-a", data="warn\n"),
            Frame(t=FRAME_EXEC_EXIT, sid="e1", pod="pod-a", code=0),
        ]

    def test_exec_open_needs_sid_and_command(self) -> None:
        bridge = _bridge(runner=lambda c, w: ExecResult(stdout="", stderr="", code=0))
        assert bridge.handle_frame(Frame(t="exec.open", sid="e1")) == []
        assert bridge.handle_frame(Frame(t="exec.open", command="echo hi")) == []

    def test_empty_output_shapes_exit_only(self) -> None:
        frames = ExecResult(stdout="", stderr="", code=3).to_frames("e1")
        assert frames == [Frame(t=FRAME_EXEC_EXIT, sid="e1", pod=None, code=3)]

    def test_truncation_caps_combined_output(self) -> None:
        out, err, truncated = _truncate_outputs("a" * 10, "b" * 10, 12)
        assert truncated is True
        assert len(out) + len(err) <= 12

    def test_passthrough_under_cap(self) -> None:
        assert _truncate_outputs("a", "b", EXEC_MAX_OUTPUT_BYTES) == ("a", "b", False)

    def test_real_command_runs(self) -> None:
        result = run_exec_command("printf hello")
        assert (result.stdout, result.stderr, result.code) == ("hello", "", 0)

    def test_bad_cwd_shapes_launch_failure(self) -> None:
        result = run_exec_command("printf hello", cwd="/no/such/dir")
        assert result.code == 127
        assert result.stderr != ""

    def test_timeout_kills_and_notes(self) -> None:
        result = run_exec_command("sleep 5", timeout=0.05)
        assert result.code == -1
        assert "timeout" in result.stderr
        assert result.truncated is True


class TestSocketHelpers:
    def test_https_maps_to_wss_sandbox_path(self) -> None:
        assert sandbox_ws_url("https://api.heygaia.io") == "wss://api.heygaia.io/ws/sandbox"

    def test_http_maps_to_ws(self) -> None:
        assert sandbox_ws_url("http://localhost:8000/") == "ws://localhost:8000/ws/sandbox"

    def test_bare_host_defaults_to_wss(self) -> None:
        assert sandbox_ws_url("api.heygaia.io") == "wss://api.heygaia.io/ws/sandbox"

    def test_auth_header_bearer(self) -> None:
        assert build_auth_header("tok") == {"Authorization": "Bearer tok"}

    def test_token_audience(self) -> None:
        assert SANDBOX_TOKEN_AUDIENCE == "sandbox-bridge"
