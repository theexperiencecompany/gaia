"""The ConversationLog port on Mongo (the head and conversation_entries) and Redis (liveness and the hint).

The head's conditional writes are the truth: seq order, the fold, and the epoch fence. Redis
holds what may lapse: an epoch's alive key proves its holder lives, and the hint is the
advisory preempt view, rebuilt from the head whenever it is missing.
"""

from app.services.conversation.mongo_log_amends import LogAmends
from app.services.conversation.mongo_log_append import LogAppends
from app.services.conversation.mongo_log_claim import StepClaims
from app.services.conversation.mongo_log_hint import LogHint
from app.services.conversation.mongo_log_reads import LogReads


class MongoConversationLog(LogAppends, LogAmends, LogReads, StepClaims, LogHint):
    """The ConversationLog port over the conversation repository, one class per responsibility."""
