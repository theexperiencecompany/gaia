"""Voice agent entrypoint — prewarm, room session lifecycle, and worker startup."""

import asyncio
from collections.abc import Coroutine
from functools import partial
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from livekit import rtc  # type: ignore[attr-defined]
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
from src.constants import (
    BACKEND_REQUEST_TIMEOUT_S,
    MIN_ENDPOINTING_DELAY_S,
    PROMETHEUS_METRICS_PORT,
    PROMETHEUS_MULTIPROC_DIR,
    VOICE_SYSTEM_PROMPT,
)
from src.llm import CustomLLM
from src.utils import extract_meta_data, ms_since, now_ts, user_id_from_room

if TYPE_CHECKING:
    from loguru import Logger

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


def _register_session_logging(ctx: JobContext, session: AgentSession, slog: "Logger") -> None:
    """Wire per-session lifecycle logging: user/agent state, STT, metrics, usage."""
    _speaking_start: dict[str, float] = {}

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent) -> None:
        if ev.new_state == "speaking":
            _speaking_start["t"] = time.monotonic()
            slog.debug(
                f"[{now_ts()}] 🎤 USER SPEAKING START",
                phase="user_speaking_start",
            )
        elif ev.old_state == "speaking":
            duration_ms = ms_since(_speaking_start.get("t", time.monotonic()))
            slog.debug(
                f"[{now_ts()}] 🎤 USER SPEAKING END | duration={duration_ms:.0f}ms",
                phase="user_speaking_end",
                duration_ms=duration_ms,
            )

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: UserInputTranscribedEvent) -> None:
        stt_latency_ms = ms_since(_speaking_start.get("t", time.monotonic()))
        if ev.is_final:
            slog.info(
                f"[{now_ts()}] 📝 STT FINAL | lang={ev.language} | stt_latency={stt_latency_ms:.0f}ms",
                phase="stt_final",
                transcript=ev.transcript,
                language=ev.language,
                stt_latency_ms=stt_latency_ms,
            )
        else:
            slog.debug(
                f"[{now_ts()}] 📝 STT INTERIM ({len(ev.transcript)} chars)",
                phase="stt_interim",
                transcript=ev.transcript,
            )

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent) -> None:
        if ev.new_state == "thinking":
            slog.debug(
                f"[{now_ts()}] 🤔 AGENT THINKING — sending to backend",
                phase="agent_thinking",
            )
        elif ev.new_state == "speaking":
            slog.debug(
                f"[{now_ts()}] 🔊 AGENT SPEAKING START",
                phase="agent_speaking_start",
            )
        elif ev.old_state == "speaking":
            slog.debug(
                f"[{now_ts()}] 🔊 AGENT SPEAKING END",
                phase="agent_speaking_end",
            )

    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent) -> None:
        # Framework handles automatic resume when ev.resumed is True
        slog.info(
            f"[{now_ts()}] ↩ FALSE INTERRUPTION | resumed={ev.resumed}",
            phase="false_interruption",
            resumed=ev.resumed,
        )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    # NOSONAR python:S7503 — add_shutdown_callback requires a coroutine function
    # (LiveKit awaits it); the body itself has no awaitable work.
    async def log_usage() -> None:  # NOSONAR python:S7503
        """Emit the session's aggregated STT/TTS/LLM usage at shutdown."""
        summary = usage_collector.get_summary()
        slog.info(
            f"[{now_ts()}] 📊 SESSION USAGE",
            phase="session_usage",
            summary=str(summary),
        )

    ctx.add_shutdown_callback(log_usage)


async def _apply_participant_credentials(
    md: str | None,
    origin: str,
    who: str,
    *,
    custom_llm: CustomLLM,
    tts: elevenlabs.TTS,
    applied_voice: dict[str, str],
    slog: "Logger",
) -> None:
    """Apply agent token, TTS voice, and conversation id from participant metadata."""
    meta = extract_meta_data(md)
    token, conv_id, voice_id = meta.agent_token, meta.conversation_id, meta.voice_id
    if token:
        custom_llm.set_agent_token(token)
        slog.debug(
            f"[{now_ts()}] 🔑 TOKEN SET | participant={who} origin={origin}",
            phase="token_set",
            participant=who,
            origin=origin,
        )
    if meta.backend_url and meta.backend_url != custom_llm.base_url:
        # Multi-backend deployments (staging previews) run ONE shared agent;
        # each session's metadata names the API that minted it.
        custom_llm.set_backend_url(meta.backend_url)
        slog.info(
            f"[{now_ts()}] 🌐 BACKEND URL SET | {meta.backend_url} participant={who}",
            phase="backend_url_set",
            backend_url=meta.backend_url,
            participant=who,
        )
    if voice_id and voice_id != applied_voice.get("id"):
        # User-selected ElevenLabs voice (set in Settings → Voice), carried
        # in the participant metadata minted by /token. Applies to all
        # synthesis from the next utterance on.
        applied_voice["id"] = voice_id
        tts.update_options(voice_id=voice_id)
        slog.info(
            f"[{now_ts()}] 🗣 VOICE SET | voice_id={voice_id} participant={who}",
            phase="voice_set",
            voice_id=voice_id,
            participant=who,
        )
    if conv_id:
        await custom_llm.set_conversation_id(conv_id)
        slog.debug(
            f"[{now_ts()}] 💬 CONV ID SET | {conv_id} participant={who}",
            phase="conv_id_set",
            conversation_id=conv_id,
            participant=who,
        )


def _spawn_credential_task(
    coro: Coroutine[Any, Any, None],
    tasks: set[asyncio.Task[None]],
    slog: "Logger",
) -> None:
    """Run a credential coroutine in the background, kept alive in `tasks`."""
    task: asyncio.Task[None] = asyncio.create_task(coro)
    tasks.add(task)

    def _done(t: asyncio.Task[None]) -> None:
        tasks.discard(t)
        if not t.cancelled() and t.exception():
            slog.error(
                "Background credential task failed",
                exc_info=t.exception(),
            )

    task.add_done_callback(_done)


async def entrypoint(ctx: JobContext) -> None:
    """Initialize and run the voice agent session for a single room."""
    settings = ctx.proc.userdata["settings"]
    ctx.log_context_fields = {"room": ctx.room.name}

    # Session-scoped logger: every event in this room carries the same
    # high-cardinality identity fields, so one LogQL filter (room=... or
    # user_id=...) reconstructs the full session timeline in Loki.
    user_id = user_id_from_room(ctx.room.name)
    slog = logger.bind(
        room=ctx.room.name,
        user_id=user_id,
        job_id=getattr(ctx.job, "id", None),
    )

    room_start = time.monotonic()
    slog.info(
        f"[{now_ts()}] 🚀 ROOM START | room={ctx.room.name}",
        phase="room_start",
    )

    custom_llm = CustomLLM(
        base_url=settings.GAIA_BACKEND_URL,
        room=ctx.room,
        request_timeout_s=BACKEND_REQUEST_TIMEOUT_S,
    )
    custom_llm.user_id = user_id

    tts = elevenlabs.TTS(
        api_key=settings.ELEVENLABS_API_KEY,
        voice_id=settings.ELEVENLABS_VOICE_ID,
        model=settings.ELEVENLABS_TTS_MODEL,
    )

    session: AgentSession = AgentSession(
        llm=custom_llm,
        stt=deepgram.STT(model="nova-3", language="multi"),
        tts=tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        min_endpointing_delay=MIN_ENDPOINTING_DELAY_S,
        preemptive_generation=True,
        use_tts_aligned_transcript=True,
    )

    # The drain speaks each delegated executor answer as its own utterance once
    # the comms turn has ended.
    custom_llm.session = session

    _register_session_logging(ctx, session, slog)

    # Tracks the currently-applied TTS voice so repeated metadata events
    # (join + metadata_changed) don't re-apply the same voice.
    applied_voice: dict[str, str] = {}
    apply_credentials = partial(
        _apply_participant_credentials,
        custom_llm=custom_llm,
        tts=tts,
        applied_voice=applied_voice,
        slog=slog,
    )

    background_tasks: set[asyncio.Task[None]] = set()

    @ctx.room.on("participant_connected")
    def _on_participant_connected(p: rtc.RemoteParticipant) -> None:
        join_ts = now_ts()
        slog.info(
            f"[{join_ts}] 👤 PARTICIPANT JOINED | identity={p.identity}",
            phase="participant_joined",
            participant=p.identity,
        )
        _spawn_credential_task(
            apply_credentials(getattr(p, "metadata", None), "participant_connected", p.identity),
            background_tasks,
            slog,
        )

    @ctx.room.on("participant_metadata_changed")
    def _on_participant_metadata_changed(p: rtc.Participant, _old_md: str, new_md: str) -> None:
        _spawn_credential_task(
            apply_credentials(new_md, "participant_metadata_changed", p.identity),
            background_tasks,
            slog,
        )

    # session.start() runs ctx.connect() CONCURRENTLY with its own setup
    # (RoomIO, STT, noise cancellation, agent track) — the previous serial
    # `await ctx.connect()` before start added ~1-2s to every session. All
    # room event handlers are registered above, before any connection exists,
    # so no participant events are missed.
    await session.start(
        agent=Agent(instructions=VOICE_SYSTEM_PROMPT),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
            delete_room_on_close=True,
        ),
    )

    # Participants who joined before the agent (the common case — the user
    # connects first) never emit participant_connected here; apply their
    # credentials now. Backgrounded: the broadcast inside does a network
    # round trip, and the first user turn is still endpointing-delay +
    # STT away, so the token lands long before it is needed.
    for p in ctx.room.remote_participants.values():
        slog.info(
            f"[{now_ts()}] 👤 EXISTING PARTICIPANT | identity={p.identity}",
            phase="existing_participant",
            participant=p.identity,
        )
        _spawn_credential_task(
            apply_credentials(getattr(p, "metadata", None), "existing_participant", p.identity),
            background_tasks,
            slog,
        )

    slog.info(
        f"[{now_ts()}] ✅ SESSION START | room={ctx.room.name} setup={ms_since(room_start):.0f}ms",
        phase="session_start",
        room=ctx.room.name,
        setup_ms=ms_since(room_start),
    )


def _run_worker_cli() -> None:
    """Hand control to LiveKit's CLI, which owns the start/dev/download-files commands."""
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # Worker metrics (lk_agents_active_job_count, lk_agents_worker_load,
            # ...) at :{port}/metrics for the Prometheus scrape job. The
            # multiproc dir aggregates metrics from forked job processes.
            prometheus_port=PROMETHEUS_METRICS_PORT,
            prometheus_multiproc_dir=PROMETHEUS_MULTIPROC_DIR,
        )
    )


def start_worker() -> None:
    """Start the voice agent worker.

    Injects Infisical secrets once in the host process before LiveKit's
    forkserver is initialised so every JobProcess inherits them.
    """
    inject_infisical_secrets()
    _run_worker_cli()


def download_files() -> None:
    """Pre-download plugin model files (turn detector, etc.) into the local cache.

    Required before the worker can run turn detection: the MultilingualModel loads
    with ``local_files_only=True`` at inference time and never fetches at runtime.
    No secrets needed — this only fetches public model files — so Infisical is not
    injected, which lets it run at Docker-build time.
    """
    _run_worker_cli()


__all__ = ["prewarm", "entrypoint", "start_worker", "download_files"]
