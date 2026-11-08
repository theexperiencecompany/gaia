"""Repository for the email_verdicts collection: one JEV verdict per user and Gmail message.

Keyed by the business (user_id, message_id) pair under a unique index; a TTL index on
created_at reaps a verdict 48h after it was last asked.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import UserScopedRepository
from app.models.email_verdict_models import EmailVerdictDocument, EmailVerdictUpdate


class EmailVerdictsRepository(UserScopedRepository[EmailVerdictDocument, EmailVerdictUpdate]):
    collection_name = "email_verdicts"
    document_model = EmailVerdictDocument
    update_model = EmailVerdictUpdate
    uses_object_id = True
    identity_field = "message_id"
    cache_policy = None

    async def keep(self, verdict: EmailVerdictDocument) -> None:
        """Store a verdict, replacing any kept for the same message; its 48h start again.

        Two first keeps of one message can both miss and insert; the unique index rejects
        the loser, and its retry overwrites the winner.
        """
        key = {"user_id": verdict.user_id, "message_id": verdict.message_id}
        fields = EmailVerdictUpdate(answers=verdict.answers, bucket=verdict.bucket)
        update = {"$set": {**fields.model_dump(mode="json"), "created_at": datetime.now(UTC)}}
        try:
            await self._apply_raw_update(key, update, scope=None, upsert=True)
        except DuplicateKeyError:
            await self._apply_raw_update(key, update, scope=None, upsert=True)


email_verdict_repository = EmailVerdictsRepository()
