"""
LangChain AgentMiddleware Integration for langgraph_bigtool.

This package provides a bridge between LangChain's official AgentMiddleware
system and our custom langgraph_bigtool-based agent architecture.

Key Components:
- MiddlewareExecutor: Executes middleware hooks at appropriate points
- SubagentMiddleware: Spawn subagents for parallel/focused work
- WorkspaceArchivingSummarizationMiddleware: Archives history to the
  persistent workspace before summarization
- WorkspaceCompactionMiddleware: Persists large tool outputs to the
  persistent workspace and replaces them with a `/workspace/...` reference
- create_middleware_stack: Factory function to create the standard middleware stack

Usage in build_graph.py:
    from app.agents.middleware import create_middleware_stack

    middleware = create_middleware_stack()

    builder = create_agent(
        llm=chat_llm,
        middleware=middleware,
        ...
    )
"""

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.executor import MiddlewareExecutor
from app.agents.middleware.factory import (
    create_comms_middleware,
    create_executor_middleware,
    create_middleware_stack,
    create_subagent_middleware,
    get_summarization_llm,
)
from app.agents.middleware.runtime_adapter import (
    BigtoolRuntime,
    BigtoolToolRuntime,
    create_model_request,
    create_tool_call_request,
)
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.middleware.summarization import (
    WorkspaceArchivingSummarizationMiddleware,
)

__all__ = [
    "BigtoolRuntime",
    "BigtoolToolRuntime",
    "LLMAccountingMiddleware",
    "MiddlewareExecutor",
    "SubagentMiddleware",
    "WorkspaceArchivingSummarizationMiddleware",
    "WorkspaceCompactionMiddleware",
    "create_comms_middleware",
    "create_executor_middleware",
    "create_middleware_stack",
    "create_model_request",
    "create_subagent_middleware",
    "create_tool_call_request",
    "get_summarization_llm",
]
