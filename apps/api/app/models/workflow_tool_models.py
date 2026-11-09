"""What the workflow tools return to the agent.

TypedDicts, not models: LangChain json.dumps a tool's return into the ToolMessage
the LLM reads, and a BaseModel would fall back to its repr.
"""

from typing import Generic, Literal, NotRequired, TypeAlias, TypedDict, TypeVar

from pydantic import JsonValue

from app.models.workflow_models import TriggerType

DataT = TypeVar("DataT")

#: A model dumped with mode="json" so json.dumps can serialize it (the tool result and the SSE frame).
JsonObject: TypeAlias = dict[str, JsonValue]

WorkflowToolStatus = Literal[
    "draft_sent", "clarifying", "completed", "created", "unchanged", "updated"
]


class WorkflowToolError(TypedDict):
    success: Literal[False]
    error: str
    message: str


class WorkflowToolSuccess(TypedDict, Generic[DataT]):
    success: Literal[True]
    data: DataT
    message: NotRequired[str]


class WorkflowStatusData(TypedDict):
    """Where a create or edit ended up; question only when clarifying, workflow_id once one exists."""

    status: WorkflowToolStatus
    question: NotRequired[str]
    workflow_id: NotRequired[str | None]


class WorkflowExecutionStarted(TypedDict):
    workflow_id: str
    execution_id: str
    message: str


class WorkflowActivationState(TypedDict):
    workflow_id: str | None
    title: str
    activated: bool


class WorkflowSummary(TypedDict):
    id: str | None
    title: str
    description: str
    trigger_type: TriggerType
    activated: bool
    step_count: int
    total_executions: int


class WorkflowPage(TypedDict):
    workflows: list[WorkflowSummary]
    page: int
    page_size: int
    total: int
    has_more: bool


class TriggerSearchPage(TypedDict):
    triggers: list[JsonObject]
    connected_count: int
    not_connected_count: int


class IntegrationSummary(TypedDict):
    id: str
    name: str
    category: str
    description: str
    connected: bool
    source: Literal["platform", "custom", "public"]


class MyIntegrationsPage(TypedDict):
    integrations: list[IntegrationSummary]
    connected_count: int
    truncated: bool
    query: str | None


class PublicIntegrationsPage(TypedDict):
    integrations: list[IntegrationSummary]
    query: str


class IntegrationToolSummary(TypedDict):
    name: str
    description: str | None


class IntegrationToolList(TypedDict):
    """One integration's tools."""

    integration_id: str
    integration_name: str
    connected: bool
    tools: list[IntegrationToolSummary]
    truncated: bool


class ConnectedToolMatch(TypedDict):
    name: str
    description: str | None
    integration_id: str
    integration_name: str


class ConnectedToolSearch(TypedDict):
    """Tools matching a query across every connected integration."""

    tools: list[ConnectedToolMatch]
    truncated: bool
    searched_integrations: list[str]
    query: str | None
