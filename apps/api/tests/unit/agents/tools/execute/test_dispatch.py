"""dispatch_tool — validation stands in for constrained decoding; analytics attribute the REAL tool.

These are the proxy's two load-bearing behaviors.
"""

import asyncio
from collections.abc import Container, Iterator
from dataclasses import dataclass, field
from datetime import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus_client import REGISTRY
from pydantic import BaseModel, Field, field_validator
import pytest

from app.agents.tools.execute.dispatch import (
    DispatchError,
    DispatchErrorKind,
    ToolExecutionResult,
    ToolSpace,
    dispatch_config_for,
    dispatch_tool,
)
from app.agents.tools.execute.resolver import ResolvedTool
from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import ACCOUNT_NEEDS_RECONNECT_HINT
from app.models.integration_models import IntegrationAccount, UserIntegrationDocument
from app.services.analytics_service import AnalyticsEvents
from tests.helpers import captured_wide_event

MODULE = "app.agents.tools.execute.dispatch"
CONFIG = {"configurable": {"user_id": "u1"}}


class _SendEmailArgs(BaseModel):
    recipient: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    max_results: int = 25


def _tool(name: str = "GMAIL_SEND_EMAIL", schema: object = _SendEmailArgs) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.args_schema = schema
    tool.ainvoke = AsyncMock(return_value={"status": "sent"})
    return tool


@pytest.fixture(autouse=True)
def account_record() -> Iterator[AsyncMock]:
    """Pin the user's accounts on the tool's integration; none on record by default."""
    with patch(f"{MODULE}.get_account_record", AsyncMock(return_value=None)) as lookup:
        yield lookup


def _gmail_accounts(
    *accounts: IntegrationAccount, primary: str = "ca_work"
) -> UserIntegrationDocument:
    return UserIntegrationDocument(
        user_id="u1",
        integration_id="gmail",
        status="connected",
        accounts=list(accounts),
        primary_account_id=primary,
    )


WORK = IntegrationAccount(
    connected_account_id="ca_work", label="work@acme.com", identity={"email": "work@acme.com"}
)
PERSONAL = IntegrationAccount(
    connected_account_id="ca_personal", label="me@gmail.com", nickname="Personal"
)


async def _dispatch_send(account: str | None, tool: MagicMock) -> ToolExecutionResult:
    with (
        patch(
            f"{MODULE}.resolve_tool",
            new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
        ),
        patch(f"{MODULE}.capture_event"),
    ):
        return await dispatch_tool(
            user_id="u1",
            tool_name="GMAIL_SEND_EMAIL",
            data={"recipient": "a@b.c", "subject": "hi"},
            config=CONFIG,
            account=account,
        )


def _invoked_account(tool: MagicMock) -> object:
    return tool.ainvoke.await_args.kwargs["config"]["metadata"]["composio_account"]


@pytest.mark.unit
class TestAccountChoice:
    async def test_no_account_named_runs_as_the_primary(self, account_record: AsyncMock) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)
        tool = _tool()

        result = await _dispatch_send(None, tool)

        assert result.ok is True
        assert _invoked_account(tool) == {"toolkit": "GMAIL", "connected_account_id": "ca_work"}
        account_record.assert_awaited_once_with("u1", "gmail")

    @pytest.mark.parametrize(
        ("name", "account"), [(None, "work@acme.com"), ("me@gmail.com", "Personal")]
    )
    async def test_with_several_accounts_the_result_names_the_one_it_ran_as(
        self, account_record: AsyncMock, name: str | None, account: str
    ) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)

        result = await _dispatch_send(name, _tool())

        assert (result.output, result.account) == ({"status": "sent"}, account)

    async def test_with_one_account_the_result_names_none(self, account_record: AsyncMock) -> None:
        account_record.return_value = _gmail_accounts(WORK)

        result = await _dispatch_send(None, _tool())

        assert result.account is None

    @pytest.mark.parametrize(
        ("name", "connected_account_id", "is_primary"),
        [(None, "ca_work", True), ("Personal", "ca_personal", False)],
    )
    async def test_the_wide_event_names_the_account_the_call_ran_as(
        self,
        account_record: AsyncMock,
        name: str | None,
        connected_account_id: str,
        is_primary: bool,
    ) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)

        async with captured_wide_event() as event:
            await _dispatch_send(name, _tool())

        assert event["execute"] == {
            "tool": "GMAIL_SEND_EMAIL",
            "connected_account_id": connected_account_id,
            "account_is_primary": is_primary,
            "outcome": "ok",
        }

    @pytest.mark.parametrize("name", ["Personal", "me@gmail.com", " ME@GMAIL.COM "])
    async def test_a_named_account_runs_as_that_account(
        self, account_record: AsyncMock, name: str
    ) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)
        tool = _tool()

        await _dispatch_send(name, tool)

        assert _invoked_account(tool) == {
            "toolkit": "GMAIL",
            "connected_account_id": "ca_personal",
        }

    async def test_an_unknown_account_lists_the_real_ones_and_never_runs(
        self, account_record: AsyncMock
    ) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)
        tool = _tool()

        result = await _dispatch_send("boss@acme.com", tool)

        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.UNKNOWN_ACCOUNT
        assert '"work@acme.com" (connected)' in result.error.hint
        assert '"Personal" (connected)' in result.error.hint
        tool.ainvoke.assert_not_awaited()

    async def test_an_expired_account_is_refused_while_another_still_works(
        self, account_record: AsyncMock
    ) -> None:
        dead = PERSONAL.model_copy(update={"status": "expired"})
        account_record.return_value = _gmail_accounts(WORK, dead)
        tool = _tool()

        result = await _dispatch_send("Personal", tool)

        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.ACCOUNT_EXPIRED
        tool.ainvoke.assert_not_awaited()

    async def test_with_every_account_dead_the_call_runs_into_the_reconnect_path(
        self, account_record: AsyncMock
    ) -> None:
        """No alternative exists, so the tool's own dead-account handling shows the connect card."""
        dead = WORK.model_copy(update={"status": "expired"})
        account_record.return_value = _gmail_accounts(dead)
        tool = _tool()

        await _dispatch_send(None, tool)

        assert _invoked_account(tool) == {"toolkit": "GMAIL", "connected_account_id": "ca_work"}

    async def test_an_account_on_a_tool_without_accounts_is_refused(self) -> None:
        tool = _tool(name="todo_create")
        with patch(
            f"{MODULE}.resolve_tool",
            new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=False)),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="todo_create",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                account="work",
            )

        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.UNKNOWN_ACCOUNT
        tool.ainvoke.assert_not_awaited()

    async def test_a_personless_run_cannot_choose_an_account(
        self, account_record: AsyncMock
    ) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)
        tool = _tool()
        with patch(
            f"{MODULE}.resolve_tool",
            new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
        ):
            result = await dispatch_tool(
                user_id=None,
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                account="Personal",
            )

        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.UNKNOWN_ACCOUNT
        tool.ainvoke.assert_not_awaited()

    async def test_an_integration_without_composio_has_no_accounts_to_choose(
        self, account_record: AsyncMock
    ) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)
        tool = _tool()
        with patch(
            f"{MODULE}.get_integration_by_tool_slug",
            return_value=get_integration_by_id("perplexity"),
        ):
            result = await _dispatch_send("Personal", tool)

        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.UNKNOWN_ACCOUNT
        tool.ainvoke.assert_not_awaited()

    async def test_the_chosen_account_joins_the_callers_metadata(
        self, account_record: AsyncMock
    ) -> None:
        """Composio wrappers read the user from metadata, so pinning an account must not drop it."""
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=dispatch_config_for("u1"),
                account="Personal",
            )

        assert tool.ainvoke.await_args.kwargs["config"]["metadata"] == {
            "user_id": "u1",
            "composio_account": {"toolkit": "GMAIL", "connected_account_id": "ca_personal"},
        }

    async def test_the_usage_event_says_how_many_accounts_and_whether_primary(
        self, account_record: AsyncMock
    ) -> None:
        account_record.return_value = _gmail_accounts(WORK, PERSONAL)
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                account="Personal",
            )

        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.TOOL_USED,
            {
                "tool_name": "GMAIL_SEND_EMAIL",
                "via": "execute",
                "account_count": 2,
                "account_is_primary": False,
            },
        )


@pytest.mark.unit
class TestDispatchTool:
    async def test_unknown_tool_is_structured_and_never_invokes(self) -> None:
        with (
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1", tool_name="NOPE_TOOL", data={}, config=CONFIG
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.UNKNOWN_TOOL
        # Failure is its own event, attributed to the user, with the reason.
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "NOPE_TOOL", "reason": "unknown_tool"},
        )

    async def test_invalid_args_fail_loud_with_pydantic_detail_and_never_invoke(self) -> None:
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c"},  # subject missing
                config=CONFIG,
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.INVALID_ARGS
        assert "subject" in result.error.detail
        tool.ainvoke.assert_not_awaited()
        # The retry-ratio numerator: every validation failure is captured.
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "GMAIL_SEND_EMAIL", "reason": "invalid_args"},
        )

    async def test_valid_args_invoke_with_coerced_supplied_fields_only(self) -> None:
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is True
        assert result.output == {"status": "sent"}
        # exclude_unset: the tool keeps ownership of its own defaults.
        tool.ainvoke.assert_awaited_once_with(
            {"recipient": "a@b.c", "subject": "hi"}, config=CONFIG
        )
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.TOOL_USED,
            {"tool_name": "GMAIL_SEND_EMAIL", "via": "execute"},
        )

    async def test_dict_schema_tool_invokes_with_raw_data(self) -> None:
        tool = _tool(name="MCP_DICT_TOOL", schema={"type": "object"})
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            result = await dispatch_tool(
                user_id="u1", tool_name="MCP_DICT_TOOL", data={"q": 1}, config=CONFIG
            )
        assert result.ok is True
        tool.ainvoke.assert_awaited_once_with({"q": 1}, config=CONFIG)

    async def test_personless_run_skips_analytics_but_still_executes(self) -> None:
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id=None,
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is True
        capture.assert_not_called()


@pytest.mark.unit
class TestObservedShapeRecording:
    async def test_a_successful_integration_dispatch_records_the_output_shape(self) -> None:
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.record_observed_shape") as record,
            patch(f"{MODULE}.spawn_logged_task") as spawn,
        ):
            await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        record.assert_called_once_with("GMAIL_SEND_EMAIL", {"status": "sent"}, scope="global")
        spawn.assert_called_once()

    async def test_internal_tools_and_failures_record_nothing(self) -> None:
        tool = _tool(name="create_todo")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool("create_todo", tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task") as spawn,
        ):
            await dispatch_tool(
                user_id="u1",
                tool_name="create_todo",
                data={"recipient": "x", "subject": "y"},
                config=CONFIG,
            )
            await dispatch_tool(  # invalid args: never invoked, never recorded
                user_id="u1", tool_name="create_todo", data={}, config=CONFIG
            )
        spawn.assert_not_called()


@pytest.mark.unit
class TestIntegrationOnlySurface:
    async def test_internal_tool_is_refused_and_never_invoked(self) -> None:
        tool = _tool(name="create_todo")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool("create_todo", tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="create_todo",
                data={"recipient": "x", "subject": "y"},
                config=CONFIG,
                space=ToolSpace(integration_only=True),
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.INTERNAL_TOOL
        tool.ainvoke.assert_not_awaited()

    async def test_internal_tool_still_runs_on_the_graph_surface(self) -> None:
        tool = _tool(name="create_todo")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool("create_todo", tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="create_todo",
                data={"recipient": "x", "subject": "y"},
                config=CONFIG,
            )
        assert result.ok is True


@pytest.mark.unit
class TestSubagentToolSpace:
    """A subagent's tool space must bound the proxy, not just its bindings.

    execute is in every subagent's tool set, and dispatch resolves names
    globally — so without a scope the proxy ran any registered tool by name,
    and the in-band refusal retrieve_tools returns ("They belong to the main
    executor, not this subagent") was advice the model could simply route
    around.
    """

    async def test_a_registered_tool_outside_the_space_is_refused(self) -> None:
        tool = _tool(name="SLACK_SEND_MESSAGE")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="SLACK_SEND_MESSAGE",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                space=ToolSpace(tool_names={"GMAIL_SEND_EMAIL", "read"}),
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.OUT_OF_SCOPE
        tool.ainvoke.assert_not_awaited()
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "SLACK_SEND_MESSAGE", "reason": "out_of_scope"},
        )

    async def test_a_tool_inside_the_space_still_runs(self) -> None:
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                space=ToolSpace(tool_names={"GMAIL_SEND_EMAIL"}),
            )
        assert result.ok is True

    async def test_an_on_demand_tool_outside_the_space_is_also_refused(self) -> None:
        """MCP tools and on-demand catalog slugs resolve outside every tool space, so a scoped subagent must not reach another integration's tool by resolving it on demand — the proxy refuses any resolved name outside the subagent's set, whether or not it came from the registry."""
        tool = _tool(name="notion_mcp_search")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="notion_mcp_search",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                space=ToolSpace(tool_names={"GMAIL_SEND_EMAIL"}),
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.OUT_OF_SCOPE
        tool.ainvoke.assert_not_awaited()
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "notion_mcp_search", "reason": "out_of_scope"},
        )

    async def test_a_subagents_own_on_demand_tool_in_scope_still_runs(self) -> None:
        """No over-refusal: a subagent carries its own MCP/on-demand tools in its tool set by name (every connected MCP tool, its whole registered toolkit), so an unregistered resolution whose name IS in scope runs."""
        tool = _tool(name="notion_mcp_search")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="notion_mcp_search",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                space=ToolSpace(tool_names={"notion_mcp_search"}),
            )
        assert result.ok is True

    async def test_the_executor_is_unscoped(self) -> None:
        tool = _tool(name="SLACK_SEND_MESSAGE")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="SLACK_SEND_MESSAGE",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is True


@pytest.mark.unit
class TestDispatchOutcomeReporting:
    async def test_an_infrastructure_failure_is_never_stamped_ok(self) -> None:
        """Execute.outcome is the migration's health metric."""
        tool = _tool()
        tool.ainvoke = AsyncMock(side_effect=ConnectionError("provider down"))
        stamped: dict[str, object] = {}
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.log") as log,
        ):
            log.set_ns.side_effect = lambda _ns, **kw: stamped.update(kw)
            with pytest.raises(ConnectionError):
                await dispatch_tool(
                    user_id="u1",
                    tool_name="GMAIL_SEND_EMAIL",
                    data={"recipient": "a@b.c", "subject": "hi"},
                    config=CONFIG,
                )
        # The tool is named (an infra failure must say which one), the outcome is not.
        assert stamped == {"tool": "GMAIL_SEND_EMAIL"}

    async def test_a_hung_tool_is_bounded_and_reported_as_unknown_effect(self) -> None:
        """The sandbox route had no bound of its own, so its client gave up first and the script's retry re-applied a mutation still in flight."""
        tool = _tool()

        async def _never_returns(*_args: object, **_kwargs: object) -> None:
            # Long enough that only the bound can end it, short enough that
            # losing the bound fails this test in seconds rather than hanging
            # until the suite-wide timeout.
            await asyncio.sleep(5)

        tool.ainvoke = AsyncMock(side_effect=_never_returns)
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
            patch(f"{MODULE}.TOOL_EXECUTION_TIMEOUT_SECONDS", 0.01),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.TIMEOUT
        # The model must not read this as "it did not happen".
        assert "may or may not have completed" in result.error.hint
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "GMAIL_SEND_EMAIL", "reason": "timeout"},
        )

    async def test_an_exempt_tool_is_not_bounded(self) -> None:
        """Long-running orchestration tools manage their own lifecycles — the in-graph node exempts them, and a proxied call must not be tighter."""
        tool = _tool(name="deep_research", schema=None)
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(
                    return_value=ResolvedTool("deep_research", tool, is_integration=False)
                ),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.TOOL_EXECUTION_TIMEOUT_SECONDS", 0.01),
        ):
            result = await dispatch_tool(
                user_id="u1", tool_name="deep_research", data={}, config=CONFIG
            )
        assert result.ok is True


def _dispatched(outcome: str) -> float:
    return REGISTRY.get_sample_value("gaia_execute_dispatch_total", {"outcome": outcome}) or 0.0


@dataclass(frozen=True)
class _Refusal:
    tool_name: str
    resolved: ResolvedTool | None
    error: DispatchError
    warning: str
    integration_only: bool = False
    scoped_tool_names: Container[str] | None = None
    data: dict[str, object] = field(default_factory=dict)
    account: str | None = None
    accounts: UserIntegrationDocument | None = None


_INTERNAL = _tool(name="create_todo")
_SLACK = _tool(name="SLACK_SEND_MESSAGE")
_GMAIL = _tool()

REFUSALS = {
    "unknown_tool": _Refusal(
        tool_name="NOPE_TOOL",
        resolved=None,
        error=DispatchError(
            kind=DispatchErrorKind.UNKNOWN_TOOL,
            detail="Unknown tool 'NOPE_TOOL'.",
            hint=(
                "The name must be an exact tool name. Discover tools with "
                "retrieve_tools(query=...) and use the name it returns verbatim."
            ),
        ),
        warning="execute: unknown tool",
    ),
    "internal_tool": _Refusal(
        tool_name="create_todo",
        resolved=ResolvedTool("create_todo", _INTERNAL, is_integration=False),
        error=DispatchError(
            kind=DispatchErrorKind.INTERNAL_TOOL,
            detail="'create_todo' is an internal tool, not an integration tool.",
            hint=(
                "Sandbox scripts can only call integration tools (Gmail, GitHub, "
                "Notion, MCP, ...). Use internal tools from the conversation instead."
            ),
        ),
        warning="execute: internal tool refused on integration-only surface",
        integration_only=True,
    ),
    "ticket_on_sandbox": _Refusal(
        tool_name="approve",
        resolved=None,
        error=DispatchError(
            kind=DispatchErrorKind.INTERNAL_TOOL,
            detail="'approve' is a conversation ticket, not an integration tool.",
            hint=(
                "Approve, revoke, and redeem only from the conversation, never from a "
                "sandbox script."
            ),
        ),
        warning="execute: ticket operation refused on integration-only surface",
        integration_only=True,
        data={"id": "ap_1"},
    ),
    "out_of_scope": _Refusal(
        tool_name="SLACK_SEND_MESSAGE",
        resolved=ResolvedTool("SLACK_SEND_MESSAGE", _SLACK, is_integration=True),
        error=DispatchError(
            kind=DispatchErrorKind.OUT_OF_SCOPE,
            detail="'SLACK_SEND_MESSAGE' is not available inside this subagent.",
            hint=(
                "It belongs to the main executor, not this subagent. Do not retry it; "
                "finish your task here and let the executor handle it."
            ),
        ),
        warning="execute: tool refused outside the calling agent's tool space",
        scoped_tool_names={"GMAIL_SEND_EMAIL"},
    ),
    "invalid_args": _Refusal(
        tool_name="GMAIL_SEND_EMAIL",
        resolved=ResolvedTool("GMAIL_SEND_EMAIL", _GMAIL, is_integration=True),
        error=DispatchError(
            kind=DispatchErrorKind.INVALID_ARGS,
            detail=json.dumps(
                [
                    {
                        "type": "missing",
                        "loc": ["subject"],
                        "msg": "Field required",
                        "input": {"recipient": "a@b.c"},
                    }
                ]
            ),
            hint=(
                "Fix `data` to match the GMAIL_SEND_EMAIL schema shown by retrieve_tools, "
                "then retry."
            ),
        ),
        warning="execute: args failed schema validation",
        data={"recipient": "a@b.c"},
    ),
    "account_on_an_accountless_tool": _Refusal(
        tool_name="create_todo",
        resolved=ResolvedTool("create_todo", _INTERNAL, is_integration=False),
        error=DispatchError(
            kind=DispatchErrorKind.UNKNOWN_ACCOUNT,
            detail="'create_todo' has no connected accounts to choose between.",
            hint="Retry without `account`.",
        ),
        warning="execute: account not usable",
        data={"recipient": "a@b.c", "subject": "hi"},
        account="work",
    ),
    "unknown_account": _Refusal(
        tool_name="GMAIL_SEND_EMAIL",
        resolved=ResolvedTool("GMAIL_SEND_EMAIL", _GMAIL, is_integration=True),
        error=DispatchError(
            kind=DispatchErrorKind.UNKNOWN_ACCOUNT,
            detail="No connected Gmail account is called 'boss@acme.com'.",
            hint=(
                'If the user meant one of these, pass it as `account`: "work@acme.com" '
                '(connected), "Personal" (expired). Otherwise ask them which account they meant.'
            ),
        ),
        warning="execute: account not usable",
        data={"recipient": "a@b.c", "subject": "hi"},
        account="boss@acme.com",
        accounts=_gmail_accounts(WORK, PERSONAL.model_copy(update={"status": "expired"})),
    ),
    "expired_account": _Refusal(
        tool_name="GMAIL_SEND_EMAIL",
        resolved=ResolvedTool("GMAIL_SEND_EMAIL", _GMAIL, is_integration=True),
        error=DispatchError(
            kind=DispatchErrorKind.ACCOUNT_EXPIRED,
            detail="The Gmail account Personal needs reconnecting.",
            hint=ACCOUNT_NEEDS_RECONNECT_HINT,
        ),
        warning="execute: account not usable",
        data={"recipient": "a@b.c", "subject": "hi"},
        account="Personal",
        accounts=_gmail_accounts(WORK, PERSONAL.model_copy(update={"status": "expired"})),
    ),
}


@pytest.mark.unit
class TestPredictableFailuresAreFullyReported:
    """Each refusal: the exact correction the model reads, one warning, metric tick, outcome and analytics event."""

    @pytest.mark.parametrize("case", REFUSALS.values(), ids=REFUSALS.keys())
    async def test_a_refusal_is_reported_on_every_channel(
        self, case: _Refusal, account_record: AsyncMock
    ) -> None:
        account_record.return_value = case.accounts
        resolver = AsyncMock(return_value=case.resolved)
        before = _dispatched(str(case.error.kind))
        with (
            patch(f"{MODULE}.resolve_tool", new=resolver),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            async with captured_wide_event() as event:
                result = await dispatch_tool(
                    user_id="u1",
                    tool_name=case.tool_name,
                    data=case.data,
                    config=CONFIG,
                    account=case.account,
                    space=ToolSpace(
                        integration_only=case.integration_only,
                        tool_names=case.scoped_tool_names,
                    ),
                )
        assert result == ToolExecutionResult(
            ok=False, resolved_name=case.tool_name, error=case.error
        )
        (warning,) = event["warnings"]
        assert warning["msg"].endswith(case.warning)
        assert warning["tool_name"] == case.tool_name
        assert event["execute"] == {"tool": case.tool_name, "outcome": str(case.error.kind)}
        assert _dispatched(str(case.error.kind)) == before + 1
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": case.tool_name, "reason": str(case.error.kind)},
        )

    async def test_the_tool_is_resolved_for_the_calling_user(self) -> None:
        resolver = AsyncMock(return_value=None)
        with patch(f"{MODULE}.resolve_tool", new=resolver), patch(f"{MODULE}.capture_event"):
            await dispatch_tool(user_id="u1", tool_name="NOPE_TOOL", data={}, config=CONFIG)
        resolver.assert_awaited_once_with("u1", "NOPE_TOOL")

    async def test_a_timeout_is_counted_and_stamped_as_its_own_outcome(self) -> None:
        tool = _tool()
        tool.ainvoke = AsyncMock(side_effect=TimeoutError)
        before = _dispatched("timeout")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            async with captured_wide_event() as event:
                result = await dispatch_tool(
                    user_id="u1",
                    tool_name="GMAIL_SEND_EMAIL",
                    data={"recipient": "a@b.c", "subject": "hi"},
                    config=CONFIG,
                )
        assert result.error is not None
        assert result.error.hint == (
            "The operation may or may not have completed on the provider side. "
            "Verify its effect before retrying — an identical retry can duplicate it."
        )
        assert event["execute"] == {"tool": "GMAIL_SEND_EMAIL", "outcome": "timeout"}
        assert _dispatched("timeout") == before + 1


@pytest.mark.unit
class TestSuccessReporting:
    async def test_a_successful_run_is_stamped_counted_and_learned_from(self) -> None:
        tool = _tool()
        before = _dispatched("ok")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task") as spawn,
        ):
            async with captured_wide_event() as event:
                await dispatch_tool(
                    user_id="u1",
                    tool_name="GMAIL_SEND_EMAIL",
                    data={"recipient": "a@b.c", "subject": "hi"},
                    config=CONFIG,
                )
        assert event["execute"] == {"tool": "GMAIL_SEND_EMAIL", "outcome": "ok"}
        assert _dispatched("ok") == before + 1
        operation, learn = spawn.call_args.args
        learn.close()
        assert operation == "record_tool_output_shape"
        assert spawn.call_args.kwargs == {"tool_name": "GMAIL_SEND_EMAIL"}

    async def test_an_honored_ticket_counts_as_an_ok_dispatch(self) -> None:
        before = _dispatched("ok")
        with patch(
            "app.services.hil.ledger_decide.revoke_ticket",
            new=AsyncMock(return_value="Revoked 'ap_1'."),
        ):
            await dispatch_tool(
                user_id="u1", tool_name="revoke", data={"id": "ap_1"}, config=CONFIG
            )
        assert _dispatched("ok") == before + 1


class _ScheduleArgs(BaseModel):
    when: datetime
    title: str

    @field_validator("title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title is blank")
        return value


@pytest.mark.unit
class TestArgsValidation:
    async def test_validated_args_reach_the_tool_as_json_values(self) -> None:
        tool = _tool(name="CAL_CREATE", schema=_ScheduleArgs)
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            await dispatch_tool(
                user_id="u1",
                tool_name="CAL_CREATE",
                data={"when": "2026-01-02T03:04:05", "title": "sync"},
                config=CONFIG,
            )
        tool.ainvoke.assert_awaited_once_with(
            {"when": "2026-01-02T03:04:05", "title": "sync"}, config=CONFIG
        )

    async def test_a_validator_error_detail_is_plain_json_without_doc_links(self) -> None:
        tool = _tool(name="CAL_CREATE", schema=_ScheduleArgs)
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="CAL_CREATE",
                data={"when": "2026-01-02T03:04:05", "title": " "},
                config=CONFIG,
            )
        assert result.error is not None
        (error,) = json.loads(result.error.detail)
        assert error["msg"] == "Value error, title is blank"
        assert error["ctx"] == {"error": "title is blank"}
        assert "url" not in error
