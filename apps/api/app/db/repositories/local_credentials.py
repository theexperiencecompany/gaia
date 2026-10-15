"""Repository for the auth_credentials collection: local-mode passwords.

Global, not user-scoped: the bootstrap gate (does the administrator exist) is a
whole-collection question. Identity fields are write-once; only the bcrypt hash
rotates, in place, never by delete-and-recreate. The first account is an
atomic claim, never check-then-create: its row carries slot=admin and a partial
unique index on slot admits at most one such row, even when concurrent
requests both read an empty collection. Member rows carry no slot.
"""

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.auth_models import (
    ADMIN_CREDENTIAL_SLOT,
    LocalCredentialDocument,
    LocalCredentialUpdate,
)


class LocalCredentialsRepository(MongoRepository[LocalCredentialDocument, LocalCredentialUpdate]):
    collection_name = "auth_credentials"
    document_model = LocalCredentialDocument
    update_model = LocalCredentialUpdate
    uses_object_id = True
    cache_policy = None

    async def get_by_user_id(self, user_id: str) -> LocalCredentialDocument | None:
        """Return the credential for one user, or None when they authenticate some other way."""
        return await self._find_one({"user_id": user_id})

    async def get_admin(self) -> LocalCredentialDocument | None:
        """Return the bootstrap administrator's credential, or None before first signup."""
        return await self._find_one({"slot": ADMIN_CREDENTIAL_SLOT})

    async def list_all(self) -> list[LocalCredentialDocument]:
        """Every local account, oldest first."""
        return await self._find({}, sort=[("created_at", 1)])

    async def try_create(self, doc: LocalCredentialDocument) -> LocalCredentialDocument | None:
        """Atomically insert the slot=admin doc, or return None if the admin slot is taken.

        The unique index on slot admits exactly one of concurrent inserts; the
        loser's DuplicateKeyError becomes None.
        """
        try:
            return await self._insert(
                doc,
                REPO_GLOBAL_SCOPE,  # pragma: no mutate — a cacheless global repo never reads its scope
            )
        except DuplicateKeyError:
            return None

    async def admin_exists(self) -> bool:
        """Fast-path pre-check for the bootstrap gate; try_create is the authoritative one."""
        return await self._count({"slot": ADMIN_CREDENTIAL_SLOT}) > 0


local_credentials_repository = LocalCredentialsRepository()
