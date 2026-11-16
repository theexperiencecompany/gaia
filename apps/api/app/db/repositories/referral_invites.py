"""Repository for the referral_invites collection: one row per invite email sent.

The unique (sender_user_id, recipient_email) index is the dedupe: claiming a
pair before sending means a sender never mails the same friend twice, even
from two tabs at once.
"""

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.referral_models import ReferralInviteDocument


class ReferralInvitesRepository(MongoRepository[ReferralInviteDocument, ReferralInviteDocument]):
    collection_name = "referral_invites"
    document_model = ReferralInviteDocument
    update_model = ReferralInviteDocument
    uses_object_id = True
    cache_policy = None

    async def claim(self, invite: ReferralInviteDocument) -> ReferralInviteDocument | None:
        """Take the (sender, recipient) pair before sending; None when it was already invited."""
        try:
            return await self.create(invite)
        except DuplicateKeyError:
            return None

    async def release(self, invite_id: str) -> None:
        """Give a claim back after its send failed, so the sender can try again."""
        await self.delete(invite_id)

    async def invited_by(self, sender_user_id: str) -> set[str]:
        """Return every normalized address this sender has invited."""
        return set(await self._distinct("recipient_email", {"sender_user_id": sender_user_id}))


referral_invite_repository = ReferralInvitesRepository()
