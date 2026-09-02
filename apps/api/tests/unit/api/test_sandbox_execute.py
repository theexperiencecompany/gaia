"""/sandbox/execute — token-only auth, dispatch pass-through."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.execute.dispatch import (
    DispatchError,
    DispatchErrorKind,
    ToolExecutionResult,
)
from app.api.v1.endpoints.sandbox_execute import SandboxExecuteRequest, sandbox_execute
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

MODULE = "app.api.v1.endpoints.sandbox_execute"
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _secret():
    with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
        yield


def _payload() -> SandboxExecuteRequest:
    return SandboxExecuteRequest(tool_name="GMAIL_FETCH_EMAILS", data={"max_results": 3})


@pytest.mark.unit
class TestSandboxExecuteRoute:
    async def test_missing_token_is_401_and_never_dispatches(self) -> None:
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch:
            with pytest.raises(AppError) as err:
                await sandbox_execute(_payload(), authorization="")
        assert err.value.status_code == 401
        dispatch.assert_not_awaited()

    async def test_tampered_token_is_401(self) -> None:
        token = mint_execute_token("u1", "run-1", ttl_seconds=60)
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch:
            with pytest.raises(AppError):
                await sandbox_execute(_payload(), authorization=f"Bearer {token}x")
        dispatch.assert_not_awaited()

    async def test_valid_token_dispatches_as_the_token_user(self) -> None:
        token = mint_execute_token("u1", "run-1", ttl_seconds=60)
        result = ToolExecutionResult(
            ok=True, resolved_name="GMAIL_FETCH_EMAILS", output=[{"id": "m1"}]
        )
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=1, rate=1)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=result)) as dispatch,
        ):
            response = await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert response.ok is True
        assert response.output == [{"id": "m1"}]
        kwargs = dispatch.await_args.kwargs
        assert kwargs["user_id"] == "u1"
        assert kwargs["tool_name"] == "GMAIL_FETCH_EMAILS"
        assert kwargs["config"]["configurable"]["user_id"] == "u1"

    async def test_dispatch_failure_shape_passes_through(self) -> None:
        token = mint_execute_token("u1", "run-1", ttl_seconds=60)
        result = ToolExecutionResult(
            ok=False,
            resolved_name="GMAIL_FETCH_EMAILS",
            error=DispatchError(kind=DispatchErrorKind.INVALID_ARGS, detail="bad", hint="fix data"),
        )
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=1, rate=1)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=result)),
        ):
            response = await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert response.ok is False
        assert response.error is not None
        assert response.error.kind is DispatchErrorKind.INVALID_ARGS


def _redis_with_counts(total: int, rate: int) -> MagicMock:
    client = MagicMock()
    client.incr = AsyncMock(side_effect=[total, rate])
    client.expire = AsyncMock()
    redis = MagicMock()
    redis.client = client
    return redis


@pytest.mark.unit
class TestSandboxExecuteBudget:
    """The wall a runaway or injected script hits — no approval gate exists here."""

    async def test_within_budget_dispatches(self) -> None:
        token = mint_execute_token("u1", "run-1", ttl_seconds=60)
        result = ToolExecutionResult(ok=True, resolved_name="GMAIL_FETCH_EMAILS", output=[])
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=2, rate=2)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=result)),
        ):
            response = await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert response.ok is True

    async def test_token_budget_exhaustion_is_429_and_never_dispatches(self) -> None:
        token = mint_execute_token("u1", "run-1", ttl_seconds=60)
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=301, rate=1)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch,
        ):
            with pytest.raises(AppError) as err:
                await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert err.value.status_code == 429
        dispatch.assert_not_awaited()

    async def test_per_minute_rate_limit_is_429_and_never_dispatches(self) -> None:
        token = mint_execute_token("u1", "run-1", ttl_seconds=60)
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=5, rate=61)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch,
        ):
            with pytest.raises(AppError) as err:
                await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert err.value.status_code == 429
        dispatch.assert_not_awaited()

    async def test_every_dispatched_call_is_audited(self) -> None:
        token = mint_execute_token("u1", "run-1", ttl_seconds=60)
        result = ToolExecutionResult(ok=True, resolved_name="GMAIL_FETCH_EMAILS", output=[])
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=1, rate=1)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=result)),
            patch(f"{MODULE}.log") as mocked_log,
        ):
            await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        audit_kwargs = mocked_log.audit.call_args.kwargs
        assert audit_kwargs["actor"] == "u1"
        assert audit_kwargs["tool"] == "GMAIL_FETCH_EMAILS"
        assert audit_kwargs["run_id"] == "run-1"
