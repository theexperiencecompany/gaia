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
