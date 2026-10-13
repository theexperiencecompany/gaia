"""Linear GraphQL payloads the Linear tool reads and sends.

Every response model declares exactly the fields the operation in
linear_utils selects; nullability follows Linear's published schema
(https://github.com/linear/linear/blob/master/packages/sdk/src/schema.graphql).
A field that only some selections ask for defaults to None and says so.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# =============================================================================
# Request side — GraphQL variables
# =============================================================================


class LinearVariables(BaseModel):
    """Variables of one operation: camelCase on the wire, unset fields left out."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class LinearTeamIdVariables(LinearVariables):
    team_id: str


class LinearMyIssuesVariables(LinearVariables):
    assignee_id: str
    include_completed: bool
    first: int


class LinearSearchIssuesVariables(LinearVariables):
    query: str
    first: int


class LinearIssueIdVariables(LinearVariables):
    """issue(id:) takes a UUID or a human identifier such as ENG-123."""

    id: str


class LinearIssueHistoryVariables(LinearVariables):
    issue_id: str
    first: int


class LinearFirstVariables(LinearVariables):
    first: int


class LinearIssueCreateInput(LinearVariables):
    """IssueCreateInput — optional fields are sent only when assigned."""

    team_id: str
    title: str
    description: str | None = None
    assignee_id: str | None = None
    priority: int | None = None
    state_id: str | None = None
    label_ids: list[str] | None = None
    project_id: str | None = None
    cycle_id: str | None = None
    due_date: str | None = None
    estimate: int | None = None
    parent_id: str | None = None


class LinearIssueCreateVariables(LinearVariables):
    input: LinearIssueCreateInput


class LinearIssueRelationCreateVariables(LinearVariables):
    issue_id: str
    related_issue_id: str
    type: str


class LinearIssueUpdateInput(LinearVariables):
    """IssueUpdateInput for a batch update.

    A field assigned None is sent as null (it clears the value); a
    field never assigned is left out. Dump with exclude_unset.
    """

    state_id: str | None = None
    priority: int | None = None
    assignee_id: str | None = None
    cycle_id: str | None = None
    project_id: str | None = None
    label_ids: list[str] | None = None


class LinearIssueBatchUpdateVariables(LinearVariables):
    issue_ids: list[str]
    input: LinearIssueUpdateInput


# =============================================================================
# Response side — the GraphQL envelope
# =============================================================================


class LinearGraphQLError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str


class LinearGraphQLEnvelope(BaseModel):
    """{data, errors} as Linear answers every operation; data is parsed per query."""

    model_config = ConfigDict(extra="ignore")

    data: dict[str, object] | None = None
    errors: list[LinearGraphQLError] | None = None


# =============================================================================
# Response side — nodes
# =============================================================================


class LinearNode(BaseModel):
    """A selected object; fields the selection did not ask for are absent, never null-filled."""

    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)


NodeT = TypeVar("NodeT", bound=BaseModel)


class LinearConnection(LinearNode, Generic[NodeT]):
    """A { nodes { … } } selection on any connection."""

    nodes: list[NodeT] = Field(default_factory=list)


class LinearPassthroughNode(LinearNode):
    """A node CUSTOM_RESOLVE_CONTEXT returns verbatim: extra="allow" keeps every selected field."""

    model_config = ConfigDict(extra="allow", alias_generator=to_camel, populate_by_name=True)

    id: str
    name: str


class LinearActiveCycleSummary(LinearNode):
    """Team.activeCycle { id name progress }."""

    id: str
    name: str | None = None
    progress: float


class LinearTeam(LinearPassthroughNode):
    """teams { id name key activeCycle }; activeCycle is null between cycles."""

    key: str
    active_cycle: LinearActiveCycleSummary | None = None


class LinearUser(LinearPassthroughNode):
    """users { id name email active }."""

    email: str
    active: bool


class LinearLabel(LinearPassthroughNode):
    """issueLabels { id name color }."""

    color: str


class LinearProject(LinearPassthroughNode):
    """projects { id name state progress }."""

    state: str
    progress: float


class LinearWorkflowStateNode(LinearPassthroughNode):
    """workflowStates { id name type position }."""

    type: str
    position: float


class LinearIssueRef(LinearNode):
    """{ id identifier title } — a parent, a relation target, a notification's issue."""

    id: str
    identifier: str
    title: str


class LinearUserRef(LinearNode):
    """{ id name } (email only where selected)."""

    id: str
    name: str
    email: str | None = None


class LinearUserName(LinearNode):
    """assignee { name }."""

    name: str


class LinearStateRef(LinearNode):
    """{ id name type }."""

    id: str
    name: str
    type: str


class LinearStateIdName(LinearNode):
    """fromState/toState { id name } on a history entry."""

    id: str
    name: str


class LinearStateName(LinearNode):
    """state { name } / state { name type }."""

    name: str
    type: str | None = None


class LinearTeamRef(LinearNode):
    """team { id key name }."""

    id: str
    key: str
    name: str


class LinearCycleRef(LinearNode):
    """cycle { id name }; a cycle's name is optional in Linear."""

    id: str
    name: str | None = None


class LinearProjectRef(LinearNode):
    id: str
    name: str


class LinearLabelRef(LinearNode):
    id: str
    name: str


class LinearIdOnly(LinearNode):
    id: str


class LinearViewer(LinearNode):
    """viewer { id name email assignedIssues { nodes { id } } }."""

    id: str
    name: str
    email: str
    assigned_issues: LinearConnection[LinearIdOnly] = Field(
        default_factory=LinearConnection[LinearIdOnly]
    )


class LinearIssueSummary(LinearNode):
    """An issue as QUERY_MY_ISSUES / QUERY_SEARCH_ISSUES list it.

    parent/slaBreachesAt are selected by the former only, createdAt
    by the latter only.
    """

    id: str
    identifier: str
    title: str
    priority: int
    state: LinearStateRef
    due_date: str | None = None
    team: LinearTeamRef
    cycle: LinearCycleRef | None = None
    parent: LinearIssueRef | None = None
    assignee: LinearUserRef | None = None
    created_at: str | None = None
    sla_breaches_at: str | None = None


class LinearChildIssue(LinearNode):
    """children { nodes { id identifier title state { name } } }."""

    id: str
    identifier: str
    title: str
    state: LinearStateName


class LinearIssueRelation(LinearNode):
    id: str
    type: str
    related_issue: LinearIssueRef


class LinearComment(LinearNode):
    """comments { nodes { id body createdAt user { id name } } }; user is null for bot comments."""

    id: str
    body: str
    created_at: str
    user: LinearUserRef | None = None


class LinearIssueHistory(LinearNode):
    """One history entry; every from/to pair is null unless that aspect changed.

    fromPriority/toPriority are selected by QUERY_ISSUE_HISTORY only.
    """

    id: str
    created_at: str
    actor: LinearUserRef | None = None
    from_state: LinearStateIdName | None = None
    to_state: LinearStateIdName | None = None
    from_assignee: LinearUserRef | None = None
    to_assignee: LinearUserRef | None = None
    from_priority: int | None = None
    to_priority: int | None = None
    added_labels: list[LinearLabelRef] | None = None
    removed_labels: list[LinearLabelRef] | None = None


class LinearAttachment(LinearNode):
    id: str
    title: str
    url: str


class LinearIssue(LinearNode):
    """The full issue QUERY_ISSUE_BY_ID selects."""

    id: str
    identifier: str
    title: str
    description: str | None = None
    priority: int
    state: LinearStateRef
    due_date: str | None = None
    estimate: float | None = None
    team: LinearTeamRef
    cycle: LinearCycleRef | None = None
    project: LinearProjectRef | None = None
    assignee: LinearUserRef | None = None
    creator: LinearUserRef | None = None
    parent: LinearIssueRef | None = None
    children: LinearConnection[LinearChildIssue] = Field(
        default_factory=LinearConnection[LinearChildIssue]
    )
    relations: LinearConnection[LinearIssueRelation] = Field(
        default_factory=LinearConnection[LinearIssueRelation]
    )
    comments: LinearConnection[LinearComment] = Field(
        default_factory=LinearConnection[LinearComment]
    )
    history: LinearConnection[LinearIssueHistory] = Field(
        default_factory=LinearConnection[LinearIssueHistory]
    )
    attachments: LinearConnection[LinearAttachment] = Field(
        default_factory=LinearConnection[LinearAttachment]
    )


class LinearIssueHistoryHolder(LinearNode):
    """issue { history(first:) { nodes { … } } }."""

    history: LinearConnection[LinearIssueHistory] = Field(
        default_factory=LinearConnection[LinearIssueHistory]
    )


class LinearCycleIssue(LinearNode):
    """cycles { issues { nodes { id identifier title state { name type } priority assignee { name } } } }."""

    id: str
    identifier: str
    title: str
    state: LinearStateName
    priority: int
    assignee: LinearUserName | None = None


class LinearCycle(LinearNode):
    """An active cycle as QUERY_ACTIVE_CYCLES selects it."""

    id: str
    name: str | None = None
    number: float
    starts_at: str
    ends_at: str
    progress: float
    team: LinearTeamRef
    issues: LinearConnection[LinearCycleIssue] = Field(
        default_factory=LinearConnection[LinearCycleIssue]
    )


class LinearNotification(LinearNode):
    """A notification; issue only on IssueNotification (the fragment), actor null for system events."""

    id: str
    type: str
    created_at: str
    read_at: str | None = None
    issue: LinearIssueRef | None = None
    actor: LinearUserRef | None = None


class LinearCreatedIssue(LinearNode):
    """issueCreate { issue { id identifier title url } }."""

    id: str
    identifier: str
    title: str
    url: str


class LinearIssuePayload(LinearNode):
    success: bool
    issue: LinearCreatedIssue | None = None


class LinearIssueRelationRef(LinearNode):
    id: str
    type: str


class LinearIssueRelationPayload(LinearNode):
    success: bool
    issue_relation: LinearIssueRelationRef | None = None


class LinearIssueBatchPayload(LinearNode):
    success: bool
    issues: list[LinearIssueRef] = Field(default_factory=list)


# =============================================================================
# Response side — the data of each operation
# =============================================================================


class LinearViewerData(LinearNode):
    viewer: LinearViewer


class LinearTeamsData(LinearNode):
    teams: LinearConnection[LinearTeam]


class LinearUsersData(LinearNode):
    users: LinearConnection[LinearUser]


class LinearLabelsData(LinearNode):
    issue_labels: LinearConnection[LinearLabel]


class LinearProjectsData(LinearNode):
    projects: LinearConnection[LinearProject]


class LinearStatesData(LinearNode):
    workflow_states: LinearConnection[LinearWorkflowStateNode]


class LinearIssuesData(LinearNode):
    issues: LinearConnection[LinearIssueSummary]


class LinearSearchIssuesData(LinearNode):
    search_issues: LinearConnection[LinearIssueSummary]


class LinearIssueData(LinearNode):
    """issue(id:) is non-null: an unknown id is a GraphQL error, not a null."""

    issue: LinearIssue


class LinearIssueHistoryData(LinearNode):
    issue: LinearIssueHistoryHolder


class LinearCyclesData(LinearNode):
    cycles: LinearConnection[LinearCycle]


class LinearNotificationsData(LinearNode):
    notifications: LinearConnection[LinearNotification]


class LinearIssueCreateData(LinearNode):
    issue_create: LinearIssuePayload


class LinearIssueRelationCreateData(LinearNode):
    issue_relation_create: LinearIssueRelationPayload


class LinearIssueBatchUpdateData(LinearNode):
    issue_batch_update: LinearIssueBatchPayload
