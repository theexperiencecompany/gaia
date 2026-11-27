"""connect_integration on a custom MCP server the user already added, which is not in the catalog."""

from collections.abc import Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.integration_tool import connect_integration
from app.constants.integrations import ConnectMode

USER_ID = "507f1f77bcf86cd799439011"
DODO_ID = "86284fb1-d7cc-48fb-86b5-4faca8a09e15"
MODULE = "app.agents.tools.integration_tool"


@dataclass(frozen=True)
class Seams:
    repo: MagicMock
    user_repo: MagicMock
    request_card: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    repo = MagicMock()
    repo.get_custom = AsyncMock(
        return_value=SimpleNamespace(integration_id=DODO_ID, name="Dodo Payments")
    )
    user_repo = MagicMock()
    user_repo.exists = AsyncMock(return_value=True)
    user_repo.is_connected = AsyncMock(return_value=True)
    with (
        patch(f"{MODULE}.current_stream_writer", return_value=MagicMock()),
        patch("app.config.oauth_config.OAUTH_INTEGRATIONS", []),
        patch(f"{MODULE}.integration_repository", repo),
        patch(f"{MODULE}.user_integration_repository", user_repo),
        patch(
            f"{MODULE}.request_integration_connection",
            new_callable=AsyncMock,
            return_value="card shown",
        ) as request_card,
    ):
        yield Seams(repo=repo, user_repo=user_repo, request_card=request_card)


async def _connect(mode: ConnectMode) -> str:
    return await connect_integration.ainvoke(
        {"integration_ids": [DODO_ID], "mode": mode}, config={"configurable": {"user_id": USER_ID}}
    )


async def test_reconnect_on_an_added_custom_server_gets_a_fresh_link_without_re_adding_it(
    seams: Seams,
) -> None:
    result = await _connect(ConnectMode.RECONNECT)

    assert result == "card shown"
    seams.request_card.assert_awaited_once_with(
        DODO_ID, "Dodo Payments", USER_ID, mode=ConnectMode.RECONNECT
    )
    seams.user_repo.exists.assert_awaited_once_with(USER_ID, DODO_ID)
    seams.repo.get_custom.assert_awaited_once_with(DODO_ID)


async def test_a_custom_server_does_not_stop_the_ids_after_it(seams: Seams) -> None:
    seams.user_repo.exists.side_effect = lambda _user, iid: iid == DODO_ID

    result = await connect_integration.ainvoke(
        {"integration_ids": [DODO_ID, "nope"], "mode": ConnectMode.RECONNECT},
        config={"configurable": {"user_id": USER_ID}},
    )

    assert result.splitlines()[0] == "card shown"
    assert result.splitlines()[1].startswith("❌ 'nope' not found.")


async def test_connect_on_a_connected_custom_server_reports_it_and_shows_no_card(
    seams: Seams,
) -> None:
    result = await _connect(ConnectMode.CONNECT)

    assert result == "✅ Dodo Payments is already added and connected."
    seams.request_card.assert_not_awaited()


async def test_connect_on_a_signed_out_custom_server_shows_the_card(seams: Seams) -> None:
    seams.user_repo.is_connected.return_value = False

    result = await _connect(ConnectMode.CONNECT)

    assert result == "card shown"
    seams.request_card.assert_awaited_once_with(
        DODO_ID, "Dodo Payments", USER_ID, mode=ConnectMode.CONNECT
    )


async def test_add_account_on_a_custom_server_says_it_holds_one_account(seams: Seams) -> None:
    result = await _connect(ConnectMode.ADD_ACCOUNT)

    assert result == "Dodo Payments connects a single account; it cannot have several."
    seams.request_card.assert_not_awaited()


async def test_a_custom_server_the_user_never_added_is_not_found(seams: Seams) -> None:
    seams.user_repo.exists.return_value = False

    result = await _connect(ConnectMode.RECONNECT)

    assert result.startswith(f"❌ '{DODO_ID}' not found.")
    seams.repo.get_custom.assert_not_awaited()
    seams.request_card.assert_not_awaited()
