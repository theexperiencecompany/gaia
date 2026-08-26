"""Repository for the ``provider_credentials`` collection — encrypted provider configs.

One document per user-configured provider, holding only the Fernet ciphertext
of the JSON payload (encryption lives in ``provider_credentials_service``).
Keyed by the business ``provider`` field; writes are upserts. No cache: the
service layer owns the short-TTL decrypted-payload cache, and the raw row is
only read on its miss path.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.base import MongoRepository
from app.models.runtime_models import ProviderCredentialDocument, ProviderCredentialUpdate


class ProviderCredentialsRepository(
    MongoRepository[ProviderCredentialDocument, ProviderCredentialUpdate]
):
    collection_name = "provider_credentials"
    document_model = ProviderCredentialDocument
    update_model = ProviderCredentialUpdate
    uses_object_id = False
    identity_field = "provider"
    cache_policy = None

    async def find_by_provider(self, provider: str) -> ProviderCredentialDocument | None:
        """The stored credential for ``provider``, or ``None`` when unconfigured."""
        return await self._find_one({"provider": provider})

    async def exists(self, provider: str) -> bool:
        """Whether any stored credential row exists for ``provider``."""
        collection = get_async_collection(self.collection_name)
        return await collection.count_documents({"provider": provider}, limit=1) > 0

    async def upsert_encrypted(self, provider: str, data_encrypted: str) -> None:
        """Insert or replace the ciphertext for ``provider`` in one round trip."""
        await self._apply_raw_update_unfetched(
            {"provider": provider},
            {"$set": {"data_encrypted": data_encrypted}},
            scope=REPO_GLOBAL_SCOPE,
            upsert=True,
        )


provider_credentials_repository = ProviderCredentialsRepository()
