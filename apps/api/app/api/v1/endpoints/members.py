"""Self-host member administration: invites, registration policy, and member removal.

Mounted at /members for local auth only; every route requires the instance
administrator.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.models.member_models import (
    InviteCreatedResponse,
    MembersOverviewResponse,
    RegistrationPolicyRequest,
    RegistrationPolicyResponse,
)
from app.models.user_models import AuthenticatedUser
from app.services.members_service import (
    create_invite,
    list_overview,
    remove_member,
    revoke_invite,
    set_registration_policy,
)
from shared.py.wide_events import log

router = APIRouter(tags=["Members"])

Admin = Annotated[AuthenticatedUser, Depends(require_instance_admin)]


@router.get("")
async def get_members(admin: Admin) -> MembersOverviewResponse:
    """List accounts, pending invites, and the registration policy."""
    log.set(user={"id": admin.user_id}, operation="members_list")
    overview = await list_overview()
    log.set(member_count=len(overview.members), invite_count=len(overview.invites))
    return overview


@router.post("/invites", status_code=201)
async def post_invite(admin: Admin) -> InviteCreatedResponse:
    """Create a single-use invite link that expires in seven days."""
    log.set(user={"id": admin.user_id}, operation="members_create_invite")
    created = await create_invite(admin.user_id)
    log.set(invite_id=created.invite.id)
    log.audit("invite created", actor=admin.user_id, invite_id=created.invite.id)
    return created


@router.delete("/invites/{invite_id}", status_code=204)
async def delete_invite(invite_id: str, admin: Admin) -> None:
    """Revoke a pending invite link."""
    log.set(user={"id": admin.user_id}, operation="members_revoke_invite", invite_id=invite_id)
    await revoke_invite(invite_id)
    log.audit("invite revoked", actor=admin.user_id, invite_id=invite_id)


@router.put("/registration")
async def put_registration(
    body: RegistrationPolicyRequest, admin: Admin
) -> RegistrationPolicyResponse:
    """Choose whether anyone can sign up or only people with an invite."""
    log.set(user={"id": admin.user_id}, operation="members_set_registration", policy=body.policy)
    policy = await set_registration_policy(body.policy)
    log.audit("registration policy changed", actor=admin.user_id, policy=policy)
    return RegistrationPolicyResponse(policy=policy)


@router.delete("/{user_id}", status_code=204)
async def delete_member(user_id: str, admin: Admin) -> None:
    """Remove a member: their login stops, and their workflows, reminders and bot links stop too."""
    log.set(user={"id": admin.user_id}, operation="members_remove", target_user_id=user_id)
    await remove_member(user_id)
    log.audit("member removed", actor=admin.user_id, target_user_id=user_id)
