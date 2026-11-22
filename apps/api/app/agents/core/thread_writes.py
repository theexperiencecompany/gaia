"""Helpers for messages written into a thread outside the normal graph path.

Out-of-band writers (interruption.record_interruption, the comms narrator's
checkpoint appends) call graph.aupdate_state directly. A node write gets ids
from LangGraph; an aupdate_state on the DeltaChannel does not, and an id-less
message can never be removed or replaced by id later — summarization folds
history away by id. Every such write goes through with_message_ids.
"""

from typing import TypeVar
from uuid import uuid4

from langchain_core.messages import BaseMessage

#: Preserves the concrete message type through with_message_ids.
M = TypeVar("M", bound=BaseMessage)


def with_message_ids(messages: list[M]) -> list[M]:
    """Give every id-less message an id, in place, for a write that bypasses a node.

    Graph input and node writes get ids from LangGraph; aupdate_state on the
    DeltaChannel does not, and an id-less message can never be removed or
    replaced by id later (summarization folds history away by id).
    """
    for message in messages:
        if message.id is None:
            message.id = str(uuid4())
    return messages
