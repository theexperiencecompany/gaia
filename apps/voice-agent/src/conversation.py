"""A voice session's conversation on the GAIA API: each spoken turn is sent, and every reply is spoken from its events.

A turn is a POST that returns at once; the replies arrive on the conversation's events
stream, which one follower per session reads and hands to TTS in order. When the user
talks over a reply, the follower posts a barge-in naming it and how far into it they heard.
"""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
import json
from typing import Annotated, Protocol
from uuid import uuid4

import aiohttp
from livekit import rtc
from livekit.agents import Agent
from livekit.agents.llm import ChatContext, ChatItem, ChatMessage
from livekit.agents.voice import SpeechHandle
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from typing_extensions import override

from shared.py.conversation_wire import (
    NEW_MESSAGE_BREAKER,
    BubblesDelta,
    BubbleTextDelta,
    ConversationUpdatedFrame,
    ReplyDelta,
    ReplyDeltaFrame,
    ReplyItem,
    ScreenFrame,
    ScreenInsertFrame,
    ScreenItemHeader,
    ScreenUpdateFrame,
)
from shared.py.wide_events import VoiceContext, log, log_context, wide_task
from src.constants import (
    CONVERSATION_DESCRIPTION_TOPIC,
    CONVERSATION_ID_TOPIC,
    FOLLOW_RECONNECT_DELAY_S,
    FRONTEND_STREAM_TOPIC,
    SSE_DATA_PREFIX,
    VOICE_SYSTEM_PROMPT,
    LogTag,
)
from src.speech import Flush, ReplySpeech

_Item = Annotated[ReplyItem | ScreenItemHeader, Field(union_mode="left_to_right")]


class _OtherFrame(BaseModel):
    """A frame voice does not act on: the conversation's state, or a retracted attempt."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: str


_Frame = (
    ScreenFrame[_Item]
    | ScreenInsertFrame[_Item]
    | ScreenUpdateFrame[_Item]
    | ReplyDeltaFrame
    | ConversationUpdatedFrame
    | _OtherFrame
)


class ConversationEvent(BaseModel):
    """One frame of the events stream: the screen, a patch to it, or a live delta."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    frame: _Frame = Field(union_mode="left_to_right")


_EVENT: TypeAdapter[ConversationEvent] = TypeAdapter(ConversationEvent)


def parse_event(data: str) -> ConversationEvent:
    """Parse one SSE data payload of the events stream."""
    return _EVENT.validate_json(data)


class Speaker(Protocol):
    """What speaks a reply: the AgentSession, whose say() plays a text stream as one interruptible speech."""

    def say(self, text: AsyncIterable[str]) -> SpeechHandle: ...


class VoiceConversation:
    """The session's conversation: sends turns, follows the events, speaks replies, reports barge-ins."""

    def __init__(self, base_url: str, room: rtc.Room, user_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.room = room
        self.user_id = user_id
        self.agent_token: str | None = None
        self.conversation_id: str | None = None
        self.speaker: Speaker | None = None
        self._http: aiohttp.ClientSession | None = None
        self._follower: asyncio.Task[None] | None = None
        self._speeches: dict[str, ReplySpeech] = {}
        self._deltas_seen: set[tuple[str, int]] = set()
        # How many bubbles each reply has opened, so a new one is spoken after a break.
        self._bubbles: dict[str, int] = {}
        self._speaking: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    def set_backend_url(self, url: str) -> None:
        """Point this session at the backend that minted it (one shared agent serves several APIs)."""
        self.base_url = url.rstrip("/")

    async def set_conversation_id(self, conversation_id: str) -> None:
        """Adopt the conversation and tell the room which one it is."""
        self.conversation_id = conversation_id
        await self._send_room_text(conversation_id, CONVERSATION_ID_TOPIC)
        await self.forward(json.dumps({"conversation_id": conversation_id}))

    async def send_turn(self, text: str) -> None:
        """Append the user's spoken turn to the conversation; its reply is spoken by the follower."""
        if self.conversation_id is None:
            # A session started outside a conversation opens a new one; the client mints its id.
            await self.set_conversation_id(str(uuid4()))
        conversation_id = self._conversation()
        accepted = await self._post(
            f"/api/v1/conversations/{conversation_id}/messages",
            {"message_id": uuid4().hex, "text": text, "voice": True},
        )
        seq = accepted["seq"]
        if not isinstance(seq, int):
            raise TypeError(f"the API accepted the turn without a seq: {accepted!r}")
        if self._follower is None or self._follower.done():
            self._follower = asyncio.create_task(self._follow(conversation_id, seq))

    async def forward(self, payload: str) -> None:
        """Send a display event to the frontend over the room's data channel."""
        await self._send_room_text(payload, FRONTEND_STREAM_TOPIC)

    async def aclose(self) -> None:
        """Stop following and close the HTTP session."""
        if self._follower is not None:
            self._follower.cancel()
        if self._http is not None and not self._http.closed:
            await self._http.close()

    async def _follow(self, conversation_id: str, after_seq: int) -> None:
        """Speak every reply opened after after_seq, reconnecting when the stream drops."""
        while True:
            async with log_context(
                "voice_follow", user_id=self.user_id, conversation_id=conversation_id
            ):
                log.set(voice=VoiceContext(operation="follow", room=self.room_name))
                try:
                    async for event in self._events(conversation_id):
                        await self.apply(event.frame, after_seq)
                except (aiohttp.ClientError, TimeoutError) as error:
                    log.warning(f"{LogTag.VOICE} events stream dropped", error=str(error))
            await asyncio.sleep(FOLLOW_RECONNECT_DELAY_S)

    async def apply(self, frame: _Frame, after_seq: int) -> None:
        """Speak and display one frame; replies at or before after_seq were never this session's."""
        match frame:
            case ScreenFrame(items=items):
                for item in items:
                    self._reply(item, after_seq)
            case ScreenInsertFrame(item=item) | ScreenUpdateFrame(item=item):
                self._reply(item, after_seq)
            case ReplyDeltaFrame(reply_id=str(reply_id), index=index, payload=payload):
                self._delta(reply_id, index, payload)
            case ConversationUpdatedFrame(description=description):
                await self._send_room_text(description, CONVERSATION_DESCRIPTION_TOPIC)

    def _reply(self, item: ReplyItem | ScreenItemHeader, after_seq: int) -> None:
        """Open a speech for a reply item of this session's, and finish it once the reply settles."""
        if not isinstance(item, ReplyItem):
            return
        if item.seq > after_seq and item.id not in self._speeches:
            self._speeches[item.id] = ReplySpeech(item.id)
        speech = self._speeches.get(item.id)
        if item.outcome is not None and speech is not None and not speech.settled:
            self._spoken(speech, speech.finish())

    def _delta(self, reply_id: str, index: int, payload: ReplyDelta) -> None:
        """Speak what the delta adds: a new bubble follows the last one after the break the reply's text joins them with."""
        speech = self._speeches.get(reply_id)
        if speech is None or (reply_id, index) in self._deltas_seen:
            return
        self._deltas_seen.add((reply_id, index))
        match payload:
            case BubbleTextDelta(bubble=bubble, text=text):
                opens = bubble >= self._bubbles.get(reply_id, 0)
                self._bubbles[reply_id] = max(self._bubbles.get(reply_id, 0), bubble + 1)
                piece = f"{NEW_MESSAGE_BREAKER}{text}" if opens and bubble > 0 else text
                self._spoken(speech, speech.add(piece))
            case BubblesDelta(bubbles=bubbles):
                # Text the model took back was already spoken; only what follows it can still be said.
                said = NEW_MESSAGE_BREAKER.join(bubbles)
                self._bubbles[reply_id] = len(bubbles)
                if said.startswith(speech.text):
                    self._spoken(speech, speech.add(said[len(speech.text) :]))
            case _:
                pass

    def _spoken(self, speech: ReplySpeech, flushed: Flush | None) -> None:
        """Start speaking the reply with its first spoken chunk; every device shows it from the events stream."""
        if flushed is None:
            return
        if flushed.spoken and speech.reply_id not in self._speaking:
            self._speak(speech)

    def _speak(self, speech: ReplySpeech) -> None:
        if self.speaker is None:
            raise RuntimeError("a reply arrived before the voice session could speak it")
        self._speaking.add(speech.reply_id)
        handle = self.speaker.say(speech.chunks())
        handle.add_done_callback(lambda done: self._on_speech_done(speech, done))

    def _on_speech_done(self, speech: ReplySpeech, handle: SpeechHandle) -> None:
        """Report a barge-in when the user cut the reply off before its end."""
        if not handle.interrupted:
            return
        heard_through = speech.heard_through(heard_text(handle.chat_items))
        if speech.settled and heard_through >= len(speech.text):
            return
        task = asyncio.create_task(self._barge_in(speech.reply_id, heard_through))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _barge_in(self, reply_id: str, heard_through: int) -> None:
        conversation_id = self._conversation()
        async with log_context(
            "voice_barge_in", user_id=self.user_id, conversation_id=conversation_id
        ):
            log.set(
                voice=VoiceContext(
                    operation="barge_in",
                    room=self.room_name,
                    reply_id=reply_id,
                    heard_through=heard_through,
                )
            )
            await self._post(
                f"/api/v1/conversations/{conversation_id}/barge-in",
                {"reply_id": reply_id, "heard_through": heard_through},
            )

    async def _events(self, conversation_id: str) -> AsyncIterator[ConversationEvent]:
        async with self._session().get(
            f"{self.base_url}/api/v1/conversations/{conversation_id}/events",
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=None, sock_read=None),
        ) as resp:
            resp.raise_for_status()
            async for raw in resp.content:
                line = raw.decode("utf-8").strip()
                if line.startswith(SSE_DATA_PREFIX):
                    yield parse_event(line[len(SSE_DATA_PREFIX) :])

    async def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        async with self._session().post(
            f"{self.base_url}{path}", json=body, headers=self._headers()
        ) as resp:
            if resp.status >= 400:
                log.error(
                    f"{LogTag.VOICE} API refused the request",
                    status=resp.status,
                    body=(await resp.text())[:500],
                )
            resp.raise_for_status()
            payload: dict[str, object] = await resp.json()
            return payload

    def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    def _headers(self) -> dict[str, str]:
        if self.agent_token is None:
            raise RuntimeError("the voice session has no agent token yet")
        return {"Authorization": f"Bearer {self.agent_token}"}

    def _conversation(self) -> str:
        if self.conversation_id is None:
            raise RuntimeError("the voice session has no conversation yet")
        return self.conversation_id

    @property
    def room_name(self) -> str:
        """Return the room's name, for the events this session logs."""
        return self.room.name

    async def _send_room_text(self, text: str, topic: str) -> None:
        if self.room.local_participant is not None:
            await self.room.local_participant.send_text(text, topic=topic)


def heard_text(items: list[ChatItem]) -> str:
    """Return what TTS reports as played of a speech: its assistant message, cut where it was interrupted."""
    for item in items:
        if isinstance(item, ChatMessage) and item.role == "assistant":
            return item.text_content or ""
    return ""


class VoiceTurnAgent(Agent):
    """The session's agent: each finished user turn goes to the conversation, which answers on its events."""

    def __init__(self, conversation: VoiceConversation) -> None:
        super().__init__(instructions=VOICE_SYSTEM_PROMPT)
        self._conversation = conversation
        self._turns = 0

    @override
    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        """Send the turn; the session has no LLM, so LiveKit generates nothing itself."""
        self._turns += 1
        conversation = self._conversation
        async with wide_task(
            "voice_turn", user_id=conversation.user_id, conversation_id=conversation.conversation_id
        ):
            log.set(
                voice=VoiceContext(
                    operation="turn", room=conversation.room_name, turn_index=self._turns
                )
            )
            text = new_message.text_content
            if not text:
                log.warning(f"{LogTag.VOICE} empty user turn, nothing sent", turn_index=self._turns)
                return
            await conversation.send_turn(text)
