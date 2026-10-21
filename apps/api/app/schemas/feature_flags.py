"""Request and response schemas for the user-facing feature flag endpoints."""

from pydantic import BaseModel, Field

from app.config.feature_flags import FeatureStage
from app.schemas.common import ResponseModel


class UserFeatureFlagResponse(ResponseModel):
    """One flag the user may toggle, with the value currently in effect for them."""

    key: str = Field(description="Flag key, the {flag} path parameter of the PATCH route")
    label: str = Field(description="Short name shown next to the toggle")
    description: str = Field(description="One or two sentences on what turning it on changes")
    stage: FeatureStage = Field(description="How finished the feature is")
    enabled: bool = Field(
        description=(
            "In effect for the caller: off while killed, else their own choice, "
            "else the rollout, else the default"
        )
    )
    available: bool = Field(
        description="False while ops have the feature killed for everyone; the switch is locked"
    )
    unavailable_reason: str | None = Field(
        default=None, description="Why the switch is locked, shown beside it; null when available"
    )


class UserFeatureFlagListResponse(ResponseModel):
    features: list[UserFeatureFlagResponse] = Field(
        description="Every user-facing flag, in registry order"
    )


class UpdateUserFeatureFlagRequest(BaseModel):
    enabled: bool = Field(description="The caller's choice; it overrides the rollout for them")
