"""True provider time-to-first-token, measured per streaming LLM call.

One LLMTtftCallback rides the agent run's callback list (wired in
app.helpers.agent_helpers._build_agent_callbacks), so it covers every tier —
comms, executor, subagents, narration — with no per-site instrumentation.
Comparing its samples against the user-facing TTFT tells "provider was slow"
apart from "our setup was slow". For comms calls on a live chat turn it also
stamps that turn's clock (see app.services.turn_clock), which is how the
turn's own overhead is separated from the provider's time.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import time
from typing import cast
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, GenerationChunk, LLMResult

from app.agents.core.background.session import get_session
from app.constants.general import COMMS_AGENT_NAME
from app.constants.llm import LLM_LABEL_METADATA_KEY
from app.models.agent_models import LlmCallMetadata
from app.services.latency_metrics import observe_llm_ttft
from app.services.turn_clock import TurnClock, TurnMark


@dataclass(frozen=True, slots=True)
class _CallStart:
    """What one in-flight call's first token is measured and labelled against."""

    started: float
    model: str
    lane: str
    agent: str
    #: The live chat turn's clock, only for comms calls on that turn.
    turn_clock: TurnClock | None


def _comms_turn_clock(meta: LlmCallMetadata, agent: str) -> TurnClock | None:
    """Return the chat turn's clock when this is a comms call on a live chat stream."""
    stream_id = meta.get("stream_id")
    if agent != COMMS_AGENT_NAME or not stream_id:
        return None
    session = get_session(stream_id)
    return session.clock if session is not None else None


class LLMTtftCallback(BaseCallbackHandler):
    """True provider time-to-first-token, measured per streaming LLM call.

    Non-streaming calls emit no sample — their duration_ms already exists, and
    substituting full duration for TTFT would poison the histogram. Each
    retry/fallback attempt is its own run, so it gets its own sample.
    """

    def __init__(self) -> None:
        self._starts: dict[str, _CallStart] = {}
        self._observed: set[str] = set()

    def on_chat_model_start(
        self,
        serialized: Mapping[str, object],  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        messages: list[list[BaseMessage]],  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        tags: list[str] | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        metadata: Mapping[str, object] | None = None,
        **_kwargs: object,
    ) -> None:
        """Stamp the run's start time and its model, lane and call labels, to be read when the first token lands."""
        # LangChain owns this bag; only GAIA's stamped keys are read, by name.
        meta: LlmCallMetadata = cast(LlmCallMetadata, metadata or {})
        # build_agent_config stamps the run's agent tier as the default label;
        # ainvoke_llm overrides it per side call (title/follow-up/memory) so
        # those never pollute the tier's p95.
        agent = str(meta.get(LLM_LABEL_METADATA_KEY) or "unknown")
        turn_clock = _comms_turn_clock(meta, agent)
        if turn_clock is not None:
            turn_clock.note_comms_call()
            turn_clock.mark(TurnMark.LLM_REQUEST)
        self._starts[str(run_id)] = _CallStart(
            started=time.perf_counter(),
            model=str(meta.get("lane_model") or "unknown"),
            lane=str(meta.get("lane_provider") or "unknown"),
            agent=agent,
            turn_clock=turn_clock,
        )

    def on_llm_new_token(
        self,
        token: str | Sequence[str | Mapping[str, object]],  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        *,
        chunk: GenerationChunk | ChatGenerationChunk | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        run_id: UUID,
        parent_run_id: UUID | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        tags: list[str] | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        **_kwargs: object,
    ) -> None:
        """Emit the TTFT sample on the first token of each run, once."""
        key = str(run_id)
        entry = self._starts.pop(key, None)
        if entry is None or key in self._observed:
            return
        self._observed.add(key)
        if entry.turn_clock is not None:
            entry.turn_clock.mark(TurnMark.LLM_FIRST_CHUNK)
        observe_llm_ttft(
            time.perf_counter() - entry.started,
            model=entry.model,
            lane=entry.lane,
            agent=entry.agent,
        )

    def on_llm_end(
        self,
        response: LLMResult,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        tags: list[str] | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        **_kwargs: object,
    ) -> None:
        """Drop the run's tracking state once it completes."""
        self._starts.pop(str(run_id), None)
        self._observed.discard(str(run_id))

    def on_llm_error(
        self,
        error: BaseException,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        tags: list[str] | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        **_kwargs: object,
    ) -> None:
        """Drop the run's tracking state on failure, emitting no sample."""
        self._starts.pop(str(run_id), None)
        self._observed.discard(str(run_id))
