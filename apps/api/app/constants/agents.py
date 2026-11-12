"""Internal agent-to-agent channel tags.

Tiers hand work to each other asynchronously as plain text landing in the next
tier's context; these XML-style tags frame that text as addressed to the
agent, never the user.

XML tags replace bare [MARKER] prefixes: a prefix only marks a start, so the
model must infer where the payload ends, while an open/close pair states it —
and a tag reads as machine framing rather than text worth copying, which is
exactly how [EXECUTOR_RESULT] kept surfacing in user-facing replies.

This module owns the vocabulary AND the framing, so the site that writes a tag
and the site that strips one (strip_internal_agent_tags) can never disagree.
"""

from enum import StrEnum
import re

from app.constants.execute import ACTIVATE_INTEGRATION_TOOL_NAME


class AgentTag(StrEnum):
    """Tag names framing an internal payload passed between agent tiers."""

    EXECUTOR_RESULT = "executor_result"
    EXECUTOR_ERROR = "executor_error"
    EXECUTOR_CANCELLED = "executor_cancelled"
    RETURNED_TO_FRONTEND = "returned_to_frontend"
    PLATFORM_DELIVERY = "platform_delivery"
    DELIVERY_INSTRUCTIONS = "delivery_instructions"
    SUBAGENT_RESULT = "subagent_result"
    SUBAGENT_CALL_RECORD = "subagent_call_record"
    LAST_RUN = "last_run"
    PLAYBOOK_FALLBACK = "playbook_fallback"
    #: The user speaking to an executor run that is already in flight.
    USER_INTERJECTION = "user_interjection"
    #: A run the user force-stopped, told to the run that follows it.
    EXECUTOR_INTERRUPTED = "executor_interrupted"
    #: A ledger approval decision, told to the run that owns the conversation.
    HIL_DECISION = "hil_decision"
    #: The executor steering a subagent run that is already in flight.
    SUBAGENT_INTERJECTION = "subagent_interjection"
    #: A subagent the executor force-stopped, told in its returned result.
    SUBAGENT_CANCELLED = "subagent_cancelled"
    #: What the chat's browser task is doing, told to comms each turn it can act on it.
    BROWSER_TASK = "browser_task"
    #: A background browser job's ending, told to the run that owns the conversation.
    BROWSER_RESULT = "browser_result"
    #: A browser job a stop ended: the thread learns it ended, and no run wakes for it.
    BROWSER_STOPPED = "browser_stopped"


#: Entries that only inform: they wait for the next run's drain and never start one.
NON_WAKING_TAGS: frozenset[AgentTag] = frozenset(
    {AgentTag.EXECUTOR_INTERRUPTED, AgentTag.BROWSER_STOPPED}
)


def wrap_agent_payload(tag: AgentTag, body: str, agent: str | None = None) -> str:
    """Frame an internal payload in its channel tag.

    agent (only carried by <subagent_result>) lets the executor tell whose
    report is whose when several land in one collection.
    """
    attribution = f' agent="{agent}"' if agent else ""
    return f"<{tag}{attribution}>\n{body.strip()}\n</{tag}>\n"


# Every internal tag, open or close, with or without attributes. Stripped
# deterministically before delivery (see ``strip_internal_agent_tags``) as the
# hard backstop for a weak model echoing its context into the reply.
INTERNAL_AGENT_TAG_PATTERN = re.compile(
    rf"</?(?:{'|'.join(tag.value for tag in AgentTag)})(?:\s[^>]*)?>",
    flags=re.IGNORECASE,
)

#: Tags that frame someone actually asking for something. Every other internal
#: tag frames a result, instruction or status the graph wrote, so it must never
#: be mistaken for the request the turn is working on.
REQUEST_AGENT_TAGS: frozenset[AgentTag] = frozenset(
    {AgentTag.USER_INTERJECTION, AgentTag.SUBAGENT_INTERJECTION}
)

_LEADING_AGENT_TAG_PATTERN = re.compile(
    rf"<(?:{'|'.join(tag.value for tag in AgentTag)})(?=[\s>])", re.IGNORECASE
)


def leading_agent_tag(text: str) -> AgentTag | None:
    """Return the internal tag a payload opens with, or None for ordinary text."""
    match = _LEADING_AGENT_TAG_PATTERN.match(text.lstrip())
    return AgentTag(match.group(0)[1:].lower()) if match else None


# The trigger-context key carrying a stopped playbook replay's report into the
# agent run that takes over. Named once here because a drift between the
# writer (workflow worker) and reader (format_workflow_execution_message) is silent.
PLAYBOOK_FALLBACK_CONTEXT_KEY = "playbook_fallback"
#: Calls a playbook never replays: delegation, whose children are in the run
#: record themselves, and tool discovery and binding, which do no work.
PLAYBOOK_UNPICKABLE_TOOLS = frozenset(
    {
        "call_executor",
        "cancel_executor",
        "spawn_subagent",
        "retrieve_tools",
        ACTIVATE_INTEGRATION_TOOL_NAME,
    }
)

#: Executor tools a spawned subagent never gets: steering other subagents, and global
#: instructions (a spawn mines untrusted output). activate_integration stays: a spawn
#: loads the integration its own slice needs.
EXECUTOR_SPAWN_EXCLUDED_TOOLS = frozenset(
    {
        "list_running_subagents",
        "message_subagent",
        "cancel_subagent",
        "update_user_instructions",
    }
)

#: A tool result at least this long (about 7k tokens) is re-read on every later
#: model call of the turn, so the agent that can spawn is pointed at spawns for
#: any further reading of that size.
LARGE_TOOL_RESULT_CHARS = 25_000

# After this many consecutive suspect replays the worker disables the playbook.
PLAYBOOK_SUSPECT_STREAK_LIMIT = 2

# A playbook whose last replay was not trusted gets this many heal runs. A heal
# that lapses, declines, or has its rewrite refused still counts; past the limit
# the worker deletes the playbook rather than briefing every later fire to heal it.
PLAYBOOK_HEAL_ATTEMPT_LIMIT = 2

#: What separates a tool's result from a note a middleware appends to it in
#: band for the model (the loop guard's repeat warning). The record reads the
#: result as the JSON document before this separator; the note is not data.
TOOL_RESULT_NOTE_SEPARATOR = "\n\n"

#: The Unix second a read tool's query ran. Stamped on every result, found or
#: not, so it is bookkeeping like the envelope's successful flag, never data.
TOOL_RESULT_FETCHED_AT_KEY = "fetched_at"

#: How many recent executions a replay searches for the last replay of a tool
#: that returned data, when judging an empty result. Reaches past every heal
#: run (which replays nothing) for every suspect the streak allows.
PLAYBOOK_SUSPECT_BASELINE_WINDOW = PLAYBOOK_SUSPECT_STREAK_LIMIT * (1 + PLAYBOOK_HEAL_ATTEMPT_LIMIT)

#: Closes every executor brief's definition of done. A memory of the same task
#: once stood in for the run: "log me in" came back "already done" with no browser.
DONE_EVIDENCE_RULE = (
    "An item that asks for an action, or for what a page or account shows now, is met "
    "only by a tool call in this run. A memory, or an earlier run of the same task, never meets it."
)


class TimeHorizon(StrEnum):
    """How long a delegated request needs attention; comms sets it on call_executor."""

    ONE_SHOT = "one_shot"
    DEADLINE = "deadline"
    ONGOING = "ongoing"


class OutcomeState(StrEnum):
    """How an executor run left the user's request, declared on finish_task."""

    DONE = "done"
    SCHEDULE = "schedule"
    SUBSCRIBE = "subscribe"
    ASK = "ask"
    BLOCKED = "blocked"


#: The calls whose success backs a declared outcome (outcome_review.review_outcome).
#: Only a tracked todo with a schedule or a recurrence wakes GAIA again; a
#: reminder just notifies the user, so it backs done, never schedule.
OUTCOME_CREATE_TODO_TOOL = "create_tracked_todo"
OUTCOME_TRACKED_TODO_TOOLS = frozenset({OUTCOME_CREATE_TODO_TOOL, "update_tracked_todo"})
OUTCOME_SCHEDULE_ARGS = ("scheduled_at", "recurrence")
OUTCOME_SUBSCRIBE_TOOL = "subscribe_todo_to_trigger"
OUTCOME_COMPLETE_TOOL = "complete_tracked_todo"

#: Opens a scheduled tracked todo run's brief: the run spent the check that woke
#: it and must close the todo or set a new one. outcome_review reads it off the
#: task turn, so the brief and the check cannot drift apart on a string.
TODO_REARM_TAG = "<todo_rearm>"
#: Opens the brief of a run whose todo wakes GAIA again on its own (its recurrence,
#: or the watch that fired it): that wake backs a schedule outcome without a new check.
TODO_WAKES_AGAIN_TAG = "<todo_wakes_again>"


#: What the executor brief tells the run each horizon demands before it may finish.
TIME_HORIZON_BRIEF: dict[TimeHorizon, str] = {
    TimeHorizon.ONE_SHOT: "one_shot: finish it in this run.",
    TimeHorizon.DEADLINE: (
        "deadline: unless it is fully done in this run, leave a tracked todo scheduled "
        "to wake you before the date."
    ),
    TimeHorizon.ONGOING: (
        "ongoing: it needs attention after this run. Leave a tracked todo with a schedule, "
        "recurrence or trigger watch before you finish."
    ),
}

IRREVERSIBLE_APPROVED_BRIEF = (
    "Irreversible actions: the user approved them for this request. Do exactly what was "
    "approved, nothing broader."
)
IRREVERSIBLE_UNAPPROVED_BRIEF = (
    "Irreversible actions: NOT approved. Deleting, bulk-changing, sending or posting needs the "
    "user's yes first: prepare it (the draft, the exact items) and finish with outcome ask."
)

#: What a delegator reads when a worker ended with no answer. Silence is not success:
#: the literal "Task completed" once stood in here and comms told the user it was done.
NO_ANSWER_NOTICE = (
    "{name} ended without reporting a result, so nothing confirms any of it happened. "
    "Treat the work as not done, and never report it as done without other evidence."
)

#: The tag both playbook briefs open with. The executor's graph loop reads it
#: off the task turn to know the run owes a decision, so the briefs and the
#: gate cannot drift apart on a string.
PLAYBOOK_CHECK_TAG = "<playbook_check>"

#: The tools that settle the decision a briefed run owes. ``read_playbook`` is
#: not one: reading the sequence is how a heal run starts, not how it ends.
PLAYBOOK_DECISION_TOOL_NAMES = frozenset({"write_playbook", "decline_playbook", "disable_playbook"})

#: A briefed run that stops in plain text without a decision gets this back
#: once, instead of ending. Bounded by MAX_PLAYBOOK_DECISION_NUDGES so a model
#: that ignores it cannot loop. Seen live: 2 of 6 heal runs ended without one.
PLAYBOOK_DECISION_NUDGE_MESSAGE = (
    "[System: this run was asked to end by calling exactly one of write_playbook, "
    "decline_playbook or disable_playbook, and it has not. Make that call now, "
    "against the calls you actually made. Your result above is already recorded: "
    "after the call, reply with one short line and do not repeat it. A refused "
    "write_playbook is not a decision: fix it or decline.]"
)
MAX_PLAYBOOK_DECISION_NUDGES = 1

#: The playbook tools. Bookkeeping about a run, never the run itself: left out
#: of the record the next run reads, or the model copies them as steps.
PLAYBOOK_TOOL_NAMES = frozenset(
    {"read_run_record", "write_playbook", "read_playbook", "decline_playbook", "disable_playbook"}
)
