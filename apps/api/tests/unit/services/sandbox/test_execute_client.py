"""execute_client — the bash-driven code-mode env: seeded client, scoped token."""

import json
import types
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.execute import (
    SANDBOX_CLIENT_DIR,
    SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS,
)
from app.services.sandbox import execute_client, execute_token
from app.services.sandbox.execute_client import (
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
        )
        assert env["GAIA_EXECUTE_URL"] == URL
        assert env["GAIA_SCHEMA_URL"] == "https://api.test/api/v1/sandbox/tool-schema"
        assert env["PYTHONPATH"] == SANDBOX_CLIENT_DIR
        claims = verify_execute_token(env["GAIA_EXECUTE_TOKEN"])
        assert claims.user_id == "u1"
        assert claims.run_id == "run-abc"
        assert claims.stream_id == "s1"
        assert claims.sandbox_id == "sbx-9"

    def test_token_ttl_is_bounded_to_the_command_timeout(self) -> None:
        import time

        env = mint_execute_env(
            user_id="u1",
            run_id="run-abc",
            config=CONFIG,
            sandbox_id=None,
            command_timeout_seconds=30,
        )
        claims = verify_execute_token(env["GAIA_EXECUTE_TOKEN"])
        remaining = claims.exp - int(time.time())
        assert remaining <= 30 + SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS
        assert remaining > 30


def _load_client(tmp_path, ttl: int = 900):
    """The real client template, executed with an isolated tool-docs dir."""
    source = execute_client._CLIENT_TEMPLATE.replace("__TOOL_DOCS_DIR__", str(tmp_path)).replace(
        "__SCHEMA_CACHE_TTL_SECONDS__", str(ttl)
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
