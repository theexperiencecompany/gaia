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
from livekit.plugins import deepgram, elevenlabs, noise_cancellation, silero  # type: ignore[attr-defined]
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from shared.py.logging import configure_file_logging, get_contextual_logger

# Write structured JSON log files for Promtail to scrape in local dev
configure_file_logging("./logs")

logger = get_contextual_logger("voice")


def _extract_conversation_id(md: Optional[str]) -> Optional[str]:
    """Extract conversationId from participant metadata JSON."""
    if not md:
        return None
    try:
        obj = json.loads(md)
        conv_id = obj.get("conversationId")
        return conv_id if isinstance(conv_id, str) and conv_id else None
    except Exception:
        return None


async def _fetch_agent_token(
    base_url: str, agent_secret: str, user_id: str, room_name: str
) -> Optional[str]:
    """Fetch a short-lived agent JWT from the backend using the shared secret (C7).

    The JWT is never placed in LiveKit room metadata — fetching it here keeps
    it out of reach of other room participants.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url}/api/v1/voice/agent-token",
                json={"user_id": user_id, "room_name": room_name},
                headers={"X-Agent-Secret": agent_secret},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("token")
                logger.warning(f"agent-token endpoint returned {resp.status}")
    except Exception as e:
        logger.error(f"Failed to fetch agent token: {e}")
    return None


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
        # Agent JWTs are single-use (C7) — fetch a fresh one per chat-stream
        # request rather than caching one for the room. The room name +
        # user id + shared secret are kept here so we can mint per-call.
        self.agent_secret: Optional[str] = None
        self.user_id_for_token: Optional[str] = None
        self.room_name: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.conversation_description: Optional[str] = None
        self.request_timeout_s = request_timeout_s
        self.room = room

    def set_agent_credentials(
        self,
        agent_secret: Optional[str],
        user_id: Optional[str],
        room_name: Optional[str],
    ):
        """Store credentials used to mint a fresh single-use JWT per call."""
        self.agent_secret = agent_secret
        self.user_id_for_token = user_id
        self.room_name = room_name

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

    async def set_conversation_description(self, description: Optional[str]):
        """Store and broadcast conversation description to room participants."""
        self.conversation_description = description
        if self.room and self.room.local_participant:
            try:
                await self.room.local_participant.send_text(
                    description, topic="conversation-description"
                )
            except Exception as e:
                logger.error(f"Failed to send conversation description: {e}")

    @asynccontextmanager
    async def chat(self, chat_ctx: ChatContext, **kwargs):  # type: ignore[override]
        """
        Stream Server-Sent Events from your backend and yield tiny ChatChunks so
        LiveKit can TTS-stream them immediately to ElevenLabs.
        """

        async def gen() -> AsyncGenerator[ChatChunk, None]:
            user_message = _extract_latest_user_text(chat_ctx)

            timeout = aiohttp.ClientTimeout(total=self.request_timeout_s)
            headers = {"x-timezone": "UTC"}
            # Mint a fresh single-use agent JWT per chat-stream call (C7).
            # The token's jti is consumed atomically by the backend on
            # verify, so reusing one across calls would fail every call
            # after the first.
            if self.agent_secret and self.user_id_for_token and self.room_name:
                fresh_token = await _fetch_agent_token(
                    self.base_url,
                    self.agent_secret,
                    self.user_id_for_token,
                    self.room_name,
                )
                if fresh_token:
                    headers["Authorization"] = f"Bearer {fresh_token}"
                    headers["X-Room-Id"] = self.room_name

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
                                    text_buffer.clear()
                            break

                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        conv_id = payload.get("conversation_id")
                        if isinstance(conv_id, str) and conv_id:
                            await self.set_conversation_id(conv_id)
                            continue

                        # Handle conversation description (title)
                        conv_desc = payload.get("conversation_description")
                        if isinstance(conv_desc, str) and conv_desc:
                            await self.set_conversation_description(conv_desc)
                            continue

                        piece = payload.get("response", "")
                        if not piece:
                            continue

                        if isinstance(piece, str):
                            piece = re.sub(r"(_BREAK|_MESSAGE|NEW|<|>)", " ", piece)

                            if piece.strip() == "":
                                piece = " "

                                last = text_buffer[-1] if text_buffer else ""
                                if (
                                    last
                                    and not last.endswith(" ")
                                    and piece
                                    and not piece.startswith(" ")
                                ):
                                    piece = " " + piece

                        if piece is None or piece == "":
                            continue

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

                        if should_flush:
                            out = joined.strip()
                            text_buffer.clear()
                            if len(out) >= 15:
                                yield ChatChunk(
                                    id="custom", delta=ChoiceDelta(content=out)
                                )
                                await asyncio.sleep(0.1)

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

    async def _apply_participant_metadata(md: Optional[str]) -> None:
        """Update conversation ID from participant metadata (agentToken no longer in metadata)."""
        conv_id = _extract_conversation_id(md)
        if conv_id:
            await custom_llm.set_conversation_id(conv_id)

    background_tasks: set[Any] = set()

    @ctx.room.on("participant_connected")
    def _on_participant_connected(p: rtc.RemoteParticipant):
        """Handle new participant connection and process their metadata."""
        task = asyncio.create_task(
            _apply_participant_metadata(getattr(p, "metadata", None))
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    @ctx.room.on("participant_metadata_changed")
    def _on_participant_metadata_changed(p: rtc.Participant, old_md: str, new_md: str):
        task = asyncio.create_task(_apply_participant_metadata(new_md))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    await ctx.connect()

    # Stash credentials on the LLM so each chat-stream call mints its own
    # fresh single-use agent JWT (C7). The identity format set by
    # voice_token.py is "user_<user_id>".
    if settings.AGENT_SECRET:
        user_id_for_token: Optional[str] = None
        for p in ctx.room.remote_participants.values():
            identity = getattr(p, "identity", "")
            if identity.startswith("user_"):
                user_id_for_token = identity[5:]
                break
        if user_id_for_token:
            custom_llm.set_agent_credentials(
                settings.AGENT_SECRET, user_id_for_token, ctx.room.name
            )

    for p in ctx.room.remote_participants.values():
        logger.info("participant already present, processing metadata")
        await _apply_participant_metadata(getattr(p, "metadata", None))

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

    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
