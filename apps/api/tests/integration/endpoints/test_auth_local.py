"""Integration tests for local-mode (self-host) authentication.

Covers the /api/v1/auth router (signup, login, logout), the session-token
utilities behind it, the AUTH_MODE local branch of WorkOSAuthMiddleware, and
the local branch of the WebSocket auth dependency.

Repositories and the instance-secret store are mocked at their seams; bcrypt,
the jose JWT encode and verify path, the middleware dispatch order, and the
cookie contract all run for real.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from http.cookies import Morsel, SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import bcrypt as bcrypt_lib
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
import httpx
from jose import jwt
import pytest

from app.config.settings import settings
from app.constants.auth import (
    AUDIT_ACTOR_UNAUTHENTICATED,
    JWT_ALGORITHM,
    REGISTRATION_SETTINGS_KEY,
    InstanceRole,
)
from app.constants.error_codes import INVALID_CREDENTIALS
from app.models.auth_models import (
    ADMIN_CREDENTIAL_SLOT,
    LocalCredentialDocument,
    LocalCredentialUpdate,
    LocalInviteDocument,
)
from app.models.runtime_models import InstanceSettingsDocument
from app.models.user_models import UserDocument
from app.utils.local_auth_utils import (
    SESSION_TTL_SECONDS,
    issue_session_token,
    resolve_session_token,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.auth import InstanceMemberJoined
from tests.helpers import captured_wide_event

TEST_SECRET = "test-instance-secret-" + "x" * 16
TEST_PASSWORD = "correct-horse-battery"

# bcrypt hashes at most 72 BYTES of input and refuses anything longer
# (bcrypt >= 5 raises ValueError instead of silently truncating).
PASSWORD_AT_BCRYPT_LIMIT = "a" * 72  # boundary: must keep working
PASSWORD_OVER_BCRYPT_LIMIT = "a" * 73  # one byte past: never 500
# 19 chars but 76 UTF-8 bytes — chars are not bytes; the byte-level cap must
# catch what a character-count limit cannot.
PASSWORD_MULTIBYTE_OVER_LIMIT = "🔐" * 19


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def _instance_secret(monkeypatch):
    """Wire local_auth_utils to a fixed instance secret.

    The cache starts warm, matching production after boot where the sync
    verify path requires the resolved secret; cold-start behavior is pinned
    by the TestSessionTokens tests below.
    """
    from app.utils import local_auth_utils

    monkeypatch.setattr(
        local_auth_utils, "get_instance_secret", AsyncMock(return_value=TEST_SECRET)
    )
    monkeypatch.setattr(local_auth_utils, "_resolved_secret", TEST_SECRET)


# A syntactically plausible bcrypt digest standing in for real hashing in the
# concurrency test — hash correctness is covered by the login tests, which run
# real bcrypt; here the point is interleaving, not crypto speed.
_FAKE_HASH = b"$2b$12$abcdefghijklmnopqrstuvABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class UserDirectory:
    """In-memory users collection: email → UserDocument."""

    def __init__(self) -> None:
        self.by_email: dict[str, UserDocument] = {}
        self.created: list[UserDocument] = []

    async def get_by_email(self, email: str) -> UserDocument | None:
        await asyncio.sleep(0)
        return self.by_email.get(email)

    async def get(self, user_id: str) -> UserDocument | None:
        await asyncio.sleep(0)
        return next((u for u in self.by_email.values() if u.id == user_id), None)

    async def create(self, doc: UserDocument) -> UserDocument:
        await asyncio.sleep(0)
        stored = doc.model_copy(update={"id": str(ObjectId())})
        # Mirror the real repository: base._insert stamps timestamps on the
        # persisted document, so consumers see created_at on the returned doc.
        now = datetime.now(UTC)
        if stored.created_at is None:
            stored = stored.model_copy(update={"created_at": now, "updated_at": now})
        self.created.append(stored)
        self.by_email[stored.email] = stored
        return stored

    async def delete(self, user_id: str) -> bool:
        await asyncio.sleep(0)
        user = next((u for u in self.by_email.values() if u.id == user_id), None)
        if user is None:
            return False
        del self.by_email[user.email]
        self.created = [u for u in self.created if u.id != user_id]
        return True


@pytest.fixture
def directory():
    return UserDirectory()


@pytest.fixture(autouse=True)
def _disable_slowapi_limiter():
    """Disable the process-global slowapi limiter for these tests.

    They build their own apps but share one bucket (keyed on 127.0.0.1), so
    cumulative signup calls would 429 each other mid-suite. Rate limiting has its
    own dedicated suite; here it only couples unrelated tests.
    """
    from app.api.v1.middleware.rate_limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def credential_store():
    """In-memory stand-in for the auth_credentials collection.

    Every operation yields to the event loop first, mirroring a real Mongo
    round trip so gathered concurrent signups interleave between gate check
    and write. try_create keeps the partial unique index's semantics: at most
    one slot=admin credential can ever land.
    """
    store: dict[str, LocalCredentialDocument] = {}

    def admin_slot_taken() -> bool:
        return any(c.slot == ADMIN_CREDENTIAL_SLOT for c in store.values())

    async def get_by_user_id(user_id: str) -> LocalCredentialDocument | None:
        await asyncio.sleep(0)
        return store.get(user_id)

    async def create(doc: LocalCredentialDocument) -> LocalCredentialDocument:
        await asyncio.sleep(0)
        stored = doc.model_copy(update={"id": str(ObjectId())})
        store[doc.user_id] = stored
        return stored

    async def try_create(doc: LocalCredentialDocument) -> LocalCredentialDocument | None:
        """Atomic insert: wins only when the admin slot is free."""
        await asyncio.sleep(0)
        if admin_slot_taken():
            return None
        store[doc.user_id] = doc
        return doc

    async def update(
        doc_id: str, update_model: LocalCredentialUpdate
    ) -> LocalCredentialDocument | None:
        """Typed set by id, mirroring MongoRepository.update semantics."""
        await asyncio.sleep(0)
        doc = next((c for c in store.values() if c.id == doc_id), None)
        if doc is None:
            return None
        updated = doc.model_copy(update=update_model.model_dump(exclude_unset=True))
        store[updated.user_id] = updated
        return updated

    async def admin_exists() -> bool:
        await asyncio.sleep(0)
        return admin_slot_taken()

    async def delete(doc_id: str) -> bool:
        await asyncio.sleep(0)
        doc = next((c for c in store.values() if c.id == doc_id), None)
        if doc is None:
            return False
        del store[doc.user_id]
        return True

    holder = MagicMock()
    holder.store = store
    holder.get_by_user_id = AsyncMock(side_effect=get_by_user_id)
    holder.create = AsyncMock(side_effect=create)
    holder.try_create = AsyncMock(side_effect=try_create)
    holder.update = AsyncMock(side_effect=update)
    holder.admin_exists = AsyncMock(side_effect=admin_exists)
    holder.delete = AsyncMock(side_effect=delete)
    return holder


class InviteStore:
    """In-memory auth_invites with the repository's redeem/revoke semantics."""

    def __init__(self) -> None:
        self.invites: dict[str, LocalInviteDocument] = {}

    def add(self, token: str, *, expires_in: timedelta = timedelta(days=7)) -> LocalInviteDocument:
        invite = LocalInviteDocument(
            id=str(ObjectId()),
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            created_by="admin",
            expires_at=datetime.now(UTC) + expires_in,
        )
        self.invites[invite.id] = invite
        return invite

    async def find_redeemable(self, token_hash: str, now: datetime) -> LocalInviteDocument | None:
        return next(
            (
                invite
                for invite in self.invites.values()
                if invite.token_hash == token_hash
                and invite.used_at is None
                and invite.revoked_at is None
                and invite.expires_at > now
            ),
            None,
        )

    async def redeem(
        self, token_hash: str, now: datetime, used_by: str
    ) -> LocalInviteDocument | None:
        await asyncio.sleep(0)
        invite = await self.find_redeemable(token_hash, now)
        if invite is None:
            return None
        self.invites[invite.id] = invite.model_copy(update={"used_at": now, "used_by": used_by})
        return self.invites[invite.id]


class SettingsStore:
    """In-memory instance_settings keyed by business key."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        value = self.values.get(key)
        return None if value is None else InstanceSettingsDocument(key=key, value=value)


@pytest.fixture
def invite_store(monkeypatch) -> InviteStore:
    from app.services import members_service

    store = InviteStore()
    monkeypatch.setattr(
        members_service.local_invites_repository, "find_redeemable", store.find_redeemable
    )
    monkeypatch.setattr(members_service.local_invites_repository, "redeem", store.redeem)
    return store


@pytest.fixture
def settings_store(monkeypatch) -> SettingsStore:
    from app.services import members_service

    store = SettingsStore()
    monkeypatch.setattr(
        members_service.instance_settings_repository, "find_by_key", store.find_by_key
    )
    return store


@pytest.fixture
def captured(monkeypatch) -> MagicMock:
    from app.services import members_service

    capture = MagicMock()
    monkeypatch.setattr(members_service, "capture", capture)
    return capture


@pytest.fixture
def patched_repos(directory, credential_store, monkeypatch):
    """Point every consumer (endpoints, middleware, ws dependency) at the in-memory stores.

    The shared setup-API conftest swaps the local_credentials module attribute
    at import time, so these tests re-bind the genuine singletons first and the
    real router code runs against controlled seams.
    """
    import app.api.v1.endpoints.auth_local as auth_local_module
    import app.db.repositories.local_credentials as creds_mod
    from app.db.repositories.users import user_repository as users_singleton
    from app.utils import local_auth_utils

    real_creds = creds_mod.LocalCredentialsRepository()
    monkeypatch.setattr(creds_mod, "local_credentials_repository", real_creds)
    if hasattr(auth_local_module, "local_credentials_repository"):
        monkeypatch.setattr(auth_local_module, "local_credentials_repository", real_creds)
    monkeypatch.setattr(local_auth_utils, "local_credentials_repository", real_creds)

    with (
        patch.object(
            users_singleton, "get_by_email", AsyncMock(side_effect=directory.get_by_email)
        ),
        patch.object(users_singleton, "get", AsyncMock(side_effect=directory.get)),
        patch.object(users_singleton, "create", AsyncMock(side_effect=directory.create)),
        patch.object(users_singleton, "delete", AsyncMock(side_effect=directory.delete)),
        patch.object(real_creds, "get_by_user_id", credential_store.get_by_user_id),
        patch.object(real_creds, "create", credential_store.create),
        patch.object(real_creds, "try_create", credential_store.try_create),
        patch.object(real_creds, "update", credential_store.update),
        patch.object(real_creds, "admin_exists", credential_store.admin_exists),
        patch.object(real_creds, "delete", credential_store.delete),
    ):
        yield directory


def seed_account(
    directory: UserDirectory, credential_store, email: str, role: InstanceRole
) -> UserDocument:
    """Insert an existing account (user + bcrypt credential) into both stores."""
    user = UserDocument.model_validate(
        {"id": str(ObjectId()), "email": email, "name": "Account", "role": role}
    )
    directory.by_email[email] = user
    credential_store.store[user.id] = LocalCredentialDocument(
        id=str(ObjectId()),
        user_id=user.id,
        password_hash=bcrypt_lib.hashpw(TEST_PASSWORD.encode(), bcrypt_lib.gensalt()).decode(),
        slot=ADMIN_CREDENTIAL_SLOT if role is InstanceRole.ADMIN else None,
    )
    return user


def seed_admin(directory: UserDirectory, credential_store, email: str) -> UserDocument:
    return seed_account(directory, credential_store, email, InstanceRole.ADMIN)


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _build_router_app() -> FastAPI:
    """Build an app carrying the real auth_local router, as routes.py mounts it.

    register_exception_handlers keeps every non-2xx body in the ErrorEnvelope
    shape clients see; a bare FastAPI app would answer with a default detail
    shape instead.
    """
    from app.api.v1.endpoints.auth_local import router as auth_router
    from app.core.exception_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
    return app


def _build_middleware_app() -> FastAPI:
    """Build an app carrying the real middleware in local mode plus the mounted router.

    The probe route reports what request.state carries after dispatch — the
    contract downstream handlers depend on.
    """
    from app.api.v1.endpoints.auth_local import router as auth_router
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware
    from app.core.exception_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/probe")
    async def probe(request: Request) -> JSONResponse:
        user = getattr(request.state, "user", None)
        if not getattr(request.state, "authenticated", False) or not user:
            return JSONResponse(status_code=401, content={"detail": "no user"})
        # request.state.user is the frozen AuthenticatedUser model (not a dict)
        # — see build_user_context.
        return JSONResponse(content={"email": user.email, "auth_provider": user.auth_provider})

    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
    app.add_middleware(WorkOSAuthMiddleware, workos_client=MagicMock())
    return app


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSignup:
    async def test_first_signup_creates_admin_and_sets_session_cookie(
        self, patched_repos, credential_store, _instance_secret
    ):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "admin@gaia.dev", "password": TEST_PASSWORD, "name": "Admin"},
            )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["user"]["email"] == "admin@gaia.dev"
        assert body["user"]["auth_provider"] == "email"
        # Regression: the payload must be JSON-safe — Mongo datetimes used to
        # blow up JSONResponse *after* the rows were committed, so the client
        # saw a 500 for a signup that had actually succeeded.
        assert "created_at" in body["user"], f"payload keys: {sorted(body['user'])}"
        assert isinstance(body["user"]["created_at"], str)

        created = patched_repos.created[0]
        assert created.email == "admin@gaia.dev"
        assert created.role is InstanceRole.ADMIN
        assert body["user"]["role"] == "admin"
        assert credential_store.store[created.id].slot == ADMIN_CREDENTIAL_SLOT

        assert await resolve_session_token(response.cookies["gaia_session"]) == created.id

    async def test_second_signup_is_403_registration_closed(
        self, patched_repos, credential_store, settings_store, _instance_secret
    ):
        """Invite-only is the default: no stored policy and no invite means closed."""
        seed_admin(patched_repos, credential_store, "admin@gaia.dev")

        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "second@gaia.dev", "password": TEST_PASSWORD},
            )

        assert response.status_code == 403
        assert response.json()["code"] == "registration_closed"
        assert patched_repos.created == []  # no second user was written

    async def test_short_password_rejected_before_any_write(
        self, patched_repos, credential_store, _instance_secret
    ):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "admin@gaia.dev", "password": "short"},
            )

        assert response.status_code == 422
        assert credential_store.store == {}
        assert patched_repos.created == []

    async def test_password_at_bcrypt_limit_is_accepted(self, patched_repos, _instance_secret):
        """Keep the 72-byte boundary working end to end; exactly 72 bytes is bcrypt cap."""
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "admin@gaia.dev", "password": PASSWORD_AT_BCRYPT_LIMIT},
            )

        assert response.status_code == 201, response.text

    async def test_password_over_bcrypt_limit_is_422_before_any_write(
        self, patched_repos, credential_store, _instance_secret
    ):
        """Reject over-72-byte passwords as 422 before any write; late hashing would orphan the row."""
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "admin@gaia.dev", "password": PASSWORD_OVER_BCRYPT_LIMIT},
            )

        assert response.status_code == 422, response.text
        # No orphan: neither the user row nor a credential may survive.
        assert patched_repos.created == []
        assert credential_store.store == {}

    async def test_multibyte_password_over_byte_limit_is_422_before_any_write(
        self, patched_repos, credential_store, _instance_secret
    ):
        """Count bytes, not characters, against bcrypt cap; 19 chars can be 76 UTF-8 bytes."""
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "admin@gaia.dev", "password": PASSWORD_MULTIBYTE_OVER_LIMIT},
            )

        assert response.status_code == 422, response.text
        assert patched_repos.created == []
        assert credential_store.store == {}

    async def test_lost_race_cleans_up_the_just_created_user_row(
        self, patched_repos, credential_store, _instance_secret
    ):
        """Remove the just-created user row when try_create loses the race; orphans poison the email."""
        credential_store.try_create.side_effect = None
        credential_store.try_create.return_value = None

        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "loser@example.com", "password": TEST_PASSWORD},
            )

        assert response.status_code == 403, response.text
        assert response.json()["code"] == "registration_closed"
        # The half-created row was compensated away — nothing orphaned.
        assert patched_repos.created == []
        assert patched_repos.by_email == {}

    async def test_signup_refuses_existing_identity_claim(
        self, patched_repos, credential_store, _instance_secret
    ):
        """Refuse signup claiming a pre-existing user row; no credential is attached."""
        existing = UserDocument.model_validate({"id": str(ObjectId()), "email": "adopted@gaia.dev"})
        patched_repos.by_email["adopted@gaia.dev"] = existing

        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "adopted@gaia.dev", "password": TEST_PASSWORD},
            )

        assert response.status_code == 403, response.text
        assert response.json()["code"] == "registration_closed"
        assert credential_store.store == {}  # nothing attached to the identity
        assert patched_repos.created == []

    async def test_signup_normalizes_email_to_lowercase(
        self, patched_repos, credential_store, _instance_secret
    ):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "Admin@EXAMPLE.COM", "password": TEST_PASSWORD},
            )

        assert response.status_code == 201, response.text
        assert patched_repos.created[0].email == "admin@example.com"
        assert response.json()["user"]["email"] == "admin@example.com"

    async def test_name_over_100_chars_is_422(self, patched_repos, _instance_secret):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "admin@example.com",
                    "password": TEST_PASSWORD,
                    "name": "x" * 101,
                },
            )

        assert response.status_code == 422

    async def test_concurrent_signups_produce_exactly_one_admin(
        self, patched_repos, credential_store, settings_store, _instance_secret, monkeypatch
    ):
        """Admit exactly one admin when signups race; losers get 403 and leave no orphan rows."""
        import app.api.v1.endpoints.auth_local as auth_local_module

        monkeypatch.setattr(auth_local_module.bcrypt, "hashpw", lambda pw, salt: _FAKE_HASH)
        monkeypatch.setattr(auth_local_module.bcrypt, "gensalt", lambda rounds=12: b"salt")

        emails = [f"racer{i}@example.com" for i in range(5)]
        app = _build_router_app()
        client = await _client(app)
        async with client:
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/api/v1/auth/signup", json={"email": email, "password": TEST_PASSWORD}
                    )
                    for email in emails
                )
            )

        statuses = [r.status_code for r in responses]
        assert statuses.count(201) == 1, f"expected exactly one 201, got {statuses}"
        assert statuses.count(403) == len(emails) - 1, statuses
        for response in responses:
            if response.status_code == 403:
                assert response.json()["code"] == "registration_closed"

        assert len(credential_store.store) == 1
        # The losers' just-created user rows were compensated away — no garbage.
        assert len(patched_repos.created) == 1


# ---------------------------------------------------------------------------
# Member signup (after the administrator exists)
# ---------------------------------------------------------------------------


async def _signup(email: str, invite: str | None = None) -> httpx.Response:
    body: dict[str, str] = {"email": email, "password": TEST_PASSWORD}
    if invite is not None:
        body["invite"] = invite
    client = await _client(_build_router_app())
    async with client:
        return await client.post("/api/v1/auth/signup", json=body)


@pytest.mark.integration
class TestMemberSignup:
    @pytest.fixture(autouse=True)
    def _admin(self, patched_repos, credential_store) -> None:
        seed_admin(patched_repos, credential_store, "admin@gaia.dev")

    async def test_valid_invite_creates_a_member_with_a_session(
        self,
        patched_repos,
        credential_store,
        invite_store,
        settings_store,
        captured,
        _instance_secret,
    ):
        invite = invite_store.add("good-token")

        response = await _signup("kid@gaia.dev", invite="good-token")

        assert response.status_code == 201, response.text
        assert response.json()["user"]["role"] == "member"
        member = patched_repos.by_email["kid@gaia.dev"]
        assert member.role is InstanceRole.MEMBER
        assert credential_store.store[member.id].slot is None
        assert await resolve_session_token(response.cookies["gaia_session"]) == member.id
        redeemed = invite_store.invites[invite.id]
        assert redeemed.used_at is not None
        assert redeemed.used_by == member.id
        captured.assert_called_once_with(UserId(member.id), InstanceMemberJoined(via="invite"))

    async def test_an_invite_admits_only_one_account(
        self, patched_repos, invite_store, settings_store, captured, _instance_secret
    ):
        invite_store.add("one-use")

        first = await _signup("first@gaia.dev", invite="one-use")
        second = await _signup("second@gaia.dev", invite="one-use")

        assert first.status_code == 201, first.text
        assert second.status_code == 403
        assert second.json()["code"] == "invite_invalid"
        assert "second@gaia.dev" not in patched_repos.by_email

    @pytest.mark.parametrize("token", ["expired-token", "unknown-token"])
    async def test_expired_or_unknown_invite_is_refused(
        self, token, patched_repos, invite_store, settings_store, _instance_secret
    ):
        invite_store.add("expired-token", expires_in=timedelta(seconds=-1))

        response = await _signup("late@gaia.dev", invite=token)

        assert response.status_code == 403
        assert response.json()["code"] == "invite_invalid"
        assert "late@gaia.dev" not in patched_repos.by_email

    async def test_open_registration_admits_without_an_invite(
        self, patched_repos, settings_store, captured, _instance_secret
    ):
        settings_store.values[REGISTRATION_SETTINGS_KEY] = {"policy": "open"}

        response = await _signup("friend@gaia.dev")

        assert response.status_code == 201, response.text
        member = patched_repos.by_email["friend@gaia.dev"]
        assert member.role is InstanceRole.MEMBER
        captured.assert_called_once_with(UserId(member.id), InstanceMemberJoined(via="open"))

    async def test_existing_email_is_refused_before_the_invite_is_spent(
        self, patched_repos, invite_store, settings_store, _instance_secret
    ):
        invite = invite_store.add("keep-me")

        response = await _signup("admin@gaia.dev", invite="keep-me")

        assert response.status_code == 403
        assert response.json()["code"] == "registration_closed"
        assert invite_store.invites[invite.id].used_at is None

    async def test_a_spent_invite_reads_as_spent_even_for_a_registered_email(
        self, patched_repos, invite_store, settings_store, captured, _instance_secret
    ):
        invite_store.add("spent")
        assert (await _signup("teammate@gaia.dev", invite="spent")).status_code == 201

        response = await _signup("teammate@gaia.dev", invite="spent")

        assert response.status_code == 403
        assert response.json()["code"] == "invite_invalid"

    async def test_a_failed_credential_write_leaves_no_account_and_keeps_the_invite(
        self, patched_repos, credential_store, invite_store, settings_store, _instance_secret
    ):
        invite = invite_store.add("retry-me")
        credential_store.create.side_effect = RuntimeError("mongo write failed")

        response = await _signup("kid@gaia.dev", invite="retry-me")

        assert response.status_code == 500
        assert "kid@gaia.dev" not in patched_repos.by_email
        assert invite_store.invites[invite.id].used_at is None
        assert all(c.slot == ADMIN_CREDENTIAL_SLOT for c in credential_store.store.values())

    async def test_racing_signups_on_one_invite_leave_one_account_and_no_orphans(
        self, patched_repos, credential_store, invite_store, settings_store, _instance_secret
    ):
        invite_store.add("contested")

        responses = await asyncio.gather(
            _signup("first@gaia.dev", invite="contested"),
            _signup("second@gaia.dev", invite="contested"),
        )

        assert sorted(r.status_code for r in responses) == [201, 403]
        members = [u for u in patched_repos.by_email.values() if u.role is InstanceRole.MEMBER]
        assert len(members) == 1
        member_credentials = [c for c in credential_store.store.values() if c.slot is None]
        assert [c.user_id for c in member_credentials] == [members[0].id]


@pytest.mark.integration
class TestRemovedMember:
    async def test_removed_member_cannot_log_in(
        self, patched_repos, credential_store, _instance_secret
    ):
        member = seed_account(patched_repos, credential_store, "gone@gaia.dev", InstanceRole.MEMBER)
        credential_store.store[member.id] = credential_store.store[member.id].model_copy(
            update={"disabled_at": datetime.now(UTC)}
        )

        client = await _client(_build_router_app())
        async with client:
            response = await client.post(
                "/api/v1/auth/login", json={"email": "gone@gaia.dev", "password": TEST_PASSWORD}
            )

        assert response.status_code == 401
        assert response.json()["code"] == INVALID_CREDENTIALS

    async def test_removed_member_session_stops_resolving(
        self, patched_repos, credential_store, _instance_secret
    ):
        member = seed_account(patched_repos, credential_store, "gone@gaia.dev", InstanceRole.MEMBER)
        token = await issue_session_token(member.id, 0)
        assert await resolve_session_token(token) == member.id

        credential_store.store[member.id] = credential_store.store[member.id].model_copy(
            update={"disabled_at": datetime.now(UTC)}
        )

        assert await resolve_session_token(token) is None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLogin:
    @pytest.fixture
    def admin(self, patched_repos, credential_store):
        return seed_admin(patched_repos, credential_store, "admin@gaia.dev")

    async def test_login_with_valid_credentials_sets_cookie(self, admin, _instance_secret):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@gaia.dev", "password": TEST_PASSWORD},
            )

        assert response.status_code == 200, response.text
        assert response.json()["user"]["email"] == "admin@gaia.dev"
        assert await resolve_session_token(response.cookies["gaia_session"]) == admin.id

    async def test_wrong_password_is_401_invalid_credentials(self, admin, _instance_secret):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@gaia.dev", "password": "wrong-password"},
            )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"
        assert "gaia_session" not in response.cookies

    async def test_over_bcrypt_limit_password_is_422_before_any_lookup(
        self, admin, _instance_secret
    ):
        """Reject over-cap passwords as 422 before any lookup; never 500, never a session."""
        app = _build_router_app()
        client = await _client(app)
        async with client:
            known = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@gaia.dev", "password": PASSWORD_OVER_BCRYPT_LIMIT},
            )
            unknown = await client.post(
                "/api/v1/auth/login",
                json={"email": "ghost@example.com", "password": PASSWORD_OVER_BCRYPT_LIMIT},
            )

        assert known.status_code == unknown.status_code == 422, known.text
        assert "gaia_session" not in known.cookies

    async def test_unknown_email_is_401(self, patched_repos, _instance_secret):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "ghost@gaia.dev", "password": TEST_PASSWORD},
            )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    async def test_user_without_credential_is_401(self, patched_repos, _instance_secret):
        """Refuse password auth for a user row with no local credential."""
        patched_repos.by_email["hollow@gaia.dev"] = UserDocument.model_validate(
            {"id": str(ObjectId()), "email": "hollow@gaia.dev"}
        )

        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "hollow@gaia.dev", "password": TEST_PASSWORD},
            )

        assert response.status_code == 401

    async def test_login_matches_mixed_case_email(self, admin, _instance_secret):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "ADMIN@GAIA.DEV", "password": TEST_PASSWORD},
            )

        assert response.status_code == 200, response.text

    async def test_unknown_email_and_wrong_password_are_indistinguishable(
        self, admin, _instance_secret, monkeypatch
    ):
        """Burn equal bcrypt work on both login failures so timing reveals no account oracle."""
        import app.api.v1.endpoints.auth_local as auth_local_module

        spy = MagicMock(wraps=bcrypt_lib.checkpw)
        monkeypatch.setattr(auth_local_module.bcrypt, "checkpw", spy)

        app = _build_router_app()
        client = await _client(app)
        async with client:
            unknown = await client.post(
                "/api/v1/auth/login",
                json={"email": "ghost@example.com", "password": TEST_PASSWORD},
            )
            wrong_password = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "wrong-password"},
            )

        assert unknown.status_code == wrong_password.status_code == 401
        assert unknown.json() == wrong_password.json()
        assert spy.call_count == 2  # one bcrypt verification per failed attempt


# ---------------------------------------------------------------------------
# bcrypt ValueError guards (bcrypt >= 5 refuses >72-byte inputs)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBcryptValueErrorGuards:
    """Pin the handler-level second line of defense behind request validation.

    Validation already turns over-cap passwords into clean 422s on the wire (see
    the signup and
    login tests above). These tests drive the handlers directly with an
    unvalidated body to pin what happens if a refused input ever reaches them
    anyway — a clean 422 on signup / uniform 401 on login, never a 500, and
    never an orphaned user row."""

    @staticmethod
    def _unvalidated_body(password: str) -> SimpleNamespace:
        """Stand-in for a request model that skipped validation."""
        return SimpleNamespace(email="admin@gaia.dev", password=password, name=None)

    async def test_signup_refused_hash_is_422_without_orphan(self, patched_repos, credential_store):
        import app.api.v1.endpoints.auth_local as auth_local_module

        with pytest.raises(HTTPException) as exc_info:
            await auth_local_module.signup(
                request=MagicMock(),
                body=self._unvalidated_body(PASSWORD_OVER_BCRYPT_LIMIT),
            )

        assert exc_info.value.status_code == 422
        # The hash refusal happens BEFORE the user insert — nothing orphaned.
        assert patched_repos.created == []
        assert credential_store.store == {}

    async def test_login_refused_hash_is_uniform_401(self, patched_repos, credential_store):
        import app.api.v1.endpoints.auth_local as auth_local_module

        seed_admin(patched_repos, credential_store, "admin@gaia.dev")

        with pytest.raises(HTTPException) as exc_info:
            await auth_local_module.login(
                request=MagicMock(),
                body=self._unvalidated_body(PASSWORD_OVER_BCRYPT_LIMIT),
            )

        assert exc_info.value.status_code == 401
        # Byte-identical to every other login failure — no oracle.
        assert exc_info.value.detail == {
            "code": INVALID_CREDENTIALS,
            "message": "Invalid email or password",
        }


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChangePassword:
    """Exercise PATCH /api/v1/auth/password self-service rotation end to end.

    Driven through the real middleware for the local admin, so the session
    requirement is exercised too.
    """

    @pytest.fixture
    def admin(self, patched_repos, credential_store):
        return seed_admin(patched_repos, credential_store, "admin@gaia.dev")

    async def test_change_then_old_fails_new_works(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        """Pin rotation: 200 on change, old password fails, new password logs in."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id, 0)
        old_hash = credential_store.store[admin.id].password_hash

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.patch(
                "/api/v1/auth/password",
                json={
                    "current_password": TEST_PASSWORD,
                    "new_password": "brand-new-password",
                },
            )
            old_login = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@gaia.dev", "password": TEST_PASSWORD},
            )
            new_login = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@gaia.dev", "password": "brand-new-password"},
            )

        assert response.status_code == 200, response.text
        assert old_login.status_code == 401
        assert new_login.status_code == 200, new_login.text
        # The stored hash really rotated — not just a re-hash of the same
        # secret (bcrypt salts differ every time).
        new_hash = credential_store.store[admin.id].password_hash
        assert new_hash != old_hash
        assert bcrypt_lib.checkpw(b"brand-new-password", new_hash.encode())

    async def test_wrong_current_password_is_401_and_changes_nothing(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        """Return uniform invalid_credentials 401 on wrong current password; change nothing."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id, 0)
        original = credential_store.store[admin.id]

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.patch(
                "/api/v1/auth/password",
                json={
                    "current_password": "wrong-current-password",
                    "new_password": "brand-new-password",
                },
            )
            assert response.status_code == 401, response.text
            assert response.json()["code"] == INVALID_CREDENTIALS
            # Nothing written — the old password still works.
            assert credential_store.store[admin.id] is original
            still_works = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@gaia.dev", "password": TEST_PASSWORD},
            )

        assert still_works.status_code == 200

    async def test_without_a_session_is_401_not_authenticated(
        self, admin, _instance_secret, monkeypatch
    ):
        """Fail closed through get_current_user without a session; verification is never reached."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            response = await client.patch(
                "/api/v1/auth/password",
                json={
                    "current_password": TEST_PASSWORD,
                    "new_password": "brand-new-password",
                },
            )

        assert response.status_code == 401
        assert response.json()["code"] == "NOT_AUTHENTICATED"

    async def test_short_new_password_is_422_before_any_verification(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        """Reject a short new password before the current-password verify runs; write nothing."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id, 0)
        original = credential_store.store[admin.id]

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.patch(
                "/api/v1/auth/password",
                json={"current_password": TEST_PASSWORD, "new_password": "short"},
            )

        assert response.status_code == 422, response.text
        assert credential_store.store[admin.id] is original

    async def test_over_bcrypt_limit_new_password_is_422_before_any_write(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        """Reject an over-72-byte new password as 422 first; bcrypt would raise mid-request."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id, 0)
        original = credential_store.store[admin.id]

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.patch(
                "/api/v1/auth/password",
                json={
                    "current_password": TEST_PASSWORD,
                    "new_password": PASSWORD_OVER_BCRYPT_LIMIT,
                },
            )

        assert response.status_code == 422, response.text
        assert credential_store.store[admin.id] is original

    async def test_update_receives_typed_rotation_model(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        """Carry new hash plus bumped token_version through the seam; identity fields cannot drift."""
        import app.api.v1.endpoints.auth_local as auth_local_module

        monkeypatch.setattr(settings, "AUTH_MODE", "local")

        app = _build_router_app()
        # Drive the handler directly against the router app with the auth
        # dependencies overridden — same seam, no middleware noise.
        app.dependency_overrides[auth_local_module.get_user_id] = lambda: admin.id
        app.dependency_overrides[auth_local_module.get_current_user] = lambda: {
            "user_id": admin.id,
            "email": "admin@gaia.dev",
            "auth_provider": "email",
        }
        client = await _client(app)
        async with client:
            response = await client.patch(
                "/api/v1/auth/password",
                json={
                    "current_password": TEST_PASSWORD,
                    "new_password": "brand-new-password",
                },
            )

        assert response.status_code == 200, response.text
        credential_store.update.assert_awaited_once()
        update_arg = credential_store.update.await_args.args[1]
        assert isinstance(update_arg, LocalCredentialUpdate)
        assert set(update_arg.model_dump(exclude_unset=True).keys()) == {
            "password_hash",
            "token_version",
        }
        assert update_arg.token_version == 1  # bumped from 0 → 1


def _build_user_route_app() -> FastAPI:
    """Build an app carrying the real user router behind the real middleware.

    Mounted exactly as routes.py mounts it, in local mode.
    """
    from app.api.v1.endpoints.user import router as user_router
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware

    app = FastAPI()
    app.include_router(user_router, prefix="/api/v1/user", tags=["User"])
    app.add_middleware(WorkOSAuthMiddleware, workos_client=MagicMock())
    return app


def test_local_auth_has_no_second_logout_route():
    from app.api.v1.endpoints.auth_local import router as auth_router

    assert "/logout" not in {getattr(route, "path", None) for route in auth_router.routes}


@pytest.mark.integration
class TestHostedLogoutRoute:
    """Authenticate POST /api/v1/user/logout like every other route.

    The canonical hosted logout endpoint the web client calls must reach
    user.py's local branch through WorkOSAuthMiddleware.
    """

    async def test_reachable_with_valid_session_cookie(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id, 0)

        app = _build_user_route_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.post("/api/v1/user/logout")

        assert response.status_code == 200, response.text
        # No logout_url: there is no hosted logout page on a local instance, so
        # the client stays put. Its absence is the local-mode signal.
        assert response.json()["logout_url"] is None
        cleared = response.headers["set-cookie"]
        assert "gaia_session=" in cleared

    async def test_without_a_session_is_401(self, patched_repos, _instance_secret, monkeypatch):
        """Fail closed on get_current_user with the route off the exclude list."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        app = _build_user_route_app()
        client = await _client(app)
        async with client:
            response = await client.post("/api/v1/user/logout")

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Cookie contract (self-host over LAN http vs production https)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSessionCookies:
    async def test_session_cookie_flags_over_lan_http(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        """Omit Secure under non-production ENV; browsers drop Secure cookies over LAN http."""
        monkeypatch.setattr(settings, "ENV", "selfhost")
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "admin@example.com", "password": TEST_PASSWORD},
            )

        assert response.status_code == 201, response.text
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert f"Max-Age={30 * 24 * 3600}" in cookie
        assert "Secure" not in cookie

    async def test_session_cookie_is_secure_when_request_is_https(
        self, patched_repos, credential_store, _instance_secret
    ):
        """Follow the request transport for Secure, not ENV; TLS proxies must mark, LAN http must not."""
        app = _build_router_app()
        client = await _client(app)
        async with client:
            plain = await client.post(
                "/api/v1/auth/signup",
                json={"email": "admin@gaia.dev", "password": TEST_PASSWORD},
            )
            # Registration closes after the first account — reset the store so
            # the second signup exercises the cookie path again.
            credential_store.store.clear()
            tls = await client.post(
                "/api/v1/auth/signup",
                json={"email": "tls@gaia.dev", "password": TEST_PASSWORD},
                headers={"X-Forwarded-Proto": "https"},
            )

        assert "Secure" not in plain.headers.get("set-cookie", "")
        assert "Secure" in tls.headers.get("set-cookie", "")

    async def test_cleared_cookie_keeps_flags_in_non_production(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        """Mirror the set-cookie attributes on the deletion cookie, minus Secure on LAN http."""
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id, 0)
        client = await _client(_build_user_route_app())
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.post("/api/v1/user/logout")

        cleared = response.headers["set-cookie"]
        assert "HttpOnly" in cleared
        assert "SameSite=lax" in cleared
        assert "Path=/" in cleared
        assert "Secure" not in cleared


# ---------------------------------------------------------------------------
# Session token utilities
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSessionTokens:
    async def test_roundtrip_returns_user_id(self, _instance_secret):
        user_id = str(uuid4())
        token = await issue_session_token(user_id, 0)
        assert await resolve_session_token(token) == user_id

    async def test_expired_token_rejected(self, _instance_secret):
        expired = jwt.encode(
            {"sub": "u1", "exp": datetime.now(UTC) - timedelta(seconds=1)},
            TEST_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        assert await resolve_session_token(expired) is None

    async def test_tampered_signature_rejected(self, _instance_secret):
        token = await issue_session_token("u1", 0)
        head, payload, sig = token.split(".")
        tampered = f"{head}.{payload}.{'0' if sig[0] != '0' else '1'}{sig[1:]}"
        assert await resolve_session_token(tampered) is None

    async def test_wrong_key_rejected(self, _instance_secret):
        foreign = jwt.encode(
            {"sub": "u1", "exp": datetime.now(UTC) + timedelta(days=1)},
            "a-completely-different-secret",
            algorithm=JWT_ALGORITHM,
        )
        assert await resolve_session_token(foreign) is None

    async def test_resolving_a_session_decodes_the_token_once(self, _instance_secret, monkeypatch):
        from app.utils import local_auth_utils

        token = await issue_session_token("u-once", 0)
        real_decode = local_auth_utils.jwt.decode
        decodes: list[str] = []

        def counting_decode(*args, **kwargs):
            decodes.append(args[0])
            return real_decode(*args, **kwargs)

        monkeypatch.setattr(local_auth_utils.jwt, "decode", counting_decode)

        assert await resolve_session_token(token) == "u-once"
        assert decodes == [token]

    async def test_resolve_session_token_warms_secret_then_verifies(
        self, _instance_secret, monkeypatch
    ):
        from app.utils import local_auth_utils

        token = await issue_session_token("u-warm", 0)

        # Simulate a fresh process: cache empty even though issue just ran.
        monkeypatch.setattr(local_auth_utils, "_resolved_secret", None)
        assert await resolve_session_token(token) == "u-warm"


# ---------------------------------------------------------------------------
# WorkOSAuthMiddleware — AUTH_MODE="local" dispatch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLocalMiddlewareDispatch:
    async def test_valid_cookie_authenticates_as_email_provider(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id, 0)

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.get("/probe")

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "admin@gaia.dev"
        assert body["auth_provider"] == "email"

    async def test_bearer_header_accepted_as_fallback(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id, 0)

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            response = await client.get("/probe", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["auth_provider"] == "email"

    async def test_invalid_cookie_passes_through_anonymous_silently(
        self, patched_repos, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", "garbage")
            response = await client.get("/probe")
        assert response.status_code == 401

    async def test_expired_cookie_passes_through_anonymous(
        self, patched_repos, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        expired = jwt.encode(
            {"sub": str(ObjectId()), "exp": datetime.now(UTC) - timedelta(minutes=1)},
            TEST_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", expired)
            response = await client.get("/probe")
        assert response.status_code == 401

    async def test_signup_path_is_excluded_from_auth(
        self, patched_repos, _instance_secret, monkeypatch
    ):
        """Let an excluded path reach the router unauthenticated; 422 proves pass-through."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            response = await client.post("/api/v1/auth/signup", json={})
        assert response.status_code == 422

    async def test_unknown_token_user_passes_through_anonymous(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        """Authenticate nobody for a token naming a deleted user, same as the WorkOS path."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        ghost_token = await issue_session_token(str(ObjectId()), 0)

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", ghost_token)
            response = await client.get("/probe")
        assert response.status_code == 401

    async def test_local_mode_does_not_construct_workos_client(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        with patch("app.api.v1.middleware.auth.get_async_workos_client") as mock_client:
            from app.api.v1.middleware.auth import WorkOSAuthMiddleware

            middleware = WorkOSAuthMiddleware(app=MagicMock())
        assert middleware.workos is None
        mock_client.assert_not_called()

    async def test_workos_mode_still_constructs_client_when_not_passed(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        from app.api.v1.middleware.auth import WorkOSAuthMiddleware

        middleware = WorkOSAuthMiddleware(app=MagicMock())
        assert middleware.workos is not None


# ---------------------------------------------------------------------------
# get_current_user_ws — local branch
# ---------------------------------------------------------------------------


def _fake_websocket(cookies: dict[str, str], protocols: str = "") -> MagicMock:
    websocket = MagicMock(spec=WebSocket)
    websocket.cookies = cookies
    websocket.headers = {"sec-websocket-protocol": protocols} if protocols else {}
    websocket.close = AsyncMock()
    return websocket


@pytest.mark.integration
class TestLocalWebSocketAuth:
    async def test_cookie_authenticates_ws_in_local_mode(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id, 0)

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        user = await get_current_user_ws(_fake_websocket({"gaia_session": token}))

        assert user.email == "admin@gaia.dev"
        assert user.auth_provider == "email"
        assert user.user_id == admin.id

    async def test_missing_credentials_close_policy_violation(
        self, patched_repos, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        from fastapi import status as fastapi_status
        from fastapi.exceptions import WebSocketException

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        websocket = _fake_websocket({})
        with pytest.raises(WebSocketException) as exc_info:
            await get_current_user_ws(websocket)

        assert exc_info.value.code == fastapi_status.WS_1008_POLICY_VIOLATION

    async def test_subprotocol_bearer_token_accepted(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id, 0)

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        websocket = _fake_websocket({}, protocols=f"Bearer, {token}")
        user = await get_current_user_ws(websocket)

        assert user.user_id == admin.id

    async def test_invalid_token_closes_connection(
        self, patched_repos, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        from fastapi import status as fastapi_status
        from fastapi.exceptions import WebSocketException

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        websocket = _fake_websocket({"gaia_session": "garbage"})
        with pytest.raises(WebSocketException) as exc_info:
            await get_current_user_ws(websocket)

        assert exc_info.value.code == fastapi_status.WS_1008_POLICY_VIOLATION


# ---------------------------------------------------------------------------
# What each credential endpoint leaves behind: wide event, audit trail, cookie
# ---------------------------------------------------------------------------


async def _post_as_router(path: str, json: dict[str, str]) -> tuple[httpx.Response, dict]:
    """POST to the bare auth router inside a wide-event boundary; return the response and event."""
    async with captured_wide_event() as live:
        client = await _client(_build_router_app())
        async with client:
            response = await client.post(path, json=json)
        event = dict(live)  # before the boundary stamps its own outcome on exit
    return response, event


def _session_cookie(response: httpx.Response) -> Morsel[str]:
    return SimpleCookie(response.headers["set-cookie"])["gaia_session"]


def _token_version(token: str) -> int:
    return int(jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])["ver"])


@pytest.mark.integration
class TestSignupTrail:
    async def test_the_first_account_is_audited_as_admin_and_named_from_its_email(
        self, patched_repos, credential_store, _instance_secret
    ):
        response, event = await _post_as_router(
            "/api/v1/auth/signup", {"email": "owner@gaia.dev", "password": TEST_PASSWORD}
        )

        assert response.status_code == 201, response.text
        [user] = patched_repos.created
        assert user.name == "owner"
        assert (event["operation"], event["email"], event["client_ip"]) == (
            "local_signup",
            "owner@gaia.dev",
            "127.0.0.1",
        )
        assert event["outcome"] == "success"
        assert event["audit"] == [
            {"msg": "account created", "actor": user.id, "mode": "local", "role": "admin"}
        ]
        cookie = _session_cookie(response)
        assert (cookie["httponly"], cookie["samesite"], cookie["path"]) == (True, "lax", "/")
        assert cookie["max-age"] == str(SESSION_TTL_SECONDS)
        assert _token_version(cookie.value) == 0

    async def test_a_closed_instance_audits_the_refused_email(
        self, patched_repos, credential_store, _instance_secret
    ):
        seed_admin(patched_repos, credential_store, "admin@gaia.dev")

        response, event = await _post_as_router(
            "/api/v1/auth/signup", {"email": "stranger@gaia.dev", "password": TEST_PASSWORD}
        )

        assert response.status_code == 403
        assert response.json()["message"] == (
            "Signing up here needs an invite from this instance's administrator"
        )
        assert event["audit"] == [
            {
                "msg": "signup rejected — registration closed",
                "actor": AUDIT_ACTOR_UNAUTHENTICATED,
                "email": "stranger@gaia.dev",
            }
        ]

    async def test_a_member_keeps_the_name_they_signed_up_with(
        self, patched_repos, credential_store, invite_store, settings_store, _instance_secret
    ):
        seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        invite_store.add("named")

        response, _ = await _post_as_router(
            "/api/v1/auth/signup",
            {"email": "kid@gaia.dev", "password": TEST_PASSWORD, "name": "Kid", "invite": "named"},
        )

        assert response.status_code == 201, response.text
        assert patched_repos.by_email["kid@gaia.dev"].name == "Kid"

    async def test_a_cleanup_that_fails_is_warned_not_masked(
        self, patched_repos, credential_store, invite_store, settings_store, _instance_secret
    ):
        from app.db.repositories.users import user_repository

        seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        invite_store.add("doomed")
        credential_store.create.side_effect = RuntimeError("mongo write failed")

        with patch.object(
            user_repository, "delete", AsyncMock(side_effect=RuntimeError("delete failed"))
        ):
            response, event = await _post_as_router(
                "/api/v1/auth/signup",
                {"email": "kid@gaia.dev", "password": TEST_PASSWORD, "invite": "doomed"},
            )

        assert response.status_code == 500
        orphan = patched_repos.by_email["kid@gaia.dev"]
        assert event["warnings"] == [
            {
                "msg": "signup compensating account delete failed",
                "user": {"id": orphan.id},
                "error": "delete failed",
                "error_type": "RuntimeError",
            }
        ]


@pytest.mark.integration
class TestLoginTrail:
    @pytest.fixture
    def admin(self, patched_repos, credential_store) -> UserDocument:
        return seed_admin(patched_repos, credential_store, "admin@gaia.dev")

    async def test_a_login_is_audited_and_carries_the_current_session_version(
        self, admin, credential_store, _instance_secret
    ):
        credential_store.store[admin.id] = credential_store.store[admin.id].model_copy(
            update={"token_version": 3}
        )

        response, event = await _post_as_router(
            "/api/v1/auth/login", {"email": "admin@gaia.dev", "password": TEST_PASSWORD}
        )

        assert response.status_code == 200, response.text
        assert (event["operation"], event["email"], event["client_ip"]) == (
            "local_login",
            "admin@gaia.dev",
            "127.0.0.1",
        )
        assert event["outcome"] == "success"
        assert event["audit"] == [{"msg": "logged in", "actor": admin.id, "mode": "local"}]
        assert _token_version(_session_cookie(response).value) == 3

    async def test_a_failed_login_is_audited_against_the_attempted_email(
        self, admin, _instance_secret
    ):
        response, event = await _post_as_router(
            "/api/v1/auth/login", {"email": "admin@gaia.dev", "password": "wrong-password"}
        )

        assert response.status_code == 401
        assert event["audit"] == [
            {"msg": "login failed", "actor": AUDIT_ACTOR_UNAUTHENTICATED, "email": "admin@gaia.dev"}
        ]

    @pytest.mark.parametrize("failure", ["unknown_email", "no_credential", "wrong_password"])
    async def test_every_login_failure_costs_exactly_one_bcrypt_verify(
        self, admin, credential_store, _instance_secret, monkeypatch, failure
    ):
        import app.api.v1.endpoints.auth_local as auth_local_module

        # A fresh process: the timing-equalizer digest is built on first use.
        monkeypatch.setattr(auth_local_module, "_dummy_digest", None)
        if failure == "no_credential":
            del credential_store.store[admin.id]
        verifies = MagicMock(wraps=bcrypt_lib.checkpw)
        monkeypatch.setattr(auth_local_module.bcrypt, "checkpw", verifies)
        email = "nobody@gaia.dev" if failure == "unknown_email" else "admin@gaia.dev"
        password = "wrong-password" if failure == "wrong_password" else TEST_PASSWORD

        response, _ = await _post_as_router(
            "/api/v1/auth/login", {"email": email, "password": password}
        )

        assert response.status_code == 401
        assert verifies.call_count == 1

    async def test_an_over_cap_password_is_warned_and_folded_into_the_uniform_401(self, admin):
        import app.api.v1.endpoints.auth_local as auth_local_module

        async with captured_wide_event() as event:
            with pytest.raises(HTTPException) as refused:
                await auth_local_module.login(
                    request=MagicMock(),
                    body=SimpleNamespace(
                        email="admin@gaia.dev", password=PASSWORD_OVER_BCRYPT_LIMIT
                    ),
                )

        assert refused.value.status_code == 401
        assert {"msg": "over-cap password folded into uniform 401", "error_type": "ValueError"} in (
            event["warnings"]
        )


@pytest.mark.integration
class TestChangePasswordTrail:
    @pytest.fixture
    def admin(self, patched_repos, credential_store) -> UserDocument:
        return seed_admin(patched_repos, credential_store, "admin@gaia.dev")

    async def test_a_rotation_is_audited_and_reissues_the_callers_session(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id, 0)

        async with captured_wide_event() as live:
            client = await _client(_build_middleware_app())
            async with client:
                client.cookies.set("gaia_session", token)
                response = await client.patch(
                    "/api/v1/auth/password",
                    json={"current_password": TEST_PASSWORD, "new_password": "brand-new-password"},
                )
            event = dict(live)

        assert response.status_code == 200, response.text
        assert response.json() == {"status": "ok"}
        assert (event["operation"], event["client_ip"]) == ("local_change_password", "127.0.0.1")
        assert event["outcome"] == "success"
        assert event["audit"] == [{"msg": "password changed", "actor": admin.id}]
        assert credential_store.store[admin.id].token_version == 1
        assert _token_version(_session_cookie(response).value) == 1
        assert await resolve_session_token(_session_cookie(response).value) == admin.id

    async def test_an_unverifiable_current_password_is_rejected_and_changes_nothing(
        self, admin, credential_store
    ):
        import app.api.v1.endpoints.auth_local as auth_local_module

        before = credential_store.store[admin.id]
        async with captured_wide_event() as event:
            with pytest.raises(HTTPException) as refused:
                await auth_local_module.change_password(
                    request=MagicMock(),
                    body=SimpleNamespace(
                        current_password=PASSWORD_OVER_BCRYPT_LIMIT,
                        new_password="brand-new-password",
                    ),
                    user_id=admin.id,
                    _user=MagicMock(),
                )

        assert refused.value.status_code == 401
        assert refused.value.detail == {
            "code": INVALID_CREDENTIALS,
            "message": "Current password is incorrect",
        }
        assert credential_store.store[admin.id] == before
        assert {"msg": "over-cap password folded into uniform 401", "error_type": "ValueError"} in (
            event["warnings"]
        )
        assert event["audit"] == [{"msg": "password change rejected", "actor": admin.id}]

    async def test_a_refused_new_hash_is_a_422_that_keeps_the_old_password(
        self, admin, credential_store
    ):
        import app.api.v1.endpoints.auth_local as auth_local_module

        before = credential_store.store[admin.id]
        with pytest.raises(HTTPException) as refused:
            await auth_local_module.change_password(
                request=MagicMock(),
                body=SimpleNamespace(
                    current_password=TEST_PASSWORD, new_password=PASSWORD_OVER_BCRYPT_LIMIT
                ),
                user_id=admin.id,
                _user=MagicMock(),
            )

        assert refused.value.status_code == 422
        assert refused.value.detail == {
            "message": "Password must be at most 72 bytes (UTF-8 encoded)"
        }
        assert credential_store.store[admin.id] == before

    async def test_a_rotation_that_did_not_persist_is_a_500_not_a_success(
        self, admin, credential_store
    ):
        import app.api.v1.endpoints.auth_local as auth_local_module

        credential_store.update.side_effect = None
        credential_store.update.return_value = None
        with pytest.raises(HTTPException) as refused:
            await auth_local_module.change_password(
                request=MagicMock(),
                body=SimpleNamespace(current_password=TEST_PASSWORD, new_password="brand-new-pw"),
                user_id=admin.id,
                _user=MagicMock(),
            )

        assert refused.value.status_code == 500
        assert refused.value.detail == {"message": "Password update did not persist"}
