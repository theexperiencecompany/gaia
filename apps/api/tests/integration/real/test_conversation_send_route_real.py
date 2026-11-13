"""POST /conversations/{id}/messages accepts into the step at once, checked against real MongoDB."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from redis.asyncio import Redis

from app.api.v1.middleware.auth import PostHogRequestContextMiddleware
from app.constants.analytics import POSTHOG_SESSION_HEADER
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.bot_models import BotChatRequest
from app.models.chat_models import ConversationSource
from app.models.conversation_frame_models import ConversationUpdatedFrame, StateFrame
from app.models.conversation_log_models import BargeIn, DisplayState, UserMessage
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.conversation.composition import RuntimeEffects
from app.services.conversation.event_stream import RedisStreamFrames
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.reply_files import ReplyFile
from app.services.conversation.runtime import install_runtime_ports, runtime_ports
from app.services.conversation.send import submit_bot_message
from shared.py.analytics.catalog.chat import ChatMessageSubmitted
from shared.py.wide_events import _spawned_tasks
from tests.conftest import FAKE_USER
from tests.helpers import log_history
from tests.unit.services.conversation.runtime_doubles import (
    EffectCall,
    RecordingEffects,
    RecordingFrames,
    ScriptedApprovals,
    ScriptedRunner,
    TickGate,
)

pytestmark = pytest.mark.service


async def _no_tick() -> None:
    return None


@dataclass(frozen=True)
class Sends:
    """The route's recorded effects, and its analytics capture."""

    effects: RecordingEffects
    frames: RecordingFrames
    captured: MagicMock


@pytest.fixture
def sends(conversations_collection: object, real_redis: Redis) -> Iterator[Sends]:
    """Install the real Mongo log behind recording effects, and clear the gates the route charges."""
    recorded = RecordingEffects()
    frames = RecordingFrames()
    ticks = TickGate()
    install_runtime_ports(
        RuntimePorts(
            log=MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC)),
            runner=ScriptedRunner(ticks),
            frames=frames,
            effects=recorded,
            approvals=ScriptedApprovals(),
            clock=lambda: datetime.now(UTC),
            tick=_no_tick,
        )
    )
    with (
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.services.conversation.send.enforce_cost_budget", new_callable=AsyncMock),
        patch("app.services.conversation.send.capture") as captured,
        patch("app.services.conversation_service.capture"),
    ):
        yield Sends(effects=recorded, frames=frames, captured=captured)


_HISTORY = [
    {"type": "user", "response": "what's on today?", "message_id": "old-u"},
    {"type": "bot", "response": "two meetings", "message_id": "old-b"},
]
# The user message, the reply and its settle.
_LOGGED = 3


def _send(message_id: str, text: str = "book it for $600") -> dict[str, object]:
    return {"message_id": message_id, "text": text}


async def test_a_send_returns_202_with_its_seq_and_kicks_the_step(
    client: AsyncClient, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json=_send("m1")
    )
    assert response.status_code == 202, response.text
    assert response.json() == {"conversation_id": conversation_id, "message_id": "m1", "seq": 1}
    assert await conversation_log_repository.read_log_head(
        conversation_id, user_id=FAKE_USER.user_id
    )
    assert EffectCall("kick") in sends.effects.calls
    states = [f.display for f in sends.frames.published if isinstance(f, StateFrame)]
    assert states == [DisplayState.THINKING]


async def test_a_spoken_turn_is_logged_as_voice_and_gets_no_instant_reaction(
    client: AsyncClient, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={**_send("m1", "what's on today"), "voice": True},
    )
    assert response.status_code == 202, response.text
    entries = await conversation_log_repository.read_log(conversation_id, user_id=FAKE_USER.user_id)
    [message] = [e.entry for e in entries or [] if isinstance(e.entry, UserMessage)]
    assert message.voice is True
    assert sends.effects.calls == [EffectCall("kick")]


async def test_a_sent_message_keeps_the_browser_session_its_reply_is_counted_in(
    test_app: FastAPI, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    # The real middleware binds the request's analytics context, as production stacks it.
    transport = ASGITransport(app=PostHogRequestContextMiddleware(test_app))
    async with AsyncClient(transport=transport, base_url="http://test") as client:  # NOSONAR
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json=_send("m1"),
            headers={POSTHOG_SESSION_HEADER: "0190f00d-sess"},
        )
    assert response.status_code == 202, response.text
    entries = await conversation_log_repository.read_log(conversation_id, user_id=FAKE_USER.user_id)
    [message] = [e.entry for e in entries or [] if isinstance(e.entry, UserMessage)]
    assert message.posthog_session_id == "0190f00d-sess"


async def test_a_barge_in_is_logged_after_the_turn_and_a_resend_keeps_its_seq(
    client: AsyncClient, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={**_send("m1"), "voice": True}
    )
    url = f"/api/v1/conversations/{conversation_id}/barge-in"
    first = await client.post(url, json={"reply_id": "r1.1", "heard_through": 12})
    again = await client.post(url, json={"reply_id": "r1.1", "heard_through": 12})
    assert (first.status_code, again.status_code) == (202, 202), first.text
    assert first.json() == again.json() == {"conversation_id": conversation_id, "seq": 2}
    entries = await conversation_log_repository.read_log(conversation_id, user_id=FAKE_USER.user_id)
    barges = [e.entry for e in entries or [] if isinstance(e.entry, BargeIn)]
    assert barges == [BargeIn(id="r1.1:barge", reply_id="r1.1", heard_through=12)]


async def test_a_barge_in_on_someone_elses_conversation_is_refused(
    client: AsyncClient, sends: Sends
) -> None:
    response = await client.post(
        f"/api/v1/conversations/convrt-{uuid4().hex[:10]}/barge-in",
        json={"reply_id": "r1.1", "heard_through": 3},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "CONVERSATION_NOT_FOUND"
    assert sends.effects.calls == []


async def test_a_resent_message_keeps_its_first_seq_and_is_stored_once(
    client: AsyncClient, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    url = f"/api/v1/conversations/{conversation_id}/messages"
    first = await client.post(url, json=_send("m1"))
    again = await client.post(url, json=_send("m1"))
    entries = await conversation_log_repository.read_log(conversation_id, user_id=FAKE_USER.user_id)
    assert (first.status_code, again.status_code) == (202, 202), first.text
    assert (first.json()["seq"], again.json()["seq"]) == (1, 1)
    assert [e.entry.id for e in entries or [] if isinstance(e.entry, UserMessage)] == ["m1"]
    assert sends.captured.call_count == 1


async def test_a_send_into_a_conversation_with_history_continues_it(
    client: AsyncClient,
    sends: Sends,
    make_conversation: Callable[..., Awaitable[str]],
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id, messages=_HISTORY)
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json=_send("m1")
    )
    entries = await conversation_log_repository.read_log(conversation_id, user_id=FAKE_USER.user_id)
    assert response.status_code == 202, response.text
    assert response.json()["seq"] == _LOGGED + 1
    assert [e.entry.id for e in entries or []][_LOGGED:] == ["m1"]
    assert EffectCall("kick") in sends.effects.calls


async def test_a_bot_session_with_history_keeps_its_conversation(
    sends: Sends, make_conversation: Callable[..., Awaitable[str]]
) -> None:
    platform_user = f"tg-{uuid4().hex[:8]}"
    user = AuthenticatedUser(user_id=FAKE_USER.user_id)
    before = await BotService.get_or_create_session(
        "telegram", platform_user, None, user, is_dm=True
    )
    await log_history(before, user.user_id, _HISTORY)
    body = BotChatRequest(
        message="and tomorrow?",
        platform="telegram",
        platform_user_id=platform_user,
        platform_message_id="901",
        is_dm=True,
    )
    with patch("app.services.conversation.send.charge_bot_turn", new_callable=AsyncMock):
        accepted = await submit_bot_message(body, user)
    assert accepted.conversation_id == before
    assert accepted.seq == _LOGGED + 1


async def test_a_bot_message_is_counted_once_after_it_is_accepted_and_never_on_a_resend(
    sends: Sends,
) -> None:
    user = AuthenticatedUser(user_id=FAKE_USER.user_id)
    body = BotChatRequest(
        message="and tomorrow?",
        platform="telegram",
        platform_user_id=f"tg-{uuid4().hex[:8]}",
        platform_message_id="902",
        is_dm=True,
    )
    with patch("app.services.conversation.send.charge_bot_turn", new_callable=AsyncMock):
        first = await submit_bot_message(body, user)
        again = await submit_bot_message(body, user)
    assert first.seq == again.seq
    [(_, event), *_] = [call.args for call in sends.captured.call_args_list]
    assert sends.captured.call_count == 1
    assert isinstance(event, ChatMessageSubmitted)
    assert (event.source, event.stream_id, event.is_retry) == ("telegram", "telegram:902", False)


async def test_a_reply_file_is_queued_to_the_bot_platform_and_never_for_a_web_chat(
    sends: Sends,
) -> None:
    user = AuthenticatedUser(user_id=FAKE_USER.user_id)
    bot_chat = await BotService.get_or_create_session(
        "telegram", f"tg-{uuid4().hex[:8]}", None, user, is_dm=True
    )
    effects = RuntimeEffects(
        MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC)),
        RedisStreamFrames(),
        runtime_ports,
    )
    files = (ReplyFile("out/report.pdf", "application/pdf"),)
    with patch(
        "app.services.conversation.composition.publish_outbound_file", new_callable=AsyncMock
    ) as queued:
        await effects.deliver_files(bot_chat, user.user_id, files)
        await effects.deliver_files(f"web-{uuid4().hex[:8]}", user.user_id, files)
    queued.assert_awaited_once_with(
        ConversationSource.TELEGRAM,
        user.user_id,
        bot_chat,
        "out/report.pdf",
        "report.pdf",
        content_type="application/pdf",
    )


async def test_a_sent_messages_files_are_stored_on_its_entry_for_every_device(
    client: AsyncClient, sends: Sends, mongo_db: AsyncIOMotorDatabase[dict[str, object]]
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    await mongo_db["files"].insert_one(
        {
            "file_id": "f-1",
            "user_id": FAKE_USER.user_id,
            "conversation_id": conversation_id,
            "filename": "invoice-march.pdf",
            "type": "application/pdf",
            "size": 10,
            "url": "https://files.example/f-1",
            "created_at": datetime.now(UTC),
        }
    )
    with patch("app.services.conversation.send.FileService.attach_uploads", new_callable=AsyncMock):
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={**_send("m1"), "file_ids": ["f-1"]},
        )
    entries = await conversation_log_repository.read_log(conversation_id, user_id=FAKE_USER.user_id)
    [message] = [e.entry for e in entries or [] if isinstance(e.entry, UserMessage)]
    assert response.status_code == 202, response.text
    assert [(f.fileId, f.filename, f.type, f.url) for f in message.files] == [
        ("f-1", "invoice-march.pdf", "application/pdf", "https://files.example/f-1")
    ]


async def test_a_new_conversation_is_titled_and_its_title_streamed(
    client: AsyncClient, sends: Sends
) -> None:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    with patch(
        "app.services.conversation.title.generate_and_update_description",
        new_callable=AsyncMock,
        return_value="Flights to Lisbon",
    ) as titled:
        first = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json=_send("m1", "fly me to Lisbon"),
        )
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages", json=_send("m2", "in May")
        )
        await asyncio.gather(*_spawned_tasks, return_exceptions=True)
    updates = [f for f in sends.frames.published if isinstance(f, ConversationUpdatedFrame)]
    assert first.status_code == 202, first.text
    assert titled.await_count == 1
    assert titled.await_args.args[1] == {"role": "user", "content": "fly me to Lisbon"}
    assert [u.description for u in updates] == ["Flights to Lisbon"]
