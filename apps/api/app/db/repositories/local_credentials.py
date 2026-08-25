"""Repository for the ``auth_credentials`` collection — local-mode passwords.

Global (not user-scoped): a self-host instance has a single administrator, and
the signup gate ("does ANY credential exist?") is a whole-collection question.
Identity fields are write-once — only the bcrypt hash may ever be updated (the
password-change endpoint rotates it via the typed update model), so a rotation
is an in-place ``$set``, never a delete-and-recreate.

Registration is gated by an ATOMIC CLAIM, never check-then-create: every
credential carries the constant ``slot="admin"`` discriminator and a unique
index on it (see ``app.db.mongodb.indexes``) means at most one document can
ever be inserted, even by concurrent requests that both read an empty
collection.
"""

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.auth_models import LocalCredentialDocument, LocalCredentialUpdate


class LocalCredentialsRepository(MongoRepository[LocalCredentialDocument, LocalCredentialUpdate]):
    collection_name = "auth_credentials"
    document_model = LocalCredentialDocument
    update_model = LocalCredentialUpdate
    uses_object_id = True
    cache_policy = None

    async def get_by_user_id(self, user_id: str) -> LocalCredentialDocument | None:
        """The credential for one user, or ``None`` when they authenticate some
        other way."""
        return await self._find_one({"user_id": user_id})

    async def try_create(self, doc: LocalCredentialDocument) -> LocalCredentialDocument | None:
        """Atomically insert ``doc``, or return ``None`` if the single admin
        slot is already taken.

        The unique index on ``slot`` makes this deterministic server-side:
        concurrent inserts race on one key and Mongo admits exactly one —
        the loser gets ``DuplicateKeyError``, translated here to ``None`` so
        callers decide the rejection without touching pymongo. A plain
        count-then-insert cannot do this: two signups on a fresh instance both
        count zero and both become admin.
        """
        try:
            return await self._insert(doc, REPO_GLOBAL_SCOPE)
        except DuplicateKeyError:
            return None

    async def any_exists(self) -> bool:
        """Whether any local credential exists at all.

        Fast-path pre-check for the registration gate; the authoritative gate
        is :meth:`try_create`, which cannot lose the race."""
        return await self._count({}) > 0


local_credentials_repository = LocalCredentialsRepository()
