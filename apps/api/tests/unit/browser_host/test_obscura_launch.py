"""Launching Obscura: its command, its endpoint, and a failed launch leaving nothing running."""

from __future__ import annotations

import socket
import subprocess
import sys
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.browser_host import obscura_launch
from app.browser_host.obscura_launch import (
    free_local_port,
    launch_obscura,
    obscura_serve_argv,
    obscura_serve_env,
)
from app.browser_host.process import EngineLaunchError, stop_process
from app.config.browser_host_settings import browser_host_settings

pytestmark = pytest.mark.unit

_WS = "ws://127.0.0.1:9333/devtools/browser/abc"


class _Proc:
    def __init__(self, returncode: int | None = None) -> None:
        self.pid = 999_999_999
        self.returncode = returncode
        self.signals: list[str] = []

    def terminate(self) -> None:
        self.signals.append("term")
        self.returncode = -15

    def kill(self) -> None:
        self.signals.append("kill")
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


def test_obscura_is_served_stealthed_on_the_port_it_is_given_and_never_privately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", "/opt/obscura/obscura")

    assert obscura_serve_argv(9931) == [
        "/opt/obscura/obscura",
        "serve",
        "--port",
        "9931",
        "--stealth",
    ]


def test_obscura_without_a_binary_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", None)

    with pytest.raises(RuntimeError) as missing:
        obscura_serve_argv(9931)
    assert missing.value.args == ("Obscura requires OBSCURA_BIN to be set",)


def test_obscura_receives_its_script_deadline_in_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_SCRIPT_DEADLINE_SECONDS", 7)
    monkeypatch.setenv("OBSCURA_PROBE_PASSTHROUGH", "kept")

    env = obscura_serve_env()

    assert env["OBSCURA_SCRIPT_DEADLINE_MS"] == "7000"
    assert env["OBSCURA_PROBE_PASSTHROUGH"] == "kept"


def test_obscura_reaches_private_addresses_only_while_the_host_allows_private_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ambient OBSCURA_ALLOW_PRIVATE_NETWORK never reaches the engine on its own."""
    monkeypatch.setenv("OBSCURA_ALLOW_PRIVATE_NETWORK", "1")
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_ALLOW_PRIVATE_ORIGINS", frozenset())

    assert "OBSCURA_ALLOW_PRIVATE_NETWORK" not in obscura_serve_env()

    monkeypatch.delenv("OBSCURA_ALLOW_PRIVATE_NETWORK")
    monkeypatch.setattr(
        browser_host_settings,
        "BROWSER_HOST_ALLOW_PRIVATE_ORIGINS",
        frozenset({"http://localhost:8123"}),
    )

    assert obscura_serve_env()["OBSCURA_ALLOW_PRIVATE_NETWORK"] == "1"


def test_obscura_trusts_a_test_stacks_ca_only_while_one_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_TEST_CA_FILE", None)
    assert "SSL_CERT_FILE" not in obscura_serve_env()

    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_TEST_CA_FILE", "/stack/ca.pem")

    assert obscura_serve_env()["SSL_CERT_FILE"] == "/stack/ca.pem"


def test_a_free_port_is_one_nothing_listens_on() -> None:
    port = free_local_port()

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def _version_client(*responses: httpx.Response) -> tuple[httpx.AsyncClient, list[str]]:
    asked: list[str] = []
    queue = list(responses)

    def _handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return queue.pop(0)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler)), asked


async def test_obscuras_endpoint_is_what_json_version_publishes_once_it_answers() -> None:
    client, asked = _version_client(
        httpx.Response(503),
        httpx.Response(200, json={"Browser": "x"}),
        httpx.Response(200, json={"webSocketDebuggerUrl": _WS}),
    )
    read = obscura_launch._json_version_reader(client, 9333)

    assert [await read(), await read(), await read()] == [None, None, _WS]
    assert asked == ["http://127.0.0.1:9333/json/version"] * 3


async def test_obscura_is_launched_on_a_free_port_and_stopped_when_it_never_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", "/opt/obscura/obscura")
    monkeypatch.setattr(obscura_launch, "free_local_port", lambda: 9444)
    proc = _Proc()
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(obscura_launch.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(
        obscura_launch, "until_published", AsyncMock(side_effect=EngineLaunchError("x"))
    )

    with pytest.raises(EngineLaunchError):
        await launch_obscura()

    assert spawn.await_args is not None
    assert spawn.await_args.args == ("/opt/obscura/obscura", "serve", "--port", "9444", "--stealth")
    assert spawn.await_args.kwargs["stdout"] is subprocess.DEVNULL
    assert spawn.await_args.kwargs["env"]["OBSCURA_SCRIPT_DEADLINE_MS"]
    assert proc.signals == ["term"]


async def test_a_launched_obscura_knows_its_port_and_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", "/opt/obscura/obscura")
    monkeypatch.setattr(obscura_launch, "free_local_port", lambda: 9444)
    monkeypatch.setattr(obscura_launch, "spawn_engine", AsyncMock(return_value=_Proc()))
    monkeypatch.setattr(obscura_launch, "until_published", AsyncMock(return_value=_WS))

    launched = await launch_obscura()

    assert (launched.port, launched.ws_url, launched.http_url) == (
        9444,
        _WS,
        "http://127.0.0.1:9444",
    )


# Stands in for `obscura serve --port N --stealth`: chatters on both streams,
# then serves /json/version on the port it was named.
_FAKE_OBSCURA = """#!{python}
import http.server, json, sys
port = int(sys.argv[sys.argv.index("--port") + 1])
print("ENGINE-CHATTER-OUT", flush=True)
print("ENGINE-CHATTER-ERR", file=sys.stderr, flush=True)

class Version(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({{"webSocketDebuggerUrl": f"ws://127.0.0.1:{{port}}/devtools/browser/fake"}}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

http.server.HTTPServer(("127.0.0.1", port), Version).serve_forever()
"""


async def test_obscura_is_launched_found_and_stopped_as_a_real_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capfd: pytest.CaptureFixture[str]
) -> None:
    binary = tmp_path / "obscura"
    binary.write_text(_FAKE_OBSCURA.format(python=sys.executable))
    binary.chmod(0o755)
    monkeypatch.setattr(browser_host_settings, "OBSCURA_BIN", str(binary))

    launched = await launch_obscura()
    try:
        assert launched.ws_url == f"ws://127.0.0.1:{launched.port}/devtools/browser/fake"
        assert launched.proc.returncode is None
    finally:
        await stop_process(launched.proc)

    assert launched.proc.returncode is not None
    captured = capfd.readouterr()
    assert "ENGINE-CHATTER" not in captured.out + captured.err
