"""list_active_bot_conversations: what a restarted bot follows again, from where it got to."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.conversation import ACTIVE_BOT_CONVERSATIONS_LIMIT
from app.db.repositories.conversation_log import SweepHead
from app.models.bot_models import BotDelivery, BotSessionDocument
from app.services.conversation.bot_followers import list_active_bot_conversations
from app.services.conversation.runtime import install_runtime_ports
from tests.unit.services.conversation.log_helpers import fold, replied, user
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

FOLLOWERS = "app.services.conversation.bot_followers"
USER = "user-1"


def _session(
    conversation_id: str, platform: str, delivery: BotDelivery | None
) -> BotSessionDocument:
    return BotSessionDocument(
        session_key=f"{platform}:{conversation_id}",
        conversation_id=conversation_id,
        platform=platform,
        platform_user_id="556677",
        delivery=delivery,
    )


@dataclass
class Store:
    owed: list[BotSessionDocument]
    heads: list[SweepHead]
    sessions: dict[str, BotSessionDocument]
    asked: list[tuple[str, str, int]]

    def list_owed(self, platform: str, limit: int) -> list[BotSessionDocument]:
        self.asked.append(("owed", platform, limit))
        return self.owed

    def list_heads(self, platform: str, limit: int) -> list[SweepHead]:
        self.asked.append(("heads", platform, limit))
        return self.heads


@pytest.fixture
def store() -> Iterator[Store]:
    store = Store(owed=[], heads=[], sessions={}, asked=[])
    with (
        patch(
            f"{FOLLOWERS}.bot_session_repository.list_owed",
            new=AsyncMock(side_effect=store.list_owed),
        ),
        patch(
            f"{FOLLOWERS}.bot_session_repository.get_by_conversation_id",
            new=AsyncMock(side_effect=store.sessions.get),
        ),
        patch(
            f"{FOLLOWERS}.conversation_log_repository.list_live_heads",
            new=AsyncMock(side_effect=store.list_heads),
        ),
    ):
        yield store


async def _head(runtime: Runtime, conversation_id: str, settled_through: int) -> SweepHead:
    entries = [user("u1"), *replied("s1", ["u1"], 1), user("u2"), *replied("s2", ["u2"], 4)]
    for entry in entries:
        await runtime.log.append(conversation_id, USER, entry)
    state, _ = fold(entries)
    return SweepHead(
        cursor="c",
        conversation_id=conversation_id,
        user_id=USER,
        has_outbox=False,
        state=state.model_copy(update={"settled_through": settled_through}),
    )


async def test_an_owed_session_resumes_from_its_recorded_cursor(store: Store) -> None:
    store.owed = [_session("conv-owed", "telegram", BotDelivery(delivered_seq=5))]

    (active,) = await list_active_bot_conversations("telegram")

    assert (active.conversation_id, active.after_seq) == ("conv-owed", 5)
    assert store.asked == [
        ("owed", "telegram", ACTIVE_BOT_CONVERSATIONS_LIMIT),
        ("heads", "telegram", ACTIVE_BOT_CONVERSATIONS_LIMIT),
    ]


async def test_a_live_session_that_has_a_cursor_resumes_from_it(store: Store) -> None:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    store.heads = [await _head(runtime, "conv-live", settled_through=1)]
    store.sessions["conv-live"] = _session("conv-live", "telegram", BotDelivery(delivered_seq=4))

    (active,) = await list_active_bot_conversations("telegram")

    assert (active.conversation_id, active.after_seq) == ("conv-live", 4)


async def test_a_live_session_with_nothing_settled_since_resumes_where_the_log_had_settled(
    store: Store,
) -> None:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    store.heads = [await _head(runtime, "conv-live", settled_through=6)]
    store.sessions["conv-live"] = _session("conv-live", "telegram", None)

    (active,) = await list_active_bot_conversations("telegram")

    assert active.after_seq == 6


async def test_a_live_session_with_no_cursor_resumes_after_its_newest_settled_reply(
    store: Store,
) -> None:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    store.heads = [await _head(runtime, "conv-live", settled_through=1)]
    store.sessions["conv-live"] = _session("conv-live", "telegram", None)

    (active,) = await list_active_bot_conversations("telegram")

    assert (active.conversation_id, active.after_seq) == ("conv-live", 6)


async def test_a_live_head_is_followed_once_and_only_on_its_own_platform(store: Store) -> None:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    store.owed = [_session("conv-owed", "telegram", BotDelivery(delivered_seq=5))]
    store.heads = [
        await _head(runtime, "conv-owed", settled_through=1),
        await _head(runtime, "conv-discord", settled_through=1),
        await _head(runtime, "conv-gone", settled_through=1),
        await _head(runtime, "conv-live", settled_through=1),
    ]
    store.sessions["conv-discord"] = _session("conv-discord", "discord", None)
    store.sessions["conv-live"] = _session("conv-live", "telegram", None)

    active = await list_active_bot_conversations("telegram")

    assert [(a.conversation_id, a.after_seq) for a in active] == [
        ("conv-owed", 5),
        ("conv-live", 6),
    ]
