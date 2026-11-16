"""Repository for the referral_codes collection: one immutable code per referrer.

Unique indexes on user_id and code are the guarantees: a racing second mint for
the same user, or a suffix clash between two users, is a DuplicateKeyError the
service resolves, never a second code.
"""

from app.db.repositories.base import MongoRepository
from app.models.referral_models import ReferralCodeDocument


class ReferralCodesRepository(MongoRepository[ReferralCodeDocument, ReferralCodeDocument]):
    collection_name = "referral_codes"
    document_model = ReferralCodeDocument
    update_model = ReferralCodeDocument
    uses_object_id = True
    cache_policy = None

    async def get_for_user(self, user_id: str) -> ReferralCodeDocument | None:
        """Return the user's code, if they were ever given one."""
        return await self._find_one({"user_id": user_id})

    async def get_by_code(self, code: str) -> ReferralCodeDocument | None:
        """Return the code record a link carries."""
        return await self._find_one({"code": code})


referral_code_repository = ReferralCodesRepository()
