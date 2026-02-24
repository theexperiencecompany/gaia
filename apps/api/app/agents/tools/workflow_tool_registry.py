from app.agents.tools.workflow_tool import (
    list_workflows,
    search_triggers,
)

# Tools for the workflow subagent - used by WorkflowSubagentRunner
SUBAGENT_WORKFLOW_TOOLS = [
    search_triggers,
    list_workflows,
]

__all__ = [
    "SUBAGENT_WORKFLOW_TOOLS",
]
