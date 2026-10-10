"""/sandbox/execute — token-only auth, dispatch pass-through."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.agents.tools.execute.dispatch import (
    DispatchError,
    DispatchErrorKind,
    ToolExecutionResult,
)
from app.agents.tools.execute.resolver import ResolvedTool
from app.agents.tools.execute.tool_info import ToolContract
from app.api.v1.endpoints.sandbox_execute import (
    SandboxExecuteRequest,
    SandboxToolSchemaRequest,
    sandbox_execute,
    sandbox_tool_schema,
)
from app.constants.execute import (
    SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS,
    SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE,
    SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN,
)
from app.schemas.errors import ErrorEnvelope
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError
from tests.helpers import captured_wide_event

MODULE = "app.api.v1.endpoints.sandbox_execute"
DISPATCH = "app.agents.tools.execute.dispatch"
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
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch:
            with pytest.raises(AppError):
                await sandbox_execute(_payload(), authorization=f"Bearer {token}x")
        dispatch.assert_not_awaited()

    async def test_valid_token_dispatches_as_the_token_user(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
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

    async def test_a_scoped_token_cannot_reach_another_agents_tools(self) -> None:
        """The bypass this closes: a subagent refused SLACK_SEND_MESSAGE by its own execute ran it from a sandbox script instead, because the route dispatched every token as if it were the executor's."""
        token = mint_execute_token(
            "u1", "run-1", scoped_tool_names=["GMAIL_SEND_EMAIL"], ttl_seconds=60
        )
        slack = MagicMock()
        slack.name = "SLACK_SEND_MESSAGE"
        slack.args_schema = None
        slack.ainvoke = AsyncMock(return_value={"ok": True})
        resolved = ResolvedTool("SLACK_SEND_MESSAGE", slack, is_integration=True)
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=1, rate=1)),
            patch(f"{DISPATCH}.resolve_tool", new=AsyncMock(return_value=resolved)),
            patch(f"{DISPATCH}.capture_event"),
        ):
            response = await sandbox_execute(
                SandboxExecuteRequest(tool_name="SLACK_SEND_MESSAGE"),
                authorization=f"Bearer {token}",
            )
        assert response.ok is False
        assert response.error is not None
        assert response.error.kind is DispatchErrorKind.OUT_OF_SCOPE
        slack.ainvoke.assert_not_awaited()

    async def test_tool_schema_requires_the_token_and_shares_the_budget(self) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock()) as info:
            with pytest.raises(AppError) as err:
                await sandbox_tool_schema(
                    SandboxToolSchemaRequest(tool_name="GMAIL_FETCH_EMAILS"), authorization=""
                )
        assert err.value.status_code == 401
        info.assert_not_awaited()

        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=10_000, rate=1)),
            patch(f"{MODULE}.full_tool_info", new=AsyncMock()) as info,
        ):
            with pytest.raises(AppError) as err:
                await sandbox_tool_schema(
                    SandboxToolSchemaRequest(tool_name="GMAIL_FETCH_EMAILS"),
                    authorization=f"Bearer {token}",
                )
        assert err.value.status_code == 429
        info.assert_not_awaited()

    async def test_tool_schema_returns_the_full_contract_for_the_token_user(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
        contract = ToolContract(
            tool_name="GMAIL_FETCH_EMAILS",
            description="Fetch emails.",
            input_schema={"type": "object"},
            observed_output_schema={"type": "object"},
            observed_call_count=12,
        )
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=1, rate=1)),
            patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=contract)) as info,
        ):
            response = await sandbox_tool_schema(
                SandboxToolSchemaRequest(tool_name="GMAIL_FETCH_EMAILS"),
                authorization=f"Bearer {token}",
            )
        assert response is contract
        info.assert_awaited_once_with("u1", "GMAIL_FETCH_EMAILS")

    async def test_tool_schema_unknown_tool_is_404(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=1, rate=1)),
            patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=None)),
        ):
            with pytest.raises(AppError) as err:
                await sandbox_tool_schema(
                    SandboxToolSchemaRequest(tool_name="NOPE"), authorization=f"Bearer {token}"
                )
        assert err.value.status_code == 404

    async def test_dispatch_failure_shape_passes_through(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
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
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
        result = ToolExecutionResult(ok=True, resolved_name="GMAIL_FETCH_EMAILS", output=[])
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=2, rate=2)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=result)),
        ):
            response = await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert response.ok is True

    async def test_token_budget_exhaustion_is_429_and_never_dispatches(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=301, rate=1)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch,
        ):
            with pytest.raises(AppError) as err:
                await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert err.value.status_code == 429
        dispatch.assert_not_awaited()

    async def test_per_minute_rate_limit_is_429_and_never_dispatches(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
        with (
            patch(f"{MODULE}.redis_cache", _redis_with_counts(total=5, rate=61)),
            patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch,
        ):
            with pytest.raises(AppError) as err:
                await sandbox_execute(_payload(), authorization=f"Bearer {token}")
        assert err.value.status_code == 429
        dispatch.assert_not_awaited()

    async def test_every_dispatched_call_is_audited(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)
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


FROZEN_MINUTE = 29_000_000
TOTAL_KEY = "sandbox_execute:calls:run-1"
MINUTE_KEY = f"sandbox_execute:rate:run-1:{FROZEN_MINUTE}"
# Redis reports whole seconds left, so a TTL read may trail its window by a tick or more.
TTL_SLACK = 5


@pytest.fixture(autouse=True)
def _frozen_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the route's clock inside one rate-limit minute so MINUTE_KEY is deterministic."""
    monkeypatch.setattr(f"{MODULE}.time", SimpleNamespace(time=lambda: FROZEN_MINUTE * 60 + 30))


def _bearer(sandbox_id: str | None = None, run_id: str = "run-1") -> str:
    token = mint_execute_token(
        "u1", run_id, sandbox_id=sandbox_id, scoped_tool_names=None, ttl_seconds=60
    )
    return f"Bearer {token}"


def _envelope(err: pytest.ExceptionInfo[AppError]) -> dict[str, object]:
    return ErrorEnvelope.from_app_error(err.value).model_dump(exclude_none=True)


def _ok_dispatch() -> AsyncMock:
    return AsyncMock(
        return_value=ToolExecutionResult(ok=True, resolved_name="GMAIL_FETCH_EMAILS", output=[])
    )


@pytest.mark.unit
class TestSandboxExecuteCounters:
    async def test_first_call_arms_both_counters_with_their_windows(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        with patch(f"{MODULE}.dispatch_tool", new=_ok_dispatch()):
            await sandbox_execute(_payload(), authorization=_bearer())

        assert await fake_redis.get(TOTAL_KEY) == "1"
        assert (
            SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS - TTL_SLACK
            <= await fake_redis.ttl(TOTAL_KEY)
            <= SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS
        )
        assert await fake_redis.get(MINUTE_KEY) == "1"
        assert 120 - TTL_SLACK <= await fake_redis.ttl(MINUTE_KEY) <= 120

    async def test_later_calls_never_extend_the_windows(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(TOTAL_KEY, 5, ex=100)
        await fake_redis.set(MINUTE_KEY, 5, ex=50)

        with patch(f"{MODULE}.dispatch_tool", new=_ok_dispatch()):
            await sandbox_execute(_payload(), authorization=_bearer())

        assert await fake_redis.get(TOTAL_KEY) == "6"
        assert 100 - TTL_SLACK <= await fake_redis.ttl(TOTAL_KEY) <= 100
        assert await fake_redis.get(MINUTE_KEY) == "6"
        assert 50 - TTL_SLACK <= await fake_redis.ttl(MINUTE_KEY) <= 50

    async def test_counters_are_per_run(self, fake_redis: fakeredis.aioredis.FakeRedis) -> None:
        await fake_redis.set(TOTAL_KEY, SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN)

        with patch(f"{MODULE}.dispatch_tool", new=_ok_dispatch()):
            response = await sandbox_execute(_payload(), authorization=_bearer(run_id="run-2"))

        assert response.ok is True
        assert await fake_redis.get("sandbox_execute:calls:run-2") == "1"

    async def test_the_last_call_inside_both_budgets_still_dispatches(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(TOTAL_KEY, SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN - 1)
        await fake_redis.set(MINUTE_KEY, SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE - 1)

        with patch(f"{MODULE}.dispatch_tool", new=_ok_dispatch()) as dispatch:
            response = await sandbox_execute(_payload(), authorization=_bearer())

        assert response.ok is True
        dispatch.assert_awaited_once()

    async def test_token_budget_exhaustion_tells_the_script_how_to_recover(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(TOTAL_KEY, SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN)

        with pytest.raises(AppError) as err:
            await sandbox_execute(_payload(), authorization=_bearer())

        assert _envelope(err) == {
            "message": "Sandbox execute call budget exhausted for this run",
            "why": f"more than {SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN} calls on one token",
            "fix": "Batch work inside the script; a fresh bash run mints a fresh budget",
        }

    async def test_rate_limit_tells_the_script_how_to_recover(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await fake_redis.set(MINUTE_KEY, SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE)

        with pytest.raises(AppError) as err:
            await sandbox_execute(_payload(), authorization=_bearer())

        assert err.value.status_code == 429
        assert _envelope(err) == {
            "message": "Sandbox execute rate limit hit",
            "why": f"more than {SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE} calls in one minute",
            "fix": "Slow the loop down or batch the work",
        }

    async def test_tool_schema_spends_the_same_run_budget(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        contract = ToolContract(
            tool_name="GMAIL_FETCH_EMAILS", description="Fetch emails.", input_schema={}
        )
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=contract)):
            await sandbox_tool_schema(
                SandboxToolSchemaRequest(tool_name="GMAIL_FETCH_EMAILS"), authorization=_bearer()
            )

        assert await fake_redis.get(TOTAL_KEY) == "1"


@pytest.mark.unit
class TestSandboxExecuteAuthorizationHeader:
    async def test_a_missing_token_tells_the_script_how_to_send_one(self) -> None:
        with pytest.raises(AppError) as err:
            await sandbox_execute(_payload(), authorization="")

        assert _envelope(err) == {
            "message": "Missing sandbox execute token",
            "why": "the route is token-authenticated; there is no session here",
            "fix": "Tokens are injected into bash runs as GAIA_EXECUTE_TOKEN; send "
            "'Authorization: Bearer <token>'",
        }

    async def test_a_valid_token_under_another_scheme_is_refused(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)

        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch:
            with pytest.raises(AppError) as err:
                await sandbox_execute(_payload(), authorization=f"Basic {token}")

        assert err.value.message == "Missing sandbox execute token"
        dispatch.assert_not_awaited()

    async def test_the_scheme_is_matched_case_insensitively(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)

        with patch(f"{MODULE}.dispatch_tool", new=_ok_dispatch()):
            response = await sandbox_execute(_payload(), authorization=f"bEaReR {token}")

        assert response.ok is True

    async def test_everything_after_the_first_space_is_judged_as_the_token(self) -> None:
        token = mint_execute_token("u1", "run-1", scoped_tool_names=None, ttl_seconds=60)

        with pytest.raises(AppError) as err:
            await sandbox_execute(_payload(), authorization=f"Bearer  {token}")

        assert err.value.message == "Invalid sandbox execute token"


@pytest.mark.unit
class TestSandboxExecuteRecord:
    async def test_dispatch_carries_the_script_data_and_integration_only_scope(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        with patch(f"{MODULE}.dispatch_tool", new=_ok_dispatch()) as dispatch:
            await sandbox_execute(_payload(), authorization=_bearer())

        kwargs = dispatch.await_args.kwargs
        assert kwargs["data"] == {"max_results": 3}
        assert kwargs["integration_only"] is True
        assert kwargs["scoped_tool_names"] is None

    async def test_the_call_is_audited_and_recorded_on_the_wide_event(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        async with captured_wide_event() as event:
            with patch(f"{MODULE}.dispatch_tool", new=_ok_dispatch()):
                await sandbox_execute(_payload(), authorization=_bearer(sandbox_id="sbx-9"))

        assert event["audit"] == [
            {
                "msg": "sandbox_execute call",
                "actor": "u1",
                "tool": "GMAIL_FETCH_EMAILS",
                "run_id": "run-1",
                "sandbox_id": "sbx-9",
                "ok": True,
            }
        ]
        assert event["user"] == {"id": "u1"}
        assert event["sandbox_execute"] == {
            "tool_name": "GMAIL_FETCH_EMAILS",
            "run_id": "run-1",
            "resolved_name": "GMAIL_FETCH_EMAILS",
            "ok": True,
        }

    async def test_tool_schema_lookup_is_recorded_on_the_wide_event(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        contract = ToolContract(
            tool_name="GMAIL_FETCH_EMAILS", description="Fetch emails.", input_schema={}
        )
        async with captured_wide_event() as event:
            with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=contract)):
                await sandbox_tool_schema(
                    SandboxToolSchemaRequest(tool_name="gmail_fetch_emails"),
                    authorization=_bearer(),
                )

        assert event["user"] == {"id": "u1"}
        assert event["sandbox_tool_schema"] == {
            "tool_name": "gmail_fetch_emails",
            "run_id": "run-1",
            "resolved_name": "GMAIL_FETCH_EMAILS",
        }

    async def test_an_unknown_tool_names_itself_and_points_at_discovery(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        with patch(f"{MODULE}.full_tool_info", new=AsyncMock(return_value=None)):
            with pytest.raises(AppError) as err:
                await sandbox_tool_schema(
                    SandboxToolSchemaRequest(tool_name="NOPE"), authorization=_bearer()
                )

        assert _envelope(err) == {
            "message": "Unknown tool 'NOPE'",
            "why": "the name resolved to no registry, MCP, or catalog tool",
            "fix": "Use the exact tool name from retrieve_tools or the execute schema docs",
        }
