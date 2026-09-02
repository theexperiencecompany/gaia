"""execute_client — the bash-driven code-mode env: seeded client, scoped token."""

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
        assert "GAIA_EXECUTE_TOKEN" in source

    def test_env_carries_url_token_and_pythonpath(self) -> None:
        env = mint_execute_env(
            user_id="u1",
            run_id="run-abc",
            config=CONFIG,
            sandbox_id="sbx-9",
            command_timeout_seconds=120,
        )
        assert env["GAIA_EXECUTE_URL"] == URL
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
