"""Bridge between LangChain's official AgentMiddleware system and our langgraph_bigtool agent architecture.

Key components: MiddlewareExecutor (runs hooks), SubagentMiddleware (spawns
subagents), WorkspaceArchivingSummarizationMiddleware (archives history
before summarization), WorkspaceCompactionMiddleware (persists large tool
outputs to a /workspace/... reference), create_middleware_stack (the
standard stack factory, used in build_graph.py).
"""

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.executor import MiddlewareExecutor
from app.agents.middleware.factory import (
    AccountingOptions,
    ContextOptions,
    LoopGuardOptions,
    SubagentStackOptions,
    create_comms_middleware,
    create_executor_middleware,
    create_middleware_stack,
    create_subagent_middleware,
)
from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.agents.middleware.media import MediaDescriptionMiddleware
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
    "LoopGuardMiddleware",
    "MediaDescriptionMiddleware",
    "MiddlewareExecutor",
    "SubagentMiddleware",
    "WorkspaceArchivingSummarizationMiddleware",
    "WorkspaceCompactionMiddleware",
    "create_comms_middleware",
    "create_executor_middleware",
    "AccountingOptions",
    "ContextOptions",
    "LoopGuardOptions",
    "SubagentStackOptions",
    "create_middleware_stack",
    "create_model_request",
    "create_subagent_middleware",
    "create_tool_call_request",
]
