"""Self-host membership: the registration policy, invite links, and member removal."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Literal

from app.constants.auth import (
    INVITE_TOKEN_BYTES,
    INVITE_TTL_DAYS,
    REGISTRATION_SETTINGS_KEY,
    InstanceRole,
    RegistrationPolicy,
)
from app.constants.error_codes import CANNOT_REMOVE_ADMIN, INVITE_INVALID
from app.db.repositories.instance_settings import instance_settings_repository
from app.db.repositories.local_credentials import local_credentials_repository
from app.db.repositories.local_invites import local_invites_repository
from app.db.repositories.users import user_repository
from app.models.auth_models import LocalCredentialUpdate, LocalInviteDocument, LocalInviteUpdate
from app.models.member_models import (
    InviteCreatedResponse,
    InviteResponse,
    MemberResponse,
    MembersOverviewResponse,
    RegistrationSetting,
)
from app.services.analytics_service import capture
from app.services.member_offboarding import stop_acting_for_removed_member
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.auth import InstanceInviteCreated, InstanceMemberJoined


@dataclass(frozen=True, slots=True)
class MemberAdmission:
    """Why a member signup was let in; invite_id is the redeemed invite, if any."""

    via: Literal["invite", "open"]
    invite_id: str | None = None


def _hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _invite_response(invite: LocalInviteDocument) -> InviteResponse:
    return InviteResponse(id=invite.id, created_at=invite.created_at, expires_at=invite.expires_at)


async def get_registration_policy() -> RegistrationPolicy:
    """Return the stored policy; invite-only until an administrator opens signup."""
    stored = await instance_settings_repository.find_by_key(REGISTRATION_SETTINGS_KEY)
    if stored is None:
        return RegistrationPolicy.INVITE_ONLY
    return RegistrationSetting.model_validate(stored.value).policy


async def set_registration_policy(policy: RegistrationPolicy) -> RegistrationPolicy:
    """Persist the registration policy."""
    await instance_settings_repository.put(
        REGISTRATION_SETTINGS_KEY, RegistrationSetting(policy=policy).model_dump(mode="json")
    )
    return policy


async def create_invite(admin_user_id: str) -> InviteCreatedResponse:
    """Mint a single-use invite; the raw token is returned here and never stored."""
    token = secrets.token_urlsafe(INVITE_TOKEN_BYTES)
    invite = await local_invites_repository.create(
        LocalInviteDocument(
            token_hash=_hash_invite_token(token),
            created_by=admin_user_id,
            expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
        )
    )
    capture(UserId(admin_user_id), InstanceInviteCreated())
    return InviteCreatedResponse(invite=_invite_response(invite), token=token)


async def revoke_invite(invite_id: str) -> None:
    """Revoke a pending invite; 404 when it is unknown, used or already revoked."""
    if not await local_invites_repository.revoke(invite_id, datetime.now(UTC)):
        raise AppError(message="Invite not found", status_code=404)


async def admit_member(invite_token: str | None) -> MemberAdmission | None:
    """Decide whether a non-bootstrap signup may proceed; None means registration is closed.

    A presented invite is redeemed atomically here, so it is spent even if the
    account write that follows fails.
    """
    if invite_token is not None:
        invite = await local_invites_repository.redeem(
            _hash_invite_token(invite_token), datetime.now(UTC)
        )
        if invite is None:
            raise AppError(
                message="This invite link is invalid or has expired",
                status_code=403,
                code=INVITE_INVALID,
            )
        return MemberAdmission(via="invite", invite_id=invite.id)
    if await get_registration_policy() is RegistrationPolicy.OPEN:
        return MemberAdmission(via="open")
    return None


async def record_member_joined(admission: MemberAdmission, user_id: str) -> None:
    """Attribute a redeemed invite to the account it created and emit the join event."""
    if admission.invite_id is not None:
        await local_invites_repository.update(
            admission.invite_id, LocalInviteUpdate(used_by=user_id)
        )
    capture(UserId(user_id), InstanceMemberJoined(via=admission.via))


async def list_overview() -> MembersOverviewResponse:
    """Return active accounts oldest first, pending invites, and the registration policy."""
    credentials = [
        c for c in await local_credentials_repository.list_all() if c.disabled_at is None
    ]
    users = {u.id: u for u in await user_repository.find_by_ids([c.user_id for c in credentials])}
    members: list[MemberResponse] = []
    for credential in credentials:
        user = users.get(credential.user_id)
        if user is None:
            continue
        if user.role is None:
            raise AppError(
                message="A local account has no role",
                why="every local signup stores a role and boot backfills the first admin",
                fix="restart the API so the role backfill runs, then inspect the users row",
                meta={"user_id": user.id},
            )
        members.append(
            MemberResponse(
                user_id=user.id,
                email=user.email,
                name=user.name,
                role=user.role,
                created_at=user.created_at,
            )
        )
    invites = await local_invites_repository.list_pending(datetime.now(UTC))
    return MembersOverviewResponse(
        members=members,
        invites=[_invite_response(invite) for invite in invites],
        registration_policy=await get_registration_policy(),
    )


async def remove_member(user_id: str) -> None:
    """Disable a member's login and stop everything that runs for them; their data stays untouched.

    Idempotent: removing an already removed member re-runs the stop, finishing
    whatever a failed removal left. Administrators cannot be removed.
    """
    credential = await local_credentials_repository.get_by_user_id(user_id)
    if credential is None:
        raise AppError(message="Member not found", status_code=404)
    user = await user_repository.get(user_id)
    if user is not None and user.role is InstanceRole.ADMIN:
        raise AppError(
            message="An administrator cannot be removed",
            status_code=409,
            code=CANNOT_REMOVE_ADMIN,
        )
    if credential.disabled_at is None:
        await local_credentials_repository.update(
            credential.id, LocalCredentialUpdate(disabled_at=datetime.now(UTC))
        )
    await stop_acting_for_removed_member(user_id)
