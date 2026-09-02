"""Account-center workspace projections — one model per ``account/**.json`` file.

These are read-only views over Mongo/Postgres truth, materialized onto JuiceFS
by :mod:`app.services.account_fs`. Deliberately curated (not raw document
dumps): provider ids and internal bookkeeping never reach the agent's workspace.
"""

from pydantic import BaseModel, Field

from app.schemas.usage import BudgetWindow, FeatureUsageSummary


class SubscriptionProjection(BaseModel):
    """``account/subscription.json`` — what the user's plan looks like right now."""

    plan_type: str = Field(description="'free' or 'pro'")
    plan_name: str | None = Field(default=None, description="Plan display name; null on free")
    price: str | None = Field(
        default=None, description="Formatted recurring price, e.g. '$15.00 / month'"
    )
    status: str | None = Field(default=None, description="Provider subscription status")
    cancel_scheduled: bool = Field(
        default=False, description="True when the subscription ends at the next billing date"
    )


class UsageProjection(BaseModel):
    """``account/usage.json`` — allowance consumption as percentages, never USD."""

    plan_type: str
    daily: BudgetWindow
    monthly: BudgetWindow | None = None
    per_request_token_ceiling: int
    features: dict[str, FeatureUsageSummary] = Field(default_factory=dict)


class NotificationsProjection(BaseModel):
    """``account/notifications.json`` — per-channel enabled flags."""

    channels: dict[str, bool] = Field(default_factory=dict)


class PreferencesProjection(BaseModel):
    """``account/preferences.json`` — response style + home timezone."""

    response_style: str | None = None
    timezone: str | None = None


class CustomInstructionsProjection(BaseModel):
    """``account/custom-instructions.json`` — standing instructions, null when unset."""

    instructions: str | None = None


class VoiceCatalogEntry(BaseModel):
    voice_id: str
    name: str
    starred: bool = False


class VoiceCatalogProjection(BaseModel):
    """``account/voices/catalog.json`` — selectable voices."""

    voices: list[VoiceCatalogEntry] = Field(default_factory=list)


class VoiceSelectedProjection(BaseModel):
    """``account/voices/selected.json`` — current TTS voice; nulls mean default."""

    voice_id: str | None = None
    name: str | None = None


class LinkedAccountProjection(BaseModel):
    """One ``account/linked-accounts/<platform>.json`` — link status only."""

    platform: str
    connected: bool = False
    connected_at: str | None = None
    username: str | None = None
    display_name: str | None = None


__all__ = [
    "CustomInstructionsProjection",
    "LinkedAccountProjection",
    "NotificationsProjection",
    "PreferencesProjection",
    "SubscriptionProjection",
    "UsageProjection",
    "VoiceCatalogEntry",
    "VoiceCatalogProjection",
    "VoiceSelectedProjection",
]
