"""Voice agent entrypoint — prewarm, room session lifecycle, and worker startup."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import partial
import os
from pathlib import Path
import time
from typing import Any

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

from shared.py.analytics import PostHogAnalytics, VoiceAnalyticsEvents
from shared.py.logging import configure_file_logging
from shared.py.secrets import inject_infisical_secrets
from shared.py.wide_events import ModelContext, VoiceContext, get_trace_id, log, log_context
from src.config import bootstrap_settings
from src.constants import (
    BACKEND_REQUEST_TIMEOUT_S,
    MIN_ENDPOINTING_DELAY_S,
    PROMETHEUS_METRICS_PORT,
    PROMETHEUS_MULTIPROC_DIR,
    VOICE_SYSTEM_PROMPT,
    LogTag,
)
from src.llm import CustomLLM
from src.utils import extract_meta_data, ms_since, user_id_from_room

# Absolute path so logs land in the right place regardless of CWD. A no-op
# under LOG_FORMAT=json (containers), where stdout NDJSON goes to Loki instead.
# Promtail labels this container by its compose service name; keep the
# in-event `service` field equal to it so {service="voice-agent-worker"}
# and | json | service=... agree.
os.environ.setdefault("GAIA_SERVICE_NAME", "voice-agent-worker")

configure_file_logging(Path(__file__).parent.parent / "logs")


# evlog-map-disable-next-line wide-event -- sync per-fork bootstrap; no event loop for a boundary
def prewarm(proc: JobProcess) -> None:
    """
    Run once per JobProcess at startup — before any room is assigned.

    LiveKit uses forkserver on Linux: each JobProcess is a fresh interpreter.
    Bootstrapping settings here guarantees exactly one Infisical network call per
    process, not one per room. VAD is also loaded here so room-join latency is
    not affected by model I/O. MultilingualModel is created per-room in entrypoint()
    because its constructor requires a job context.
    """
    t0 = time.monotonic()

    settings = bootstrap_settings()
    proc.userdata["settings"] = settings
    settings_ms = ms_since(t0)

    # One PostHog client per JobProcess, for the same reason settings live here:
    # LiveKit forks a fresh interpreter per process, and a per-room client would
    # spawn a consumer thread per call. No-ops when the project token is absent.
    proc.userdata["analytics"] = PostHogAnalytics()

    t_vad = time.monotonic()
    proc.userdata["vad"] = silero.VAD.load()
    vad_ms = ms_since(t_vad)

    # MultilingualModel cannot be instantiated here — its __init__ calls
    # get_job_context().inference_executor which only exists inside entrypoint().
    log.info(
        f"{LogTag.AGENT} prewarm done",
        phase="prewarm_done",
        settings_ms=settings_ms,
        vad_ms=vad_ms,
        total_ms=ms_since(t0),
    )


@dataclass
class _SessionStats:
    """Per-session counters accumulated by the AgentSession lifecycle callbacks.

    Those callbacks fire after ``entrypoint`` has returned — i.e. after its
    wide event has already been emitted — so a ``log.set()`` from them reaches
    nothing. They accumulate here instead, and the shutdown callback reports
    the whole aggregate as one ``voice_session_end`` event.

    Transcript *content* stays out of the aggregate on purpose: only lengths
    and counts are carried into the queryable event.
    """

    speaking_start: float | None = None
    user_turns: int = 0
    user_speaking_ms: float = 0.0
    stt_final_count: int = 0
    stt_transcript_chars: int = 0
    stt_latency_ms_total: float = 0.0
    false_interruptions: int = 0

    @property
    def stt_latency_ms_avg(self) -> float:
        if not self.stt_final_count:
            return 0.0
        return round(self.stt_latency_ms_total / self.stt_final_count, 2)


def _register_session_logging(
    ctx: JobContext,
    session: AgentSession,
    identity: dict[str, Any],
    trace_id: str,
    analytics: PostHogAnalytics,
) -> None:
    """Wire per-session lifecycle logging: user/agent state, STT, metrics, usage.

    ``identity`` carries the room/user/job fields onto every event so one Loki
    filter reconstructs the session timeline; these callbacks fire outside the
    entrypoint's context, so the fields are passed explicitly rather than bound.
    ``trace_id`` is the entrypoint's, so the session-end event joins its
    ``voice_session_start`` counterpart.
    """
    stats = _SessionStats()

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent) -> None:
        if ev.new_state == "speaking":
            stats.speaking_start = time.monotonic()
            stats.user_turns += 1
            log.debug(
                f"{LogTag.AGENT} user speaking start", phase="user_speaking_start", **identity
            )
        elif ev.old_state == "speaking":
            duration_ms = ms_since(stats.speaking_start or time.monotonic())
            stats.user_speaking_ms += duration_ms
            log.debug(
                f"{LogTag.AGENT} user speaking end",
                phase="user_speaking_end",
                duration_ms=duration_ms,
                **identity,
            )

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: UserInputTranscribedEvent) -> None:
        stt_latency_ms = ms_since(stats.speaking_start or time.monotonic())
        if ev.is_final:
            stats.stt_final_count += 1
            stats.stt_transcript_chars += len(ev.transcript)
            stats.stt_latency_ms_total += stt_latency_ms
            log.info(
                f"{LogTag.AGENT} STT final",
                phase="stt_final",
                transcript=ev.transcript,
                language=ev.language,
                stt_latency_ms=stt_latency_ms,
                **identity,
            )
        else:
            log.debug(
                f"{LogTag.AGENT} STT interim",
                phase="stt_interim",
                transcript=ev.transcript,
                **identity,
            )

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent) -> None:
        if ev.new_state == "thinking":
            log.debug(f"{LogTag.AGENT} agent thinking", phase="agent_thinking", **identity)
        elif ev.new_state == "speaking":
            log.debug(
                f"{LogTag.AGENT} agent speaking start", phase="agent_speaking_start", **identity
            )
        elif ev.old_state == "speaking":
            log.debug(f"{LogTag.AGENT} agent speaking end", phase="agent_speaking_end", **identity)

    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent) -> None:
        # Framework handles automatic resume when ev.resumed is True
        stats.false_interruptions += 1
        log.info(
            f"{LogTag.AGENT} false interruption",
            phase="false_interruption",
            resumed=ev.resumed,
            **identity,
        )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_session_end(reason: str) -> None:
        """Emit the session's aggregated turn stats and STT/TTS/LLM usage.

        The boundary lives here, not in ``entrypoint``: LiveKit runs shutdown
        callbacks only after the entrypoint task has returned and the
        AgentSession has closed, so this is the first moment the whole session
        is knowable. It reuses the entrypoint's ``trace_id`` so this event and
        its ``voice_session_start`` counterpart join on it.
        """
        summary = usage_collector.get_summary()
        async with log_context("voice_session_end", trace_id=trace_id or None, **identity):
            log.set(
                voice=VoiceContext(
                    operation="session_end",
                    room=ctx.room.name,
                    shutdown_reason=reason,
                    user_turns=stats.user_turns,
                    user_speaking_ms=round(stats.user_speaking_ms, 2),
                    stt_final_count=stats.stt_final_count,
                    stt_transcript_chars=stats.stt_transcript_chars,
                    stt_latency_ms_avg=stats.stt_latency_ms_avg,
                    false_interruptions=stats.false_interruptions,
                    tts_characters=summary.tts_characters_count,
                    stt_audio_duration_s=round(summary.stt_audio_duration, 2),
                ),
                model=ModelContext(
                    input_tokens=summary.llm_prompt_tokens,
                    output_tokens=summary.llm_completion_tokens,
                    tokens_used=summary.llm_prompt_tokens + summary.llm_completion_tokens,
                    cached_tokens=summary.llm_prompt_cached_tokens,
                ),
            )
        # The same aggregate as the wide event, minus transcript lengths — Loki
        # answers "what happened in this session", PostHog answers "how much do
        # people use voice", so this carries only the usage shape. Outside the
        # log_context: a PostHog failure must not colour the event's outcome.
        user_id = identity.get("user_id")
        if user_id:
            analytics.capture(
                str(user_id),
                VoiceAnalyticsEvents.SESSION_ENDED,
                {
                    "shutdown_reason": reason,
                    "user_turns": stats.user_turns,
                    "user_speaking_ms": round(stats.user_speaking_ms, 2),
                    "tts_characters": summary.tts_characters_count,
                    "stt_audio_duration_s": round(summary.stt_audio_duration, 2),
                    "tokens_used": summary.llm_prompt_tokens + summary.llm_completion_tokens,
                },
            )

    ctx.add_shutdown_callback(log_session_end)


async def _apply_participant_credentials(
    md: str | None,
    origin: str,
    who: str,
    *,
    custom_llm: CustomLLM,
    tts: elevenlabs.TTS,
    applied_voice: dict[str, str],
    identity: dict[str, Any],
) -> None:
    """Apply agent token, TTS voice, and conversation id from participant metadata."""
    meta = extract_meta_data(md)
    token, conv_id, voice_id = meta.agent_token, meta.conversation_id, meta.voice_id
    if token:
        custom_llm.set_agent_token(token)
        log.debug(
            f"{LogTag.AGENT} token set",
            phase="token_set",
            participant=who,
            origin=origin,
            **identity,
        )
    if meta.backend_url and meta.backend_url != custom_llm.base_url:
        # Multi-backend deployments (staging previews) run ONE shared agent;
        # each session's metadata names the API that minted it.
        custom_llm.set_backend_url(meta.backend_url)
        log.info(
            f"{LogTag.AGENT} backend url set",
            phase="backend_url_set",
            backend_url=meta.backend_url,
            participant=who,
            **identity,
        )
    if voice_id and voice_id != applied_voice.get("id"):
        # User-selected ElevenLabs voice (set in Settings → Voice), carried
        # in the participant metadata minted by /token. Applies to all
        # synthesis from the next utterance on.
        applied_voice["id"] = voice_id
        tts.update_options(voice_id=voice_id)
        log.info(
            f"{LogTag.AGENT} voice set",
            phase="voice_set",
            voice_id=voice_id,
            participant=who,
            **identity,
        )
    if conv_id:
        await custom_llm.set_conversation_id(conv_id)
        log.debug(
            f"{LogTag.AGENT} conversation id set",
            phase="conv_id_set",
            conversation_id=conv_id,
            participant=who,
            **identity,
        )


def _spawn_credential_task(
    apply: Callable[[str | None, str, str], Coroutine[Any, Any, None]],
    md: str | None,
    origin: str,
    who: str,
    *,
    tasks: set[asyncio.Task[None]],
    identity: dict[str, Any],
    trace_id: str,
) -> None:
    """Run a credential coroutine in its own wide event, kept alive in `tasks`.

    This work applies the session's agent token, backend URL, TTS voice and
    conversation id — if it fails the session talks to the wrong backend or
    none at all — and it is spawned from room callbacks that fire long after
    the entrypoint's event emitted. Its own boundary (carrying the
    entrypoint's ``trace_id``) makes a credential failure one queryable event
    instead of a lone real-time line.
    """

    async def _run() -> None:
        async with log_context(
            "voice_credentials",
            trace_id=trace_id or None,
            origin=origin,
            **identity,
        ):
            log.set(
                voice=VoiceContext(
                    operation="credentials",
                    room=identity["room"],
                    participant=who,
                )
            )
            await apply(md, origin, who)

    task: asyncio.Task[None] = asyncio.create_task(_run())
    tasks.add(task)

    def _done(t: asyncio.Task[None]) -> None:
        # The boundary above already emitted the queryable failure event; this
        # keeps the traceback (which the event does not carry) and retrieves
        # the exception so asyncio does not report it as never-retrieved.
        tasks.discard(t)
        if not t.cancelled() and t.exception():
            log.error(
                f"{LogTag.AGENT} Background credential task failed",
                exc_info=t.exception(),
                **identity,
            )

    task.add_done_callback(_done)


async def entrypoint(ctx: JobContext) -> None:
    """Initialize and run the voice agent session for a single room."""
    settings = ctx.proc.userdata["settings"]
    ctx.log_context_fields = {"room": ctx.room.name}

    # Session identity: every event in this room carries the same
    # high-cardinality fields, so one LogQL filter (room=... or user_id=...)
    # reconstructs the full session timeline in Loki. The session event
    # callbacks fire outside this task's context, so identity is passed
    # explicitly into each log call rather than bound.
    user_id = user_id_from_room(ctx.room.name)
    identity: dict[str, Any] = {
        "room": ctx.room.name,
        "user_id": user_id,
        "job_id": getattr(ctx.job, "id", None),
    }
    # LiveKit invokes entrypoint with no logging middleware, so a boundary is
    # required — without it every log.set() below is silently discarded.
    #
    # This boundary deliberately covers SETUP ONLY. entrypoint() returns as
    # soon as session.start() has wired the room up; the call itself then runs
    # on LiveKit's own tasks until the room closes, and the job process only
    # awaits entrypoint again *after* shutdown (with a 15s cancel timeout), so
    # stretching this boundary over the session would either emit nothing for
    # the whole call or risk being cancelled before it emits. The session is
    # therefore reported by two events sharing one trace_id:
    #   voice_session_start — this one, setup and its latency;
    #   voice_session_end   — the shutdown callback in _register_session_logging,
    #                         carrying turn stats and STT/TTS/LLM usage.
    # Per-turn events come from the wide_task boundary in llm.py.
    analytics: PostHogAnalytics = ctx.proc.userdata["analytics"]

    async with log_context("voice_session_start", **identity):
        log.set(voice=VoiceContext(operation="session_start", room=ctx.room.name))
        session_trace_id = get_trace_id()
        # Attributed to the stable GAIA user id recovered from the room name —
        # the same id the API and web capture against, so a voice session lands
        # on the user's real profile. A room not minted by /token has no user to
        # attribute to, so it is left uncaptured rather than sent anonymously.
        if user_id:
            analytics.capture(
                user_id,
                VoiceAnalyticsEvents.SESSION_STARTED,
                {"room": ctx.room.name},
            )

        room_start = time.monotonic()

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

        # The drain speaks each delegated executor answer as its own utterance
        # once the comms turn has ended.
        custom_llm.session = session

        _register_session_logging(ctx, session, identity, session_trace_id, analytics)

        # Tracks the currently-applied TTS voice so repeated metadata events
        # (join + metadata_changed) don't re-apply the same voice.
        applied_voice: dict[str, str] = {}
        apply_credentials = partial(
            _apply_participant_credentials,
            custom_llm=custom_llm,
            tts=tts,
            applied_voice=applied_voice,
            identity=identity,
        )

        background_tasks: set[asyncio.Task[None]] = set()
        spawn_credentials = partial(
            _spawn_credential_task,
            apply_credentials,
            tasks=background_tasks,
            identity=identity,
            trace_id=session_trace_id,
        )

        @ctx.room.on("participant_connected")
        def _on_participant_connected(p: rtc.RemoteParticipant) -> None:
            log.info(
                f"{LogTag.AGENT} participant joined",
                phase="participant_joined",
                participant=p.identity,
                **identity,
            )
            spawn_credentials(getattr(p, "metadata", None), "participant_connected", p.identity)

        @ctx.room.on("participant_metadata_changed")
        def _on_participant_metadata_changed(p: rtc.Participant, _old_md: str, new_md: str) -> None:
            spawn_credentials(new_md, "participant_metadata_changed", p.identity)

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
            log.info(
                f"{LogTag.AGENT} existing participant",
                phase="existing_participant",
                participant=p.identity,
                **identity,
            )
            spawn_credentials(getattr(p, "metadata", None), "existing_participant", p.identity)

        log.info(
            f"{LogTag.AGENT} session start",
            phase="session_start",
            setup_ms=ms_since(room_start),
            **identity,
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
