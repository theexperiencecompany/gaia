"""Repository for the provider_credentials collection: encrypted provider configs.

One document per user-configured provider, holding only the Fernet ciphertext
of the JSON payload (encryption lives in provider_credentials_service).
Keyed by the business provider field and written as upserts. No cache: the
service layer owns the short-TTL decrypted-payload cache, and the raw row is
only read on its miss path.
"""

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
        """Return the stored credential for provider, or None when unconfigured."""
        return await self._find_one({"provider": provider})

    async def exists(self, provider: str) -> bool:
        """Whether any stored credential row exists for provider."""
        return await self._count({"provider": provider}) > 0

    async def upsert_encrypted(self, provider: str, data_encrypted: str) -> None:
        """Insert or replace the ciphertext for provider in one round trip."""
        await self.upsert(provider, ProviderCredentialUpdate(data_encrypted=data_encrypted))


provider_credentials_repository = ProviderCredentialsRepository()
