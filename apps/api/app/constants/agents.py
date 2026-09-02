"""Internal agent-to-agent channel tags.

The tiers hand work to each other asynchronously — executor results reach comms,
subagent results reach the executor — and the handoff is plain text landing in
the next tier's context. These XML-style tags frame that text: they say where an
internal payload starts, where it ends, and that it is addressed to the agent and
never to the user.

XML tags rather than the bare ``[MARKER]`` prefixes they replace, for two
reasons. A prefix only marks a start, so the model has to infer where the
internal payload stops and its own reply begins; an open/close pair states it.
And models are trained on tagged context blocks, so a tag reads as machine
framing while a bracketed word reads as text worth copying — which is exactly how
``[EXECUTOR_RESULT]`` kept surfacing at the top of user-facing replies.

This module owns the vocabulary AND the framing, so the site that writes a tag
and the site that strips one (``strip_internal_agent_tags``) can never disagree
about the syntax.
"""

from enum import StrEnum
import re


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
    STYLE_CORRECTION = "style_correction"
    LAST_RUN = "last_run"
    PLAYBOOK_FALLBACK = "playbook_fallback"


def wrap_agent_payload(tag: AgentTag, body: str, agent: str | None = None) -> str:
    """Frame an internal payload in its channel tag.

    ``agent`` names the tier that produced the payload, which only a
    ``<subagent_result>`` carries — several land in one collection and the
    executor has to tell whose report is whose.

    Trailing newline included so consecutive blocks concatenate into one
    readable document without the caller managing separators.
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


# The trigger-context key carrying a stopped playbook replay's report into the
# agent run that takes over from it. Written by the workflow worker, read by
# ``format_workflow_execution_message`` — named once here because a drift
# between those two sites is silent and the agent would re-run a side effect.
PLAYBOOK_FALLBACK_CONTEXT_KEY = "playbook_fallback"

# After this many consecutive suspect replays the worker disables the playbook.
PLAYBOOK_SUSPECT_STREAK_LIMIT = 2

# After this many declines on one unchanged workflow the check brief stops
# asking; an edit to the workflow (new hash) asks again.
PLAYBOOK_DECLINE_LIMIT = 3

# A playbook whose last replay was not trusted gets this many heal runs. A heal
# that lapses, declines, or has its rewrite refused still counts; past the limit
# the worker deletes the playbook rather than briefing every later fire to heal it.
PLAYBOOK_HEAL_ATTEMPT_LIMIT = 2

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

#: The playbook decision tools. Bookkeeping about a run, never the run itself:
#: left out of the record the next run reads, or the model copies them as steps.
PLAYBOOK_TOOL_NAMES = frozenset(
    {"write_playbook", "read_playbook", "decline_playbook", "disable_playbook"}
)
