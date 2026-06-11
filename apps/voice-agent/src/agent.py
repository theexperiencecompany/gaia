"""Voice agent entrypoint — prewarm, room session lifecycle, and worker startup."""

import asyncio
from pathlib import Path
import time
from typing import Any

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    AgentStateChangedEvent,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
    WorkerOptions,
    cli,
    metrics,
)
from livekit.plugins import deepgram, elevenlabs, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from shared.py.logging import configure_file_logging, get_contextual_logger
from shared.py.secrets import inject_infisical_secrets
from src.config import bootstrap_settings
from src.constants import MIN_ENDPOINTING_DELAY_S, VOICE_SYSTEM_PROMPT
from src.llm import CustomLLM
from src.utils import extract_meta_data, ms_since, now_ts

# Use an absolute path so logs land in the right place regardless of CWD
configure_file_logging(Path(__file__).parent.parent / "logs")

logger = get_contextual_logger("voice")


def prewarm(proc: JobProcess) -> None:
    """
    Run once per JobProcess at startup — before any room is assigned.

    LiveKit uses forkserver on Linux: each JobProcess is a fresh interpreter.
    Bootstrapping settings here guarantees exactly one Infisical network call per
    process, not one per room. VAD is also loaded here so room-join latency is
    not affected by model I/O. MultilingualModel is created per-room in entrypoint()
    because its constructor requires a job context.
    """
    logger.info(f"[{now_ts()}] ⚙ PREWARM START")
    t0 = time.monotonic()

    settings = bootstrap_settings()
    proc.userdata["settings"] = settings
    logger.info(f"[{now_ts()}] ⚙ settings loaded | {ms_since(t0):.0f}ms")

    t_vad = time.monotonic()
    proc.userdata["vad"] = silero.VAD.load()
    logger.info(f"[{now_ts()}] ⚙ VAD loaded | {ms_since(t_vad):.0f}ms")

    # MultilingualModel cannot be instantiated here — its __init__ calls
    # get_job_context().inference_executor which only exists inside entrypoint().
    logger.info(
        f"[{now_ts()}] ⚙ PREWARM DONE | total={ms_since(t0):.0f}ms",
        phase="prewarm_done",
        total_ms=ms_since(t0),
    )


async def entrypoint(ctx: JobContext) -> None:
    """Initialize and run the voice agent session for a single room."""
    settings = ctx.proc.userdata["settings"]
    ctx.log_context_fields = {"room": ctx.room.name}

    room_start = time.monotonic()
    logger.info(
        f"[{now_ts()}] 🚀 ROOM START | room={ctx.room.name}",
        phase="room_start",
        room=ctx.room.name,
    )

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
        min_endpointing_delay=MIN_ENDPOINTING_DELAY_S,
        preemptive_generation=True,
        use_tts_aligned_transcript=True,
    )

    _speaking_start: dict[str, float] = {}

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent) -> None:
        if ev.new_state == "speaking":
            _speaking_start["t"] = time.monotonic()
            logger.debug(
                f"[{now_ts()}] 🎤 USER SPEAKING START",
                phase="user_speaking_start",
            )
        elif ev.old_state == "speaking":
            duration_ms = ms_since(_speaking_start.get("t", time.monotonic()))
            logger.debug(
                f"[{now_ts()}] 🎤 USER SPEAKING END | duration={duration_ms:.0f}ms",
                phase="user_speaking_end",
                duration_ms=duration_ms,
            )

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: UserInputTranscribedEvent) -> None:
        stt_latency_ms = ms_since(_speaking_start.get("t", time.monotonic()))
        if ev.is_final:
            logger.info(
                f"[{now_ts()}] 📝 STT FINAL | lang={ev.language} | stt_latency={stt_latency_ms:.0f}ms",
                phase="stt_final",
                transcript=ev.transcript,
                language=ev.language,
                stt_latency_ms=stt_latency_ms,
            )
        else:
            logger.debug(
                f"[{now_ts()}] 📝 STT INTERIM ({len(ev.transcript)} chars)",
                phase="stt_interim",
                transcript=ev.transcript,
            )

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent) -> None:
        if ev.new_state == "thinking":
            logger.debug(
                f"[{now_ts()}] 🤔 AGENT THINKING — sending to backend",
                phase="agent_thinking",
            )
        elif ev.new_state == "speaking":
            logger.debug(
                f"[{now_ts()}] 🔊 AGENT SPEAKING START",
                phase="agent_speaking_start",
            )
        elif ev.old_state == "speaking":
            logger.debug(
                f"[{now_ts()}] 🔊 AGENT SPEAKING END",
                phase="agent_speaking_end",
            )

    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent) -> None:
        # Framework handles automatic resume when ev.resumed is True
        logger.info(
            f"[{now_ts()}] ↩ FALSE INTERRUPTION | resumed={ev.resumed}",
            phase="false_interruption",
            resumed=ev.resumed,
        )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage() -> None:
        summary = usage_collector.get_summary()
        logger.info(
            f"[{now_ts()}] 📊 SESSION USAGE",
            phase="session_usage",
            summary=str(summary),
        )

    ctx.add_shutdown_callback(log_usage)

    async def _apply_participant_credentials(md: str | None, origin: str, who: str) -> None:
        token, conv_id = extract_meta_data(md)
        if token:
            custom_llm.set_agent_token(token)
            logger.debug(
                f"[{now_ts()}] 🔑 TOKEN SET | participant={who} origin={origin}",
                phase="token_set",
                participant=who,
                origin=origin,
            )
        if conv_id:
            await custom_llm.set_conversation_id(conv_id)
            logger.debug(
                f"[{now_ts()}] 💬 CONV ID SET | {conv_id} participant={who}",
                phase="conv_id_set",
                conversation_id=conv_id,
                participant=who,
            )

    background_tasks: set[asyncio.Task[None]] = set()

    def _make_background_task(coro: Any) -> asyncio.Task[None]:
        task: asyncio.Task[None] = asyncio.create_task(coro)
        background_tasks.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            background_tasks.discard(t)
            if not t.cancelled() and t.exception():
                logger.error(
                    "Background credential task failed",
                    exc_info=t.exception(),
                )

        task.add_done_callback(_done)
        return task

    @ctx.room.on("participant_connected")
    def _on_participant_connected(p: rtc.RemoteParticipant) -> None:
        join_ts = now_ts()
        logger.info(
            f"[{join_ts}] 👤 PARTICIPANT JOINED | identity={p.identity}",
            phase="participant_joined",
            participant=p.identity,
        )
        _make_background_task(
            _apply_participant_credentials(
                getattr(p, "metadata", None), "participant_connected", p.identity
            )
        )

    @ctx.room.on("participant_metadata_changed")
    def _on_participant_metadata_changed(p: rtc.Participant, old_md: str, new_md: str) -> None:
        _make_background_task(
            _apply_participant_credentials(new_md, "participant_metadata_changed", p.identity)
        )

    # Connect before processing existing participants to avoid missing events
    # between connect() and the existing-participants loop (benign race: credentials
    # for a participant processed twice are idempotent).
    await ctx.connect()

    for p in ctx.room.remote_participants.values():
        logger.info(
            f"[{now_ts()}] 👤 EXISTING PARTICIPANT | identity={p.identity}",
            phase="existing_participant",
            participant=p.identity,
        )
        await _apply_participant_credentials(
            getattr(p, "metadata", None), "existing_participant", p.identity
        )

    logger.info(
        f"[{now_ts()}] ✅ SESSION START | room={ctx.room.name} setup={ms_since(room_start):.0f}ms",
        phase="session_start",
        room=ctx.room.name,
        setup_ms=ms_since(room_start),
    )

    await session.start(
        agent=Agent(instructions=VOICE_SYSTEM_PROMPT),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )


def start_worker() -> None:
    """Start the voice agent worker."""
    inject_infisical_secrets()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))


__all__ = ["prewarm", "entrypoint", "start_worker"]
