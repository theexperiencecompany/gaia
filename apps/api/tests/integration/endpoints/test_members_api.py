"""Integration tests for the self-host /members router.

The real router, admin dependency and members service run; only the four
repositories they read and write, and the analytics capture, are in-memory.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import hashlib
from unittest.mock import AsyncMock, MagicMock

from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints.members import router as members_router
from app.config.settings import settings
from app.constants.auth import REGISTRATION_SETTINGS_KEY, InstanceRole
from app.core.exception_handlers import register_exception_handlers
from app.models.auth_models import (
    ADMIN_CREDENTIAL_SLOT,
    LocalCredentialDocument,
    LocalCredentialUpdate,
    LocalInviteDocument,
)
from app.models.runtime_models import InstanceSettingsDocument
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services import member_offboarding, members_service
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.auth import InstanceInviteCreated
from tests.helpers import captured_wide_event

API = "/api/v1/members"


class Instance:
    """The users, credentials, invites and settings of one self-host instance."""

    def __init__(self) -> None:
        self.users: dict[str, UserDocument] = {}
        self.credentials: dict[str, LocalCredentialDocument] = {}
        self.invites: dict[str, LocalInviteDocument] = {}
        self.settings: dict[str, dict[str, object]] = {}

    def add_account(self, email: str, role: InstanceRole) -> UserDocument:
        user = UserDocument.model_validate(
            {
                "id": str(ObjectId()),
                "email": email,
                "name": email.split("@")[0],
                "role": role,
                "created_at": datetime.now(UTC),
            }
        )
        self.users[user.id] = user
        self.credentials[user.id] = LocalCredentialDocument(
            id=str(ObjectId()),
            user_id=user.id,
            password_hash="bcrypt-hash",
            slot=ADMIN_CREDENTIAL_SLOT if role is InstanceRole.ADMIN else None,
            created_at=datetime.now(UTC),
        )
        return user

    # local_credentials_repository
    async def list_all(self) -> list[LocalCredentialDocument]:
        return list(self.credentials.values())

    async def get_by_user_id(self, user_id: str) -> LocalCredentialDocument | None:
        return self.credentials.get(user_id)

    async def update_credential(
        self, doc_id: str, update: LocalCredentialUpdate
    ) -> LocalCredentialDocument | None:
        for user_id, credential in self.credentials.items():
            if credential.id == doc_id:
                self.credentials[user_id] = credential.model_copy(
                    update=update.model_dump(exclude_unset=True)
                )
                return self.credentials[user_id]
        return None

    # local_invites_repository
    async def create_invite(self, doc: LocalInviteDocument) -> LocalInviteDocument:
        stored = doc.model_copy(update={"id": str(ObjectId()), "created_at": datetime.now(UTC)})
        self.invites[stored.id] = stored
        return stored

    async def list_pending(self, now: datetime) -> list[LocalInviteDocument]:
        return [
            i
            for i in self.invites.values()
            if i.used_at is None and i.revoked_at is None and i.expires_at > now
        ]

    async def find_redeemable(self, token_hash: str, now: datetime) -> LocalInviteDocument | None:
        return next(
            (
                i
                for i in self.invites.values()
                if i.token_hash == token_hash
                and i.used_at is None
                and i.revoked_at is None
                and i.expires_at > now
            ),
            None,
        )

    async def revoke(self, invite_id: str, now: datetime) -> bool:
        invite = self.invites.get(invite_id)
        if invite is None or invite.used_at is not None or invite.revoked_at is not None:
            return False
        self.invites[invite_id] = invite.model_copy(update={"revoked_at": now})
        return True

    # instance_settings_repository
    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        value = self.settings.get(key)
        return None if value is None else InstanceSettingsDocument(key=key, value=value)

    async def put(self, key: str, value: dict[str, object]) -> InstanceSettingsDocument:
        self.settings[key] = value
        return InstanceSettingsDocument(key=key, value=value)

    # user_repository
    async def find_by_ids(self, user_ids: list[str]) -> list[UserDocument]:
        return [self.users[i] for i in user_ids if i in self.users]

    async def get_user(self, user_id: str) -> UserDocument | None:
        return self.users.get(user_id)


@pytest.fixture
def instance(monkeypatch: pytest.MonkeyPatch) -> Instance:
    store = Instance()
    creds = members_service.local_credentials_repository
    invites = members_service.local_invites_repository
    settings_repo = members_service.instance_settings_repository
    users = members_service.user_repository
    monkeypatch.setattr(creds, "list_all", store.list_all)
    monkeypatch.setattr(creds, "get_by_user_id", store.get_by_user_id)
    monkeypatch.setattr(creds, "update", store.update_credential)
    monkeypatch.setattr(invites, "create", store.create_invite)
    monkeypatch.setattr(invites, "list_pending", store.list_pending)
    monkeypatch.setattr(invites, "revoke", store.revoke)
    monkeypatch.setattr(invites, "find_redeemable", store.find_redeemable)
    monkeypatch.setattr(settings_repo, "find_by_key", store.find_by_key)
    monkeypatch.setattr(settings_repo, "put", store.put)
    monkeypatch.setattr(users, "find_by_ids", store.find_by_ids)
    monkeypatch.setattr(users, "get", store.get_user)
    return store


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    capture = MagicMock()
    monkeypatch.setattr(members_service, "capture", capture)
    return capture


@pytest.fixture(autouse=True)
def offboarding(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    stop = AsyncMock()
    monkeypatch.setattr(members_service, "stop_acting_for_removed_member", stop)
    return stop


@pytest.fixture
def admin(instance: Instance) -> UserDocument:
    return instance.add_account("admin@gaia.dev", InstanceRole.ADMIN)


@pytest.fixture
def member(instance: Instance) -> UserDocument:
    return instance.add_account("kid@gaia.dev", InstanceRole.MEMBER)


def _client_as(user: UserDocument) -> AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(members_router, prefix=API, tags=["Members"])
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=user.id, role=user.role
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def admin_client(admin: UserDocument) -> AsyncIterator[AsyncClient]:
    async with _client_as(admin) as client:
        yield client


@pytest.mark.integration
class TestAdminOnly:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", ""),
            ("POST", "/invites"),
            ("DELETE", "/invites/x"),
            ("PUT", "/registration"),
            ("DELETE", "/someone"),
        ],
    )
    async def test_a_member_is_refused_every_route(
        self, method: str, path: str, member: UserDocument, instance: Instance
    ) -> None:
        async with _client_as(member) as client:
            resp = await client.request(method, f"{API}{path}", json={"policy": "open"})
        assert resp.status_code == 403
        assert instance.invites == {}
        assert instance.settings == {}

    async def test_hosted_auth_refuses_even_an_admin_role(
        self, admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        monkeypatch.setattr(settings, "ENV", "development")
        assert (await admin_client.get(API)).status_code == 403


@pytest.mark.integration
class TestOverview:
    async def test_lists_active_accounts_invites_and_policy(
        self, admin_client: AsyncClient, admin: UserDocument, member: UserDocument, instance
    ) -> None:
        removed = instance.add_account("gone@gaia.dev", InstanceRole.MEMBER)
        instance.credentials[removed.id] = instance.credentials[removed.id].model_copy(
            update={"disabled_at": datetime.now(UTC)}
        )

        body = (await admin_client.get(API)).json()

        assert body["members"] == [
            {
                "user_id": account.id,
                "email": account.email,
                "name": account.name,
                "role": account.role,
                "created_at": account.created_at.isoformat().replace("+00:00", "Z"),
            }
            for account in (admin, member)
        ]
        assert body["invites"] == []
        assert body["registration_policy"] == "invite_only"

    async def test_an_account_without_a_role_fails_loud(
        self, admin_client: AsyncClient, member: UserDocument, instance
    ) -> None:
        instance.users[member.id] = member.model_copy(update={"role": None})

        async with captured_wide_event() as event:
            resp = await admin_client.get(API)

        assert resp.status_code == 500
        assert [e["error"]["user_id"] for e in event["errors"]] == [member.id]
        body = resp.json()
        assert body["message"] == "A local account has no role"
        assert body["why"] == "every local signup stores a role and boot backfills the first admin"
        assert body["fix"] == (
            "restart the API so the role backfill runs, then inspect the users row"
        )

    async def test_a_credential_without_an_account_row_is_skipped_not_fatal(
        self, admin_client: AsyncClient, admin: UserDocument, instance
    ) -> None:
        orphan = instance.add_account("orphan@gaia.dev", InstanceRole.MEMBER)
        del instance.users[orphan.id]
        instance.credentials = {
            orphan.id: instance.credentials[orphan.id],
            admin.id: instance.credentials[admin.id],
        }

        body = (await admin_client.get(API)).json()

        assert [m["user_id"] for m in body["members"]] == [admin.id]

    async def test_listing_stamps_the_wide_event(
        self, admin_client: AsyncClient, admin: UserDocument, member: UserDocument
    ) -> None:
        async with captured_wide_event() as event:
            assert (await admin_client.get(API)).status_code == 200

        assert event["user"] == {"id": admin.id}
        assert event["operation"] == "members_list"
        assert event["member_count"] == 2
        assert event["invite_count"] == 0


@pytest.mark.integration
class TestInvites:
    async def test_create_returns_a_token_whose_digest_is_stored(
        self, admin_client: AsyncClient, admin: UserDocument, instance, captured
    ) -> None:
        resp = await admin_client.post(f"{API}/invites")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        (stored,) = instance.invites.values()
        assert stored.token_hash == hashlib.sha256(body["token"].encode()).hexdigest()
        assert body["token"] not in stored.model_dump_json()
        assert stored.created_by == admin.id
        lifetime = stored.expires_at - datetime.now(UTC)
        assert timedelta(days=6, hours=23) < lifetime <= timedelta(days=7)
        captured.assert_called_once_with(UserId(admin.id), InstanceInviteCreated())
        listed = (await admin_client.get(API)).json()["invites"]
        assert [i["id"] for i in listed] == [body["invite"]["id"]]
        assert listed[0]["created_at"] == body["invite"]["created_at"]
        assert body["invite"]["created_at"] is not None

    async def test_creating_an_invite_is_audited(
        self, admin_client: AsyncClient, admin: UserDocument, instance, captured
    ) -> None:
        async with captured_wide_event() as event:
            invite_id = (await admin_client.post(f"{API}/invites")).json()["invite"]["id"]

        assert event["user"] == {"id": admin.id}
        assert event["operation"] == "members_create_invite"
        assert event["invite_id"] == invite_id
        assert event["audit"] == [
            {"msg": "invite created", "actor": admin.id, "invite_id": invite_id}
        ]

    async def test_revoke_removes_the_invite_once(
        self, admin_client: AsyncClient, instance, captured
    ) -> None:
        invite_id = (await admin_client.post(f"{API}/invites")).json()["invite"]["id"]

        first = await admin_client.delete(f"{API}/invites/{invite_id}")
        second = await admin_client.delete(f"{API}/invites/{invite_id}")

        assert first.status_code == 204
        assert second.status_code == 404
        assert second.json()["message"] == "Invite not found"
        assert instance.invites[invite_id].revoked_at.utcoffset() == timedelta(0)
        assert (await admin_client.get(API)).json()["invites"] == []

    async def test_revoking_an_invite_is_audited(
        self, admin_client: AsyncClient, admin: UserDocument, instance, captured
    ) -> None:
        invite_id = (await admin_client.post(f"{API}/invites")).json()["invite"]["id"]

        async with captured_wide_event() as event:
            assert (await admin_client.delete(f"{API}/invites/{invite_id}")).status_code == 204

        assert event["user"] == {"id": admin.id}
        assert event["operation"] == "members_revoke_invite"
        assert event["invite_id"] == invite_id
        assert event["audit"] == [
            {"msg": "invite revoked", "actor": admin.id, "invite_id": invite_id}
        ]

    async def test_a_revoked_invite_is_refused_at_signup(
        self, admin_client: AsyncClient, instance, captured
    ) -> None:
        token = (await admin_client.post(f"{API}/invites")).json()["token"]
        await members_service.ensure_invite_redeemable(token)
        (invite_id,) = instance.invites
        await admin_client.delete(f"{API}/invites/{invite_id}")

        with pytest.raises(AppError) as refused:
            await members_service.ensure_invite_redeemable(token)

        assert refused.value.status_code == 403
        assert refused.value.message == "This invite link was already used or has expired"


@pytest.mark.integration
class TestRegistrationPolicy:
    async def test_admin_opens_and_closes_signup(self, admin_client: AsyncClient, instance) -> None:
        opened = await admin_client.put(f"{API}/registration", json={"policy": "open"})
        assert opened.json() == {"policy": "open"}
        assert instance.settings[REGISTRATION_SETTINGS_KEY] == {"policy": "open"}
        assert (await admin_client.get(API)).json()["registration_policy"] == "open"

        closed = await admin_client.put(f"{API}/registration", json={"policy": "invite_only"})
        assert closed.json() == {"policy": "invite_only"}

    async def test_changing_the_policy_is_audited(
        self, admin_client: AsyncClient, admin: UserDocument, instance
    ) -> None:
        async with captured_wide_event() as event:
            await admin_client.put(f"{API}/registration", json={"policy": "open"})

        assert event["user"] == {"id": admin.id}
        assert event["operation"] == "members_set_registration"
        assert event["policy"] == "open"
        assert event["audit"] == [
            {"msg": "registration policy changed", "actor": admin.id, "policy": "open"}
        ]

    async def test_unknown_policy_is_422(self, admin_client: AsyncClient, instance) -> None:
        resp = await admin_client.put(f"{API}/registration", json={"policy": "everyone"})
        assert resp.status_code == 422
        assert instance.settings == {}


@pytest.mark.integration
class TestRemoveMember:
    async def test_removal_disables_the_login_and_keeps_the_account_row(
        self, admin_client: AsyncClient, member: UserDocument, instance
    ) -> None:
        resp = await admin_client.delete(f"{API}/{member.id}")

        assert resp.status_code == 204
        assert instance.credentials[member.id].disabled_at.utcoffset() == timedelta(0)
        assert member.id in instance.users
        listed = (await admin_client.get(API)).json()["members"]
        assert member.id not in [m["user_id"] for m in listed]

    async def test_admin_cannot_remove_themselves(
        self, admin_client: AsyncClient, admin: UserDocument, instance
    ) -> None:
        resp = await admin_client.delete(f"{API}/{admin.id}")

        assert resp.status_code == 409
        assert resp.json()["code"] == "cannot_remove_admin"
        assert resp.json()["message"] == "An administrator cannot be removed"
        assert instance.credentials[admin.id].disabled_at is None

    async def test_removal_stops_everything_running_for_the_member(
        self, admin_client: AsyncClient, member: UserDocument, offboarding: AsyncMock
    ) -> None:
        assert (await admin_client.delete(f"{API}/{member.id}")).status_code == 204

        offboarding.assert_awaited_once_with(member.id)

    async def test_removing_again_succeeds_and_finishes_what_a_failed_removal_left(
        self, admin_client: AsyncClient, member: UserDocument, offboarding: AsyncMock, instance
    ) -> None:
        offboarding.side_effect = [RuntimeError("telegram unreachable"), None]
        with pytest.raises(RuntimeError):
            await admin_client.delete(f"{API}/{member.id}")
        disabled_at = instance.credentials[member.id].disabled_at
        assert disabled_at is not None

        assert (await admin_client.delete(f"{API}/{member.id}")).status_code == 204
        assert offboarding.await_count == 2
        assert instance.credentials[member.id].disabled_at == disabled_at

    async def test_a_removal_that_could_not_stop_everything_is_a_503_naming_what_still_runs(
        self,
        admin_client: AsyncClient,
        member: UserDocument,
        offboarding: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workflow = MagicMock(id="wf-1")
        for name, found in (
            ("workflow_repository.find_activated_for_user", [workflow]),
            ("reminder_repository.find_scheduled_for_user", []),
            ("todo_repository.find_running_tracked_for_user", []),
            ("PlatformLinkService.get_linked_platforms", {}),
        ):
            owner, attr = name.split(".")
            monkeypatch.setattr(
                getattr(member_offboarding, owner), attr, AsyncMock(return_value=found)
            )
        monkeypatch.setattr(
            member_offboarding.WorkflowService,
            "deactivate_workflow",
            AsyncMock(side_effect=RuntimeError("composio down")),
        )
        offboarding.side_effect = member_offboarding.stop_acting_for_removed_member

        resp = await admin_client.delete(f"{API}/{member.id}")

        assert resp.status_code == 503
        body = resp.json()
        assert body["code"] == "member_offboarding_incomplete"
        assert "workflow:wf-1" in body["why"]
        assert "again" in body["fix"]

    async def test_an_unknown_member_is_404(
        self, admin_client: AsyncClient, offboarding: AsyncMock
    ) -> None:
        resp = await admin_client.delete(f"{API}/{ObjectId()}")

        assert resp.status_code == 404
        assert resp.json()["message"] == "Member not found"
        offboarding.assert_not_awaited()

    async def test_removing_a_member_is_audited(
        self, admin_client: AsyncClient, admin: UserDocument, member: UserDocument
    ) -> None:
        async with captured_wide_event() as event:
            assert (await admin_client.delete(f"{API}/{member.id}")).status_code == 204

        assert event["user"] == {"id": admin.id}
        assert event["operation"] == "members_remove"
        assert event["target_user_id"] == member.id
        assert event["audit"] == [
            {"msg": "member removed", "actor": admin.id, "target_user_id": member.id}
        ]
