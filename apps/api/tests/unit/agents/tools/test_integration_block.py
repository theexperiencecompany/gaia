"""invoke_tool: an integration only the user can fix gets one connect card, then its calls are refused.

Symbols the fix adds are reached through their modules: the regression lane replays the
marked tests on the base revision, where a from-import would break collection instead of
failing the test.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
import pytest

from app.agents.core.subagents.integration_activation import activate_integration
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.tools import invocation, run_record
from app.agents.tools.invocation import invoke_tool, invoke_tool_sync
from app.agents.tools.run_record import read_run_record
from app.constants import cache
from app.constants.integrations import ConnectMode
from app.db.repositories.user_integrations import user_integration_repository
from app.services.integrations import integration_accounts
from app.utils import errors
from app.utils.integration_checker import request_integration_connection

STREAM_ID = "stream-block"
USER_ID = "user-block"
CONFIG: RunnableConfig = {
    "configurable": {"stream_id": STREAM_ID, "user_id": USER_ID, "source_category": "ui"}
}
CHECKER = "app.utils.integration_checker"
ACTIVATION = "app.agents.core.subagents.integration_activation"
RESOLUTION = "app.agents.core.subagents.integration_resolution"
INVOCATION = "app.agents.tools.invocation"
BLOCKED_GMAIL = (
    "'gmail' is not connected and the user was already shown how to connect it this run, so "
    "this call was not sent. Do not call gmail again this run; finish the rest of the task and "
    "say what is waiting on the connection."
)


@contextmanager
def _ui_run(*, expired: bool = False) -> Iterator[MagicMock]:
    """Run inside the graph run the connect card is written into, yielding its stream writer."""
    writer = MagicMock()

    async def _is_expired(user_id: str, _integration_id: str) -> bool:
        # Checks who it is asked about: a card for no user would read every grant as new.
        assert user_id == USER_ID
        return expired

    with (
        patch(f"{CHECKER}.get_config", return_value=CONFIG),
        patch(f"{CHECKER}.current_stream_writer", return_value=writer),
        patch.object(user_integration_repository, "is_expired", AsyncMock(side_effect=_is_expired)),
    ):
        yield writer


def _gmail_tool(calls: list[str]) -> BaseTool:
    """Build a Gmail tool whose account pin finds nothing connected, counting calls that reach it."""

    @tool("GMAIL_FETCH_MESSAGES")
    async def fetch(query: str) -> str:
        """Fetch messages."""
        calls.append(query)
        raise integration_accounts.toolkit_not_connected(
            "GMAIL", "This integration has no connected account"
        )

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

    # A Composio error already names its integration; a lookup would rename the card.
    elsewhere = MagicMock(managed_by="composio")
    elsewhere.name = "Looked Up"
    with (
        _ui_run() as writer,
        patch(f"{INVOCATION}.IntegrationResolver.resolve", AsyncMock(return_value=elsewhere)),
    ):
        first = await invoke_tool(gmail, {"query": "one"}, CONFIG)
        with pytest.raises(invocation.IntegrationBlockedError) as refused:
            await invoke_tool(gmail, {"query": "two"}, CONFIG)

    assert str(refused.value) == BLOCKED_GMAIL

    assert calls == ["one"]
    assert isinstance(first, str)
    assert first.startswith("Gmail needs to be connected.")
    assert "do not call any Gmail tool again this run" in first
    (card,) = _cards(writer)
    assert (card["integration_id"], card["integration_name"], card["expired"]) == (
        "gmail",
        "Gmail",
        False,
    )


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
        raise errors.IntegrationNotConnectedError(
            integration_id="readai",
            integration_name=None,
            why="401",
            grant_died=True,
        )

    list_meetings.metadata = {"integration_id": "readai"}
    resolved = MagicMock()
    resolved.name = "Read.ai"

    with (
        _ui_run() as writer,
        patch(
            f"{INVOCATION}.IntegrationResolver.resolve", AsyncMock(return_value=resolved)
        ) as lookup,
        patch(
            f"{CHECKER}._standalone_mcp_auth",
            AsyncMock(return_value=MagicMock(kind="unavailable", url=None)),
        ),
    ):
        await invoke_tool(list_meetings, {"limit": 5}, CONFIG)
        with pytest.raises(invocation.IntegrationBlockedError):
            await invoke_tool(list_meetings, {"limit": 5}, CONFIG)

    lookup.assert_awaited_once_with("readai")
    (card,) = _cards(writer)
    assert (card["integration_id"], card["integration_name"], card["expired"]) == (
        "readai",
        "Read.ai",
        True,
    )


async def test_the_connect_card_is_shown_once_per_run(fake_redis: Any) -> None:
    """Activation and a tool call can each ask; the user sees one card."""
    with _ui_run() as writer:
        first = await request_integration_connection("gmail", "Gmail", USER_ID)
        again = await request_integration_connection("gmail", "Gmail", USER_ID)

    assert len(_cards(writer)) == 1
    assert first == again


async def test_activating_an_unconnected_integration_blocks_its_calls(fake_redis: Any) -> None:
    """activate_integration is where an unconnected integration shows its card in a chat."""
    calls: list[str] = []
    activation_call = {
        "type": "tool_call",
        "id": "call-activate",
        "name": "activate_integration",
        "args": {"integration_id": "gmail"},
    }

    with (
        _ui_run() as writer,
        patch(
            f"{ACTIVATION}.get_integration_target",
            AsyncMock(return_value=get_subagent_by_id("gmail")),
        ),
        patch(f"{RESOLUTION}.check_integration_status", AsyncMock(return_value=False)),
    ):
        await activate_integration.ainvoke(activation_call, CONFIG)
        with pytest.raises(invocation.IntegrationBlockedError):
            await invoke_tool(_gmail_tool(calls), {"query": "q"}, CONFIG)

    assert calls == []
    (card,) = _cards(writer)
    assert card["integration_id"] == "gmail"


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
        with pytest.raises(invocation.IntegrationBlockedError):
            await invoke_tool(gmail, {"query": "two"}, config)

    assert calls == ["one"]


async def test_a_workflow_run_records_both_blocked_calls_as_failed(fake_redis: Any) -> None:
    config: RunnableConfig = {
        "configurable": {"stream_id": STREAM_ID, "user_id": USER_ID, "workflow_id": "wf-block"}
    }

    with (
        patch(f"{CHECKER}.get_config", return_value=config),
        patch(f"{CHECKER}.current_stream_writer", return_value=MagicMock()),
        patch(f"{CHECKER}.build_connect_link_url", AsyncMock(return_value=None)),
        patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=False)),
    ):
        first = await invoke_tool(_gmail_tool([]), {"query": "one"}, config)
        with pytest.raises(invocation.IntegrationBlockedError) as refused:
            await invoke_tool(_gmail_tool([]), {"query": "two"}, config)

    recorded = await read_run_record(STREAM_ID)
    assert [(c.args, c.failed) for c in recorded] == [
        ({"query": "one"}, True),
        ({"query": "two"}, True),
    ]
    assert recorded[0].result_digest == first
    assert recorded[1].result_digest == f"Error: IntegrationBlockedError: {refused.value}"


async def test_a_call_with_no_user_behind_it_gets_the_error_and_no_card(fake_redis: Any) -> None:
    """A trigger option lookup has nobody to show a card to."""
    config: RunnableConfig = {"configurable": {"stream_id": STREAM_ID}}

    with _ui_run() as writer:
        answer = await invoke_tool(_gmail_tool([]), {"query": "q"}, config)

    assert answer == "Gmail is not connected. Reconnect it to continue."
    assert _cards(writer) == []


async def test_a_graph_tool_call_without_an_id_is_answered_with_an_empty_one(
    fake_redis: Any,
) -> None:
    gmail = _gmail_tool([])
    call = {"type": "tool_call", "id": None, "name": gmail.name, "args": {"query": "q"}}

    with _ui_run():
        answer = await invoke_tool(gmail, call, CONFIG)

    assert isinstance(answer, ToolMessage)
    assert answer.tool_call_id == ""


def test_the_sync_twin_refuses_a_blocked_integration_too(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(run_record, "_sync_client", lambda: client)
    client.sadd(f"{cache.RUN_BLOCKED_INTEGRATIONS_PREFIX}{STREAM_ID}", "gmail")
    calls: list[str] = []

    @tool("GMAIL_SEND_EMAIL")
    def send(to: str) -> str:
        """Send an email."""
        calls.append(to)
        return "sent"

    with pytest.raises(invocation.IntegrationBlockedError) as refused:
        invoke_tool_sync(send, {"to": "a@b.c"}, CONFIG)

    assert str(refused.value) == BLOCKED_GMAIL
    assert calls == []
