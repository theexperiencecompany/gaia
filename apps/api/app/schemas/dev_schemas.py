"""Request/response schemas for the dev-only identity + seeding endpoints."""

from pydantic import BaseModel, Field


class CreateDevUserRequest(BaseModel):
    """Mint (find-or-create) a dev user by email."""

    email: str = Field(min_length=3, max_length=320, description="User email (unique key)")
    name: str | None = Field(default=None, max_length=200, description="Display name")


class DevUserResponse(BaseModel):
    """Stable identity of the minted user (never the raw Mongo doc — internal
    fields like datetimes are not part of this contract)."""

    id: str
    email: str
    name: str | None = None


class SeedDevDataRequest(BaseModel):
    """Seed deterministic sample data for an existing dev user."""

    email: str = Field(min_length=3, max_length=320)
    todos: int = Field(default=0, ge=0, le=100)
    conversations: int = Field(default=0, ge=0, le=100)
    platform_links: list[str] = Field(
        default_factory=list,
        description="Platforms to link (discord, slack, telegram, whatsapp)",
    )


class SeedDevDataResponse(BaseModel):
    """Summary of what the seed run created."""

    email: str
    user_id: str
    todos_created: int
    conversations_created: int
    platforms_linked: list[str]


class DeleteDevUserResponse(BaseModel):
    """Summary of the user + owned data removed during teardown."""

    email: str
    user_id: str
    deleted: dict[str, int]
