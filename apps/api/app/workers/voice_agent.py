"""Voice agent module for GAIA.

This module provides LiveKit-based voice agent functionality with STT, TTS, and LLM integration.
It streams chat responses from the backend and integrates with ElevenLabs for text-to-speech.
"""

import asyncio
import json
import re
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional, Any

import aiohttp
from app.config.loggers import app_logger as logger
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
from livekit.plugins import deepgram, elevenlabs, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

_settings_instance: Any = None


def load_settings():
    """Dynamically loads settings, triggering Infisical only on the first call."""
    global _settings_instance
    if _settings_instance is None:
        from app.config.settings import settings

        _settings_instance = settings
    return _settings_instance


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
        self.agent_token: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.request_timeout_s = request_timeout_s
        self.room = room

    def set_agent_token(self, token: Optional[str]):
        """Set the authentication token for backend requests."""
        self.agent_token = token

    async def set_conversation_id(self, conversation_id: Optional[str]):
        """Store and broadcast conversation ID to room participants."""
        self.conversation_id = conversation_id
        if self.room and self.room.local_participant:
            try:
                await self.room.local_participant.send_text(
                    conversation_id, topic="conversation-id"
                )
            except Exception as e:
                logger.error(f"Failed to send conversation ID: {e}")

    @asynccontextmanager
    async def chat(self, chat_ctx: ChatContext, **kwargs):
        """
        Stream Server-Sent Events from your backend and yield tiny ChatChunks so
        LiveKit can TTS-stream them immediately to ElevenLabs.
        """

        async def gen() -> AsyncGenerator[ChatChunk, None]:
            user_message = _extract_latest_user_text(chat_ctx)

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

                    async for raw in resp.content:
                        if not raw:
                            continue
                        line = raw.decode("utf-8", errors="ignore").strip()
                        if not line or not line.startswith("data:"):
                            continue

                        data = line[5:].strip()
                        if data == "[DONE]":
                            if text_buffer:
                                chunk = "".join(text_buffer).strip()
                                if chunk:
                                    yield ChatChunk(
                                        id="custom", delta=ChoiceDelta(content=chunk)
                                    )
                                    text_buffer.clear()  # Clear buffer after yielding to avoid duplicate final flush
                            break

                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        conv_id = payload.get("conversation_id")
                        if isinstance(conv_id, str) and conv_id:
                            await self.set_conversation_id(conv_id)
                            continue

                        piece = payload.get("response", "")
                        if not piece:
                            continue

                        if isinstance(piece, str):
                            piece = re.sub(r"(_BREAK|_MESSAGE|NEW|<|>)", " ", piece)

                            if piece.strip() == "":
                                piece = " "

                                last = text_buffer[-1]
                                if (
                                    last
                                    and not last.endswith(" ")
                                    and piece
                                    and not piece.startswith(" ")
                                ):
                                    piece = " " + piece

                        if piece is None or piece == "":
                            continue

                        # Ensure only strings are appended to text_buffer
                        if isinstance(piece, str):
                            text_buffer.append(piece)
                        elif isinstance(piece, (list, tuple, set)):
                            text_buffer.append("".join(str(x) for x in piece))
                        else:
                            text_buffer.append(str(piece))
                        joined = "".join(text_buffer)

                        #  Control when to send buffered text chunks to the text-to-speech (TTS) system for streaming playback.
                        should_flush = False

                        # Natural sentence boundary
                        if any(joined.endswith(p) for p in [".", "!", "?"]):
                            if len(joined) >= 40:  # avoid ultra-short chunks
                                should_flush = True

                        # Mid-sentence, buffer getting long
                        elif len(joined) >= 120:
                            should_flush = True

                        if should_flush:
                            out = joined.strip()
                            text_buffer.clear()
                            if len(out) >= 15:  # safety: never flush tiny fragments
                                # small debounce to coalesce nearby tokens
                                yield ChatChunk(
                                    id="custom", delta=ChoiceDelta(content=out)
                                )
                                await asyncio.sleep(0.1)

                    # Final flush (only if buffer is not empty, and wasn't just flushed)
                    if text_buffer:
                        tail = "".join(text_buffer).strip()
                        if len(tail) >= 1:
                            yield ChatChunk(
                                id="custom", delta=ChoiceDelta(content=tail)
                            )

        yield gen()


def prewarm(proc: JobProcess):
    """Preload VAD model to reduce first-turn latency."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """Initialize and run the voice agent with STT, TTS, and LLM."""

    settings = load_settings()

    ctx.log_context_fields = {"room": ctx.room.name}

    custom_llm = CustomLLM(
        base_url=settings.GAIA_BACKEND_URL,
        room=ctx.room,
    )

    session = AgentSession(
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

    # --- Register event listeners BEFORE connecting ---
    async def _extract_and_set_participant_credentials(
        md: Optional[str], origin: str, who: str
    ):
        """Extract and set agent token and conversation ID from participant metadata."""
        token, conv_id = _extract_meta_data(md)
        if token:
            custom_llm.set_agent_token(token)
        if conv_id:
            await custom_llm.set_conversation_id(conv_id)

    background_tasks = set()

    @ctx.room.on("participant_connected")
    def _on_participant_connected(p: rtc.RemoteParticipant):
        """Handle new participant connection and process their metadata."""
        logger.info("ddd")
        task = asyncio.create_task(
            _extract_and_set_participant_credentials(
                getattr(p, "metadata", None), "participant_connected", p.identity
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    @ctx.room.on("participant_metadata_changed")
    def _on_participant_metadata_changed(p: rtc.Participant, old_md: str, new_md: str):
        task = asyncio.create_task(
            _extract_and_set_participant_credentials(
                new_md, "participant_metadata_changed", p.identity
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    await ctx.connect()
    for p in ctx.room.remote_participants.values():
        logger.info("participant already present, processing metadata")
        await _extract_and_set_participant_credentials(
            getattr(p, "metadata", None), "existing_participant", p.identity
        )

    await session.start(
        agent=Agent(instructions="Avoid markdowns"),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )


if __name__ == "__main__":
    is_download_command = any(arg.endswith("download-files") for arg in sys.argv)

    if not is_download_command:
        load_settings()

    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
