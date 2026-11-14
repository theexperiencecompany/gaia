"""The voice session speaks every reply from the conversation's events, and reports where the user cut one off."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Callable
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import cast

from livekit import rtc
from livekit.agents.llm import ChatItem, ChatMessage
from livekit.agents.voice import SpeechHandle
from src.conversation import ConversationEvent, VoiceConversation, parse_event

from shared.py.conversation_wire import (
    NEW_MESSAGE_BREAKER,
    BubbleTextDelta,
    ReplyDeltaFrame,
    ReplyItem,
    ReplyOutcome,
    ToolTimeline,
)

FIRST = "Your flight to Berlin leaves at nine tomorrow morning."
SECOND = " The hotel near the station is booked for two nights."
CONVERSATION = "c1"
# A room nobody has joined: there is no participant to send display events to.
ROOM = SimpleNamespace(name="voice_u1", local_participant=None)


class FakeSpeech:
    """A speech handle the test ends, interrupted or not, with what TTS reports as played."""

    def __init__(self, text: AsyncIterable[str]) -> None:
        self.text = text
        self.interrupted = False
        self.chat_items: list[ChatItem] = []
        self._done: list[Callable[[SpeechHandle], None]] = []

    def add_done_callback(self, callback: Callable[[SpeechHandle], None]) -> None:
        self._done.append(callback)

    def end(self, *, interrupted: bool, played: str) -> None:
        self.interrupted = interrupted
        self.chat_items = [ChatMessage(role="assistant", content=[played], interrupted=interrupted)]
        for callback in self._done:
            callback(cast(SpeechHandle, self))


class FakeSpeaker:
    def __init__(self) -> None:
        self.speeches: list[FakeSpeech] = []

    def say(self, text: AsyncIterable[str]) -> SpeechHandle:
        speech = FakeSpeech(text)
        self.speeches.append(speech)
        return cast(SpeechHandle, speech)


class RecordingApi(VoiceConversation):
    """The conversation with its HTTP replaced: posts are recorded, the events stream is scripted."""

    def __init__(self, events: list[str] | None = None) -> None:
        super().__init__("http://api", cast(rtc.Room, ROOM), "u1")
        self.agent_token = "token"
        self.speaker = FakeSpeaker()
        self.posts: list[tuple[str, dict[str, object]]] = []
        self.scripted = events or []
        self.drained = asyncio.Event()

    async def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        self.posts.append((path, body))
        return {"seq": 1}

    async def _events(self, conversation_id: str) -> AsyncIterator[ConversationEvent]:
        for data in self.scripted:
            yield parse_event(data)
        self.drained.set()


def entry(seq: int, kind: str, reply_id: str) -> str:
    """Return a reply item patch: inserted as the reply opens, updated with its outcome as it settles."""
    opened = kind == "reply"
    item = ReplyItem(
        id=reply_id,
        seq=seq,
        at=datetime(2026, 11, 14, tzinfo=UTC),
        bubbles=(),
        tool_data=(),
        timeline=ToolTimeline(),
        follow_up_actions=(),
        image=None,
        pinned=False,
        quote=None,
        outcome=None if opened else ReplyOutcome.ANSWERED,
        failure=None,
        narrates=(),
    )
    patch = "screen_insert" if opened else "screen_update"
    return json.dumps({"frame": {"kind": patch, "item": item.model_dump(mode="json")}})


def delta(reply_id: str, index: int, text: str, bubble: int = 0) -> str:
    frame = ReplyDeltaFrame(
        attempt_id="1.1",
        reply_id=reply_id,
        index=index,
        payload=BubbleTextDelta(bubble=bubble, text=text),
    )
    return json.dumps({"frame": frame.model_dump(mode="json")})


async def follow(conversation: VoiceConversation, *events: str, after_seq: int = 1) -> None:
    for data in events:
        await conversation.apply(parse_event(data).frame, after_seq)
    # Let a barge-in posted from a done callback run.
    await asyncio.sleep(0)


def spoken(conversation: RecordingApi) -> FakeSpeaker:
    return cast(FakeSpeaker, conversation.speaker)


def barge_ins(conversation: RecordingApi) -> list[dict[str, object]]:
    return [body for path, body in conversation.posts if path.endswith("/barge-in")]


def test_talking_over_a_reply_posts_how_far_into_it_the_user_heard() -> None:
    async def scenario() -> None:
        conversation = RecordingApi()
        conversation.conversation_id = CONVERSATION
        await follow(
            conversation,
            entry(2, "reply", "r1"),
            delta("r1", 0, FIRST),
            delta("r1", 1, SECOND),
            entry(3, "reply_settled", "r1"),
        )
        [speech] = spoken(conversation).speeches
        speech.end(interrupted=True, played=FIRST + " The hotel near")
        await asyncio.sleep(0)
        assert barge_ins(conversation) == [{"reply_id": "r1", "heard_through": len(FIRST)}]
        assert conversation.posts[0][0] == f"/api/v1/conversations/{CONVERSATION}/barge-in"

    asyncio.run(scenario())


def test_a_reply_heard_to_its_end_or_never_cut_off_posts_nothing() -> None:
    async def scenario() -> None:
        conversation = RecordingApi()
        conversation.conversation_id = CONVERSATION
        await follow(
            conversation,
            entry(2, "reply", "r1"),
            delta("r1", 0, FIRST),
            entry(3, "reply_settled", "r1"),
            entry(4, "reply", "r2"),
            delta("r2", 0, FIRST),
            entry(5, "reply_settled", "r2"),
        )
        heard_all, finished = spoken(conversation).speeches
        heard_all.end(interrupted=True, played=FIRST)
        finished.end(interrupted=False, played=FIRST)
        await asyncio.sleep(0)
        assert barge_ins(conversation) == []

    asyncio.run(scenario())


def test_a_reply_opened_before_the_sessions_first_turn_is_not_spoken() -> None:
    async def scenario() -> None:
        conversation = RecordingApi()
        await follow(conversation, entry(2, "reply", "r0"), delta("r0", 0, FIRST), after_seq=5)
        assert spoken(conversation).speeches == []

    asyncio.run(scenario())


def test_a_replayed_delta_is_spoken_once() -> None:
    async def scenario() -> None:
        conversation = RecordingApi()
        await follow(
            conversation,
            entry(2, "reply", "r1"),
            delta("r1", 0, FIRST),
            delta("r1", 0, FIRST),
            entry(3, "reply_settled", "r1"),
        )
        [speech] = spoken(conversation).speeches
        assert [chunk async for chunk in speech.text] == [FIRST]

    asyncio.run(scenario())


def test_talking_over_a_second_bubble_posts_where_it_was_cut_in_the_saved_text() -> None:
    async def scenario() -> None:
        conversation = RecordingApi()
        conversation.conversation_id = CONVERSATION
        await follow(
            conversation,
            entry(2, "reply", "r1"),
            delta("r1", 0, FIRST),
            delta("r1", 1, SECOND, bubble=1),
            delta("r1", 2, "Dinner is at eight in the hotel restaurant.", bubble=2),
            entry(3, "reply_settled", "r1"),
        )
        [speech] = spoken(conversation).speeches
        speech.end(interrupted=True, played=FIRST + SECOND + " Dinner is")
        await asyncio.sleep(0)
        # heard_through indexes the saved text, whose bubbles the break joins.
        heard = len(f"{FIRST}{NEW_MESSAGE_BREAKER}{SECOND}")
        assert barge_ins(conversation) == [{"reply_id": "r1", "heard_through": heard}]

    asyncio.run(scenario())


def test_a_spoken_turn_is_sent_as_voice_and_its_reply_is_followed() -> None:
    async def scenario() -> None:
        conversation = RecordingApi(
            [entry(2, "reply", "r1"), delta("r1", 0, FIRST), entry(3, "reply_settled", "r1")]
        )
        await conversation.send_turn("when is my flight")
        await asyncio.wait_for(conversation.drained.wait(), timeout=1)
        await conversation.aclose()
        [(path, body)] = conversation.posts
        assert path == f"/api/v1/conversations/{conversation.conversation_id}/messages"
        assert (body["text"], body["voice"]) == ("when is my flight", True)
        [speech] = spoken(conversation).speeches
        assert [chunk async for chunk in speech.text] == [FIRST]

    asyncio.run(scenario())


def test_a_reply_is_spoken_but_shown_only_through_the_events_stream() -> None:
    """Regression: the reply was also sent on the data channel, so the web voice screen showed it twice."""
    sent: list[tuple[str, str]] = []

    async def send_text(text: str, *, topic: str) -> None:
        sent.append((topic, text))

    async def scenario() -> None:
        conversation = RecordingApi()
        conversation.room = cast(
            rtc.Room,
            SimpleNamespace(
                name="voice_u1", local_participant=SimpleNamespace(send_text=send_text)
            ),
        )
        await follow(
            conversation,
            entry(2, "reply", "r1"),
            delta("r1", 0, FIRST),
            entry(3, "reply_settled", "r1"),
        )
        [speech] = spoken(conversation).speeches
        assert [chunk async for chunk in speech.text] == [FIRST]

    asyncio.run(scenario())
    assert sent == []
