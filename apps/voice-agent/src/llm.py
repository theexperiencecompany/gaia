"""CustomLLM — streams SSE from the GAIA backend and yields ChatChunks for ElevenLabs TTS."""

import json
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Optional

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
    RESPONSE_UI_KEY,
    SSE_DATA_PREFIX,
    TTS_FINAL_MIN_CHARS,
    TTS_HARD_FLUSH_CHARS,
    TTS_MIN_EMIT_CHARS,
    TTS_MIN_SENTENCE_CHARS,
)
from src.utils import (
    extract_latest_user_text,
    has_open_openui_fence_at_tail,
    has_open_tag_at_tail,
    ms_since,
    now_ts,
    sanitize_for_tts,
    split_response_for_ui_and_tts,
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


class CustomLLM(LLM):  # type: ignore[type-arg]
    """LLM adapter that streams SSE from POST /api/v1/chat-stream on the GAIA backend."""

    def __init__(
        self,
        base_url: str,
        request_timeout_s: float = 60.0,
        room: rtc.Room | None = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.agent_token: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.conversation_description: Optional[str] = None
        self.request_timeout_s = request_timeout_s
        self.room: rtc.Room | None = room
        # Reused across turns to avoid TCP reconnect overhead per turn
        self._http_session: Optional[aiohttp.ClientSession] = None

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
            )
        except Exception as e:
            logger.warning(
                "Failed to forward backend stream event to frontend",
                topic=FRONTEND_STREAM_TOPIC,
                error=str(e),
            )

    # The base class declares chat() -> LLMStream, but the LiveKit pipeline calls it as
    # `async with llm.chat(...) as stream: async for chunk in stream:`, which is exactly
    # what @asynccontextmanager + yield gen() provides. The type: ignore suppresses the
    # return-type mismatch; runtime behaviour is fully compatible with livekit-agents 1.x.
    @asynccontextmanager  # type: ignore[override]
    async def chat(
        self, *, chat_ctx: ChatContext, **kwargs: Any
    ) -> AsyncGenerator[AsyncGenerator[ChatChunk, None], None]:  # type: ignore[override]
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

            payload: dict[str, Any] = {
                "message": user_message,
                "messages": [{"role": "user", "content": user_message}],
            }
            if self.conversation_id:
                payload["conversation_id"] = self.conversation_id

            logger.debug(
                f"[{now_ts()}] ⬆ BACKEND REQUEST | {self.base_url}/api/v1/chat-stream",
                phase="backend_request",
                elapsed_ms=ms_since(turn_start),
                conversation_id=self.conversation_id,
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
                            # Forward [DONE] so the frontend knows the stream ended
                            await self._forward_stream_event_to_frontend(data)
                            if text_buffer:
                                final = sanitize_for_tts("".join(text_buffer))
                                text_buffer.clear()
                                if final:
                                    yield ChatChunk(
                                        id="custom",
                                        delta=ChoiceDelta(content=final),
                                    )
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
                        # Response-only events are split into a UI fragment
                        # (forwarded immediately) and a TTS fragment (delivered
                        # via LiveKit's TTS-aligned transcription channel). The
                        # raw event is NOT forwarded for response-only events so
                        # the chat bubble's spoken text fills in lockstep with
                        # ElevenLabs playback instead of racing ahead of audio.
                        is_response_only = event_keys == {RESPONSE_KEY}

                        if not is_response_only:
                            # Plumbing, multi-key, or anything else: forward as-is.
                            await self._forward_stream_event_to_frontend(data)

                        logger.debug(
                            f"[{now_ts()}] ~ BACKEND EVENT",
                            phase="backend_event",
                            event_keys=list(event_keys),
                            is_plumbing=is_plumbing,
                            is_response_only=is_response_only,
                            elapsed_ms=ms_since(turn_start),
                        )

                        if event_payload.get(MAIN_RESPONSE_COMPLETE_KEY) is True:
                            if tts_enabled and text_buffer:
                                final = sanitize_for_tts("".join(text_buffer))
                                text_buffer.clear()
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

                        # Split: UI-only fragments forward immediately so OpenUI
                        # cards render now; TTS-spoken text is buffered for
                        # ElevenLabs and reaches the frontend later via the
                        # TTS-aligned transcription channel.
                        ui_only, tts_text = split_response_for_ui_and_tts(piece)
                        if not ui_only and not tts_text:
                            continue

                        if ui_only:
                            ui_event = json.dumps({RESPONSE_UI_KEY: ui_only})
                            await self._forward_stream_event_to_frontend(ui_event)

                        if not tts_enabled or not tts_text:
                            continue

                        text_buffer.append(piece)

                        total_tokens += 1
                        logger.debug(
                            f"[{now_ts()}] ≈ TOKEN #{total_tokens}",
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
                            out = sanitize_for_tts(joined)
                            text_buffer.clear()
                            deferred_flushes = 0
                            if len(out) >= TTS_MIN_EMIT_CHARS:
                                logger.debug(
                                    f"[{now_ts()}] 🔊 TTS FLUSH ({len(out)} chars) elapsed={ms_since(turn_start):.0f}ms",
                                    phase="tts_flush",
                                    text=out,
                                    char_count=len(out),
                                    elapsed_ms=ms_since(turn_start),
                                )
                                yield ChatChunk(
                                    id="custom", delta=ChoiceDelta(content=out)
                                )

                    if tts_enabled and text_buffer:
                        tail = sanitize_for_tts("".join(text_buffer))
                        if len(tail) >= TTS_FINAL_MIN_CHARS:
                            logger.debug(
                                f"[{now_ts()}] 🔊 TTS FINAL ({len(tail)} chars) elapsed={ms_since(turn_start):.0f}ms",
                                phase="tts_final",
                                text=tail,
                                char_count=len(tail),
                                elapsed_ms=ms_since(turn_start),
                            )
                            yield ChatChunk(
                                id="custom", delta=ChoiceDelta(content=tail)
                            )

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
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        await super().aclose()


__all__ = ["CustomLLM"]
