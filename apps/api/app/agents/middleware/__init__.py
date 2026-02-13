"""
LangChain AgentMiddleware Integration for langgraph_bigtool.

This package provides a bridge between LangChain's official AgentMiddleware
system and our custom langgraph_bigtool-based agent architecture.

Key Components:
- MiddlewareExecutor: Executes middleware hooks at appropriate points
- TodoMiddleware: Task planning and tracking tools (plan_tasks, mark_task, add_task)
- SubagentMiddleware: Spawn subagents for parallel/focused work
- VFSArchivingSummarizationMiddleware: Extends SummarizationMiddleware with VFS archiving
- VFSCompactionMiddleware: Compacts large tool outputs to VFS
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

from app.agents.middleware.executor import MiddlewareExecutor
from app.agents.middleware.factory import (
    create_comms_middleware,
    create_default_middleware,
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
from app.agents.middleware.todo import Todo, TodoMiddleware, TodoState
from app.agents.middleware.vfs_compaction import VFSCompactionMiddleware
from app.agents.middleware.vfs_summarization import VFSArchivingSummarizationMiddleware

__all__ = [
    # Factory functions (preferred)
    "create_middleware_stack",
    "create_default_middleware",
    "create_executor_middleware",
    "create_comms_middleware",
    "create_subagent_middleware",
    "get_summarization_llm",
    # Executor
    "MiddlewareExecutor",
    # Runtime adapters
    "BigtoolRuntime",
    "BigtoolToolRuntime",
    "create_model_request",
    "create_tool_call_request",
    # Middleware classes (for custom configuration)
    "TodoMiddleware",
    "Todo",
    "TodoState",
    "SubagentMiddleware",
    "VFSArchivingSummarizationMiddleware",
    "VFSCompactionMiddleware",
]
