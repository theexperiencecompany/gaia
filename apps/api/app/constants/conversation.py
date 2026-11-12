"""Conversation runtime constants."""

from datetime import timedelta
from enum import StrEnum

from app.constants.cache import ONE_DAY_TTL

# p90 time to a first reply is about 16s, so a newer input inside this window still beats waiting.
RESTART_WINDOW_SECONDS = 20.0
RESTART_WINDOW = timedelta(seconds=RESTART_WINDOW_SECONDS)

#: conv:alive:{user_id}:{conversation_id}:{epoch} exists while that epoch's step holder lives.
RUNNER_ALIVE_KEY_PREFIX = "conv:alive:"
# A holder that cannot renew its key for this long is dead, and its claim can be taken over.
RUNNER_ALIVE_TTL_SECONDS = 10
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
#: Suffix of the ids of the turn context messages around a batch (system prompt, context, clock).
TURN_CONTEXT_ID_SUFFIX = ":turn"

REACTION_NOTE = "[You already reacted {emoji} to this message.]"
NOTICE_DELIVERED_NOTE = "[You already sent the user this message: {text}]"
WORK_DONE_NOTE = (
    "[Background work finished. The user has not seen this result yet, so report it in your "
    "reply: {report}]"
)
WORK_UNFINISHED_NOTE = (
    "[Background work ended {outcome}. The user has not seen this yet, so tell them in your "
    "reply: {report}]"
)
WORKFLOW_FIRED_NOTE = "[Workflow {workflow_id} fired. Its context: {context}]"
BARGE_IN_NOTE = "[The user spoke over your reply. They heard only this much of it: {heard}]"
SERVER_RESTART_NOTE = (
    "<server_restart>Your previous reply was cut off by a server restart before it finished. "
    "Do not redo anything it already did; tell the user it was interrupted, then carry on."
    "</server_restart>"
)
