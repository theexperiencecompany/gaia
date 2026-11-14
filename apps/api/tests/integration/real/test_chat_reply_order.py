"""A reply's place in a conversation is its seq, taken when the user first sees it: real Redis + MongoDB.

Only call_agent is faked; the turn, its saves and the conversation read are real.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import MagicMock, patch

from bson import ObjectId
from httpx import AsyncClient
import pytest

from app.constants.chat import (
    CONVERSATION_ENTRIES_COLLECTION,
    TURN_INTERRUPTED,
    TURN_REPLY_NOT_SAVED,
)
from app.core.stream_manager import stream_manager
from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversations import conversation_repository
from app.models.message_models import MessageRequestWithHistory
from app.services.chat.persistence import (
    BotReply,
    open_bot_reply,
    save_bot_reply,
    save_user_message,
)
from app.services.chat.stream import run_chat_stream_background
from app.services.conversation.reaction import ReactionTarget, react_as_chat_model
from app.workers.tasks.reply_sweep_tasks import sweep_unfinished_replies
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.service

_REPLY = "Reply to A"


def _body(conversation_id: str, text: str) -> MessageRequestWithHistory:
    return MessageRequestWithHistory(
        message=text,
        messages=[{"role": "user", "content": text}],
        conversation_id=conversation_id,
    )


def _usage() -> MagicMock:
    handler = MagicMock()
    handler.return_value.usage_metadata = {}
    return handler


@contextmanager
def _agent(stream: AsyncIterator[str]) -> Iterator[list[str]]:
    """Run turns against stream, collecting every frame the turn publishes."""
    published: list[str] = []
    publish = stream_manager.publish_chunk

    async def _spy(stream_id: str, chunk: str) -> None:
        published.append(chunk)
        await publish(stream_id, chunk)

    with (
        patch("app.services.chat.stream.call_agent", new=MagicMock(return_value=stream)),
        patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage()),
        patch.object(stream_manager, "publish_chunk", new=_spy),
    ):
        yield published


def _frames(published: list[str]) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for chunk in published:
        if chunk.startswith("data: {"):
            frames.append(json.loads(chunk.removeprefix("data: ")))
    return frames


async def _shown_then_held(shown: asyncio.Event, release: asyncio.Event) -> AsyncIterator[str]:
    yield f"data: {json.dumps({'response': _REPLY})}\n\n"
    shown.set()
    await release.wait()
    yield f"nostream: {json.dumps({'complete_message': _REPLY})}"
    yield "data: [DONE]\n\n"


async def _entries(mongo_db, conversation_id: str) -> list[dict[str, object]]:
    return (
        await mongo_db[CONVERSATION_ENTRIES_COLLECTION]
        .find({"conversation_id": conversation_id})
        .sort("seq", 1)
        .to_list(length=None)
    )


async def _read(client: AsyncClient, conversation_id: str) -> list[dict[str, object]]:
    response = await client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    return response.json()["messages"]


@pytest.mark.regression
async def test_reply_streaming_when_the_user_sends_again_stays_above_that_message(
    client: AsyncClient, real_redis, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    shown, release = asyncio.Event(), asyncio.Event()
    with _agent(_shown_then_held(shown, release)):
        turn = asyncio.create_task(
            run_chat_stream_background(
                stream_id=f"stream_{ObjectId()}",
                body=_body(conversation_id, "A"),
                user=FAKE_USER,
                conversation_id=conversation_id,
            )
        )
        await asyncio.wait_for(shown.wait(), timeout=10)
        await save_user_message(_body(conversation_id, "B"), FAKE_USER, conversation_id, "msg-b")
        release.set()
        await turn

    messages = await _read(client, conversation_id)

    assert [m["response"] for m in messages] == ["A", _REPLY, "B"]
    assert [m["seq"] for m in messages] == [1, 2, 3]
    assert all(m.get("in_progress") is None for m in messages)


async def test_the_stream_tells_the_client_each_message_seq(real_redis, make_conversation) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    shown, release = asyncio.Event(), asyncio.Event()
    release.set()
    with _agent(_shown_then_held(shown, release)) as published:
        await run_chat_stream_background(
            stream_id=f"stream_{ObjectId()}",
            body=_body(conversation_id, "A"),
            user=FAKE_USER,
            conversation_id=conversation_id,
        )

    frames = _frames(published)
    identity = next(f for f in frames if "user_message_id" in f)
    opened = [i for i, f in enumerate(frames) if "bot_message_seq" in f]
    first_text = next(i for i, f in enumerate(frames) if f.get("response"))
    assert identity["user_message_seq"] == 1
    assert [frames[i]["bot_message_seq"] for i in opened] == [2]
    assert opened[0] < first_text


async def test_a_turn_that_fails_after_showing_text_settles_its_entry_as_failed(
    client: AsyncClient, real_redis, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)

    async def _fails() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'response': 'partial'})}\n\n"
        raise RuntimeError("model went away")

    with _agent(_fails()):
        await run_chat_stream_background(
            stream_id=f"stream_{ObjectId()}",
            body=_body(conversation_id, "A"),
            user=FAKE_USER,
            conversation_id=conversation_id,
        )

    [_, reply] = await _read(client, conversation_id)
    assert reply["seq"] == 2
    assert reply["error"] == "model went away"
    assert reply.get("in_progress") is None


async def test_a_stopped_turn_settles_its_entry_as_stopped(
    client: AsyncClient, real_redis, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    stream_id = f"stream_{ObjectId()}"

    async def _stopped() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'response': 'half a'})}\n\n"
        await stream_manager.cancel_stream(stream_id)
        payload = {"complete_message": "half a", "cancelled": True}
        yield f"nostream: {json.dumps(payload)}"

    with _agent(_stopped()):
        await run_chat_stream_background(
            stream_id=stream_id,
            body=_body(conversation_id, "A"),
            user=FAKE_USER,
            conversation_id=conversation_id,
        )

    [_, reply] = await _read(client, conversation_id)
    assert reply["seq"] == 2
    assert reply["stopped"] is True
    assert reply.get("in_progress") is None


async def test_a_reply_that_cannot_be_saved_settles_its_entry_with_the_save_error(
    client: AsyncClient, real_redis, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    shown, release = asyncio.Event(), asyncio.Event()
    release.set()
    with (
        _agent(_shown_then_held(shown, release)),
        patch(
            "app.services.chat.stream.recover_stream_state",
            side_effect=RuntimeError("redis lost the turn"),
        ),
    ):
        await run_chat_stream_background(
            stream_id=f"stream_{ObjectId()}",
            body=_body(conversation_id, "A"),
            user=FAKE_USER,
            conversation_id=conversation_id,
        )

    [_, reply] = await _read(client, conversation_id)
    assert reply["seq"] == 2
    assert reply["error"] == TURN_REPLY_NOT_SAVED
    assert reply.get("in_progress") is None


async def test_a_turn_that_never_shows_anything_appends_its_reply_at_the_end(
    client: AsyncClient, real_redis, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    started = asyncio.Event()
    release = asyncio.Event()

    async def _silent_until_done() -> AsyncIterator[str]:
        started.set()
        await release.wait()
        yield f"nostream: {json.dumps({'complete_message': 'late answer'})}"

    with _agent(_silent_until_done()) as published:
        turn = asyncio.create_task(
            run_chat_stream_background(
                stream_id=f"stream_{ObjectId()}",
                body=_body(conversation_id, "A"),
                user=FAKE_USER,
                conversation_id=conversation_id,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=10)
        await save_user_message(_body(conversation_id, "B"), FAKE_USER, conversation_id, "msg-b")
        release.set()
        await turn

    messages = await _read(client, conversation_id)
    assert [m["response"] for m in messages] == ["A", "B", "late answer"]
    assert [f["bot_message_seq"] for f in _frames(published) if "bot_message_seq" in f] == [3]


async def _crashed_turn(mongo_db, conversation_id: str) -> None:
    """Leave the state a process killed mid-reply leaves: the reply's entry opened, never settled."""
    await save_user_message(_body(conversation_id, "A"), FAKE_USER, conversation_id, "msg-a")
    await open_bot_reply(_body(conversation_id, "A"), FAKE_USER, conversation_id, "msg-reply")
    await conversation_repository.flush_outbox(conversation_id, user_id=FAKE_USER.user_id)
    await mongo_db[CONVERSATION_ENTRIES_COLLECTION].update_many(
        {"conversation_id": conversation_id},
        {"$set": {"at": datetime.now(UTC) - timedelta(hours=1)}},
    )


async def test_a_crashed_turn_leaves_no_reply_in_progress_after_the_sweep(
    client: AsyncClient, real_redis, mongo_db, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    await _crashed_turn(mongo_db, conversation_id)
    assert [e.get("in_progress") for e in await _entries(mongo_db, conversation_id)] == [None, True]

    await sweep_unfinished_replies({})

    [_, reply] = await _read(client, conversation_id)
    assert reply["seq"] == 2
    assert reply["error"] == TURN_INTERRUPTED
    assert reply.get("in_progress") is None


async def test_a_turn_killed_before_its_flush_is_swept_from_the_outbox(
    client: AsyncClient, real_redis, mongo_db, make_conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    # The process dies right after the reply's commit: no flush it spawned ever runs.
    monkeypatch.setattr(
        conversations_module, "spawn_logged_task", lambda _name, coro, **_: coro.close()
    )
    await save_user_message(_body(conversation_id, "A"), FAKE_USER, conversation_id, "msg-a")
    await open_bot_reply(_body(conversation_id, "A"), FAKE_USER, conversation_id, "msg-reply")
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    await mongo_db["conversations"].update_one(
        {"conversation_id": conversation_id},
        {"$set": {"outbox.1.at": hour_ago, "outbox.2.at": hour_ago}},
    )
    assert await _entries(mongo_db, conversation_id) == []

    async with captured_wide_event() as event:
        assert await sweep_unfinished_replies({}) == "failed=1"

    assert (event["unfinished_reply_conversations"], event["failed_reply_count"]) == (1, 1)
    [_, reply] = await _read(client, conversation_id)
    assert (reply["error"], reply.get("in_progress")) == (TURN_INTERRUPTED, None)


async def test_a_reply_whose_open_committed_but_raised_is_still_saved_in_full(
    client: AsyncClient, real_redis, mongo_db, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    await save_user_message(_body(conversation_id, "A"), FAKE_USER, conversation_id, "msg-a")
    # The open's write landed, then the call raised: the turn never learned its entry exists.
    await open_bot_reply(_body(conversation_id, "A"), FAKE_USER, conversation_id, "msg-reply")

    await save_bot_reply(
        _body(conversation_id, "A"),
        FAKE_USER,
        conversation_id,
        BotReply(complete_message="the full answer", bot_message_id="msg-reply"),
    )

    [_, reply] = await _read(client, conversation_id)
    assert (reply["seq"], reply["response"], reply.get("in_progress")) == (
        2,
        "the full answer",
        None,
    )


async def test_the_chat_models_reaction_is_announced_only_once_it_is_stored(
    real_redis, mongo_db, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    await save_user_message(_body(conversation_id, "A"), FAKE_USER, conversation_id, "msg-a")

    def target(message_id: str) -> ReactionTarget:
        return ReactionTarget(
            stream_id="stream-r",
            conversation_id=conversation_id,
            user_id=FAKE_USER.user_id,
            message_id=message_id,
        )

    published: list[str] = []

    async def spy(_stream_id: str, chunk: str) -> None:
        published.append(chunk)

    with patch.object(stream_manager, "publish_chunk", new=spy):
        assert await react_as_chat_model(target("never-saved"), "\U0001f44d") is False
        assert _frames(published) == []
        assert await react_as_chat_model(target("msg-a"), "\U0001f44d") is True

    assert _frames(published) == [
        {"reaction": {"message_id": "msg-a", "emoji": "\U0001f44d", "by": "chat_model"}}
    ]


async def test_a_second_sweep_changes_nothing(real_redis, mongo_db, make_conversation) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    await _crashed_turn(mongo_db, conversation_id)
    assert await sweep_unfinished_replies({}) == "failed=1"
    settled = await _entries(mongo_db, conversation_id)

    assert await sweep_unfinished_replies({}) == "failed=0"
    assert await _entries(mongo_db, conversation_id) == settled


async def test_the_sweep_spares_a_reply_whose_turn_is_still_streaming(
    real_redis, mongo_db, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    await _crashed_turn(mongo_db, conversation_id)
    await stream_manager.start_stream(f"stream_{ObjectId()}", conversation_id, FAKE_USER.user_id)

    assert await sweep_unfinished_replies({}) == "failed=0"
    assert await sweep_unfinished_replies({}) == "failed=0"

    assert [e.get("in_progress") for e in await _entries(mongo_db, conversation_id)] == [None, True]


async def test_batch_sync_returns_each_message_with_its_seq_in_seq_order(
    client: AsyncClient, real_redis, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    for n, text in enumerate(["first", "second", "third"]):
        await save_user_message(_body(conversation_id, text), FAKE_USER, conversation_id, f"m{n}")

    response = await client.post(
        "/api/v1/conversations/batch-sync",
        json={"conversations": [{"conversation_id": conversation_id}]},
    )

    assert response.status_code == 200, response.text
    [row] = response.json()["conversations"]
    assert [(m["response"], m["seq"]) for m in row["messages"]] == [
        ("first", 1),
        ("second", 2),
        ("third", 3),
    ]


async def test_appending_messages_returns_the_seq_of_each(
    client: AsyncClient, real_redis, make_conversation
) -> None:
    conversation_id = await make_conversation(FAKE_USER.user_id)
    await save_user_message(_body(conversation_id, "earlier"), FAKE_USER, conversation_id, "m0")

    response = await client.put(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "conversation_id": conversation_id,
            "messages": [
                {"type": "user", "response": "one", "message_id": "m1"},
                {"type": "bot", "response": "two", "message_id": "m2"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["message_ids"], body["message_seqs"]) == (["m1", "m2"], [2, 3])
