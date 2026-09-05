"""Playbook models — a workflow's settled tool-call sequence, written down.

A playbook is authored by the agent at the end of a run it judges repeatable,
and replayed by a script-driven subagent instead of being re-reasoned from
scratch. The document is YAML the agent reads and edits; these models are the
parsed form the runner executes.

The grammar is deliberately three keys — ``description``, ``steps`` and
``result_brief``. It carries no BRANCHING: a run whose order depends on what it
finds is not compilable and stays on the agent path, which is the correct
outcome rather than a gap to fill with conditionals.

Bounded repetition is not branching, and ``for_each`` is where that line is
drawn. A step may repeat over a list, capped by ``max_items``, with ``$item``
addressing the element. The order of steps is still fixed and known before the
run; only how many times one of them repeats varies. Without it the commonest
workflow shape GAIA has — fetch the mail, then act on the ones that need it —
was unfreezable, and declined as "the call order depends on what the fetch
finds" when the order never changed at all.

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
from typing import Annotated, Any, Self, TypeGuard, cast
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)

from app.db.repositories.base import MongoDocument
from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN

#: The key that marks an argument value as a slot a model fills at replay,
#: rather than as data. A ``$`` prefix because no tool takes an argument or a
#: JSON field by that name, so the marker cannot collide with real content.
#: ``AskSlot`` below repeats the literal because a pydantic alias has to be one.
ASK_KEY = "$ask"

#: Cap on a single ``$ask`` slot's output. Generous enough for a briefing body,
#: small enough that a runaway prompt cannot turn one replay into a long
#: generation — the whole point of a playbook is a bounded token cost.
DEFAULT_ASK_MAX_TOKENS = 1024

#: Ceiling on how many times one ``for_each`` step may repeat. A replay's cost
#: has to be knowable before it runs, and the fan-out is the only part of a
#: playbook whose size the author cannot see when they write it: today's inbox
#: had three mails that wanted a reply, tomorrow's has forty.
MAX_FOR_EACH_ITEMS = 25

#: The key a ``for_each`` ask slot answers to, appended to the step's prefix.
#: Distinct from every argument path because no argument is named this.
FOR_EACH_ASK_PATH = "$for_each"


#: The one description every step id carries, wherever a step is spelled out.
_STEP_ID_DESCRIPTION = "Referencable name, e.g. $steps.<id>.field"


class DeclineKind(str, Enum):
    """Why a run refused to freeze its sequence, as a value rather than prose.

    The set is deliberately narrow. A free-text reason let a run decline because
    the *arguments* differed between runs — the attendees of today's meeting, the
    subject of today's mail — which the placeholder vocabulary already handles
    and which the check brief already says is not a reason. Prose could spell
    that; an enum cannot, because no member means it. The same goes for a run
    whose only variation was how MANY times one call repeated: that is what a
    ``for_each`` step is for, so it has no member either and the tool redirects.

    The ``BLOCKED_*`` members are not really declines at all. They say the run
    never got to do the work, so there was no sequence to judge — see
    :data:`BLOCKED_DECLINE_KINDS`.
    """

    #: The workflow needs an integration the user has never connected. The run
    #: could only check integration status and report the gap.
    BLOCKED_MISSING_INTEGRATION = "blocked_missing_integration"
    #: The integration is connected but its authorisation is dead (expired
    #: token, revoked grant, persistent 403).
    BLOCKED_AUTH_EXPIRED = "blocked_auth_expired"
    #: The user's daily allowance was already spent, so no call ran.
    BLOCKED_NO_BUDGET = "blocked_no_budget"
    #: The genuine article: some call happens on one run and not on another, so
    #: the ORDER itself differs. Requires naming that call.
    ORDER_BRANCHES = "order_branches"
    #: The run had to discover something mid-flight that a later run would have
    #: to discover differently — an inferred set, a schema probe, a recovery.
    UNSTABLE_DISCOVERY = "unstable_discovery"
    #: The run found nothing to act on, so the calls that do the work never
    #: happened and there is nothing to freeze yet. Not a verdict on the
    #: sequence: the check is asked again on a day the work happens.
    NO_WORK_TODAY = "no_work_today"


#: Kinds that describe a run which never reached the work. They must not count
#: toward ``PLAYBOOK_DECLINE_LIMIT``: a workflow blocked on a disconnected
#: integration fires twice a day and would exhaust its three chances in under
#: two days, then be locked out of ever earning a playbook — including after the
#: user connects the integration, because only a workflow edit resets the tally.
BLOCKED_DECLINE_KINDS = frozenset(
    {
        DeclineKind.BLOCKED_MISSING_INTEGRATION,
        DeclineKind.BLOCKED_AUTH_EXPIRED,
        DeclineKind.BLOCKED_NO_BUDGET,
    }
)

#: A call that changes something, by its name: every tool in this codebase and
#: every Composio action spells its verb first (``create_todo``,
#: ``GMAIL_SEND_EMAIL``). A run that made one of these did the work, whatever it
#: says about the day. A heuristic by name, not a catalogue: a doing-tool with
#: a novel verb slips through, which is today's behaviour, and no listing tool
#: (``list_``, ``get_``, ``fetch_``, ``search_``) can be mistaken for one.
WORK_CALL_VERBS = frozenset(
    {
        "create",
        "add",
        "send",
        "update",
        "delete",
        "remove",
        "complete",
        "mark",
        "schedule",
        "reply",
        "post",
        "move",
        "archive",
        "set",
        "write",
        "upload",
        "insert",
        "cancel",
    }
)


def is_work_call(tool_name: str) -> bool:
    """Whether a tool call, by its name, changed something."""
    parts = tool_name.lower().replace("-", "_").split("_")
    return any(part in WORK_CALL_VERBS for part in parts)


#: Kinds that do not count toward the limit: the blocked ones, and a quiet day.
#: A fan-out over an empty list makes no calls, and a playbook freezes calls
#: that ran, so a workflow whose work is seasonal would spend its chances on
#: the days nothing happened and be locked out on the day something did.
UNCOUNTED_DECLINE_KINDS = BLOCKED_DECLINE_KINDS | {DeclineKind.NO_WORK_TODAY}

#: Blocked kinds that name integrations and can therefore pause the workflow.
INTEGRATION_DECLINE_KINDS = frozenset(
    {
        DeclineKind.BLOCKED_MISSING_INTEGRATION,
        DeclineKind.BLOCKED_AUTH_EXPIRED,
    }
)


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

    # Serialised by alias always: the stored form is the read form. Seen live:
    # a body dumped by field name wrote ``prompt`` where the read wanted
    # ``$ask``, and the playbook could never be read back.
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)

    prompt: str = Field(alias="$ask", min_length=1, description="What to write for this value")
    max_tokens: int = Field(default=DEFAULT_ASK_MAX_TOKENS, ge=1, le=8192)


TIME_KEY = "$time"


class TimeSlot(BaseModel):
    """A time argument written as a placeholder plus the layout the tool takes.

    ``{"$time": "$today + 1d 09:00", "format": "%Y-%m-%d %H:%M:%S"}`` stands in
    the argument's place. The placeholder is one of the time roots with its
    optional offset and clock; ``format`` is the strftime layout the tool
    accepted in the authoring run, so the replay renders the moment exactly the
    way the tool has already taken it once.
    """

    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)

    # A literal alias: the mypy plugin reads it as one, and TIME_KEY is its twin.
    placeholder: str = Field(alias="$time", min_length=1)
    format: str = Field(min_length=1, description="strftime layout the tool takes")

    @field_validator("placeholder")
    @classmethod
    def _a_whole_time_placeholder(cls, value: str) -> str:
        match = PLACEHOLDER_TOKEN.fullmatch(value.strip())
        if match is None or match.group("root") not in ("now", "today") or match.group("path"):
            raise ValueError(
                f"{TIME_KEY} takes one time placeholder ($now or $today, with an optional "
                f"offset and clock such as $today + 1d 09:00), not {value!r}"
            )
        return value.strip()

    @field_validator("format")
    @classmethod
    def _a_layout_that_renders(cls, value: str) -> str:
        # strftime renders any text, so the one way a layout can be wrong is
        # to hold no field at all: a constant renders the same on every fire.
        if "%" not in value:
            raise ValueError(f"format {value!r} carries no strftime field")
        return value


def is_time_slot(value: object) -> TypeGuard[Mapping[str, Any]]:
    """Whether a value is a time placeholder with its layout."""
    return isinstance(value, Mapping) and TIME_KEY in value


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


class AskKind(str, Enum):
    """What a slot is answered with: one value, or the elements a step repeats over."""

    TEXT = "text"
    ITEMS = "items"


@dataclass(frozen=True, slots=True)
class LocatedAsk:
    """One ask slot, the key that addresses it, and the kind of answer it takes."""

    key: str
    slot: AskSlot
    kind: AskKind


class PlaybookAskAnswer(BaseModel):
    """One ``$ask`` slot, written by an ask call.

    A slot standing in for an argument is answered with ``text``. A slot that is
    a step's ``for_each`` source is answered with ``items``, because what it
    stands for is the list the step repeats over rather than one value. An
    answer carries exactly one of the two: ``text`` is optional only so ``items``
    can exist, and an answer with neither would land as an empty string in a
    real tool argument where the missing-slot check could not see it.
    """

    name: str = Field(description="The slot's key, exactly as listed in <asks>")
    text: str = Field(default="", description="What to write for that slot")
    items: list[str] | None = Field(
        default=None,
        description=(
            "For a for_each slot only: the elements the step repeats over. An empty list "
            "is the answer when nothing qualifies."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> Self:
        # ``items`` is judged by presence, not length: an empty list is the
        # answer "nothing qualifies today", which a for_each slot must be able
        # to receive. Seen on a scheduled fire: the model answered ``[]`` on a
        # quiet day and the refusal turned a right body into a failed replay.
        has_text, has_items = bool(self.text.strip()), self.items is not None
        if has_text == has_items:
            raise ValueError(
                f"{self.name}: answer with text, or with items for a for_each slot, not both "
                "and not neither"
            )
        return self

    @property
    def kind(self) -> AskKind:
        return AskKind.ITEMS if self.items is not None else AskKind.TEXT


class PlaybookAskFill(BaseModel):
    """What one ask call produces: the slots its own step needs, and nothing else."""

    asks: list[PlaybookAskAnswer] = Field(default_factory=list)


def _nulls_are_unset(data: object) -> object:
    """Documents written before the step variants existed carry every field.

    The old single model defaulted ``tool``/``handoff``/``for_each``/``max_items``
    to ``None`` and ``steps`` to ``[]``, and those defaults are on every stored
    playbook. Under ``extra="forbid"`` they would refuse the variant they belong
    to, so a null (or an empty child list) is read as the field being unset,
    which is exactly what it meant when it was written.
    """
    if not isinstance(data, Mapping):
        return data
    return {
        key: value
        for key, value in data.items()
        if value is not None and not (key == "steps" and value == [])
    }


class _CallStep(BaseModel):
    """What a tool call step and a repeating tool call step share."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", description=_STEP_ID_DESCRIPTION)
    tool: str = Field(min_length=1, description="Exact name of the tool this step calls")
    args: dict[str, Any] = Field(default_factory=dict, description="Args, may hold $placeholders")

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_nulls(cls, data: object) -> object:
        return _nulls_are_unset(data)

    @property
    def label(self) -> str:
        """How the step is named in prompts and records: its id, else its tool."""
        return self.id or self.tool

    def arg_ask_slots(self, prefix: str) -> list[LocatedAsk]:
        """The slots inside this step's arguments, keyed under ``prefix``.

        The prefix is a parameter because a repeating step fills its arguments
        once per element, and two elements' answers must not share a key: the
        evaluator looks each one back up by exactly this string, so a collision
        would put the first element's text into the second element's call.
        """
        return [
            LocatedAsk(
                key=ask_slot_key(prefix, path),
                slot=AskSlot.model_validate(value),
                kind=AskKind.TEXT,
            )
            for path, value in walk_ask_slots(self.args)
        ]

    def _document_head(self) -> dict[str, Any]:
        node: dict[str, Any] = {}
        if self.id:
            node["id"] = self.id
        node["tool"] = self.tool
        if self.args:
            node["args"] = self.args
        return node


class ToolStep(_CallStep):
    """One tool call, replayed once."""

    def ask_slots(self, prefix: str) -> list[LocatedAsk]:
        return self.arg_ask_slots(prefix)

    def to_document(self) -> dict[str, Any]:
        """The step as the YAML the agent reads and edits."""
        return self._document_head()


class ForEachStep(_CallStep):
    """One tool call, replayed once per element of a list, ``$item`` addressing
    the element.

    Bounded repetition is not branching: the order of steps is still fixed and
    known before the run, only how many times this one repeats varies. The
    ceiling is required because a replay's cost has to be knowable before it
    runs, and the fan-out is the one part of a playbook whose size the author
    cannot see when they write it.
    """

    #: Either a placeholder naming a previous step's list, or an ``$ask`` slot
    #: a model fills with the elements at replay. The whole value, nothing else.
    for_each: str | AskSlot = Field(description="A list to repeat this step over")
    max_items: int = Field(ge=1, le=MAX_FOR_EACH_ITEMS, description="Cap on repetitions")

    @field_validator("for_each")
    @classmethod
    def _names_a_list(cls, value: str | AskSlot) -> str | AskSlot:
        """A placeholder woven into prose resolves to a STRING, and a string is
        not a list. Seen on the first real authoring run:
        ``for_each: overdue-items-from-$steps.list``. Refused here, at the write,
        rather than on the replay a whole agentic run later."""
        if isinstance(value, AskSlot) or PLACEHOLDER_TOKEN.fullmatch(value):
            return value
        raise ValueError(
            "for_each must be the whole value, either one placeholder naming a list "
            f"($steps.<step_id>.<field>) or an $ask slot, but it is {value!r}; a placeholder "
            "inside a longer string resolves to text, and text is not a list"
        )

    @property
    def source_key(self) -> str:
        """The key the loop source answers to when it is an ``$ask``."""
        return ask_slot_key(self.label, (FOR_EACH_ASK_PATH,))

    def ask_slots(self, prefix: str) -> list[LocatedAsk]:
        """The source slot first, then the arguments: the arguments are written
        once per element and cannot be addressed until the elements exist."""
        located: list[LocatedAsk] = []
        if isinstance(self.for_each, AskSlot):
            located.append(LocatedAsk(key=self.source_key, slot=self.for_each, kind=AskKind.ITEMS))
        located.extend(self.arg_ask_slots(prefix))
        return located

    def to_document(self) -> dict[str, Any]:
        node = self._document_head()
        node["for_each"] = (
            self.for_each.model_dump(exclude_defaults=True)
            if isinstance(self.for_each, AskSlot)
            else self.for_each
        )
        node["max_items"] = self.max_items
        return node


def _call_shape(value: object) -> str:
    """Which call variant a value is: the one that carries ``for_each``."""
    if isinstance(value, ForEachStep):
        return "for_each"
    if isinstance(value, ToolStep):
        return "tool"
    if isinstance(value, Mapping) and value.get("for_each") is not None:
        return "for_each"
    return "tool"


#: A handoff's child: a call, plain or repeating, never another handoff. Depth
#: one is a property of this type, not of a validator.
HandoffChild = Annotated[
    Annotated[ToolStep, Tag("tool")] | Annotated[ForEachStep, Tag("for_each")],
    Discriminator(_call_shape),
]


class HandoffStep(BaseModel):
    """A delegation to a subagent, carrying the calls that subagent ran.

    The children execute in that subagent's context, so the subagent's existing
    tool space *is* the auth boundary; there is no separate binding rule.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", description=_STEP_ID_DESCRIPTION)
    handoff: str = Field(min_length=1, description="Subagent id")
    steps: list[HandoffChild] = Field(min_length=1, description="The calls that subagent ran")

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_nulls(cls, data: object) -> object:
        return _nulls_are_unset(data)

    @property
    def label(self) -> str:
        return self.id or self.handoff

    def ask_slots(self, prefix: str) -> list[LocatedAsk]:
        """The children's slots, each under its own label: a child's key names
        the child, since that is the step the evaluator fills."""
        del prefix  # a handoff has no slots of its own; its children key themselves
        return [slot for child in self.steps for slot in child.ask_slots(child.label)]

    def to_document(self) -> dict[str, Any]:
        node: dict[str, Any] = {}
        if self.id:
            node["id"] = self.id
        node["handoff"] = self.handoff
        node["steps"] = [child.to_document() for child in self.steps]
        return node


def _step_shape(value: object) -> str:
    """Which variant a value is, read off its shape.

    No ``kind`` key is stored or rendered: the documents already in Mongo and
    the YAML the agent reads carry none, and the shape says it anyway. A
    ``handoff`` key is a handoff; a ``for_each`` key is a repeating call; the
    rest is a plain call.
    """
    if isinstance(value, HandoffStep):
        return "handoff"
    if isinstance(value, Mapping) and value.get("handoff") is not None:
        return "handoff"
    return _call_shape(value)


PlaybookStep = Annotated[
    Annotated[ToolStep, Tag("tool")]
    | Annotated[ForEachStep, Tag("for_each")]
    | Annotated[HandoffStep, Tag("handoff")],
    Discriminator(_step_shape),
]


def ask_slots(steps: Sequence[ToolStep | ForEachStep | HandoffStep]) -> list[LocatedAsk]:
    """Every ask slot in a playbook, in execution order, handoff children included.

    Keys are unique: step ids are unique (the validator refuses a repeat) and
    two slots in one step sit at two different argument paths.
    """
    return [slot for step in steps for slot in step.ask_slots(step.label)]


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
    if is_time_slot(value):
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
    "$last_run.<TOOL_NAME>.<path>. A time may carry a clock: $today + 1d 09:00. "
    "A time argument the tool takes in its own layout is written as "
    '{"$time": "$today + 1d 09:00", "format": "%Y-%m-%d %H:%M:%S"}, the format '
    "being the layout of the value you actually sent. $ask is not a placeholder; "
    "if a value genuinely cannot be frozen or built from $now/$today/$user/$trigger/"
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


_FOR_EACH_DESCRIPTION = (
    "Repeat this step once per element of a list, with $item addressing the "
    "element ($item.field for a field of it). This is the WHOLE value and "
    "nothing else: either one placeholder naming a previous step's list, e.g. "
    '$steps.inbox.messages, or {"$ask": "which of the above to act on"} for a '
    "list a model picks at replay. A placeholder inside a longer string, like "
    "'overdue-from-$steps.list', resolves to text, and text is not a list. Use "
    "this when the NUMBER of calls depends on what the run found; it is not a "
    "reason to decline."
)
_MAX_ITEMS_DESCRIPTION = (
    f"Required with for_each, at most {MAX_FOR_EACH_ITEMS}: the most elements this "
    "step may ever run for."
)


class _CallInput(BaseModel):
    """What every authored call carries, at the tool boundary.

    Unknown keys are dropped rather than refused. A model that adds a ``goal``
    or a ``note`` to a step it otherwise wrote correctly has said everything the
    playbook needs; refusing the whole write over a stray key threw away 17 of
    the 57 authoring attempts made in production. The near-miss spellings of
    ``args`` are the one exception, refused by name, because dropping one of
    those would store a call with no arguments and pass it off as authored.
    """

    id: str = Field(default="", description=_STEP_ID_DESCRIPTION)
    args: dict[str, Any] = Field(default_factory=dict, description=_ARGS_DESCRIPTION)
    for_each: str | AskSlot | None = Field(default=None, description=_FOR_EACH_DESCRIPTION)
    max_items: int | None = Field(default=None, description=_MAX_ITEMS_DESCRIPTION)

    @model_validator(mode="before")
    @classmethod
    def _args_spelled_right(cls, data: object) -> object:
        if isinstance(data, Mapping):
            _refuse_args_near_miss(data)
        return data

    @model_validator(mode="after")
    def _ceiling_only_with_a_loop(self) -> Self:
        # Unrepresentable on the executed model; a model can still send it here.
        if self.for_each is None and self.max_items is not None:
            raise ValueError(
                f"step {self.id or '<unnamed>'}: max_items only means something with for_each"
            )
        return self

    def _call(self, tool: str) -> ToolStep | ForEachStep:
        if self.for_each is None:
            return ToolStep(id=self.id, tool=tool, args=self.args)
        if self.max_items is None:
            raise ValueError(
                f"step {self.id or tool}: for_each needs max_items, at most {MAX_FOR_EACH_ITEMS}, "
                "so the replay's cost is known before it runs"
            )
        return ForEachStep(
            id=self.id, tool=tool, args=self.args, for_each=self.for_each, max_items=self.max_items
        )


class PlaybookHandoffStepInput(_CallInput):
    """A tool call recorded inside a handoff, as the authoring tool takes it.

    Flat by design: playbooks are depth-1, so a handoff's children are always
    calls. Modelling that here instead of reusing the step union keeps the
    tool's JSON Schema free of the self-``$ref`` that several function-calling
    providers mishandle.
    """

    tool: str = Field(description="Exact name of the tool this step calls")

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
        return data

    def to_step(self) -> ToolStep | ForEachStep:
        return self._call(self.tool)


class PlaybookStepInput(_CallInput):
    """One top-level step as the authoring tool takes it: a tool call, or a
    handoff carrying the calls that subagent ran."""

    tool: str | None = Field(
        default=None, description="Exact name of the tool this step calls, for a tool step"
    )
    handoff: str | None = Field(
        default=None, description="Subagent id, for a handoff step. Leave 'tool' unset."
    )
    steps: list[PlaybookHandoffStepInput] = Field(
        default_factory=list,
        description="The tool calls the handoff's subagent ran. Only a handoff carries these.",
    )

    @model_validator(mode="after")
    def exactly_one_shape(self) -> Self:
        """A model can send any combination; the executed types cannot hold one."""
        where = self.id or "<unnamed>"
        if bool(self.tool) == bool(self.handoff):
            raise ValueError(f"step {where}: set exactly one of 'tool' or 'handoff'")
        if self.handoff and not self.steps:
            raise ValueError(
                f"handoff {self.handoff}: carries no steps, so it would do nothing; list "
                "the calls that subagent ran (its handoff result records them) in this "
                "step's 'steps' field"
            )
        if self.handoff and self.for_each is not None:
            raise ValueError(
                f"step {where}: for_each repeats a single tool call, so it cannot sit on a "
                "handoff; put it on the call inside the handoff that repeats"
            )
        if self.tool and self.steps:
            raise ValueError(f"step {where}: only a handoff may carry nested steps")
        return self

    def to_step(self) -> ToolStep | ForEachStep | HandoffStep:
        if self.handoff is not None:
            return HandoffStep(
                id=self.id, handoff=self.handoff, steps=[child.to_step() for child in self.steps]
            )
        # exactly_one_shape guarantees a tool when there is no handoff.
        return self._call(cast(str, self.tool))


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
    #: The run (its stream id) that wrote this body. A run is one decision: a
    #: decline voiced after the write in the same run is not a second one.
    authored_run: str | None = None
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
    authored_run: str | None = None
    last_run_status: PlaybookRunStatus | None = None
    last_run_reason: str | None = None
    suspect_streak: int | None = None
    heal_attempts: int | None = None
    updated_at: datetime | None = None
