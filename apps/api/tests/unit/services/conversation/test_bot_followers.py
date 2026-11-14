"""list_active_bot_conversations: which bot conversations a restarted bot follows, and from where."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.conversation import ACTIVE_BOT_CONVERSATIONS_LIMIT
from app.db.repositories.conversation_log import SweepHead
from app.models.bot_models import BotSessionDocument
from app.models.conversation_send_models import ActiveBotConversation
from app.services.conversation.bot_followers import list_active_bot_conversations
from tests.unit.services.conversation.log_helpers import EMPTY, logged, notice, settled, user

MODULE = "app.services.conversation.bot_followers"


def _head(conversation_id: str, settled_through: int) -> SweepHead:
    return SweepHead(
        cursor=f"cur-{conversation_id}",
        conversation_id=conversation_id,
        user_id=f"user-{conversation_id}",
        has_outbox=False,
        state=EMPTY.model_copy(update={"settled_through": settled_through}),
    )


def _session(conversation_id: str, platform: str, channel_id: str | None) -> BotSessionDocument:
    return BotSessionDocument(
        session_key=f"{platform}:{conversation_id}",
        conversation_id=conversation_id,
        platform=platform,
        platform_user_id=f"pu-{conversation_id}",
        channel_id=channel_id,
    )


@pytest.fixture
def ports() -> Iterator[SimpleNamespace]:
    log = SimpleNamespace(read_after=AsyncMock(return_value=[]))
    ports = SimpleNamespace(log=log)
    with patch(f"{MODULE}.runtime_ports", return_value=ports):
        yield ports


@pytest.fixture
def heads() -> Iterator[AsyncMock]:
    with patch(f"{MODULE}.conversation_log_repository") as repo:
        repo.list_live_heads = AsyncMock(return_value=[])
        yield repo.list_live_heads


@pytest.fixture
def sessions() -> Iterator[AsyncMock]:
    with patch(f"{MODULE}.bot_session_repository") as repo:
        repo.get_by_conversation_id = AsyncMock(return_value=None)
        yield repo.get_by_conversation_id


async def test_it_lists_the_platforms_sessions_from_their_newest_settled_reply(
    ports: SimpleNamespace, heads: AsyncMock, sessions: AsyncMock
) -> None:
    heads.return_value = [_head("dm", 3), _head("group", 6)]
    by_conversation = {
        "dm": _session("dm", "telegram", None),
        "group": _session("group", "telegram", "chan-9"),
    }
    sessions.side_effect = lambda conversation_id: by_conversation[conversation_id]
    reads = {
        "dm": [
            logged(4, settled("s4", ["u1"], 3)),
            logged(5, notice("n5")),
            logged(8, settled("s8", ["u2"], 7)),
            logged(9, user("u9")),
        ],
        "group": [logged(7, user("u7"))],
    }
    ports.log.read_after.side_effect = lambda conversation_id, _user, _since: reads[conversation_id]

    active = await list_active_bot_conversations("telegram")

    heads.assert_awaited_once_with("telegram", ACTIVE_BOT_CONVERSATIONS_LIMIT)
    assert active == [
        ActiveBotConversation(
            conversation_id="dm",
            platform_user_id="pu-dm",
            channel_id=None,
            is_dm=True,
            after_seq=8,
        ),
        ActiveBotConversation(
            conversation_id="group",
            platform_user_id="pu-group",
            channel_id="chan-9",
            is_dm=False,
            after_seq=6,
        ),
    ]
    assert [call.args for call in ports.log.read_after.await_args_list] == [
        ("dm", "user-dm", 3),
        ("group", "user-group", 6),
    ]


async def test_a_head_without_this_platforms_session_is_skipped(
    ports: SimpleNamespace, heads: AsyncMock, sessions: AsyncMock
) -> None:
    heads.return_value = [_head("none", 0), _head("slack", 0), _head("ok", 2)]
    by_conversation = {
        "none": None,
        "slack": _session("slack", "slack", None),
        "ok": _session("ok", "telegram", None),
    }
    sessions.side_effect = lambda conversation_id: by_conversation[conversation_id]

    active = await list_active_bot_conversations("telegram")

    assert [item.conversation_id for item in active] == ["ok"]
    assert active[0].after_seq == 2
