"""Request/response schemas for the dev-only identity + seeding endpoints."""

from pydantic import BaseModel, Field


class CreateDevUserRequest(BaseModel):
    """Mint (find-or-create) a dev user by email."""

    email: str = Field(min_length=3, max_length=320, description="User email (unique key)")
    name: str | None = Field(default=None, max_length=200, description="Display name")


class SeedDevDataRequest(BaseModel):
    """Seed deterministic sample data for an existing dev user."""

    email: str = Field(min_length=3, max_length=320)
    todos: int = Field(default=0, ge=0, le=100)
    conversations: int = Field(default=0, ge=0, le=100)
    platform_links: list[str] = Field(
        default_factory=list,
        description="Platforms to link (discord, slack, telegram, whatsapp)",
    )


class SeedDevDataResponse(BaseModel):
    """Summary of what the seed run created."""

    email: str
    user_id: str
    todos_created: int
    conversations_created: int
    platforms_linked: list[str]
    # Contract for harness clients: inject messages as these ids — never
    # re-derive the format client-side.
    platform_user_ids: dict[str, str]


class DevDeletedCounts(BaseModel):
    """How many rows teardown removed, per collection."""

    todos: int
    conversations: int
    projects: int
    user: int


class DeleteDevUserResponse(BaseModel):
    """Summary of the user + owned data removed during teardown."""

    email: str
    user_id: str
    deleted: DevDeletedCounts


class RunDevAgentRequest(BaseModel):
    """Run the executor or one subagent directly, skipping the comms agent."""

    email: str = Field(min_length=3, max_length=320, description="Dev user to run as")
    task: str = Field(
        min_length=1,
        max_length=20000,
        description="Task text; sim-mode directives ([[tool:...]], [[say:...]]) work here",
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=100,
        description="Pass the same id across calls to keep the agent's thread state",
    )
    model: str | None = Field(
        default=None,
        max_length=100,
        description="DEV_MODEL_OPTIONS key (e.g. custom, minimax-m3). Unset = DEV_DEFAULT_MODEL.",
    )


class DevAgentRunResponse(BaseModel):
    """Outcome of a direct agent run."""

    user_id: str
    conversation_id: str
    thread_id: str
    agent: str
    message: str
    converged: bool = True
    """False when the agent ran out of steps instead of reaching an answer.

    Not reaching a conclusion is an agent outcome, not a server fault, so it is
    reported in the response rather than raised as a 500. A caller that treats
    every 500 as infrastructure would otherwise exclude these from its accuracy
    and quietly flatter the agent.
    """


class DevSubagentInfo(BaseModel):
    """A subagent id/name pair accepted by the direct-run endpoint."""

    id: str
    name: str
    short_name: str | None = None
    agent_name: str
