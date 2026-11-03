"""invoke_tool: an integration only the user can fix gets one connect card, then its calls are refused."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
import pytest

from app.agents.tools.invocation import IntegrationBlockedError, invoke_tool
from app.agents.tools.run_record import read_run_record
from app.constants.integrations import ConnectMode
from app.db.repositories.user_integrations import user_integration_repository
from app.services.integrations.integration_accounts import toolkit_not_connected
from app.utils.errors import IntegrationNotConnectedError
from app.utils.integration_checker import request_integration_connection

STREAM_ID = "stream-block"
USER_ID = "user-block"
CONFIG: RunnableConfig = {
    "configurable": {"stream_id": STREAM_ID, "user_id": USER_ID, "source_category": "ui"}
}
CHECKER = "app.utils.integration_checker"


@contextmanager
def _ui_run(*, expired: bool = False) -> Iterator[MagicMock]:
    """Run inside the graph run the connect card is written into, yielding its stream writer."""
    writer = MagicMock()
    with (
        patch(f"{CHECKER}.get_config", return_value=CONFIG),
        patch(f"{CHECKER}.current_stream_writer", return_value=writer),
        patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=expired)),
    ):
        yield writer


def _gmail_tool(calls: list[str]) -> BaseTool:
    """Build a Gmail tool whose account pin finds nothing connected, counting calls that reach it."""

    @tool("GMAIL_FETCH_MESSAGES")
    async def fetch(query: str) -> str:
        """Fetch messages."""
        calls.append(query)
        raise toolkit_not_connected("GMAIL", "This integration has no connected account")

    return fetch


def _cards(writer: MagicMock) -> list[dict[str, Any]]:
    return [
        call.args[0]["integration_connection_required"]
        for call in writer.call_args_list
        if "integration_connection_required" in call.args[0]
    ]


@pytest.mark.regression
async def test_a_second_call_to_a_blocked_integration_is_refused_without_reaching_it(
    fake_redis: Any,
) -> None:
    """Regression: one chat made 16 GMAIL_FETCH_MESSAGES calls against an unconnected Gmail."""
    calls: list[str] = []
    gmail = _gmail_tool(calls)

    with _ui_run() as writer:
        first = await invoke_tool(gmail, {"query": "one"}, CONFIG)
        with pytest.raises(IntegrationBlockedError, match="was not sent"):
            await invoke_tool(gmail, {"query": "two"}, CONFIG)

    assert calls == ["one"]
    assert isinstance(first, str)
    assert first.startswith("Gmail needs to be connected.")
    assert "do not call any Gmail tool again this run" in first
    (card,) = _cards(writer)
    assert (card["integration_id"], card["expired"]) == ("gmail", False)
    recorded = await read_run_record(STREAM_ID)
    assert [(c.args, c.failed) for c in recorded] == [
        ({"query": "one"}, True),
        ({"query": "two"}, True),
    ]


async def test_another_integration_in_the_same_run_still_runs(fake_redis: Any) -> None:
    calls: list[str] = []

    @tool("NOTION_SEARCH")
    async def notion(query: str) -> str:
        """Search Notion."""
        calls.append(query)
        return "found"

    with _ui_run():
        await invoke_tool(_gmail_tool([]), {"query": "one"}, CONFIG)
        assert await invoke_tool(notion, {"query": "x"}, CONFIG) == "found"

    assert calls == ["x"]


async def test_a_graph_tool_call_is_answered_with_an_error_tool_message(fake_redis: Any) -> None:
    gmail = _gmail_tool([])
    call = {"type": "tool_call", "id": "call-1", "name": gmail.name, "args": {"query": "q"}}

    with _ui_run():
        answer = await invoke_tool(gmail, call, CONFIG)

    assert isinstance(answer, ToolMessage)
    assert (answer.tool_call_id, answer.name, answer.status) == ("call-1", gmail.name, "error")
    assert "Gmail needs to be connected." in str(answer.content)


async def test_an_mcp_server_rejecting_its_token_asks_for_a_reconnect(fake_redis: Any) -> None:
    @tool("list_meetings")
    async def list_meetings(limit: int) -> str:
        """List meetings."""
        raise IntegrationNotConnectedError(
            integration_id="readai",
            integration_name="Read.ai",
            why="401",
            grant_died=True,
        )

    list_meetings.metadata = {"integration_id": "readai", "integration_name": "Read.ai"}

    with (
        _ui_run() as writer,
        patch(
            f"{CHECKER}._standalone_mcp_auth",
            AsyncMock(return_value=MagicMock(kind="unavailable", url=None)),
        ),
    ):
        await invoke_tool(list_meetings, {"limit": 5}, CONFIG)
        with pytest.raises(IntegrationBlockedError):
            await invoke_tool(list_meetings, {"limit": 5}, CONFIG)

    (card,) = _cards(writer)
    assert (card["integration_id"], card["expired"]) == ("readai", True)


async def test_the_connect_card_is_shown_once_per_run(fake_redis: Any) -> None:
    """Activation, a handoff and a tool call can each ask; the user sees one card."""
    with _ui_run() as writer:
        first = await request_integration_connection("gmail", "Gmail", USER_ID)
        again = await request_integration_connection("gmail", "Gmail", USER_ID)

    assert len(_cards(writer)) == 1
    assert first == again


async def test_adding_an_account_does_not_block_the_integration(fake_redis: Any) -> None:
    calls: list[str] = []

    @tool("GMAIL_SEND_EMAIL")
    async def send(to: str) -> str:
        """Send an email."""
        calls.append(to)
        return "sent"

    with (
        _ui_run(),
        patch(f"{CHECKER}._connected_account_names", AsyncMock(return_value=["me@x.com"])),
    ):
        from_mode = await request_integration_connection(
            "gmail",
            "Gmail",
            USER_ID,
            mode=ConnectMode.ADD_ACCOUNT,
        )
        assert await invoke_tool(send, {"to": "a@b.c"}, CONFIG) == "sent"

    assert from_mode
    assert calls == ["a@b.c"]


@pytest.mark.parametrize(
    "surface",
    [
        {"source_category": "bot"},
        {"source_category": "ui", "execution_mode": "background"},
    ],
    ids=["bot", "workflow"],
)
async def test_bot_and_workflow_runs_stop_calling_the_integration_too(
    fake_redis: Any, surface: dict[str, str]
) -> None:
    """No card travels on these surfaces, but the run still stops calling the integration."""
    calls: list[str] = []
    gmail = _gmail_tool(calls)
    config: RunnableConfig = {
        "configurable": {"stream_id": STREAM_ID, "user_id": USER_ID, **surface}
    }

    with (
        patch(f"{CHECKER}.get_config", return_value=config),
        patch(f"{CHECKER}.current_stream_writer", return_value=MagicMock()),
        patch(f"{CHECKER}.build_connect_link_url", AsyncMock(return_value=None)),
        patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=False)),
    ):
        await invoke_tool(gmail, {"query": "one"}, config)
        with pytest.raises(IntegrationBlockedError):
            await invoke_tool(gmail, {"query": "two"}, config)

    assert calls == ["one"]
