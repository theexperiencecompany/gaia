"""Repository for the auth_credentials collection: local-mode passwords.

Global, not user-scoped: a self-host instance has a single administrator, and
the signup gate (does any credential exist) is a whole-collection question.
Identity fields are write-once; only the bcrypt hash rotates, in place, never
by delete-and-recreate. Registration is an atomic claim, never
check-then-create: every credential carries the constant slot=admin
discriminator and a unique index on it admits at most one document, even when
concurrent requests both read an empty collection.
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
        """Return the credential for one user, or None when they authenticate some other way."""
        return await self._find_one({"user_id": user_id})

    async def try_create(self, doc: LocalCredentialDocument) -> LocalCredentialDocument | None:
        """Atomically insert doc, or return None if the single admin slot is taken.

        The unique index on slot admits exactly one of concurrent inserts; the
        loser gets DuplicateKeyError, translated here to None. A plain
        count-then-insert cannot do this: two signups both count zero and both
        become admin.
        """
        try:
            return await self._insert(doc, REPO_GLOBAL_SCOPE)
        except DuplicateKeyError:
            return None

    async def any_exists(self) -> bool:
        """Whether any local credential exists at all.

        Fast-path pre-check for the registration gate; the authoritative gate
        is try_create, which cannot lose the race.
        """
        return await self._count({}) > 0


local_credentials_repository = LocalCredentialsRepository()
