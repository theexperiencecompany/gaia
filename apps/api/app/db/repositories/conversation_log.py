"""The repository the ConversationLog port runs on: the log's append, reads and amends, and the step's claim."""

from __future__ import annotations

from app.db.repositories.conversation_log_amends import LogAmendRepository
from app.db.repositories.conversation_log_append import LogAppendRepository
from app.db.repositories.conversation_step_claim import StepClaimRepository


class ConversationLogRepository(LogAppendRepository, LogAmendRepository, StepClaimRepository):
    """Every head and entry operation MongoConversationLog makes, one class per responsibility."""


conversation_log_repository = ConversationLogRepository()
