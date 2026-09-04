"""execute_client — the bash-driven code-mode env: seeded client, scoped token."""

import json
import re
import types
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.execute import (
    SANDBOX_CLIENT_DIR,
    SANDBOX_EXECUTE_CLIENT_TIMEOUT_BUFFER_SECONDS,
    SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS,
)
from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS
from app.services.sandbox import execute_client, execute_token
from app.services.sandbox.execute_client import (
    GAIA_SANDBOX_CLIENT_SOURCE,
    mint_execute_env,
    sandbox_execute_enabled,
    seed_execute_client,
)
from app.services.sandbox.execute_token import verify_execute_token

SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
URL = "https://api.test/api/v1/sandbox/execute"
CONFIG = {"configurable": {"user_id": "u1", "stream_id": "s1"}}


@pytest.fixture(autouse=True)
def _configured():
    with (
        patch.object(execute_client.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET),
        patch.object(execute_client.settings, "SANDBOX_EXECUTE_CALLBACK_URL", URL),
        patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET),
    ):
        yield


@pytest.mark.unit
class TestExecuteClient:
    def test_enabled_requires_both_settings(self) -> None:
        assert sandbox_execute_enabled() is True
        with patch.object(execute_client.settings, "SANDBOX_EXECUTE_CALLBACK_URL", None):
            assert sandbox_execute_enabled() is False
        with patch.object(execute_client.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", None):
            assert sandbox_execute_enabled() is False

    async def test_seed_writes_client_into_the_sandbox(self) -> None:
        sbx = AsyncMock()
        await seed_execute_client(sbx)
        path, source = sbx.files.write.await_args.args
        assert path == f"{SANDBOX_CLIENT_DIR}/gaia.py"
        assert "def execute(" in source
        assert "def schema(" in source
        assert "GAIA_EXECUTE_TOKEN" in source
        assert "__TOOL_DOCS_DIR__" not in source  # placeholders resolved

    def test_env_carries_url_token_and_pythonpath(self) -> None:
        env = mint_execute_env(
            user_id="u1",
            run_id="run-abc",
            config=CONFIG,
            sandbox_id="sbx-9",
            command_timeout_seconds=120,
            scoped_tool_names=["GMAIL_SEND_EMAIL"],
        )
        assert env["GAIA_EXECUTE_URL"] == URL
        assert env["GAIA_SCHEMA_URL"] == "https://api.test/api/v1/sandbox/tool-schema"
        assert env["PYTHONPATH"] == SANDBOX_CLIENT_DIR
        claims = verify_execute_token(env["GAIA_EXECUTE_TOKEN"])
        assert claims.user_id == "u1"
        assert claims.run_id == "run-abc"
        assert claims.stream_id == "s1"
        assert claims.sandbox_id == "sbx-9"
        # The caller's tool space travels in the token — the route has no other
        # way to confine a sandbox call the way the in-graph proxy confines one.
        assert claims.scoped_tool_names == ["GMAIL_SEND_EMAIL"]

    def test_token_ttl_is_bounded_to_the_command_timeout(self) -> None:
        import time

        env = mint_execute_env(
            user_id="u1",
            run_id="run-abc",
            config=CONFIG,
            sandbox_id=None,
            command_timeout_seconds=30,
            scoped_tool_names=None,
        )
        claims = verify_execute_token(env["GAIA_EXECUTE_TOKEN"])
        remaining = claims.exp - int(time.time())
        assert remaining <= 30 + SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS
        assert remaining > 30


def _load_client(tmp_path, ttl: int = 900):
    """The real client, rendered by production's own substitution, with an
    isolated tool-docs dir. Rendering it here instead would silently stop
    testing the shipped client the next time a placeholder is added."""
    source = execute_client.render_sandbox_client_source(
        tool_docs_dir=str(tmp_path), schema_cache_ttl_seconds=ttl
    )
    module = types.ModuleType("gaia_under_test")
    exec(source, module.__dict__)  # noqa: S102 -- executing our own template is the test subject
    return module


@pytest.mark.unit
class TestSandboxSchemaLookup:
    def test_schema_fetches_once_then_serves_from_the_file_cache(self, tmp_path) -> None:
        gaia = _load_client(tmp_path)
        calls: list[dict] = []

        def fake_post(url_env: str, payload: dict) -> dict:
            calls.append(payload)
            return {"tool_name": payload["tool_name"], "input_schema": {"type": "object"}}

        gaia._post = fake_post
        first = gaia.schema("GMAIL_FETCH_EMAILS")
        second = gaia.schema("GMAIL_FETCH_EMAILS")
        assert first == second
        assert len(calls) == 1  # the second read came from the file
        cached = json.loads((tmp_path / "GMAIL_FETCH_EMAILS.json").read_text())
        assert cached == first

    def test_a_stale_cache_file_is_refetched(self, tmp_path) -> None:
        gaia = _load_client(tmp_path, ttl=0)
        calls: list[dict] = []

        def fake_post(url_env: str, payload: dict) -> dict:
            calls.append(payload)
            return {"tool_name": payload["tool_name"]}

        gaia._post = fake_post
        gaia.schema("T")
        gaia.schema("T")
        assert len(calls) == 2


@pytest.mark.unit
class TestClientTimeoutOutlivesTheHost:
    def test_the_client_waits_longer_than_the_host_bound(self, tmp_path) -> None:
        """The host must always be the one that gives up.

        The client used to wait 60s against a 120s host bound, so a slow
        GMAIL_SEND_EMAIL raised socket.timeout inside the script AFTER the host
        had already sent it — and the docs tell the model to fix `data` and
        rerun, so the send happened twice. There is no idempotency key here.
        """
        gaia = _load_client(tmp_path)
        assert gaia._REQUEST_TIMEOUT_SECONDS > TOOL_EXECUTION_TIMEOUT_SECONDS

    def test_the_shipped_client_carries_the_same_bound(self) -> None:
        """The seeded source is what actually runs in the sandbox — an
        unsubstituted placeholder there is a NameError on the first tool call."""
        expected = TOOL_EXECUTION_TIMEOUT_SECONDS + SANDBOX_EXECUTE_CLIENT_TIMEOUT_BUFFER_SECONDS
        assert f"_REQUEST_TIMEOUT_SECONDS = {expected}" in GAIA_SANDBOX_CLIENT_SOURCE
        assert re.search(r"__[A-Z_]+__", GAIA_SANDBOX_CLIENT_SOURCE) is None
