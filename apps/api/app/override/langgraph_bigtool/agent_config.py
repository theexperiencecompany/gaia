"""Configuration dataclasses for the overridden langgraph create_agent.

Lives in its own module so consumers that build configs (e.g.
``app.agents.tools.core.tool_runtime_config``) can import the types without
importing the graph builder itself — create_agent pulls in the whole agent
stack, and a config-only import must not.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from app.override.langgraph_bigtool.hooks import HookType
from app.override.langgraph_bigtool.utils import RetrieveToolsResult

RetrieveToolsResponse = RetrieveToolsResult | list[str]


@dataclass(frozen=True)
class ToolRetrievalConfig:
    """How tools are retrieved and bound onto the agent.

    - limit / metadata_filter / namespace_prefix: semantic retrieval settings
      for the default retrieve_tools tool.
    - retrieve_tools_function / retrieve_tools_coroutine: custom retrieval.
    - initial_tool_ids: tool IDs bound directly without retrieve_tools.
    - disable_retrieve_tools: no retrieve_tools mechanism at all; only initially
      bound tools (plus any already-selected tools) are available.
    """

    limit: int = 2
    metadata_filter: dict[str, Any] | None = None
    namespace_prefix: tuple[str, ...] = ("tools",)
    retrieve_tools_function: Callable[..., RetrieveToolsResponse] | None = None
    retrieve_tools_coroutine: Callable[..., Awaitable[RetrieveToolsResponse]] | None = None
    initial_tool_ids: list[str] | None = None
    disable_retrieve_tools: bool = False


@dataclass(frozen=True)
class HookConfig:
    """Lifecycle hooks and end-of-run gating.

    Hooks are executed in sequence as provided. Each hook has signature:
    (state: State, config: RunnableConfig, store: BaseStore) -> State.
    """

    pre_model_hooks: list[HookType] | None = None
    end_graph_hooks: list[HookType] | None = None
    require_finish_to_end: bool = False


@dataclass(frozen=True)
class AgentConfig:
    """Identity and middleware configuration for the agent graph."""

    agent_name: str = "main_agent"
    context_schema: type[Any] | None = None
    middleware: Sequence[AgentMiddleware] | None = None
