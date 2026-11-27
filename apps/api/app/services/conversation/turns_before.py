"""What the user said and was shown just before a point in the conversation log."""

import itertools

from app.constants.conversation import RECENT_TURNS_LOOKBACK_SEQS
from app.models.conversation_log_models import Reply, ReplySettled, UserMessage
from app.models.message_models import MessageDict
from app.services.conversation.ports import ConversationLog


async def turns_before(
    log: ConversationLog, conversation_id: str, user_id: str, seq: int
) -> list[MessageDict]:
    """Return the user messages and shown replies logged shortly before seq, as chat turns.

    A reply counts only once settled before seq (its text kept growing while open, so the
    user could not have seen it all), and only as far as they heard it after a barge-in.
    """
    since = max(0, seq - 1 - RECENT_TURNS_LOOKBACK_SEQS)
    entries = await log.read_after(conversation_id, user_id, since)
    before = list(itertools.takewhile(lambda logged: logged.seq < seq, entries))
    settled = {logged.entry.reply_id for logged in before if isinstance(logged.entry, ReplySettled)}
    turns: list[MessageDict] = []
    for logged in before:
        match logged.entry:
            case UserMessage(text=text):
                turns.append({"role": "user", "content": text})
            case Reply(reply_id=reply_id, text=text, heard_through=heard) if reply_id in settled:
                heard_text = text if heard is None else text[:heard]
                if heard_text:
                    turns.append({"role": "assistant", "content": heard_text})
    return turns
