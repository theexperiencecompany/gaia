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
from importlib import import_module
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
    WorkerOptions,
    cli,
    metrics,
    room_io,
)
from livekit.agents.llm import LLM, ChatChunk, ChatContext, ChoiceDelta
from shared.py.logging import configure_file_logging, get_contextual_logger

# Write structured JSON log files for Promtail to scrape in local dev
configure_file_logging("./logs")

logger = get_contextual_logger("voice")

_SENTENCE_ENDINGS = frozenset({".", "!", "?"})
_CLAUSE_ENDINGS = frozenset({",", ":", ";"})
_MIN_FLUSH_CHARS: int = 15
_COMMA_FLUSH_CHARS: int = 60
_HARD_FLUSH_CHARS: int = 80
_RUNTIME_MODULE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("deepgram", "livekit.plugins.deepgram", "livekit-plugins-deepgram"),
    ("elevenlabs", "livekit.plugins.elevenlabs", "livekit-plugins-elevenlabs"),
    (
        "noise_cancellation",
        "livekit.plugins.noise_cancellation",
        "livekit-plugins-noise-cancellation",
    ),
    ("silero", "livekit.plugins.silero", "livekit-plugins-silero"),
)
_TURN_DETECTOR_MODULE = "livekit.plugins.turn_detector.multilingual"
_TURN_DETECTOR_PACKAGE = "livekit-plugins-turn-detector"
_RUNTIME_DEPS: Optional[dict[str, Any]] = None


def _load_runtime_deps() -> dict[str, Any]:
    """Load LiveKit runtime plugins with clear errors when missing."""
    global _RUNTIME_DEPS

    if _RUNTIME_DEPS is not None:
        return _RUNTIME_DEPS

    deps: dict[str, Any] = {}
    missing_packages: list[str] = []

    for alias, module_path, package_name in _RUNTIME_MODULE_SPECS:
        try:
            deps[alias] = import_module(module_path)
        except ModuleNotFoundError:
            missing_packages.append(package_name)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to import {module_path!r} ({package_name}): {exc}"
            ) from exc

    try:
        turn_detector_mod = import_module(_TURN_DETECTOR_MODULE)
        deps["MultilingualModel"] = getattr(turn_detector_mod, "MultilingualModel")
    except ModuleNotFoundError:
        missing_packages.append(_TURN_DETECTOR_PACKAGE)
    except AttributeError as exc:
        raise RuntimeError(
            "Turn detector plugin is installed but MultilingualModel is missing."
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Failed to import {_TURN_DETECTOR_MODULE!r} "
            f"({_TURN_DETECTOR_PACKAGE}): {exc}"
        ) from exc

    if missing_packages:
        missing = ", ".join(sorted(set(missing_packages)))
        raise RuntimeError(
            "Voice agent dependency check failed. Missing LiveKit plugin "
            f"package(s): {missing}. Run `nx run voice-agent:sync` (or "
            "`uv sync --frozen` in apps/voice-agent) and retry."
        )

    _RUNTIME_DEPS = deps
    return deps


def _verify_startup_dependencies() -> None:
    """Fail fast with actionable guidance before process pool startup."""
    _load_runtime_deps()


def _verify_elevenlabs_credentials(settings: Any) -> None:
    """Validate ElevenLabs credentials with a lightweight API check."""
    api_key = settings.ELEVENLABS_API_KEY
    voice_id = settings.ELEVENLABS_VOICE_ID

    if not api_key:
        raise RuntimeError(
            "Voice agent startup check failed: ELEVENLABS_API_KEY is missing."
        )
    if not voice_id:
        raise RuntimeError(
            "Voice agent startup check failed: ELEVENLABS_VOICE_ID is missing."
        )

    request = Request(
        f"https://api.elevenlabs.io/v1/voices/{voice_id}",
        headers={"xi-api-key": api_key},
        method="GET",
    )

    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(
                    "Voice agent startup check failed: ElevenLabs voice lookup "
                    f"returned HTTP {response.status}."
                )
    except HTTPError as exc:
        body = exc.read(300).decode("utf-8", "ignore")
        if exc.code in {401, 403}:
            raise RuntimeError(
                "Voice agent startup check failed: ElevenLabs rejected "
                "ELEVENLABS_API_KEY. Please update the key in your secrets "
                "store."
            ) from exc
        if exc.code == 404:
            raise RuntimeError(
                "Voice agent startup check failed: ELEVENLABS_VOICE_ID was "
                "not found for the current account."
            ) from exc
        raise RuntimeError(
            "Voice agent startup check failed: ElevenLabs voice lookup "
            f"returned HTTP {exc.code}. Body: {body}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            "Voice agent startup check failed: could not reach ElevenLabs API. "
            "Check network/firewall/proxy settings."
        ) from exc


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
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
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

    def __init__(
        self,
        base_url: str,
        request_timeout_s: float = 60.0,
        room: Optional[rtc.Room] = None,
    ) -> None:
        """Initialize CustomLLM with backend URL and optional LiveKit room."""
        super().__init__()
        self.base_url = base_url
        self.agent_token: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.conversation_description: Optional[str] = None
        self.request_timeout_s = request_timeout_s
        self.room = room
        self._pending_tasks: set[asyncio.Task] = set()
        self._connector = aiohttp.TCPConnector(limit=10, keepalive_timeout=30)
        self._http_session = aiohttp.ClientSession(
            connector=self._connector,
            connector_owner=True,
        )

    def set_agent_token(self, token: Optional[str]):
        """Set the authentication token for backend requests."""
        self.agent_token = token

    async def set_conversation_id(self, conversation_id: Optional[str]):
        """Store and broadcast conversation ID to room participants."""
        self.conversation_id = conversation_id
        if self.room and self.room.local_participant and conversation_id:
            try:
                await self.room.local_participant.send_text(
                    conversation_id, topic="conversation-id"
                )
            except Exception as e:
                logger.error(f"Failed to send conversation ID: {e}")

    async def set_conversation_description(self, description: Optional[str]):
        """Store and broadcast conversation description to room participants."""
        self.conversation_description = description
        if self.room and self.room.local_participant and description:
            try:
                await self.room.local_participant.send_text(
                    description, topic="conversation-description"
                )
            except Exception as e:
                logger.error(f"Failed to send conversation description: {e}")

    async def aclose(self) -> None:
        """Close persistent HTTP session and connector."""
        await self._http_session.close()
        await self._connector.close()

    def _track_task(self, coro: Any) -> asyncio.Task:
        """Create and track an asyncio task to prevent GC before completion."""
        task: asyncio.Task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        return task

    async def _publish_event(self, topic: str, payload: dict[str, object]) -> None:
        """Serialize and broadcast a structured event to room participants."""
        if not (self.room and self.room.local_participant):
            return
        try:
            await self.room.local_participant.send_text(
                json.dumps(payload), topic=topic
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to publish event on topic %r: %s", topic, exc)

    # type: ignore[override]: livekit-agents LLM.chat() signature varies by version;
    # we accept **kwargs to remain forward-compatible with the plugin API.
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
            if self.agent_token:
                headers["Authorization"] = f"Bearer {self.agent_token}"

            request_body = {
                "message": user_message,
                "messages": [{"role": "user", "content": user_message}],
            }
            if self.conversation_id:
                request_body["conversation_id"] = self.conversation_id

            async with self._http_session.post(
                f"{self.base_url}/api/v1/chat-stream",
                headers=headers,
                json=request_body,
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()

                text_buffer: list[str] = []

                async for raw in resp.content:
                    if not raw:
                        continue
                    try:
                        line = raw.decode("utf-8").strip()
                    except UnicodeDecodeError as ude:
                        logger.warning("SSE line UTF-8 decode error, skipping: %s", ude)
                        continue
                    if not line or not line.startswith("data:") or line.startswith(":"):
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
                        event_data = json.loads(data)
                    except json.JSONDecodeError as exc:
                        logger.debug("Skipping malformed SSE line: %s", exc)
                        continue

                    if not isinstance(event_data, dict):
                        continue

                    conv_id = event_data.get("conversation_id")
                    if isinstance(conv_id, str) and conv_id:
                        await self.set_conversation_id(conv_id)
                        continue

                    # Handle conversation description (title)
                    conv_desc = event_data.get("conversation_description")
                    if isinstance(conv_desc, str) and conv_desc:
                        await self.set_conversation_description(conv_desc)
                        continue

                    # Route non-TTS events to LiveKit topics.
                    # Use fire-and-forget (create_task) to avoid blocking TTS.
                    if "error" in event_data and isinstance(event_data["error"], str):
                        await self._publish_event(
                            "stream-error", {"error": event_data["error"]}
                        )
                        continue

                    if "progress" in event_data and isinstance(
                        event_data["progress"], dict
                    ):
                        self._track_task(
                            self._publish_event(
                                "stream-progress", event_data["progress"]
                            )
                        )
                        continue

                    if "tool_data" in event_data and isinstance(
                        event_data["tool_data"], dict
                    ):
                        self._track_task(
                            self._publish_event(
                                "stream-tool-data", event_data["tool_data"]
                            )
                        )
                        continue

                    if "tool_output" in event_data and isinstance(
                        event_data["tool_output"], dict
                    ):
                        self._track_task(
                            self._publish_event(
                                "stream-tool-output", event_data["tool_output"]
                            )
                        )
                        continue

                    if "todo_progress" in event_data and isinstance(
                        event_data["todo_progress"], dict
                    ):
                        self._track_task(
                            self._publish_event(
                                "stream-todo-progress", event_data["todo_progress"]
                            )
                        )
                        continue

                    if "follow_up_actions" in event_data and isinstance(
                        event_data["follow_up_actions"], list
                    ):
                        self._track_task(
                            self._publish_event(
                                "stream-follow-up-actions",
                                {"actions": event_data["follow_up_actions"]},
                            )
                        )
                        continue

                    piece = event_data.get("response", "")
                    if not piece:
                        continue

                    if isinstance(piece, str):
                        piece = re.sub(r"(_BREAK|_MESSAGE|NEW|<|>)", " ", piece)

                    if not piece:
                        continue

                    if isinstance(piece, str):
                        text_buffer.append(piece)
                    elif isinstance(piece, (list, tuple, set)):
                        text_buffer.append("".join(str(x) for x in piece))
                    else:
                        text_buffer.append(str(piece))
                    joined = "".join(text_buffer)

                    should_flush = False

                    if (
                        joined[-1] in _SENTENCE_ENDINGS
                        and len(joined) >= _MIN_FLUSH_CHARS
                    ):
                        should_flush = True
                    elif (
                        joined[-1] in _CLAUSE_ENDINGS
                        and len(joined) >= _COMMA_FLUSH_CHARS
                    ):
                        should_flush = True
                    elif len(joined) >= _HARD_FLUSH_CHARS:
                        should_flush = True

                    if should_flush:
                        out = joined.strip()
                        text_buffer.clear()
                        if len(out) >= 15:
                            yield ChatChunk(id="custom", delta=ChoiceDelta(content=out))
                    # NOTE: No sleep here — ElevenLabs turbo handles pacing internally.

                if text_buffer:
                    tail = "".join(text_buffer).strip()
                    if len(tail) >= 1:
                        yield ChatChunk(id="custom", delta=ChoiceDelta(content=tail))

        yield gen()


def prewarm(proc: JobProcess):
    """Preload VAD model to reduce first-turn latency."""
    from src.config import load_settings

    runtime_deps = _load_runtime_deps()
    silero = runtime_deps["silero"]
    s = load_settings()
    proc.userdata["vad"] = silero.VAD.load(
        min_silence_duration=s.VAD_MIN_SILENCE_DURATION,
        prefix_padding_duration=s.VAD_PREFIX_PADDING_DURATION,
    )


async def entrypoint(ctx: JobContext):
    """Initialize and run the voice agent with STT, TTS, and LLM."""
    from src.config import load_settings

    runtime_deps = _load_runtime_deps()
    deepgram = runtime_deps["deepgram"]
    elevenlabs = runtime_deps["elevenlabs"]
    noise_cancellation = runtime_deps["noise_cancellation"]
    multilingual_model = runtime_deps["MultilingualModel"]

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
            streaming_latency=settings.ELEVENLABS_STREAMING_LATENCY,
            auto_mode=settings.ELEVENLABS_AUTO_MODE,
            chunk_length_schedule=settings.ELEVENLABS_CHUNK_LENGTH_SCHEDULE,
        ),
        turn_detection=multilingual_model(),
        vad=ctx.proc.userdata["vad"],
        min_endpointing_delay=settings.MIN_ENDPOINTING_DELAY,
        max_endpointing_delay=settings.MAX_ENDPOINTING_DELAY,
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
    ctx.add_shutdown_callback(custom_llm.aclose)

    async def _extract_and_set_participant_credentials(
        md: Optional[str], origin: str, who: str
    ):
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

    @ctx.room.on("participant_disconnected")
    def _on_participant_disconnected(p: rtc.Participant):
        logger.info("participant disconnected: {}", p.identity)

    await ctx.connect()
    for p in ctx.room.remote_participants.values():
        logger.info("participant already present, processing metadata")
        await _extract_and_set_participant_credentials(
            getattr(p, "metadata", None), "existing_participant", p.identity
        )

    await session.start(
        agent=Agent(instructions="Avoid markdowns"),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            close_on_disconnect=False,
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVC(),
            ),
        ),
    )


def download_files():
    """Download required model files."""
    logger.info("Downloading model files...")
    _verify_startup_dependencies()
    # The livekit-agents CLI handles model downloads
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))


def start_worker():
    """Start the voice agent worker."""
    from src.config import load_settings

    settings = load_settings()
    _verify_startup_dependencies()
    _verify_elevenlabs_credentials(settings)
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))


if __name__ == "__main__":
    is_download_command = any(arg.endswith("download-files") for arg in sys.argv)

    if not is_download_command:
        from src.config import load_settings

        settings = load_settings()
        _verify_elevenlabs_credentials(settings)

    _verify_startup_dependencies()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
