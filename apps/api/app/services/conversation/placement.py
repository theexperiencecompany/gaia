"""What a comms attempt owes and how far its settles move the log's settled mark, from log order alone.

A user message is owed until a closing tool names it; one an instant reaction already
answered is not owed. Every other input (finished work, a workflow fire, a connection) rides
with the attempt's last settle. Inputs settle out of order, so the settled mark only moves
past an input once every input handed below it is answered too.
"""

from collections.abc import Collection, Sequence

from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import LoggedEntry, UserMessage


def owed(entries: Sequence[LoggedEntry]) -> dict[int, str]:
    """Return the user messages among entries that a reply still has to close, log seq -> message id."""
    return {
        logged.seq: logged.entry.id
        for logged in entries
        if isinstance(logged.entry, UserMessage)
        and not (logged.entry.reaction is not None and logged.entry.reaction.by is ReactionBy.JEV)
    }


def watermark(handed: Sequence[LoggedEntry], answered: Collection[int], floor: int) -> int:
    """Return the newest handed seq with every handed input up to it answered; floor when the oldest is not."""
    through = floor
    for logged in handed:
        if logged.seq not in answered:
            break
        through = logged.seq
    return through
