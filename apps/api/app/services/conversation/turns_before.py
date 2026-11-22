"""What the user said and was shown just before a point in the conversation log."""

import itertools

from app.constants.conversation import RECENT_TURNS_LOOKBACK_SEQS
from app.models.conversation_log_models import Reply, UserMessage
from app.models.message_models import MessageDict
from app.services.conversation.ports import ConversationLog


async def turns_before(
    log: ConversationLog, conversation_id: str, user_id: str, seq: int
) -> list[MessageDict]:
    """Return the user messages and shown replies logged shortly before seq, as chat turns."""
    since = max(0, seq - 1 - RECENT_TURNS_LOOKBACK_SEQS)
    entries = await log.read_after(conversation_id, user_id, since)
    turns: list[MessageDict] = []
    for logged in itertools.takewhile(lambda logged: logged.seq < seq, entries):
        match logged.entry:
            case UserMessage(text=text):
                turns.append({"role": "user", "content": text})
            case Reply(text=text) if text:
                turns.append({"role": "assistant", "content": text})
    return turns
