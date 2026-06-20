"""CustomLLM — streams SSE from the GAIA backend and yields ChatChunks for ElevenLabs TTS."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import json
import time
from typing import TYPE_CHECKING, Any

import aiohttp
from livekit import rtc  # type: ignore[attr-defined]
from livekit.agents.llm import LLM, ChatChunk, ChatContext, ChoiceDelta

from shared.py.wide_events import log, wide_task
from src.constants import (
    BACKEND_REQUEST_TIMEOUT_S,
    DONE_SENTINEL,
    FRONTEND_STREAM_TOPIC,
    MAIN_RESPONSE_COMPLETE_KEY,
    MESSAGE_ID_KEY,
    OPEN_TAG_DEFER_CAP,
    PLUMBING_EVENT_KEYS,
    RESPONSE_KEY,
    SENTENCE_ENDINGS,
    SSE_DATA_PREFIX,
    TTS_FINAL_MIN_CHARS,
    TTS_HARD_FLUSH_CHARS,
    TTS_MIN_EMIT_CHARS,
    TTS_MIN_SENTENCE_CHARS,
    VOICE_TTS_KEY,
)
from src.utils import (
    build_messages_from_ctx,
    extract_latest_user_text,
    has_open_openui_fence_at_tail,
    has_open_tag_at_tail,
    ms_since,
    sanitize_for_tts,
)

if TYPE_CHECKING:
    from livekit.agents import AgentSession


class CustomLLM(LLM):
    """LLM adapter that streams SSE from POST /api/v1/chat-stream on the GAIA backend."""

    def __init__(
        self,
        base_url: str,
        request_timeout_s: float = BACKEND_REQUEST_TIMEOUT_S,
        room: rtc.Room | None = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.agent_token: str | None = None
        self.conversation_id: str | None = None
        self.conversation_description: str | None = None
        self.request_timeout_s = request_timeout_s
        self.room: rtc.Room | None = room
        # Set by the session entrypoint (derived from the room name) so every
        # turn log carries the user identity for Loki queries.
        self.user_id: str | None = None
        self._turn_index = 0
        # Reused across turns to avoid TCP reconnect overhead per turn
        self._http_session: aiohttp.ClientSession | None = None
        # Set by the entrypoint once the AgentSession exists. The drain uses it
        # to speak each delegated executor answer as its own utterance.
        self.session: AgentSession | None = None
        # Keep drain tasks referenced so they aren't garbage-collected mid-run.
        self._drain_tasks: set[asyncio.Task[None]] = set()

    def get_http_session(self) -> aiohttp.ClientSession:
        """Return the shared HTTP session, creating it on first call."""
        if self._http_session is None or self._http_session.closed:
            connector = aiohttp.TCPConnector(limit=4)
            self._http_session = aiohttp.ClientSession(connector=connector)
        return self._http_session

    def set_agent_token(self, token: str) -> None:
        """Set the authentication token for backend requests."""
        self.agent_token = token

    def set_backend_url(self, url: str) -> None:
        """Point this session at the backend that minted it.

        Used by multi-backend deployments (staging previews) where one shared
        agent serves rooms created by different APIs.
        """
        self.base_url = url.rstrip("/")

    async def set_conversation_id(self, conversation_id: str) -> None:
        """Store and broadcast conversation ID to room participants."""
        if not conversation_id:
            return
        self.conversation_id = conversation_id
        if self.room and self.room.local_participant:
            try:
                await self.room.local_participant.send_text(
                    conversation_id, topic="conversation-id"
                )
            except Exception as e:
                log.error("Failed to send conversation ID", error=str(e))

    async def set_conversation_description(self, description: str) -> None:
        """Store and broadcast conversation description to room participants."""
        if not description:
            return
        self.conversation_description = description
        if self.room and self.room.local_participant:
            try:
                await self.room.local_participant.send_text(
                    description, topic="conversation-description"
                )
            except Exception as e:
                log.error("Failed to send conversation description", error=str(e))

    async def forward_stream_event_to_frontend(self, raw_event: str) -> None:
        """Forward a raw backend SSE payload to the frontend via LiveKit data channel."""
        if not raw_event or not self.room or not self.room.local_participant:
            return
        try:
            await self.room.local_participant.send_text(
                raw_event,
                topic=FRONTEND_STREAM_TOPIC,
            )
            log.debug(
                "forward to frontend",
                phase="forward_frontend",
                payload_len=len(raw_event),
                payload_preview=raw_event[:300],
            )
        except Exception as e:
            log.warning(
                "Failed to forward backend stream event to frontend",
                topic=FRONTEND_STREAM_TOPIC,
                error=str(e),
            )

    async def forward_response_text_to_frontend(self, text: str) -> None:
        """Forward spoken response text to the frontend in flush-sized chunks.

        Sent at the same TTS-flush cadence as the audio (not per backend token)
        so the chat bubble fills in sync with the speech. The text is the raw
        buffered slice — OpenUI fences and markdown are preserved for rendering;
        only the TTS copy is sanitised.
        """
        if text:
            await self.forward_stream_event_to_frontend(json.dumps({RESPONSE_KEY: text}))

    def spawn_drain(self, resp: aiohttp.ClientResponse) -> None:
        """Drain the rest of a comms turn's stream in the background.

        The comms turn (its chat() generator) ends as soon as the reply is done,
        so the ack plays immediately. The executor's UI events and narrated
        answer arrive later on the same still-open stream — this keeps reading
        them: forwarding tool cards to the screen and speaking each answer.
        """
        task = asyncio.create_task(self._drain(resp))
        self._drain_tasks.add(task)
        task.add_done_callback(self._drain_tasks.discard)

    async def _drain(self, resp: aiohttp.ClientResponse) -> None:
        """Forward the post-reply UI events and speak each executor answer.

        Mirrors what's shown on screen: forward what's displayed (tool cards,
        follow-ups), speak what's a bot message (each ``voice_tts`` answer, in
        order, as its own utterance via ``session.say``).
        """
        try:
            async for raw in resp.content:
                data = _parse_sse_line(raw)
                if data is None:
                    continue
                if data == DONE_SENTINEL:
                    await self.forward_stream_event_to_frontend(data)
                    break
                await self._handle_drain_event(data)
        except Exception as e:
            log.warning("Voice stream drain failed", error=str(e))
        finally:
            await resp.release()

    async def _handle_drain_event(self, data: str) -> None:
        """Speak a ``voice_tts`` answer, or forward a plumbing event to the screen."""
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return
        voice_tts = event.get(VOICE_TTS_KEY)
        if isinstance(voice_tts, str) and voice_tts:
            spoken = sanitize_for_tts(voice_tts)
            if spoken and self.session is not None:
                # say() schedules its own utterance; the comms turn is already
                # over so it plays as soon as it lands.
                self.session.say(spoken)
            # Bubble the answer immediately off the data channel, keyed by the
            # saved message_id so the backend's WebSocket push (same id)
            # reconciles in place instead of duplicating. Without this the
            # bubble waits on (or misses) that WebSocket push while TTS already
            # played.
            await self.forward_stream_event_to_frontend(
                json.dumps({RESPONSE_KEY: voice_tts, MESSAGE_ID_KEY: event.get(MESSAGE_ID_KEY)})
            )
            return
        if event.keys() & PLUMBING_EVENT_KEYS:
            await self.forward_stream_event_to_frontend(data)

    # The base class declares chat() -> LLMStream, but the LiveKit pipeline calls it as
    # `async with llm.chat(...) as stream: async for chunk in stream:`, which is exactly
    # what @asynccontextmanager + yield gen() provides
    @asynccontextmanager
    async def chat(  # type: ignore[override]
        self, *, chat_ctx: ChatContext, **kwargs: Any
    ) -> AsyncGenerator[AsyncGenerator[ChatChunk, None], None]:
        """Stream SSE from the backend and yield ChatChunks for TTS."""

        async def gen() -> AsyncGenerator[ChatChunk, None]:
            self._turn_index += 1
            turn = _VoiceTurn(self, chat_ctx, self._turn_index)
            async for chunk in turn.run():
                yield chunk

        yield gen()

    async def aclose(self) -> None:
        """Clean up HTTP session and room reference."""
        self.room = None
        try:
            if self._http_session and not self._http_session.closed:
                await self._http_session.close()
        except Exception as e:
            log.warning("Failed to close backend HTTP session", error=str(e))
        finally:
            await super().aclose()


def _tts_chunk(content: str) -> ChatChunk:
    """Wrap sanitized text in the ChatChunk shape the LiveKit TTS pipeline expects."""
    return ChatChunk(id="custom", delta=ChoiceDelta(content=content))


def _parse_sse_line(raw: bytes) -> str | None:
    """Extract the data payload from one SSE line; None for blanks/non-data lines."""
    if not raw:
        return None
    line = raw.decode("utf-8", errors="ignore").strip()
    if not line or not line.startswith(SSE_DATA_PREFIX):
        return None
    return line[len(SSE_DATA_PREFIX) :].strip()


class _VoiceTurn:
    """One voice turn: stream backend SSE, flush sentence-sized TTS chunks.

    Owns all per-turn state (buffers, counters, latency marks) so each step of
    the stream loop stays a small, single-purpose method.
    """

    def __init__(self, llm: CustomLLM, chat_ctx: ChatContext, turn_index: int) -> None:
        self.llm = llm
        self.turn_index = turn_index
        self.turn_start = time.monotonic()
        self.user_message = extract_latest_user_text(chat_ctx)
        # Build full message history from the LiveKit context so the backend
        # LLM has the complete conversation rather than just the latest turn.
        history = build_messages_from_ctx(chat_ctx)
        self.messages = history if history else [{"role": "user", "content": self.user_message}]

        self.tts_enabled = True
        self.first_token_received = False
        self.total_tokens = 0
        self.ttfb_ms: float | None = None
        self.first_tts_flush_ms: float | None = None
        self.tts_flush_count = 0
        self.tts_chars_total = 0
        self.executor_tts_chars = 0
        self.text_buffer: list[str] = []
        self.deferred_flushes = 0
        # Set once the comms reply is done. The turn ends here so the ack plays
        # immediately instead of being held while the executor runs (~tens of s).
        self.comms_complete = False
        # Set when the stream fully ended ([DONE]) within the comms turn — then
        # there's nothing left to drain.
        self.stream_done = False

    async def run(self) -> AsyncGenerator[ChatChunk, None]:
        """Drive the whole turn; yields sanitized TTS chunks as they flush."""
        # Per-turn wide-event scope: every line in this turn carries the same
        # identity + turn fields, so Loki can slice by any of them.
        async with wide_task(
            "voice_turn",
            room=self.llm.room.name if self.llm.room else None,
            user_id=self.llm.user_id,
            conversation_id=self.llm.conversation_id,
            turn_index=self.turn_index,
        ):
            async for chunk in self._run():
                yield chunk

    async def _run(self) -> AsyncGenerator[ChatChunk, None]:
        if not self.user_message:
            log.warning("empty user message, skipping LLM turn", phase="turn_skip")
            return

        log.info(
            "chat turn start",
            phase="chat_turn_start",
            user_msg=self.user_message,
            user_msg_len=len(self.user_message),
        )

        payload = self._build_payload()
        log.debug(
            "backend request",
            phase="backend_request",
            elapsed_ms=ms_since(self.turn_start),
            conversation_id=self.llm.conversation_id,
            user_message=self.user_message,
            history_turns=len(self.messages),
        )

        http_session = self.llm.get_http_session()
        resp = await http_session.post(
            f"{self.llm.base_url}/api/v1/chat-stream",
            headers=self._build_headers(),
            json=payload,
            timeout=aiohttp.ClientTimeout(sock_read=self.llm.request_timeout_s),
        )
        handed_off = False
        try:
            if resp.status >= 400:
                body = await resp.text()
                log.error(
                    "Backend returned error response",
                    status=resp.status,
                    body=body[:500],
                    conversation_id=self.llm.conversation_id,
                    elapsed_ms=ms_since(self.turn_start),
                )
                resp.raise_for_status()

            async for chunk in self._stream_chunks(resp):
                yield chunk

            # The comms reply is done but the stream is still open — a delegated
            # executor's events/answer are still coming. Hand the open stream to
            # a background reader (which forwards tool cards and speaks each
            # answer) and end this turn now, so the ack plays immediately.
            if self.comms_complete and not self.stream_done:
                self.llm.spawn_drain(resp)
                handed_off = True

            log.info(
                "chat turn end",
                phase="chat_turn_end",
                elapsed_ms=ms_since(self.turn_start),
            )
            # Canonical per-turn wide event — one INFO line carrying the comms
            # turn so Loki can answer latency/volume/behaviour questions without
            # stitching DEBUG lines together.
            log.info(
                "turn complete",
                phase="turn_complete",
                status="ok",
                **self._turn_fields(),
            )

        except Exception as e:
            # Same wide event on the failure path (status=error) so error
            # turns are queryable with the identical field set.
            log.error(
                "turn failed",
                phase="turn_complete",
                status="error",
                error=str(e),
                error_type=type(e).__name__,
                **self._turn_fields(),
            )
            raise
        finally:
            # The drain owns the response once handed off; otherwise release it.
            if not handed_off:
                await resp.release()

    def _emit(self, text: str, source: str) -> ChatChunk:
        """Log + wrap a TTS chunk so we can see exactly WHEN text is handed to TTS."""
        log.info(
            "yield to TTS",
            phase="yield_tts",
            source=source,
            char_count=len(text),
            elapsed_ms=ms_since(self.turn_start),
        )
        return _tts_chunk(text)

    async def _stream_chunks(self, resp: aiohttp.ClientResponse) -> AsyncGenerator[ChatChunk, None]:
        """Consume the SSE body, yielding TTS chunks until [DONE] or stream end."""
        async for raw in resp.content:
            data = _parse_sse_line(raw)
            if data is None:
                continue

            if data == DONE_SENTINEL:
                self.stream_done = True
                log.info(
                    "[DONE] received",
                    phase="done_received",
                    elapsed_ms=ms_since(self.turn_start),
                )
                tail = await self._on_stream_done()
                if tail:
                    yield self._emit(tail, "stream_done_tail")
                # Forward [DONE] so the frontend knows the stream ended
                await self.llm.forward_stream_event_to_frontend(data)
                break

            spoken = await self._handle_event(data)
            if spoken:
                yield self._emit(spoken, "event")

            # Comms reply done — end the audio turn now so the ack plays at
            # once. The rest of the stream (executor events + answer) is handled
            # by the background drain spawned in run().
            if self.comms_complete:
                return

        # Stream ended without a completion marker — nothing left to drain.
        self.stream_done = True
        if self.tts_enabled:
            final_tail = await self._flush_buffer(
                min_chars=TTS_FINAL_MIN_CHARS, count_stats=True, label="TTS FINAL"
            )
            if final_tail:
                yield self._emit(final_tail, "final_tail")

    def _build_headers(self) -> dict[str, str]:
        headers = {"x-timezone": "UTC"}
        if self.llm.agent_token:
            headers["Authorization"] = f"Bearer {self.llm.agent_token}"
        return headers

    def _build_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message": self.user_message,
            "messages": self.messages,
            # Hold the stream open for a delegated executor's narrated answer
            # so we can speak it (it arrives as a `voice_tts` frame below).
            "voice_mode": True,
        }
        if self.llm.conversation_id:
            payload["conversation_id"] = self.llm.conversation_id
        return payload

    def _turn_fields(self) -> dict[str, Any]:
        """Shared field set for the turn_complete wide event (ok and error paths)."""
        return {
            "conversation_id": self.llm.conversation_id,
            "user_msg_len": len(self.user_message),
            "history_turns": len(self.messages),
            "total_tokens": self.total_tokens,
            "ttfb_ms": self.ttfb_ms,
            "first_tts_flush_ms": self.first_tts_flush_ms,
            "tts_flush_count": self.tts_flush_count,
            "tts_chars_total": self.tts_chars_total,
            "executor_tts_chars": self.executor_tts_chars,
            "total_ms": ms_since(self.turn_start),
        }

    async def _on_stream_done(self) -> str | None:
        """Log stream end and flush whatever text is still buffered."""
        log.debug(
            "stream done",
            phase="stream_done",
            total_tokens=self.total_tokens,
            elapsed_ms=ms_since(self.turn_start),
        )
        return await self._flush_buffer(min_chars=1, count_stats=False, label=None)

    async def _handle_event(self, data: str) -> str | None:
        """Process one SSE payload; returns sanitized text to speak, if any."""
        try:
            event_payload = json.loads(data)
        except json.JSONDecodeError:
            return None

        self._note_first_token()

        event_keys = set(event_payload.keys())
        is_plumbing = bool(event_keys & PLUMBING_EVENT_KEYS)

        # Plumbing/UI events (tool_data, follow_up_actions, conversation_*,
        # init chunk, main_response_complete) reach the frontend immediately so
        # cards render without waiting on speech. Response text is forwarded at
        # TTS-flush cadence below so the bubble fills in sync with the audio.
        if is_plumbing:
            await self.llm.forward_stream_event_to_frontend(data)

        log.info(
            "backend event",
            phase="backend_event",
            event_keys=list(event_keys),
            event_data=data[:300],
            is_plumbing=is_plumbing,
            elapsed_ms=ms_since(self.turn_start),
        )

        if event_payload.get(MAIN_RESPONSE_COMPLETE_KEY) is True:
            return await self._on_main_response_complete()

        conv_id = event_payload.get("conversation_id")
        if isinstance(conv_id, str) and conv_id:
            await self.llm.set_conversation_id(conv_id)
            return None

        conv_desc = event_payload.get("conversation_description")
        if isinstance(conv_desc, str) and conv_desc:
            await self.llm.set_conversation_description(conv_desc)
            return None

        # Delegated executor's narrated answer, delivered after the main
        # response (so after main_response_complete disabled TTS). Speak it
        # regardless of tts_enabled. Forward the frame to the frontend as the
        # comms→executor boundary marker (it does NOT render the text — the
        # answer comes from its own WebSocket push — but uses the frame's
        # arrival to stop folding TTS-aligned transcript into the comms bubble).
        voice_tts = event_payload.get(VOICE_TTS_KEY)
        if isinstance(voice_tts, str) and voice_tts:
            await self.llm.forward_stream_event_to_frontend(data)
            return self._on_executor_answer(voice_tts)

        # Plumbing events never contribute to TTS — drop here even if they
        # happen to carry a stray response field.
        if is_plumbing:
            return None

        return await self._on_response_piece(event_payload)

    def _note_first_token(self) -> None:
        if self.first_token_received:
            return
        self.first_token_received = True
        self.ttfb_ms = ms_since(self.turn_start)
        log.debug(
            "first token",
            phase="first_token",
            ttfb_ms=self.ttfb_ms,
        )

    async def _on_main_response_complete(self) -> str | None:
        """Flush the buffered main response, then disable TTS for later events."""
        tail = None
        if self.tts_enabled:
            tail = await self._flush_buffer(min_chars=1, count_stats=False, label=None)
        self.tts_enabled = False
        self.comms_complete = True
        log.info(
            "main response complete, ending audio turn",
            phase="main_response_complete",
            elapsed_ms=ms_since(self.turn_start),
            ack_flushed=bool(tail),
        )
        return tail

    def _on_executor_answer(self, voice_tts: str) -> str | None:
        spoken = sanitize_for_tts(voice_tts)
        if not spoken:
            return None
        self.executor_tts_chars += len(spoken)
        log.info(
            "executor answer arrived",
            phase="tts_executor_answer",
            char_count=len(spoken),
            elapsed_ms=ms_since(self.turn_start),
        )
        return spoken

    async def _on_response_piece(self, event_payload: dict[str, Any]) -> str | None:
        """Accumulate one response token and flush when a chunk is speakable."""
        piece = event_payload.get(RESPONSE_KEY, "")
        if not piece:
            return None
        if isinstance(piece, (list, tuple, set)):
            piece = "".join(str(x) for x in piece)
        elif not isinstance(piece, str):
            piece = str(piece)

        if not self.tts_enabled:
            return None

        self.text_buffer.append(piece)
        self.total_tokens += 1
        log.debug(
            "token",
            phase="token",
            token_index=self.total_tokens,
            token=piece,
            elapsed_ms=ms_since(self.turn_start),
        )

        if not self._should_flush():
            return None
        return await self._flush_buffer(
            min_chars=TTS_MIN_EMIT_CHARS, count_stats=True, label="TTS FLUSH"
        )

    def _should_flush(self) -> bool:
        """Sentence-or-size flush, deferred while a tag/fence straddles the boundary."""
        joined = "".join(self.text_buffer)
        should_flush = False
        if joined.endswith(SENTENCE_ENDINGS):
            if len(joined) >= TTS_MIN_SENTENCE_CHARS:
                should_flush = True
        elif len(joined) >= TTS_HARD_FLUSH_CHARS:
            should_flush = True

        if not should_flush:
            return False

        # An OpenUI fence must NEVER be split: a partial fence leaks its raw
        # component markup into TTS (the tail chunk no longer starts with
        # ':::openui', so the sanitiser can't recognise it) and reaches the
        # frontend as a broken block. Defer unconditionally until it closes —
        # _on_main_response_complete / _on_stream_done flush the rest, so a
        # complete (or genuinely truncated) fence is always sanitised as a unit.
        if has_open_openui_fence_at_tail(joined):
            return False

        # HTML tags are small; defer a bounded number of times so a
        # never-closing tag can't stall the stream indefinitely.
        if has_open_tag_at_tail(joined) and self.deferred_flushes < OPEN_TAG_DEFER_CAP:
            self.deferred_flushes += 1
            return False

        return True

    async def _flush_buffer(
        self, *, min_chars: int, count_stats: bool, label: str | None
    ) -> str | None:
        """Forward the raw buffer to the frontend, sanitize it for TTS, and clear it.

        The frontend gets the full display chunk (markdown + OpenUI preserved);
        TTS gets the sanitised copy, only when it clears ``min_chars``.
        """
        if not self.text_buffer:
            return None
        raw = "".join(self.text_buffer)
        self.text_buffer.clear()
        self.deferred_flushes = 0
        await self.llm.forward_response_text_to_frontend(raw)
        out = sanitize_for_tts(raw)
        if not out or len(out) < min_chars:
            return None
        if count_stats:
            self.tts_flush_count += 1
            self.tts_chars_total += len(out)
            if self.first_tts_flush_ms is None:
                self.first_tts_flush_ms = ms_since(self.turn_start)
        if label:
            log.debug(
                label,
                phase="tts_flush" if label == "TTS FLUSH" else "tts_final",
                text_before_sanitize=raw,
                text_after_sanitize=out,
                char_count=len(out),
                elapsed_ms=ms_since(self.turn_start),
            )
        return out


__all__ = ["CustomLLM"]
