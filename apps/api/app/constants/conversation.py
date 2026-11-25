"""Conversation runtime constants."""

from datetime import timedelta
from enum import IntEnum, StrEnum

from app.constants.cache import ONE_DAY_TTL
from shared.py.conversation_wire import FailureReason

#: The line a chat platform shows under a failed reply: what happened, and how to get an answer.
REPLY_FAILURE_LINE: dict[FailureReason, str] = {
    FailureReason.MODEL_ERROR: (
        "I couldn't finish that reply because something went wrong on my side. "
        "Send your message again to retry."
    ),
    FailureReason.STEP_LIMIT: (
        "This took more steps than I can take in one go, so I stopped before answering. "
        "Send it again, or split it into smaller asks."
    ),
    FailureReason.SERVER_RESTART: (
        "I restarted while answering. I'll answer again in a moment, so there's no need to resend."
    ),
}

# p90 time to a first reply is about 16s, so a newer input inside this window still beats waiting.
RESTART_WINDOW_SECONDS = 20.0
RESTART_WINDOW = timedelta(seconds=RESTART_WINDOW_SECONDS)

#: conv:alive:{user_id}:{conversation_id}:{epoch} exists while that epoch's step holder lives.
RUNNER_ALIVE_KEY_PREFIX = "conv:alive:"
# A holder that cannot renew its key for this long is dead, and its claim can be taken over.
RUNNER_ALIVE_TTL_SECONDS = 10
# The holder renews its key this many times per TTL, from its own task for the whole claim.
RUNNER_ALIVE_BEATS_PER_TTL = 4
#: conv:hint:{user_id}:{conversation_id}, the advisory preempt view a running step polls.
HINT_KEY_PREFIX = "conv:hint:"
# A lapsed hint is rebuilt from the head, so it only needs to outlive an active conversation.
HINT_TTL_SECONDS = ONE_DAY_TTL


class HintField(StrEnum):
    """The fields of a conversation's hint hash."""

    HEAD = "head"
    STOP = "stop"
    OPEN = "open"
    BARGE = "barge"
    EPOCH = "epoch"


# One task.cancel() can be swallowed by the Postgres pool's connection check, so a cancel is re-sent at this interval.
COMMS_CANCEL_CONFIRM_SECONDS = 1.0

# --- the comms thread messages a log entry becomes ---------------------------
#: additional_kwargs key holding the seq of the log entry a thread message was made from.
LOG_SEQ = "log_seq"
#: Thread message ids of log entries are this prefix plus the entry id, so a re-sent batch upserts.
LOG_MESSAGE_ID_PREFIX = "log:"
#: Suffix of the id of the note that says a user message was already reacted to.
REACTION_NOTE_SUFFIX = ":reaction"
#: Suffix of the id of the note after user messages handed to a run already working on earlier ones.
ABSORBED_NOTE_SUFFIX = ":absorbed"
#: Suffix of the ids of the turn context messages around a batch (system prompt, context, clock).
TURN_CONTEXT_ID_SUFFIX = ":turn"

REACTION_NOTE = "[You already reacted {emoji} to this message.]"
#: What a user message starts with for the comms model: the handle its closing tools name it by.
MESSAGE_HANDLE = "[#{seq}] "
#: Said to a run that tried to end owing messages; one line per open message follows.
STILL_OPEN_NOTE = (
    "[Still open, never named by answered, react, stay_silent or call_executor:\n{messages}\n"
    "If you already answered one, just name it with answered and write nothing more. Otherwise "
    "answer it and name it, or hand it to call_executor.]"
)
STILL_OPEN_LINE = '#{seq} "{text}"'
#: Suffix of the id of the still-open note, after the batch's anchor.
STILL_OPEN_NOTE_SUFFIX = ":still-open"

#: How much of an open message the still-open note quotes.
STILL_OPEN_QUOTE_CHARS = 80
ABSORBED_NOTE = (
    "[The user sent this while you were still working on their earlier message. If it changes "
    "or cancels that request, follow it. Otherwise answer it now and name it. Your lookups are "
    "closed for the rest of this turn: hand what is left of the earlier request to "
    "call_executor, or answer it with what you have; it stays open until you name it too.]"
)
NOTICE_DELIVERED_NOTE = "[You already sent the user this message: {text}]"
WORK_DONE_NOTE = (
    "[Background work finished. The user has not seen this result yet, so report it in your "
    "reply: {report}]"
)
#: Names the cards finished work put on the app screen; one WORK_CARD_LINE per card kind follows.
WORK_CARDS_NOTE = (
    "[The work above already shows the user these cards:\n{cards}\n"
    "They show its raw items, so do not re-type them row by row or rebuild them as a component. "
    "They are not your reply: still tell the user what the work found and what matters in it.]"
)
WORK_CARD_LINE = "- {name}: {count}{maker}"
WORK_CARD_MAKER = ", made by {subagent}"
WORK_UNFINISHED_NOTE = (
    "[Background work ended {outcome}. The user has not seen this yet, so tell them in your "
    "reply: {report}]"
)
# What a workflow turn asks, before its steps and trigger reframe it.
WORKFLOW_RUN_REQUEST = "Execute workflow: {title}"
INTEGRATION_CONNECTED_NOTE = (
    "[The user just connected {integration}. Carry on with the work that was waiting on it; "
    "the user did not type a message.]"
)
BARGE_IN_NOTE = (
    "[The user spoke over your reply and heard only this much of it: {heard}\n"
    "They did not hear the rest, so do not assume they know it.]"
)
SERVER_RESTART_NOTE = (
    "<server_restart>Your previous reply was cut off by a server restart before it finished. "
    "Do not redo anything it already did; tell the user it was interrupted, then carry on."
    "</server_restart>"
)

#: conv:events:{conversation_id}, the one Redis Stream of a conversation's output frames.
EVENTS_KEY_PREFIX = "conv:events:"
#: conv:events-open:{conversation_id} exists while a reply is open; its stream is not trimmed meanwhile.
EVENTS_OPEN_REPLY_KEY_PREFIX = "conv:events-open:"
# A reply streams a few hundred deltas; older frames are replayed from the log instead.
EVENTS_STREAM_MAXLEN = 2000
# An idle conversation's frames are all in the log, so the stream only needs to outlive a session.
EVENTS_STREAM_TTL_SECONDS = ONE_DAY_TTL
# How long one events read blocks before the follower checks the client is still there.
EVENTS_BLOCK_MS = 15_000
#: The cursor that reads a stream from its oldest retained frame.
EVENTS_STREAM_START = "0-0"
# A client's head is nearly always among the newest frames; a reply's deltas are a few hundred.
EVENTS_RESUME_PAGE = 64
# Each read further back asks for this many times more of the stream's newest end.
EVENTS_RESUME_PAGE_GROWTH = 4


class EventsWire(IntEnum):
    """How the events stream writes its frames for one connection; a client names the newest it reads."""

    # Whole items carrying their cards twice, as tool_data and as timeline; what a client built before wire 2 reads.
    ITEMS = 1
    # Cards once, as timeline; a change to an item already sent is a screen_patch, a reply's cards a timeline delta.
    PATCHES = 2


#: conv:work_deltas:{conversation_id}:{task_id}, every payload a task's work published; a resumed run appends to it.
WORK_DELTAS_KEY_PREFIX = "conv:work_deltas:"
# Outlives the longest approval a paused run waits on, so a resumed run still has its cards.
WORK_DELTAS_TTL_SECONDS = 7 * ONE_DAY_TTL
# Seqs read back for the turns just before a point: what the approval-reply classifier
# weighs a typed answer against, and what the auto-mode judge reads a turn in.
RECENT_TURNS_LOOKBACK_SEQS = 20
# How often a running step polls its preempt hint while the model is silent.
STEP_TICK_SECONDS = 0.25
# Heads one sweep reads; the sweep runs every SWEEP_SECONDS, so a backlog drains over a few runs.
SWEEP_BATCH = 200
# Conversations one active-conversations read returns to a restarting bot.
ACTIVE_BOT_CONVERSATIONS_LIMIT = 500
SWEEP_SECONDS = frozenset({0, 15, 30, 45})
#: What a user's Stop leaves as the work's report, in the user's words, not the runner's.
WORK_STOPPED_REPORT = "You stopped this before it finished."
WORK_LOST_REPORT = (
    "The background work stopped unexpectedly when the server running it went down, "
    "so it did not finish."
)
# Past its expiry by this much, an approval the HIL sweep has not timed out is the conversation sweep's to settle.
APPROVAL_EXPIRY_GRACE = timedelta(minutes=5)
# The gate asks in the log, then registers the row: a request older than this with no row never will have one.
APPROVAL_REGISTER_GRACE = timedelta(minutes=1)
# How long a shutting-down process lets its running conversation steps finish.
STEP_DRAIN_GRACE_SECONDS = 20.0
# How far back a connect looks for work waiting on that integration.
INTEGRATION_NEED_WINDOW = timedelta(days=1)

# The WebSocket push a user's clients get after a change to a conversation's list row
# (title, last activity, unread, star), so the conversation list re-syncs.
CONVERSATION_LIST_CHANGED_EVENT = "conversation.list_changed"
