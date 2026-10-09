"""Agent run, tool and background LLM events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "AgentRunCompleted",
    "AgentRunFailed",
    "AgentRunStarted",
    "AiLlmCallCompleted",
    "ToolExecuteFailed",
    "ToolUsed",
]


class _AgentRunEvent(ServerEvent):
    """The properties every agent-run lifecycle event carries; trigger_type and source name a comms run's caller."""

    agent: Literal["comms", "executor"]
    mode: Literal["interactive", "background"]
    conversation_id: Identifier
    task_id: Identifier | None = None
    trigger_type: Identifier | None = None
    source: Identifier | None = None


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
    """An agent run ended in an error; reason is the exception type, error type or "cancelled"."""

    event: ClassVar[str] = "agent:run_failed"
    budget_per_user_day: ClassVar[int] = 20

    reason: Identifier


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
    """One llm_calls ledger row: every priced model call, graph or one-shot, success or error."""

    event: ClassVar[str] = "ai:llm_call_completed"
    budget_per_user_day: ClassVar[int] = 2500

    feature: Identifier
    agent_name: Identifier
    background: bool
    charge_to_budget: bool
    model: Identifier
    model_served: Identifier | None = None
    provider: Identifier | None = None
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    total_tokens: int
    cost_usd: float
    cost_source: Literal["provider", "table"]
    status: Literal["ok", "error"]
    error_family: Identifier | None = None
    finish_reason: Identifier | None = None
    duration_ms: float | None = None
    channel: Identifier | None = None
    generation_id: Identifier | None = None
    conversation_id: Identifier | None = None
    workflow_id: Identifier | None = None
    llm_call_id: Identifier
