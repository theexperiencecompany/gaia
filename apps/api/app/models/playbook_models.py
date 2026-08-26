"""Playbook models — a workflow's settled tool-call sequence, written down.

A playbook is authored by the agent at the end of a run it judges repeatable,
and replayed by a script-driven subagent instead of being re-reasoned from
scratch. The document is YAML the agent reads and edits; these models are the
parsed form the runner executes.

The grammar is deliberately three keys — ``description``, ``steps``,
``synthesize`` (plus ``ask`` when a step needs text a model has to write). It
carries no control flow: a run whose order depends on what it finds is not
compilable and stays on the agent path, which is the correct outcome rather
than a gap to fill with branches.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Self
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.repositories.base import MongoDocument

#: Cap on a single ``$ask`` field's output. Generous enough for a briefing body,
#: small enough that a runaway prompt cannot turn one replay into a long
#: generation — the whole point of a playbook is a bounded token cost.
DEFAULT_ASK_MAX_TOKENS = 1024


class PlaybookRunStatus(str, Enum):
    """How the workflow's most recent run went for this playbook.

    Kept on the playbook rather than the execution record because it answers a
    question about the playbook: is the frozen sequence still carrying the
    workflow, or did it break and need re-authoring? ``NOT_RUN`` is a playbook
    written but not yet replayed.
    """

    NOT_RUN = "not_run"
    SUCCESS = "success"
    FAILED = "failed"


class PlaybookStep(BaseModel):
    """One node: either a tool call, or a handoff carrying the steps that
    subagent ran.

    Both shapes share one model because the YAML reads better without a ``kind``
    discriminator the author has to remember, and because the two are mutually
    exclusive by construction — enforced below rather than by the type system.

    A handoff's children execute in that subagent's context, so the subagent's
    existing tool space *is* the auth boundary; there is no separate binding
    rule for playbooks.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", description="Referencable name, e.g. $steps.<id>.field")
    tool: str | None = Field(default=None, description="Tool name, for a tool step")
    args: dict[str, Any] = Field(default_factory=dict, description="Args, may hold $placeholders")
    handoff: str | None = Field(default=None, description="Subagent id, for a handoff step")
    steps: list["PlaybookStep"] = Field(
        default_factory=list, description="A handoff's recorded child steps"
    )

    @model_validator(mode="after")
    def exactly_one_shape(self) -> Self:
        """A node is a tool call or a handoff, never both and never neither.

        Caught here rather than at execution because a malformed node means the
        agent mis-authored the playbook, and the write must fail loudly with the
        offending id instead of producing a runner that silently skips a step.
        """
        if bool(self.tool) == bool(self.handoff):
            raise ValueError(
                f"step {self.id or '<unnamed>'}: set exactly one of 'tool' or 'handoff'"
            )
        if self.handoff and not self.steps:
            raise ValueError(f"handoff {self.handoff}: carries no steps, so it would do nothing")
        if self.tool and self.steps:
            raise ValueError(f"step {self.id or self.tool}: only a handoff may carry nested steps")
        return self


class PlaybookAsk(BaseModel):
    """A named slot the model fills.

    Every ask in a playbook resolves in ONE call that also produces the
    synthesis, so an ask costs nothing beyond the call the run already makes.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(description="What to write for this field")
    uses: list[str] = Field(
        default_factory=list, description="Step ids whose output this ask needs to see"
    )
    max_tokens: int = Field(default=DEFAULT_ASK_MAX_TOKENS, ge=1, le=8192)


class PlaybookBody(BaseModel):
    """The authored part of a playbook — what round-trips through YAML."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="What this playbook does, in the agent's own words")
    steps: list[PlaybookStep] = Field(min_length=1)
    ask: dict[str, PlaybookAsk] = Field(default_factory=dict)
    synthesize: str = Field(description="How to write the run's user-facing result")


class PlaybookDocument(PlaybookBody, MongoDocument):
    """A playbook as stored in Mongo.

    Identity is the business key ``playbook_id``; one active playbook per
    workflow. ``raw_yaml`` is kept verbatim alongside the parsed body because it
    is what the agent reads and edits — reserializing the model would quietly
    reformat the author's own document.
    """

    playbook_id: str = Field(default_factory=lambda: f"pb_{uuid.uuid4().hex[:12]}")
    workflow_id: str
    user_id: str
    #: Hash of the workflow's prompt + steps at authoring time. A mismatch means
    #: the user edited the workflow, so the frozen sequence no longer matches
    #: what was asked and the playbook is skipped rather than replayed blind.
    workflow_hash: str
    raw_yaml: str
    last_run_status: PlaybookRunStatus = PlaybookRunStatus.NOT_RUN
    created_at: datetime
    updated_at: datetime


class PlaybookUpdate(BaseModel):
    """Partial ``$set`` update for a playbook."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    steps: list[PlaybookStep] | None = None
    ask: dict[str, PlaybookAsk] | None = None
    synthesize: str | None = None
    workflow_hash: str | None = None
    raw_yaml: str | None = None
    last_run_status: PlaybookRunStatus | None = None
    updated_at: datetime | None = None
