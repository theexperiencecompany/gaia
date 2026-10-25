"""Schemas for reporting a message a user should have received and did not."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource
from app.constants.delivery_alerts import DeliveryFailureKind
from app.schemas.common import ResponseModel


class DeliveryFailureReport(BaseModel):
    """A bot's report of a message it could not deliver."""

    platform: ConversationSource
    kind: DeliveryFailureKind
    reason: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        max_length=64,
        description="Closed snake_case failure code, e.g. destination_blocked or platform_error.",
    )
    error_code: str | None = Field(
        default=None, max_length=64, description="The platform's own error code, e.g. 130497."
    )
    error_message: str | None = Field(
        default=None, max_length=500, description="The platform's description of the error."
    )
    destination_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Platform-native recipient (a user id, or a channel id when is_channel); "
        "absent when the lost message could not be read.",
    )
    is_channel: bool = False
    country: str | None = Field(
        default=None, pattern=r"^[A-Z]{2}$", description="Recipient country, ISO 3166-1 alpha-2."
    )
    envelope_id: str | None = Field(default=None, max_length=128)
    platform_message_id: str | None = Field(default=None, max_length=256)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _bot_platform_only(self) -> Self:
        if self.platform not in BOT_CONVERSATION_SOURCES:
            raise ValueError(f"{self.platform.value} is not a messaging-platform bot")
        return self


class DeliveryFailure(DeliveryFailureReport):
    """One lost message, from any reporter; what the alerting job records."""

    user_id: str | None = None
    reporter: str = Field(min_length=1, max_length=64)


class DeliveryFailureAccepted(ResponseModel):
    """The report was queued for alerting."""

    status: Literal["queued"] = "queued"
