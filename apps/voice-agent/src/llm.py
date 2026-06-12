"""CustomLLM — streams SSE from the GAIA backend and yields ChatChunks for ElevenLabs TTS."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import json
import time
from typing import Any

import aiohttp
from livekit import rtc  # type: ignore[attr-defined]
from livekit.agents.llm import LLM, ChatChunk, ChatContext, ChoiceDelta

from shared.py.logging import get_contextual_logger
from src.constants import (
    DONE_SENTINEL,
    FRONTEND_STREAM_TOPIC,
    MAIN_RESPONSE_COMPLETE_KEY,
    OPEN_TAG_DEFER_CAP,
    RESPONSE_KEY,
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
    now_ts,
    sanitize_for_tts,
)

# Plumbing event keys that must never reach TTS.
# Any backend SSE event carrying one of these keys is forwarded to the frontend
# but never appended to the TTS text buffer.
PLUMBING_EVENT_KEYS = frozenset(
    {
        "tool_data",
        "tool_output",
        "follow_up_actions",
        "main_response_complete",
        "conversation_id",
        "conversation_description",
    }
)

logger = get_contextual_logger("voice")


class CustomLLM(LLM):
    """LLM adapter that streams SSE from POST /api/v1/chat-stream on the GAIA backend."""

    def __init__(
        self,
        base_url: str,
        request_timeout_s: float = 60.0,
        room: rtc.Room | None = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.agent_token: str | None = None
        self.conversation_id: str | None = None
        self.conversation_description: str | None = None
        self.request_timeout_s = request_timeout_s
        self.room: rtc.Room | None = room
        # Reused across turns to avoid TCP reconnect overhead per turn
        self._http_session: aiohttp.ClientSession | None = None

    def _get_http_session(self) -> aiohttp.ClientSession:
        """Return the shared HTTP session, creating it on first call."""
        if self._http_session is None or self._http_session.closed:
            connector = aiohttp.TCPConnector(limit=4)
            self._http_session = aiohttp.ClientSession(connector=connector)
        return self._http_session

    def set_agent_token(self, token: str) -> None:
        """Set the authentication token for backend requests."""
        self.agent_token = token

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
                logger.error("Failed to send conversation ID", error=str(e))

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
                logger.error("Failed to send conversation description", error=str(e))

    async def _forward_stream_event_to_frontend(self, raw_event: str) -> None:
        """Forward a raw backend SSE payload to the frontend via LiveKit data channel."""
        if not raw_event or not self.room or not self.room.local_participant:
            return
        try:
            await self.room.local_participant.send_text(
                raw_event,
                topic=FRONTEND_STREAM_TOPIC,
            )
            logger.debug(
                f"[{now_ts()}] → FRONTEND | topic={FRONTEND_STREAM_TOPIC} len={len(raw_event)}",
                phase="forward_frontend",
                payload_len=len(raw_event),
                payload_preview=raw_event[:300],
            )
        except Exception as e:
            logger.warning(
                "Failed to forward backend stream event to frontend",
                topic=FRONTEND_STREAM_TOPIC,
                error=str(e),
            )

    async def _forward_response_text_to_frontend(self, text: str) -> None:
        """Forward spoken response text to the frontend in flush-sized chunks.

        Sent at the same TTS-flush cadence as the audio (not per backend token)
        so the chat bubble fills in sync with the speech. The text is the raw
        buffered slice — OpenUI fences and markdown are preserved for rendering;
        only the TTS copy is sanitised.
        """
        if text:
            await self._forward_stream_event_to_frontend(json.dumps({RESPONSE_KEY: text}))

    # The base class declares chat() -> LLMStream, but the LiveKit pipeline calls it as
    # `async with llm.chat(...) as stream: async for chunk in stream:`, which is exactly
    # what @asynccontextmanager + yield gen() provides
    @asynccontextmanager
    async def chat(
        self, *, chat_ctx: ChatContext, **kwargs: Any
    ) -> AsyncGenerator[AsyncGenerator[ChatChunk, None], None]:
        """Stream SSE from the backend and yield ChatChunks for TTS."""

        async def gen() -> AsyncGenerator[ChatChunk, None]:
            turn_start = time.monotonic()
            ts = now_ts()

            user_message = extract_latest_user_text(chat_ctx)
            if not user_message:
                logger.warning(
                    f"[{ts}] ⚠ EMPTY USER MESSAGE — skipping LLM turn",
                    phase="turn_skip",
                )
                return

            logger.debug(
                f"[{ts}] ▶ TURN START ({len(user_message)} chars)",
                phase="turn_start",
                user_msg=user_message,
                user_msg_len=len(user_message),
            )

            tts_enabled = True
            first_token_received = False
            total_tokens = 0

            timeout = aiohttp.ClientTimeout(sock_read=self.request_timeout_s)
            headers = {"x-timezone": "UTC"}
            if self.agent_token:
                headers["Authorization"] = f"Bearer {self.agent_token}"

            # Build full message history from the LiveKit context so the backend
            # LLM has the complete conversation rather than just the latest turn.
            history = build_messages_from_ctx(chat_ctx)
            messages = history if history else [{"role": "user", "content": user_message}]

            payload: dict[str, Any] = {
                "message": user_message,
                "messages": messages,
                # Hold the stream open for a delegated executor's narrated answer
                # so we can speak it (it arrives as a `voice_tts` frame below).
                "voice_mode": True,
            }
            if self.conversation_id:
                payload["conversation_id"] = self.conversation_id

            logger.debug(
                f"[{now_ts()}] ⬆ BACKEND REQUEST | {self.base_url}/api/v1/chat-stream",
                phase="backend_request",
                elapsed_ms=ms_since(turn_start),
                conversation_id=self.conversation_id,
                user_message=user_message,
                history_turns=len(messages),
            )

            session = self._get_http_session()
            try:
                async with session.post(
                    f"{self.base_url}/api/v1/chat-stream",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        logger.error(
                            "Backend returned error response",
                            status=resp.status,
                            body=body[:500],
                            conversation_id=self.conversation_id,
                            elapsed_ms=ms_since(turn_start),
                        )
                        resp.raise_for_status()

                    text_buffer: list[str] = []
                    deferred_flushes = 0

                    async for raw in resp.content:
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="ignore").strip()
                        if not line or not line.startswith(SSE_DATA_PREFIX):
                            continue

                        data = line[len(SSE_DATA_PREFIX) :].strip()

                        if data == DONE_SENTINEL:
                            logger.debug(
                                f"[{now_ts()}] ■ STREAM DONE | tokens={total_tokens} elapsed={ms_since(turn_start):.0f}ms",
                                phase="stream_done",
                                total_tokens=total_tokens,
                                elapsed_ms=ms_since(turn_start),
                            )
                            if text_buffer:
                                tail = "".join(text_buffer)
                                text_buffer.clear()
                                await self._forward_response_text_to_frontend(tail)
                                final = sanitize_for_tts(tail)
                                if final:
                                    yield ChatChunk(
                                        id="custom",
                                        delta=ChoiceDelta(content=final),
                                    )
                            # Forward [DONE] so the frontend knows the stream ended
                            await self._forward_stream_event_to_frontend(data)
                            break

                        try:
                            event_payload = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        if not first_token_received:
                            first_token_received = True
                            ttfb = ms_since(turn_start)
                            logger.debug(
                                f"[{now_ts()}] ◎ FIRST TOKEN | TTFB={ttfb:.1f}ms",
                                phase="first_token",
                                ttfb_ms=ttfb,
                            )

                        event_keys = set(event_payload.keys())
                        is_plumbing = bool(event_keys & PLUMBING_EVENT_KEYS)

                        # Plumbing/UI events (tool_data, follow_up_actions,
                        # conversation_*, init chunk, main_response_complete) reach
                        # the frontend immediately so cards render without waiting
                        # on speech. Response text is forwarded at TTS-flush cadence
                        # below so the bubble fills in sync with the spoken audio.
                        if is_plumbing:
                            await self._forward_stream_event_to_frontend(data)

                        logger.debug(
                            f"[{now_ts()}] ~ BACKEND EVENT | keys={list(event_keys)} plumbing={is_plumbing}",
                            phase="backend_event",
                            event_keys=list(event_keys),
                            event_data=data[:300],
                            is_plumbing=is_plumbing,
                            elapsed_ms=ms_since(turn_start),
                        )

                        if event_payload.get(MAIN_RESPONSE_COMPLETE_KEY) is True:
                            if tts_enabled and text_buffer:
                                tail = "".join(text_buffer)
                                text_buffer.clear()
                                await self._forward_response_text_to_frontend(tail)
                                final = sanitize_for_tts(tail)
                                if final:
                                    yield ChatChunk(
                                        id="custom",
                                        delta=ChoiceDelta(content=final),
                                    )
                            tts_enabled = False
                            logger.debug(
                                f"[{now_ts()}] ✓ MAIN RESPONSE COMPLETE — TTS disabled for remaining events",
                                phase="main_response_complete",
                                elapsed_ms=ms_since(turn_start),
                            )
                            continue

                        conv_id = event_payload.get("conversation_id")
                        if isinstance(conv_id, str) and conv_id:
                            await self.set_conversation_id(conv_id)
                            continue

                        conv_desc = event_payload.get("conversation_description")
                        if isinstance(conv_desc, str) and conv_desc:
                            await self.set_conversation_description(conv_desc)
                            continue

                        # Delegated executor's narrated answer, delivered after the
                        # main response (so after main_response_complete disabled
                        # TTS). Speak it regardless of tts_enabled; do NOT forward to
                        # the frontend — it renders this from its WebSocket push.
                        voice_tts = event_payload.get(VOICE_TTS_KEY)
                        if isinstance(voice_tts, str) and voice_tts:
                            spoken = sanitize_for_tts(voice_tts)
                            if spoken:
                                logger.debug(
                                    f"[{now_ts()}] 🔊 TTS EXECUTOR ANSWER ({len(spoken)} chars)",
                                    phase="tts_executor_answer",
                                    char_count=len(spoken),
                                )
                                yield ChatChunk(
                                    id="custom",
                                    delta=ChoiceDelta(content=spoken),
                                )
                            continue

                        # Plumbing events never contribute to TTS — drop here even
                        # if they happen to carry a stray response field.
                        if is_plumbing:
                            continue

                        piece = event_payload.get(RESPONSE_KEY, "")
                        if not piece:
                            continue
                        if isinstance(piece, (list, tuple, set)):
                            piece = "".join(str(x) for x in piece)
                        elif not isinstance(piece, str):
                            piece = str(piece)

                        if not tts_enabled:
                            continue

                        text_buffer.append(piece)

                        total_tokens += 1
                        # Escape braces in the preview: loguru re-parses the
                        # message as a brace-format template (kwargs are present),
                        # so a JSON-ish token like {"label": ...} (e.g. an OpenUI
                        # fragment) would raise KeyError and kill the turn.
                        preview = piece[:60].replace("{", "{{").replace("}", "}}")
                        logger.debug(
                            f"[{now_ts()}] ≈ TOKEN #{total_tokens} | raw='{preview}'",
                            phase="token",
                            token_index=total_tokens,
                            token=piece,
                            elapsed_ms=ms_since(turn_start),
                        )

                        joined = "".join(text_buffer)

                        should_flush = False
                        if any(joined.endswith(p) for p in [".", "!", "?"]):
                            if len(joined) >= TTS_MIN_SENTENCE_CHARS:
                                should_flush = True
                        elif len(joined) >= TTS_HARD_FLUSH_CHARS:
                            should_flush = True

                        # Defer flush while an HTML tag or an OpenUI fence
                        # straddles the chunk boundary so sanitisation can see
                        # the whole construct.
                        if (
                            should_flush
                            and (
                                has_open_tag_at_tail(joined)
                                or has_open_openui_fence_at_tail(joined)
                            )
                            and deferred_flushes < OPEN_TAG_DEFER_CAP
                        ):
                            deferred_flushes += 1
                            should_flush = False

                        if should_flush:
                            # Send the full display chunk to the frontend (markdown
                            # + OpenUI preserved); TTS gets a sanitised copy.
                            await self._forward_response_text_to_frontend(joined)
                            out = sanitize_for_tts(joined)
                            text_buffer.clear()
                            deferred_flushes = 0
                            if len(out) >= TTS_MIN_EMIT_CHARS:
                                logger.debug(
                                    f"[{now_ts()}] 🔊 TTS FLUSH ({len(out)} chars) elapsed={ms_since(turn_start):.0f}ms",
                                    phase="tts_flush",
                                    text_before_sanitize=joined,
                                    text_after_sanitize=out,
                                    char_count=len(out),
                                    elapsed_ms=ms_since(turn_start),
                                )
                                yield ChatChunk(id="custom", delta=ChoiceDelta(content=out))

                    if tts_enabled and text_buffer:
                        raw_tail = "".join(text_buffer)
                        text_buffer.clear()
                        await self._forward_response_text_to_frontend(raw_tail)
                        tail = sanitize_for_tts(raw_tail)
                        if len(tail) >= TTS_FINAL_MIN_CHARS:
                            logger.debug(
                                f"[{now_ts()}] 🔊 TTS FINAL ({len(tail)} chars) elapsed={ms_since(turn_start):.0f}ms",
                                phase="tts_final",
                                text_before_sanitize=raw_tail,
                                text_after_sanitize=tail,
                                char_count=len(tail),
                                elapsed_ms=ms_since(turn_start),
                            )
                            yield ChatChunk(id="custom", delta=ChoiceDelta(content=tail))

                    logger.info(
                        f"[{now_ts()}] ✓ TURN COMPLETE | tokens={total_tokens} total={ms_since(turn_start):.0f}ms",
                        phase="turn_complete",
                        total_tokens=total_tokens,
                        total_ms=ms_since(turn_start),
                    )

            except aiohttp.ClientResponseError:
                raise
            except Exception as e:
                logger.error(
                    "Backend HTTP request failed",
                    error=str(e),
                    elapsed_ms=ms_since(turn_start),
                )
                raise

        yield gen()

    async def aclose(self) -> None:
        """Clean up HTTP session and room reference."""
        self.room = None
        try:
            if self._http_session and not self._http_session.closed:
                await self._http_session.close()
        except Exception as e:
            logger.warning("Failed to close backend HTTP session", error=str(e))
        finally:
            await super().aclose()


__all__ = ["CustomLLM"]
