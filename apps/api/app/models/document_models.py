"""Base models of every stored document; a leaf, so any model can extend them without the db layer."""

from pydantic import BaseModel, ConfigDict


class MongoDocument(BaseModel):
    """Base for every repository document model — carries the string id.

    ``extra="ignore"`` so a legacy document with stray fields still reads (the
    write side is fully controlled by the update model's ``extra="forbid"``).
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""


class UserScopedDocument(MongoDocument):
    """A document owned by a user — the base for user-scoped repositories."""

    user_id: str
