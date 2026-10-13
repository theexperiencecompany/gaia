"""Request and response models for self-host member administration (/api/v1/members)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants.auth import InstanceRole, RegistrationPolicy
from app.schemas.common import ResponseModel


class RegistrationSetting(BaseModel):
    """The registration policy as stored under instance_settings key registration."""

    policy: RegistrationPolicy = RegistrationPolicy.INVITE_ONLY


class MemberResponse(ResponseModel):
    """One active account on the instance."""

    user_id: str
    email: str | None
    name: str | None
    role: InstanceRole
    created_at: datetime | None


class InviteResponse(ResponseModel):
    """A pending invite link; the token itself is only ever returned at creation."""

    id: str
    created_at: datetime | None
    expires_at: datetime


class InviteCreatedResponse(ResponseModel):
    """A new invite and its one-time token, which the web turns into /signup?invite=<token>."""

    invite: InviteResponse
    token: str


class MembersOverviewResponse(ResponseModel):
    """Everything the admin Members settings page shows."""

    members: list[MemberResponse]
    invites: list[InviteResponse]
    registration_policy: RegistrationPolicy


class RegistrationPolicyRequest(BaseModel):
    """Body of PUT /api/v1/members/registration."""

    model_config = ConfigDict(extra="forbid")

    policy: RegistrationPolicy = Field(..., description="Who may create an account")


class RegistrationPolicyResponse(ResponseModel):
    """The registration policy now in force."""

    policy: RegistrationPolicy
