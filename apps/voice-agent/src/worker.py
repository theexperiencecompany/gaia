"""Voice agent module for GAIA.

This module provides LiveKit-based voice agent functionality with STT, TTS, and LLM integration.
It streams chat responses from the backend and integrates with ElevenLabs for text-to-speech.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import json
import re
import sys
from typing import Any

import aiohttp
from livekit import rtc  # type: ignore[attr-defined]
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    metrics,
)
from livekit.agents.llm import LLM, ChatChunk, ChatContext, ChoiceDelta
from livekit.plugins import (  # type: ignore[attr-defined]
    deepgram,
    elevenlabs,
    noise_cancellation,
    silero,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from shared.py.logging import configure_file_logging, get_contextual_logger

# Write structured JSON log files for Promtail to scrape in local dev
configure_file_logging("./logs")

logger = get_contextual_logger("voice")

SSE_DATA_PREFIX = "data:"
DONE_SENTINEL = "[DONE]"
FRONTEND_STREAM_TOPIC = "backend-stream-event"
RESPONSE_KEY = "response"
MAIN_RESPONSE_COMPLETE_KEY = "main_response_complete"

# Matches OpenUI / HTML-style tags inside `response` chunks (e.g. <Label …>,
# </Section>, <Text foo="bar"/>). The LLM streams OpenUI markup through the
# same `response` field the UI parses for cards; without this, the tag names
# and attribute values leak into TTS.
_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_-]*(?:\s+[^>]*)?/?>")
_SENTINEL_RE = re.compile(r"(_BREAK|_MESSAGE|NEW)")
# Strip markdown structural characters that have no spoken form. Note: we
# intentionally do NOT strip `<` and `>` separately — _TAG_RE already removes
# matched tags, and standalone angle brackets in dictated prose are rare.
_MARKDOWN_RE = re.compile(r"[*_#`]")
_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_for_tts(piece: str) -> str:
    """Strip OpenUI tags, sentinel tokens, and markdown chars from a response chunk."""
    piece = _TAG_RE.sub(" ", piece)
    piece = _SENTINEL_RE.sub(" ", piece)
    piece = _MARKDOWN_RE.sub(" ", piece)
    return _WHITESPACE_RE.sub(" ", piece).strip()


def _has_open_tag_at_tail(s: str) -> bool:
    """True when the string ends inside an open tag (last `<` is later than last `>`)."""
    last_open = s.rfind("<")
    if last_open == -1:
        return False
    return s.rfind(">") < last_open


# Bound on how many times a flush may be deferred while a tag straddles chunks.
# Caps worst-case latency on a malformed/runaway tag stream.
_OPEN_TAG_DEFER_CAP = 4


def _extract_meta_data(md: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Extract agentToken and conversationId from participant metadata JSON."""
    if not md:
        return None, None
    try:
        obj = json.loads(md)
        token = obj.get("agentToken")
        conv_id = obj.get("conversationId")
        token = token if isinstance(token, str) and token else None
        conv_id = conv_id if isinstance(conv_id, str) and conv_id else None
        return token, conv_id
    except Exception:
        return None, None


def _extract_latest_user_text(chat_ctx: ChatContext) -> str:
    """Best-effort extraction of the latest user text string from ChatContext."""
    for item in reversed(chat_ctx.items):
        role = getattr(item, "role", item.__class__.__name__.lower())
        if role == "user":
            content = getattr(item, "content", [getattr(item, "output", "")])
            parts = []
            for c in content:
                if hasattr(c, "model_dump"):
                    d = c.model_dump()
                    if isinstance(d, dict):
                        parts.append(d.get("text", ""))
                else:
                    parts.append(str(c))
            out = " ".join(p for p in parts if p)
            if out:
                return out
    return ""


class CustomLLM(LLM):
    """Custom LLM adapter for streaming chat responses from backend."""

    def __init__(self, base_url: str, request_timeout_s: float = 60.0, room=None):
        """Initialize CustomLLM with backend URL and optional LiveKit room."""
        super().__init__()
        self.base_url = base_url
        self.agent_token: str | None = None
        self.conversation_id: str | None = None
        self.conversation_description: str | None = None
        self.request_timeout_s = request_timeout_s
        self.room = room

    def set_agent_token(self, token: str | None):
        """Set the authentication token for backend requests."""
        self.agent_token = token

    async def set_conversation_id(self, conversation_id: str | None):
        """Store and broadcast conversation ID to room participants."""
        self.conversation_id = conversation_id
        if self.room and self.room.local_participant:
            try:
                await self.room.local_participant.send_text(
                    conversation_id, topic="conversation-id"
                )
            except Exception as e:
                logger.error(f"Failed to send conversation ID: {e}")

    async def set_conversation_description(self, description: str | None):
        """Store and broadcast conversation description to room participants."""
        self.conversation_description = description
        if self.room and self.room.local_participant:
            try:
                await self.room.local_participant.send_text(
                    description, topic="conversation-description"
                )
            except Exception as e:
                logger.error(f"Failed to send conversation description: {e}")

    async def _forward_stream_event_to_frontend(self, raw_event: str) -> None:
        """Forward raw backend stream payloads to frontend without modification."""
        if not raw_event or not self.room or not self.room.local_participant:
            return
        try:
            await self.room.local_participant.send_text(
                raw_event,
                topic=FRONTEND_STREAM_TOPIC,
            )
            logger.info(
                "Forwarded backend stream event",
                stream_route="frontend",
                topic=FRONTEND_STREAM_TOPIC,
                payload=raw_event,
            )
        except Exception as e:
            logger.warning(
                "Failed to forward backend stream event",
                topic=FRONTEND_STREAM_TOPIC,
                error=str(e),
            )

    @asynccontextmanager
    async def chat(self, chat_ctx: ChatContext, **kwargs):  # type: ignore[override]
        """
        Stream Server-Sent Events from your backend and yield tiny ChatChunks so
        LiveKit can TTS-stream them immediately to ElevenLabs.
        """

        async def gen() -> AsyncGenerator[ChatChunk, None]:
            user_message = _extract_latest_user_text(chat_ctx)
            tts_enabled = True

            timeout = aiohttp.ClientTimeout(total=self.request_timeout_s)
            headers = {"x-timezone": "UTC"}
            if self.agent_token:
                headers["Authorization"] = f"Bearer {self.agent_token}"

            payload = {
                "message": user_message,
                "messages": [{"role": "user", "content": user_message}],
            }
            if self.conversation_id:
                payload["conversation_id"] = self.conversation_id

            async with aiohttp.ClientSession(timeout=timeout) as session:  # noqa: SIM117
                async with session.post(
                    f"{self.base_url}/api/v1/chat-stream",
                    headers=headers,
                    json=payload,
                ) as resp:
                    resp.raise_for_status()

                    text_buffer: list[str] = []
                    # Counts how many times we've deferred a flush because a tag
                    # straddles a chunk boundary. Reset on every successful flush.
                    deferred_flushes = 0

                    async for raw in resp.content:
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="ignore").strip()
                        if not line or not line.startswith(SSE_DATA_PREFIX):
                            continue

                        data = line[len(SSE_DATA_PREFIX) :].strip()
                        await self._forward_stream_event_to_frontend(data)

                        if data == DONE_SENTINEL:
                            if text_buffer:
                                final = _sanitize_for_tts("".join(text_buffer))
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

                        logger.info(
                            "Received backend stream event",
                            stream_route="backend",
                            event_keys=list(event_payload.keys()),
                        )

                        if event_payload.get(MAIN_RESPONSE_COMPLETE_KEY) is True:
                            if tts_enabled and text_buffer:
                                final = _sanitize_for_tts("".join(text_buffer))
                                text_buffer.clear()
                                if final:
                                    yield ChatChunk(
                                        id="custom",
                                        delta=ChoiceDelta(content=final),
                                    )
                            tts_enabled = False
                            logger.info(
                                "Main response complete received, disabled TTS for remaining events",
                                stream_route="tts",
                            )
                            continue

                        conv_id = event_payload.get("conversation_id")
                        if isinstance(conv_id, str) and conv_id:
                            await self.set_conversation_id(conv_id)
                            continue

                        # Handle conversation description (title)
                        conv_desc = event_payload.get("conversation_description")
                        if isinstance(conv_desc, str) and conv_desc:
                            await self.set_conversation_description(conv_desc)
                            continue

                        piece = event_payload.get(RESPONSE_KEY, "")
                        if not tts_enabled or not piece:
                            continue

                        # Append raw to the buffer; sanitization happens at
                        # flush time so tags split across chunks (e.g. `<hea`
                        # + `d>`) reassemble before the regex sees them.
                        if isinstance(piece, str):
                            text_buffer.append(piece)
                        elif isinstance(piece, (list, tuple, set)):
                            text_buffer.append("".join(str(x) for x in piece))
                        else:
                            text_buffer.append(str(piece))

                        joined = "".join(text_buffer)

                        should_flush = False
                        if any(joined.endswith(p) for p in [".", "!", "?"]):
                            if len(joined) >= 40:
                                should_flush = True
                        elif len(joined) >= 120:
                            should_flush = True

                        # Defer flush if the buffer ends inside an open tag so
                        # the sanitizer sees the full tag once it closes.
                        if (
                            should_flush
                            and _has_open_tag_at_tail(joined)
                            and deferred_flushes < _OPEN_TAG_DEFER_CAP
                        ):
                            deferred_flushes += 1
                            should_flush = False

                        if should_flush:
                            out = _sanitize_for_tts(joined)
                            text_buffer.clear()
                            deferred_flushes = 0
                            if len(out) >= 15:
                                logger.info(
                                    "Emitting TTS chunk",
                                    stream_route="tts",
                                    chunk_length=len(out),
                                )
                                yield ChatChunk(
                                    id="custom", delta=ChoiceDelta(content=out)
                                )
                                await asyncio.sleep(0.1)

                    if tts_enabled and text_buffer:
                        tail = _sanitize_for_tts("".join(text_buffer))
                        if len(tail) >= 1:
                            logger.info(
                                "Emitting final TTS chunk",
                                stream_route="tts",
                                chunk_length=len(tail),
                            )
                            yield ChatChunk(
                                id="custom", delta=ChoiceDelta(content=tail)
                            )

        yield gen()


def prewarm(proc: JobProcess):
    """Preload VAD model to reduce first-turn latency."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """Initialize and run the voice agent with STT, TTS, and LLM."""
    from src.config import load_settings

    settings = load_settings()

    ctx.log_context_fields = {"room": ctx.room.name}

    custom_llm = CustomLLM(
        base_url=settings.GAIA_BACKEND_URL,
        room=ctx.room,
    )

    session: AgentSession = AgentSession(
        llm=custom_llm,
        stt=deepgram.STT(model="nova-3", language="multi"),
        tts=elevenlabs.TTS(
            api_key=settings.ELEVENLABS_API_KEY,
            voice_id=settings.ELEVENLABS_VOICE_ID,
            model=settings.ELEVENLABS_TTS_MODEL,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        use_tts_aligned_transcript=True,
    )

    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        """Resume agent when false interruption is detected."""
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        """Log and collect usage metrics from agent session."""
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        """Log final usage summary on shutdown."""
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    async def _extract_and_set_participant_credentials(md: str | None):
        """Extract and set agent token and conversation ID from participant metadata."""
        token, conv_id = _extract_meta_data(md)
        if token:
            custom_llm.set_agent_token(token)
        if conv_id:
            await custom_llm.set_conversation_id(conv_id)

    background_tasks: set[Any] = set()

    @ctx.room.on("participant_connected")
    def _on_participant_connected(p: rtc.RemoteParticipant):
        """Handle new participant connection and process their metadata."""
        task = asyncio.create_task(
            _extract_and_set_participant_credentials(getattr(p, "metadata", None))
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    @ctx.room.on("participant_metadata_changed")
    def _on_participant_metadata_changed(p: rtc.Participant, old_md: str, new_md: str):
        task = asyncio.create_task(_extract_and_set_participant_credentials(new_md))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    await ctx.connect()
    for p in ctx.room.remote_participants.values():
        logger.info("participant already present, processing metadata")
        await _extract_and_set_participant_credentials(getattr(p, "metadata", None))

    await session.start(
        agent=Agent(instructions="Avoid markdowns"),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )


def download_files():
    """Download required model files."""
    logger.info("Downloading model files...")
    # The livekit-agents CLI handles model downloads
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))


def start_worker():
    """Start the voice agent worker."""
    from src.config import load_settings

    load_settings()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))


if __name__ == "__main__":
    is_download_command = any(arg.endswith("download-files") for arg in sys.argv)

    if not is_download_command:
        from src.config import load_settings

        load_settings()

    # Dispatch audit (fix-voice-mode-bugs-and-ux): default global auto-dispatch
    # is correct for production. Dev non-determinism comes from FE mounts (now
    # gated). Explicit `agent_name` + `RoomAgentDispatch` in /token is the next
    # knob if join latency stays bad — requires a backend change, deferred.
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
