"""True provider time-to-first-token, measured per streaming LLM call.

One :class:`LLMTtftCallback` rides the agent run's callback list (wired in
``app.helpers.agent_helpers._build_agent_callbacks``), so it covers every
tier — comms, executor, subagents, narration — with no per-site
instrumentation. Comparing its samples against the user-facing TTFT tells
"provider was slow" apart from "our setup was slow".
"""

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, GenerationChunk, LLMResult

from app.constants.llm import LLM_LABEL_METADATA_KEY
from app.services.latency_metrics import observe_llm_ttft


class LLMTtftCallback(BaseCallbackHandler):
    """True provider time-to-first-token, measured per streaming LLM call.

    Non-streaming calls emit no sample — their ``duration_ms`` already
    exists, and substituting full duration for TTFT would poison the
    histogram. Each retry/fallback attempt is its own run, so it gets its
    own sample.
    """

    def __init__(self) -> None:
        self._starts: dict[str, tuple[float, str, str, str]] = {}
        self._observed: set[str] = set()

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        messages: list[list[BaseMessage]],  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        tags: list[str] | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        metadata: dict[str, Any] | None = None,
        **_kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        """Record the run's start time and its model/lane/agent labels."""
        meta = metadata or {}
        self._starts[str(run_id)] = (
            time.perf_counter(),
            str(meta.get("lane_model") or "unknown"),
            str(meta.get("lane_provider") or "unknown"),
            # The CALL's label: build_agent_config stamps the run's agent tier as
            # the default, and ainvoke_llm overrides it with a finer per-call
            # label for the title/follow-up/memory calls that share one turn's
            # callback list — so those side calls never pollute the tier's p95.
            str(meta.get(LLM_LABEL_METADATA_KEY) or "unknown"),
        )

    def on_llm_new_token(
        self,
        token: str | list[str | dict[str, Any]],  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        *,
        chunk: GenerationChunk | ChatGenerationChunk | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        run_id: UUID,
        parent_run_id: UUID | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        tags: list[str] | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        **_kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        """Emit the TTFT sample on the first token of each run, once."""
        key = str(run_id)
        entry = self._starts.pop(key, None)
        if entry is None or key in self._observed:
            return
        start, model, lane, agent = entry
        self._observed.add(key)
        observe_llm_ttft(time.perf_counter() - start, model=model, lane=lane, agent=agent)

    def on_llm_end(
        self,
        response: LLMResult,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        tags: list[str] | None = None,  # noqa: ARG002 -- LangChain BaseCallbackHandler contract
        **_kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
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
        **_kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        """Drop the run's tracking state on failure, emitting no sample."""
        self._starts.pop(str(run_id), None)
        self._observed.discard(str(run_id))
