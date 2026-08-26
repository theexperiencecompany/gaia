"""Instance-scoped runtime documents: instance settings and provider credentials.

Two small single-instance-per-deployment collections backing self-host runtime
configuration:

- ``instance_settings`` — a flat key/value store for instance-wide state (the
  generated instance secret under ``key="secrets"``, setup progress under
  ``key="setup"``). Keyed by the business ``key`` field, not ``_id``.
- ``provider_credentials`` — one row per user-configured provider, holding only
  the Fernet-encrypted JSON payload (see ``provider_credentials_service``);
  plaintext credentials never touch Mongo.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import MongoDocument


class InstanceSettingsDocument(MongoDocument):
    """One instance-wide setting in ``instance_settings``, keyed by ``key``."""

    model_config = ConfigDict(extra="ignore")

    key: str
    value: dict[str, object] = Field(default_factory=dict)


class InstanceSettingsUpdate(BaseModel):
    """Typed ``$set`` fields for an instance setting."""

    model_config = ConfigDict(extra="forbid")

    value: dict[str, object] | None = None


class ProviderCredentialDocument(MongoDocument):
    """A stored provider credential in ``provider_credentials``, keyed by
    ``provider``. Only ever holds ciphertext — the decrypted payload lives in
    memory (and the service's 60s cache) exclusively."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    data_encrypted: str
    updated_at: datetime | None = None


class ProviderCredentialUpdate(BaseModel):
    """Typed ``$set`` fields for a stored provider credential."""

    model_config = ConfigDict(extra="forbid")

    data_encrypted: str | None = None
