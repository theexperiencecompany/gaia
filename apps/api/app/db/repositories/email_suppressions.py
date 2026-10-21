"""Repository for the email_suppressions collection: addresses that opted out of invites.

Global and keyed by the normalized address (unique), so one opt-out silences
every sender at once.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.referral_models import EmailSuppressionDocument


class EmailSuppressionsRepository(
    MongoRepository[EmailSuppressionDocument, EmailSuppressionDocument]
):
    collection_name = "email_suppressions"
    document_model = EmailSuppressionDocument
    update_model = EmailSuppressionDocument
    uses_object_id = True
    cache_policy = None

    async def suppress(self, email: str) -> None:
        """Record the opt-out; an address already suppressed stays suppressed."""
        try:
            await self.create(EmailSuppressionDocument(email=email, created_at=datetime.now(UTC)))
        except DuplicateKeyError:
            return

    async def suppressed_among(self, emails: list[str]) -> set[str]:
        """Return which of these normalized addresses opted out."""
        if not emails:
            return set()
        return set(await self._distinct("email", {"email": {"$in": emails}}))


email_suppression_repository = EmailSuppressionsRepository()
