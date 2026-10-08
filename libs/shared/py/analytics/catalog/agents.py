"""Agent run, tool and background LLM events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier


class _AgentRunEvent(ServerEvent):
    """The properties every agent-run lifecycle event carries."""

    agent: Literal["comms", "executor"]
    mode: Literal["interactive", "background"]
    conversation_id: Identifier
    task_id: Identifier | None = None


class _AgentRunEndedEvent(_AgentRunEvent):
    """A run's terminal event; executor timings are absent on runs dispatched before the stamp."""

    queued: bool | None = None
    queue_wait_ms: float | None = None
    executor_ttft_ms: float | None = None
    executor_active_ms: float | None = None


class AgentRunStarted(_AgentRunEvent):
    """A comms or executor run (or a resumed executor segment) started."""

    event: ClassVar[str] = "agent:run_started"
    budget_per_user_day: ClassVar[int] = 500


class AgentRunCompleted(_AgentRunEndedEvent):
    """An agent run finished successfully."""

    event: ClassVar[str] = "agent:run_completed"
    budget_per_user_day: ClassVar[int] = 500


class AgentRunFailed(_AgentRunEndedEvent):
    """An agent run ended in an error."""

    event: ClassVar[str] = "agent:run_failed"
    budget_per_user_day: ClassVar[int] = 20


class ToolUsed(ServerEvent):
    """A tool ran; via splits bound calls from proxied execute calls, source marks MCP-app calls."""

    event: ClassVar[str] = "tool:used"
    budget_per_user_day: ClassVar[int] = 5000

    tool_name: Identifier
    via: Literal["bound", "execute"] | None = None
    source: Literal["mcp_app"] | None = None


class ToolExecuteFailed(ServerEvent):
    """A proxied dispatch failed before the tool ran; against tool:used{via=execute} it is retries per success."""

    event: ClassVar[str] = "tool:execute_failed"
    budget_per_user_day: ClassVar[int] = 200

    tool_name: Identifier
    reason: Identifier


class AiLlmCallCompleted(ServerEvent):
    """A background model call outside an agent graph finished; graph calls are covered by $ai_generation."""

    event: ClassVar[str] = "ai:llm_call_completed"
    budget_per_user_day: ClassVar[int] = 500

    feature: Identifier
    label: Identifier
    model: Identifier
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    total_tokens: int
    cost_usd: float
    charged: bool
    cost_estimated: bool
