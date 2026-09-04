"""Playbook models — a workflow's settled tool-call sequence, written down.

A playbook is authored by the agent at the end of a run it judges repeatable,
and replayed by a script-driven subagent instead of being re-reasoned from
scratch. The document is YAML the agent reads and edits; these models are the
parsed form the runner executes.

The grammar is deliberately three keys — ``description``, ``steps`` and
``result_brief``. It carries no control flow: a run whose order depends on what
it finds is not compilable and stays on the agent path, which is the correct
outcome rather than a gap to fill with branches.

Text a model has to write at replay has no section of its own: it lives inline,
as ``{"$ask": "what to write"}`` standing where the argument's value goes. That
is not cosmetic. A slot declared in its own table can be declared and then
referenced by nothing — five of the eight asks ever written in production were
dead that way, filled by a model call and thrown away — and an inline slot is
read by exactly the step it sits in, so a dead one cannot be written.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Self, TypeGuard
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.repositories.base import MongoDocument

#: The key that marks an argument value as a slot a model fills at replay,
#: rather than as data. A ``$`` prefix because no tool takes an argument or a
#: JSON field by that name, so the marker cannot collide with real content.
#: ``AskSlot`` below repeats the literal because a pydantic alias has to be one.
ASK_KEY = "$ask"

#: Cap on a single ``$ask`` slot's output. Generous enough for a briefing body,
#: small enough that a runaway prompt cannot turn one replay into a long
#: generation — the whole point of a playbook is a bounded token cost.
DEFAULT_ASK_MAX_TOKENS = 1024


class PlaybookRunStatus(str, Enum):
    """How the workflow's most recent run went for this playbook.

    Kept on the playbook rather than the execution record because it answers a
    question about the playbook: is the frozen sequence still carrying the
    workflow, or did it break and need re-authoring? ``NOT_RUN`` is a playbook
    written but not yet replayed. ``SUSPECT`` is a replay that completed but
    whose results the runner did not trust.
    """

    NOT_RUN = "not_run"
    SUCCESS = "success"
    FAILED = "failed"
    SUSPECT = "suspect"


@dataclass(frozen=True)
class PlaybookRunOutcome:
    """How a replay went, as the worker records it: the status, why (for a
    failed or suspect run) and whether a suspect counts toward deletion. The
    narration's verdict is the model's opinion and does not count; only the
    deterministic record check does."""

    status: PlaybookRunStatus
    reason: str | None = None
    counts_toward_streak: bool = True


class AskSlot(BaseModel):
    """An argument value a model writes at replay, written where it is used.

    ``{"$ask": "<what to write>", "max_tokens": <optional int>}`` stands in the
    argument's place. It carries no name and no list of steps to read, because
    it needs neither: its address is its position in the arguments, and the one
    model call that fills it sees every step that ran before its own step.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(alias="$ask", min_length=1, description="What to write for this value")
    max_tokens: int = Field(default=DEFAULT_ASK_MAX_TOKENS, ge=1, le=8192)


def is_ask_slot(value: object) -> TypeGuard[Mapping[str, Any]]:
    """Whether a value stands for text a model writes, rather than being data.

    A ``TypeGuard`` rather than a plain ``bool`` so the callers that go on to
    read the slot's keys — the validator naming what a bad one contains — get
    the mapping type from the check they already make.
    """
    return isinstance(value, Mapping) and ASK_KEY in value


def has_ask_slots(value: object) -> bool:
    """Whether a value holds an ask slot at any depth, itself included."""
    return any(True for _ in walk_ask_slots(value))


def ask_slot_key(prefix: str, path: Sequence[str | int]) -> str:
    """The key one slot answers to: its step, then its path inside the args.

    Defined once on purpose. The runner lists these keys to the model that
    fills them and the evaluator looks the written text back up by the same
    key, so two spellings of the rule would be a slot that is written and then
    never substituted — a hole reaching a real tool.
    """
    return ".".join([prefix, *(str(part) for part in path)])


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
            raise ValueError(
                f"handoff {self.handoff}: carries no steps, so it would do nothing; list "
                "the calls that subagent ran (its handoff result records them) in this "
                "step's 'steps' field"
            )
        if self.tool and self.steps:
            raise ValueError(f"step {self.id or self.tool}: only a handoff may carry nested steps")
        return self


@dataclass(frozen=True, slots=True)
class LocatedAsk:
    """One ask slot and the key that addresses it."""

    key: str
    slot: AskSlot


def ask_slots(steps: Sequence[PlaybookStep]) -> list[LocatedAsk]:
    """Every ask slot in a playbook, in execution order, handoff children included.

    Keys are unique: step ids are unique (the validator refuses a repeat) and
    two slots in one step sit at two different argument paths.
    """
    located: list[LocatedAsk] = []
    for step in steps:
        if step.handoff:
            located.extend(ask_slots(step.steps))
            continue
        prefix = step.id or step.tool or ""
        located.extend(
            LocatedAsk(key=ask_slot_key(prefix, path), slot=AskSlot.model_validate(value))
            for path, value in walk_ask_slots(step.args)
        )
    return located


def walk_ask_slots(
    value: object, path: tuple[str | int, ...] = ()
) -> Iterator[tuple[tuple[str | int, ...], Mapping[str, Any]]]:
    """Every ask slot inside one value, with the argument path that addresses it.

    A slot is a leaf: nothing inside one is walked, so a prompt that happens to
    read like a nested structure is text rather than more slots.
    """
    if is_ask_slot(value):
        yield path, value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from walk_ask_slots(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_ask_slots(item, (*path, index))


class PlaybookBody(BaseModel):
    """The authored part of a playbook — what round-trips through YAML."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="What this playbook does, in the agent's own words")
    steps: list[PlaybookStep] = Field(min_length=1)
    result_brief: str = Field(
        description="How to write the run's result for the user, from every step's result."
    )


#: The placeholder vocabulary, spelled out for the tool-boundary schema. A JSON
#: Schema cannot express "this string may be a reference", so the model only
#: learns the namespaces if the ``args`` description carries them.
_ARGS_DESCRIPTION = (
    "The call's arguments, exactly as the tool takes them. A value may be a "
    "placeholder resolved at replay: $now, $today, $now + 1d; $user.email, "
    "$user.name, $user.timezone; $trigger.<path>; $steps.<step_id>.<path>; "
    "$last_run.<TOOL_NAME>.<path>. $ask is not a placeholder; if a value "
    "genuinely cannot be frozen or built from $now/$today/$user/$trigger/"
    '$steps/$last_run, write {"$ask": "what to write"} as that value and a '
    "model fills it at replay."
)


#: Names a model reaches for when it means ``args``. Dropped as unknown keys,
#: any of these would store a call with no arguments at all and pass it off as
#: authored; refusing them by name is what keeps lenience from swallowing the
#: one key a step cannot do without.
_ARGS_NEAR_MISSES = ("arguments", "input", "inputs", "params", "parameters", "kwargs")


def _refuse_args_near_miss(data: Mapping[str, Any]) -> None:
    if "args" in data:
        return
    for key in _ARGS_NEAR_MISSES:
        if key in data:
            raise ValueError(f"a step's arguments go under 'args', not {key!r}; rename it")


class PlaybookHandoffStepInput(BaseModel):
    """A tool call recorded inside a handoff, as the authoring tool takes it.

    Flat by design: playbooks are depth-1, so a handoff's children are always
    plain tool calls. Modelling that here instead of reusing ``PlaybookStep``
    keeps the tool's JSON Schema free of the self-``$ref`` that several
    function-calling providers mishandle.

    Unknown keys are dropped rather than refused. A model that adds a ``goal``
    or a ``note`` to a step it otherwise wrote correctly has said everything the
    playbook needs; refusing the whole write over a stray key threw away 17 of
    the 57 authoring attempts made in production.
    """

    id: str = Field(description="Referencable name for this call, e.g. $steps.<id>.field")
    tool: str = Field(description="Exact name of the tool this step calls")
    args: dict[str, Any] = Field(default_factory=dict, description=_ARGS_DESCRIPTION)

    @model_validator(mode="before")
    @classmethod
    def _flat_or_refused(cls, data: object) -> object:
        # Lenient about unknown keys, but not about these two: a child that
        # carries its own ``steps`` or ``handoff`` is the author nesting a
        # delegation a level deeper than a playbook goes, and dropping that
        # silently would store a playbook that runs a fraction of what the
        # author wrote and pass it off as the whole sequence.
        if isinstance(data, Mapping):
            nested = sorted(key for key in ("steps", "handoff") if key in data)
            if nested:
                raise ValueError(
                    f"a handoff's child is one tool call and cannot carry {' or '.join(nested)}: "
                    "playbooks are one level deep, so list the calls that subagent made "
                    "as the handoff's own steps"
                )
            _refuse_args_near_miss(data)
        return data

    def to_step(self) -> PlaybookStep:
        return PlaybookStep(id=self.id, tool=self.tool, args=self.args)


class PlaybookStepInput(BaseModel):
    """One top-level step as the authoring tool takes it: a tool call, or a
    handoff carrying the plain tool calls that subagent ran.

    Lenient about unknown keys for the same reason as the handoff child above;
    the shape rule below is the only one worth failing a write over.
    """

    id: str = Field(default="", description="Referencable name, e.g. $steps.<id>.field")
    tool: str | None = Field(
        default=None, description="Exact name of the tool this step calls, for a tool step"
    )
    args: dict[str, Any] = Field(default_factory=dict, description=_ARGS_DESCRIPTION)
    handoff: str | None = Field(
        default=None, description="Subagent id, for a handoff step. Leave 'tool' unset."
    )
    steps: list[PlaybookHandoffStepInput] = Field(
        default_factory=list,
        description="The tool calls the handoff's subagent ran. Only a handoff carries these.",
    )

    @model_validator(mode="before")
    @classmethod
    def _args_spelled_right(cls, data: object) -> object:
        if isinstance(data, Mapping):
            _refuse_args_near_miss(data)
        return data

    @model_validator(mode="after")
    def exactly_one_shape(self) -> Self:
        if bool(self.tool) == bool(self.handoff):
            raise ValueError(
                f"step {self.id or '<unnamed>'}: set exactly one of 'tool' or 'handoff'"
            )
        if self.handoff and not self.steps:
            raise ValueError(
                f"handoff {self.handoff}: carries no steps, so it would do nothing; list "
                "the calls that subagent ran (its handoff result records them) in this "
                "step's 'steps' field"
            )
        if self.tool and self.steps:
            raise ValueError(f"step {self.id or self.tool}: only a handoff may carry nested steps")
        return self

    def to_step(self) -> PlaybookStep:
        return PlaybookStep(
            id=self.id,
            tool=self.tool,
            args=self.args,
            handoff=self.handoff,
            steps=[child.to_step() for child in self.steps],
        )


def playbook_body_from_input(
    description: str,
    steps: Sequence[PlaybookStepInput],
    result_brief: str,
) -> PlaybookBody:
    """Turn the tool boundary's flat arguments into the stored playbook body."""
    return PlaybookBody(
        description=description,
        steps=[step.to_step() for step in steps],
        result_brief=result_brief,
    )


class PlaybookDocument(PlaybookBody, MongoDocument):
    """A playbook as stored in Mongo.

    Identity is the business key ``playbook_id``; one active playbook per
    workflow. The structured body is the only stored form: the YAML the agent
    reads back is rendered from it on demand, so there is no second copy to
    drift out of sync with the steps that actually replay.
    """

    playbook_id: str = Field(default_factory=lambda: f"pb_{uuid.uuid4().hex[:12]}")
    workflow_id: str
    user_id: str
    #: Hash of the workflow's prompt + steps at authoring time. A mismatch means
    #: the user edited the workflow, so the frozen sequence no longer matches
    #: what was asked and the playbook is skipped rather than replayed blind.
    workflow_hash: str
    last_run_status: PlaybookRunStatus = PlaybookRunStatus.NOT_RUN
    #: Why the last run failed or was not trusted; None after a success.
    last_run_reason: str | None = None
    #: Consecutive suspect replays; the worker disables the playbook past a limit.
    suspect_streak: int = 0
    #: Heal runs spent on the current body. A rewrite resets it; the worker
    #: deletes the playbook past ``PLAYBOOK_HEAL_ATTEMPT_LIMIT``.
    heal_attempts: int = 0
    #: Bumped on every write. ``playbook_id`` survives a rewrite, so this is what
    #: tells a replay's outcome that the body it ran is the body still stored.
    revision: int = 0
    created_at: datetime
    updated_at: datetime


class PlaybookUpdate(BaseModel):
    """Partial ``$set`` update for a playbook."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    steps: list[PlaybookStep] | None = None
    result_brief: str | None = None
    workflow_hash: str | None = None
    last_run_status: PlaybookRunStatus | None = None
    last_run_reason: str | None = None
    suspect_streak: int | None = None
    heal_attempts: int | None = None
    updated_at: datetime | None = None
