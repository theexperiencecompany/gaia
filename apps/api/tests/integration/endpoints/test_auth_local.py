"""Integration tests for local-mode (self-host) authentication.

Covers the ``/api/v1/auth`` router (signup/login/logout), the session-token
utilities behind it, the AUTH_MODE="local" branch of WorkOSAuthMiddleware, and
the local branch of the WebSocket auth dependency.

Repositories and the instance-secret store are mocked at their seams; bcrypt,
the jose JWT encode/verify path, the middleware dispatch order, and the cookie
contract all run for real.
"""

import asyncio
from datetime import UTC, datetime, timedelta
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
from app.constants.auth import JWT_ALGORITHM
from app.constants.error_codes import INVALID_CREDENTIALS
from app.models.auth_models import LocalCredentialDocument, LocalCredentialUpdate
from app.models.user_models import UserDocument
from app.utils.local_auth_utils import (
    issue_session_token,
    resolve_session_token,
    verify_session_token,
)

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

    The cache starts WARM: production resolves the immutable instance secret
    once per process, and the sync verify path requires it — exactly the state
    every request finds after boot. (The cold-start behavior itself is pinned
    by TestSessionTokens tests below.)
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
    """These tests build their own apps but share one process-global slowapi
    bucket (keyed on 127.0.0.1), so cumulative signup calls would 429 each
    other mid-suite. Rate limiting has its own dedicated suite; here it only
    couples unrelated tests."""
    from app.api.v1.middleware.rate_limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def credential_store():
    """In-memory stand-in for the auth_credentials collection.

    Every operation yields to the event loop first (``sleep(0)``), mirroring a
    real Mongo round trip so gathered concurrent signups actually interleave
    between the gate check and the write. ``try_create`` mirrors the real
    repository's atomic claim semantics: at most ONE credential can ever land.
    """
    store: dict[str, LocalCredentialDocument] = {}

    async def get_by_user_id(user_id: str) -> LocalCredentialDocument | None:
        await asyncio.sleep(0)
        return store.get(user_id)

    async def create(doc: LocalCredentialDocument) -> LocalCredentialDocument:
        await asyncio.sleep(0)
        store[doc.user_id] = doc
        return doc

    async def try_create(doc: LocalCredentialDocument) -> LocalCredentialDocument | None:
        """Atomic insert: wins only when no credential exists yet."""
        await asyncio.sleep(0)
        if store:
            return None
        store[doc.user_id] = doc
        return doc

    async def update(
        doc_id: str, update_model: LocalCredentialUpdate
    ) -> LocalCredentialDocument | None:
        """Typed ``$set`` by id, mirroring MongoRepository.update semantics."""
        await asyncio.sleep(0)
        doc = next((c for c in store.values() if c.id == doc_id), None)
        if doc is None:
            return None
        updated = doc.model_copy(update=update_model.model_dump(exclude_unset=True))
        store[updated.user_id] = updated
        return updated

    async def any_exists() -> bool:
        await asyncio.sleep(0)
        return bool(store)

    holder = MagicMock()
    holder.store = store
    holder.get_by_user_id = AsyncMock(side_effect=get_by_user_id)
    holder.create = AsyncMock(side_effect=create)
    holder.try_create = AsyncMock(side_effect=try_create)
    holder.update = AsyncMock(side_effect=update)
    holder.any_exists = AsyncMock(side_effect=any_exists)
    return holder


@pytest.fixture
def patched_repos(directory, credential_store, monkeypatch):
    """Point every consumer (endpoints + middleware + ws dependency) at the
    in-memory stores.

    This directory's shared conftest (setup-API tests) swaps the
    ``local_credentials`` module attribute to its own count-only fake at import
    time; these tests re-bind the genuine singletons first so the REAL router
    code runs against controlled seams. All consumers import the same singleton
    objects, so patching their methods covers every call site.
    """
    import app.api.v1.endpoints.auth_local as auth_local_module
    import app.db.repositories.local_credentials as creds_mod
    from app.db.repositories.users import user_repository as users_singleton

    real_creds = creds_mod.LocalCredentialsRepository()
    monkeypatch.setattr(creds_mod, "local_credentials_repository", real_creds)
    if hasattr(auth_local_module, "local_credentials_repository"):
        monkeypatch.setattr(auth_local_module, "local_credentials_repository", real_creds)

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
        patch.object(real_creds, "any_exists", credential_store.any_exists),
    ):
        yield directory


def seed_admin(directory: UserDirectory, credential_store, email: str) -> UserDocument:
    """Insert an existing admin (user + bcrypt credential) into both stores."""
    user = UserDocument.model_validate({"id": str(ObjectId()), "email": email, "name": "Admin"})
    directory.by_email[email] = user
    credential_store.store[user.id] = LocalCredentialDocument(
        id=str(ObjectId()),
        user_id=user.id,
        password_hash=bcrypt_lib.hashpw(TEST_PASSWORD.encode(), bcrypt_lib.gensalt()).decode(),
    )
    return user


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _build_router_app() -> FastAPI:
    """The real auth_local router mounted exactly as routes.py will mount it."""
    from app.api.v1.endpoints.auth_local import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
    return app


def _build_middleware_app() -> FastAPI:
    """The real WorkOSAuthMiddleware in local mode, plus the mounted router.

    The probe route reports what request.state carries after dispatch — the
    contract downstream handlers depend on.
    """
    from app.api.v1.endpoints.auth_local import router as auth_router
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware

    app = FastAPI()

    @app.get("/probe")
    async def probe(request: Request) -> JSONResponse:
        user = getattr(request.state, "user", None)
        if not getattr(request.state, "authenticated", False) or not user:
            return JSONResponse(status_code=401, content={"detail": "no user"})
        return JSONResponse(
            content={"email": user.get("email"), "auth_provider": user.get("auth_provider")}
        )

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
        assert created.id in credential_store.store

        assert verify_session_token(response.cookies["gaia_session"]) == created.id

    async def test_second_signup_is_403_registration_closed(
        self, patched_repos, credential_store, _instance_secret
    ):
        seed_admin(patched_repos, credential_store, "admin@gaia.dev")

        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": "second@gaia.dev", "password": TEST_PASSWORD},
            )

        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "registration_closed"
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
        """Exactly 72 bytes is bcrypt's cap, not past it — the boundary must
        keep working end to end."""
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
        """>72 bytes makes bcrypt >= 5 raise ValueError. Rejected as a plain
        422 BEFORE any row is written — hashing after the user insert used to
        orphan the row on failure, permanently locking that email out of
        signup via the existing-identity gate."""
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
        """19 characters — under any character-count limit — but 76 UTF-8
        bytes, past bcrypt's cap. Proves the limit counts bytes, not chars."""
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
        """Deterministic replay of a lost registration race: try_create comes
        back empty exactly as when a concurrent signup won the admin slot.
        The user row created moments earlier must be removed again — an
        orphaned row poisons its email against every future signup (the
        existing-identity gate refuses re-registration)."""
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
        assert response.json()["detail"]["error_code"] == "registration_closed"
        # The half-created row was compensated away — nothing orphaned.
        assert patched_repos.created == []
        assert patched_repos.by_email == {}

    async def test_signup_refuses_existing_identity_claim(
        self, patched_repos, credential_store, _instance_secret
    ):
        """A pre-existing user row (e.g. from a WorkOS era on the same DB) is
        NOT claimable by knowing its email — that would hand the identity to
        an attacker. Signup is refused; no credential is attached."""
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
        assert response.json()["detail"]["error_code"] == "registration_closed"
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
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        """N signups racing on a fresh instance: exactly one 201, every loser a
        deterministic 403 registration_closed, and no orphaned user rows.

        The seams yield (``sleep(0)``) so gathered requests genuinely interleave
        between the gate read and the write — the shape that let two signups
        both become admin under check-then-create."""
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
                assert response.json()["detail"]["error_code"] == "registration_closed"

        assert len(credential_store.store) == 1
        # The losers' just-created user rows were compensated away — no garbage.
        assert len(patched_repos.created) == 1


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
        assert verify_session_token(response.cookies["gaia_session"]) == admin.id

    async def test_wrong_password_is_401_invalid_credentials(self, admin, _instance_secret):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@gaia.dev", "password": "wrong-password"},
            )

        assert response.status_code == 401
        assert response.json()["detail"]["error_code"] == "invalid_credentials"
        assert "gaia_session" not in response.cookies

    async def test_over_bcrypt_limit_password_is_422_before_any_lookup(
        self, admin, _instance_secret
    ):
        """bcrypt >= 5 refuses to verify passwords past its 72-byte cap
        (ValueError). Request validation rejects them with a clear 422
        before any account lookup happens — never a 500, and no session."""
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
        assert response.json()["detail"]["error_code"] == "invalid_credentials"

    async def test_user_without_credential_is_401(self, patched_repos, _instance_secret):
        """A user row with no local credential must never authenticate via
        password — the credential lookup is load-bearing, not the email match."""
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
        """Both failures return byte-identical error bodies AND burn the same
        bcrypt work — response time must not reveal whether an account exists."""
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
    """Second line of defense behind request validation: validation already
    turns over-cap passwords into clean 422s on the wire (see the signup and
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
            "error_code": INVALID_CREDENTIALS,
            "message": "Invalid email or password",
        }


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChangePassword:
    """PATCH /api/v1/auth/password — self-service rotation for the local
    admin, driven through the real middleware so the session requirement is
    exercised end to end."""

    @pytest.fixture
    def admin(self, patched_repos, credential_store):
        return seed_admin(patched_repos, credential_store, "admin@gaia.dev")

    async def test_change_then_old_fails_new_works(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        """The full rotation contract: 200 on change, old password stops
        authenticating, new password logs in."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id)
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
        """A wrong current password is the uniform invalid_credentials 401 and
        leaves the working credential untouched."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id)
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
            assert response.json()["detail"]["error_code"] == INVALID_CREDENTIALS
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
        """The route is not excluded from auth: without a session it fails
        closed through get_current_user, never reaching verification."""
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
        assert response.json()["detail"]["error_code"] == "NOT_AUTHENTICATED"

    async def test_short_new_password_is_422_before_any_verification(
        self, admin, credential_store, _instance_secret, monkeypatch
    ):
        """min_length is part of the request contract — rejected before the
        current-password verify runs and before anything is written."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id)
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
        """>72 bytes would make bcrypt >= 5 raise ValueError mid-request;
        request validation rejects it as a clean 422 first (byte cap, chars
        are not bytes)."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        token = await issue_session_token(admin.id)
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
        """The repository seam gets a LocalCredentialUpdate carrying ONLY the
        new hash — identity fields (user_id/slot/created_at) can never drift
        through a password change."""
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
        assert update_arg.model_dump(exclude_unset=True).keys() == {"password_hash"}


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLogout:
    async def test_logout_clears_cookie_and_reports_local_mode(self, _instance_secret):
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post("/api/v1/auth/logout")

        assert response.status_code == 200
        assert response.json() == {"mode": "local"}
        cleared = response.headers["set-cookie"]
        assert "gaia_session=" in cleared
        assert "Max-Age=0" in cleared or "Expires=Thu, 01 Jan 1970" in cleared


def _build_user_route_app() -> FastAPI:
    """The real user router mounted exactly as routes.py mounts it, behind the
    real WorkOSAuthMiddleware in local mode."""
    from app.api.v1.endpoints.user import router as user_router
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware

    app = FastAPI()
    app.include_router(user_router, prefix="/api/v1/user", tags=["User"])
    app.add_middleware(WorkOSAuthMiddleware, workos_client=MagicMock())
    return app


@pytest.mark.integration
class TestHostedLogoutRoute:
    """POST /api/v1/user/logout — the canonical hosted logout endpoint the web
    client calls — must authenticate through WorkOSAuthMiddleware like every
    other route and reach user.py's local branch (security-review M2)."""

    async def test_reachable_with_valid_session_cookie(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id)

        app = _build_user_route_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", token)
            response = await client.post("/api/v1/user/logout")

        assert response.status_code == 200, response.text
        assert response.json() == {"mode": "local"}
        cleared = response.headers["set-cookie"]
        assert "gaia_session=" in cleared

    async def test_without_a_session_is_401(self, patched_repos, _instance_secret, monkeypatch):
        """Removing the route from the middleware's exclude list must not open
        anonymous access — get_current_user still fails closed."""
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
        """Non-production ENV (self-host on plain http) must NOT set Secure —
        a Secure cookie would never be stored by browsers over LAN http."""
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
        """Secure follows the request's ACTUAL transport (X-Forwarded-Proto),
        not ENV — a self-host instance behind a TLS proxy must mark the cookie
        Secure, while plain-HTTP LAN instances must stay login-able."""
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
        self, _instance_secret, monkeypatch
    ):
        """The deletion cookie must mirror the set cookie's attributes or some
        clients keep the session alive — and must drop Secure off LAN http."""
        monkeypatch.setattr(settings, "ENV", "selfhost")
        app = _build_router_app()
        client = await _client(app)
        async with client:
            response = await client.post("/api/v1/auth/logout")

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
        token = await issue_session_token(user_id)
        assert verify_session_token(token) == user_id

    async def test_expired_token_rejected(self, _instance_secret):
        expired = jwt.encode(
            {"sub": "u1", "exp": datetime.now(UTC) - timedelta(seconds=1)},
            TEST_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        assert verify_session_token(expired) is None

    async def test_tampered_signature_rejected(self, _instance_secret):
        token = await issue_session_token("u1")
        head, payload, sig = token.split(".")
        tampered = f"{head}.{payload}.{'0' if sig[0] != '0' else '1'}{sig[1:]}"
        assert verify_session_token(tampered) is None

    async def test_wrong_key_rejected(self, _instance_secret):
        foreign = jwt.encode(
            {"sub": "u1", "exp": datetime.now(UTC) + timedelta(days=1)},
            "a-completely-different-secret",
            algorithm=JWT_ALGORITHM,
        )
        assert verify_session_token(foreign) is None

    async def test_verify_before_secret_resolution_fails_loud(self, monkeypatch):
        """A cold secret cache is a caller bug (skipped resolve_session_token),
        not an 'invalid session' — returning None here would lock out every
        existing session after a restart until re-login, invisibly."""
        from app.utils import local_auth_utils

        monkeypatch.setattr(local_auth_utils, "_resolved_secret", None)
        with pytest.raises(RuntimeError, match="secret"):
            local_auth_utils.verify_session_token("anything")

    async def test_resolve_session_token_warms_secret_then_verifies(
        self, _instance_secret, monkeypatch
    ):
        from app.utils import local_auth_utils

        token = await issue_session_token("u-warm")

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
        token = await issue_session_token(admin.id)

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
        token = await issue_session_token(admin.id)

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
        """An excluded path must reach the ROUTER unauthenticated — the 422 from
        request validation proves the middleware let the request through."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            response = await client.post("/api/v1/auth/signup", json={})
        assert response.status_code == 422

    async def test_unknown_token_user_passes_through_anonymous(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        """A signed token naming a user that no longer exists authenticates
        nobody — same posture as the WorkOS path."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        ghost_token = await issue_session_token(str(ObjectId()))

        app = _build_middleware_app()
        client = await _client(app)
        async with client:
            client.cookies.set("gaia_session", ghost_token)
            response = await client.get("/probe")
        assert response.status_code == 401

    async def test_local_mode_does_not_construct_workos_client(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        with patch("app.api.v1.middleware.auth.AsyncWorkOSClient") as mock_client:
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
        token = await issue_session_token(admin.id)

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        user = await get_current_user_ws(_fake_websocket({"gaia_session": token}))

        assert user["email"] == "admin@gaia.dev"
        assert user["auth_provider"] == "email"
        assert user["user_id"] == admin.id

    async def test_missing_credentials_close_policy_violation(
        self, patched_repos, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        from fastapi import status as fastapi_status

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        websocket = _fake_websocket({})
        user = await get_current_user_ws(websocket)

        assert user == {}
        websocket.close.assert_awaited_once_with(code=fastapi_status.WS_1008_POLICY_VIOLATION)

    async def test_subprotocol_bearer_token_accepted(
        self, patched_repos, credential_store, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        admin = seed_admin(patched_repos, credential_store, "admin@gaia.dev")
        token = await issue_session_token(admin.id)

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        websocket = _fake_websocket({}, protocols=f"Bearer, {token}")
        user = await get_current_user_ws(websocket)

        assert user["user_id"] == admin.id

    async def test_invalid_token_closes_connection(
        self, patched_repos, _instance_secret, monkeypatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        from fastapi import status as fastapi_status

        from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws

        websocket = _fake_websocket({"gaia_session": "garbage"})
        user = await get_current_user_ws(websocket)

        assert user == {}
        websocket.close.assert_awaited_once_with(code=fastapi_status.WS_1008_POLICY_VIOLATION)
