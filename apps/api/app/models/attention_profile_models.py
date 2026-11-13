"""The attention profile: a user's short answers about what is worth telling them, read by the Judge."""

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class ProfileAnswer(BaseModel):
    """One preference: a question GAIA asked or could ask, and what the user answered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    q: str = Field(min_length=1)
    a: str = Field(min_length=1)


class AttentionProfileDocument(UserScopedDocument):
    """A user's profile, versioned so a later edit is visible to whoever reads it."""

    version: int = 1
    answers: list[ProfileAnswer]


class AttentionProfileUpdate(BaseModel):
    """Typed $set fields of a profile."""

    model_config = ConfigDict(extra="forbid")

    answers: list[ProfileAnswer] | None = None
    version: int | None = None
