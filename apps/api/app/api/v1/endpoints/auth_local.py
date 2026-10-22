"""Local-mode auth endpoints (``AUTH_MODE="local"``, self-hosting).

Mounted at ``/auth`` by ``app/api/v1/routes.py``; ``signup`` and ``login`` are
public (the coordinator lists them in the middleware's ``exclude_paths``),
while ``password`` requires a live local session. Logout is POST /user/logout.
The first signup creates the instance administrator; later signups create
members when an invite or the open registration policy admits them.
"""

import secrets
from typing import Never, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.api.v1.middleware.rate_limiter import limiter
from app.constants.auth import AUDIT_ACTOR_UNAUTHENTICATED, InstanceRole
from app.constants.error_codes import INVALID_CREDENTIALS, REGISTRATION_CLOSED
from app.db.repositories.local_credentials import local_credentials_repository
from app.db.repositories.users import user_repository
from app.models.auth_models import (
    ADMIN_CREDENTIAL_SLOT,
    ChangePasswordRequest,
    LocalCredentialDocument,
    LocalCredentialUpdate,
    LoginRequest,
    SignupRequest,
)
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.members_service import admit_member, redeem_admission
from app.utils.auth_utils import build_user_context, set_session_cookie
from app.utils.local_auth_utils import (
    LOCAL_SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    issue_session_token,
)
from app.utils.password_hashing import hash_password, verify_password
from shared.py.wide_events import log

router = APIRouter()

# Lazily-built digest used to equalize failure cost in login: an unknown email
# would otherwise return in ~0ms while a wrong password pays a full bcrypt
# verify, letting response timing reveal whether an account exists.
_dummy_digest: str | None = None


def _burn_one_verification(password: str) -> None:
    """Run one real bcrypt verify against a fixed digest — pure latency.

    An over-cap password verifies as a mismatch without any work, exactly as
    it does against a real credential, so both failure routes stay equally cheap.
    """
    global _dummy_digest
    if _dummy_digest is None:
        # pragma: no mutate start — any secret works; only the verify's latency is used
        _dummy_digest = hash_password(secrets.token_hex(16))
        # pragma: no mutate end
    verify_password(password, _dummy_digest)


def _hash_new_password(password: str) -> str:
    """Hash a password being set, refusing one past bcrypt's cap as a clean 422."""
    try:
        return hash_password(password)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Password must be at most 72 bytes (UTF-8 encoded)"},
        ) from exc


def _client_ip(request: Request) -> str | None:
    """Best-effort caller IP for the audit trail on credential endpoints."""
    return request.client.host if request.client else None


def _set_session_cookie(response: JSONResponse, token: str, *, request: Request) -> None:
    set_session_cookie(
        response, request, name=LOCAL_SESSION_COOKIE, value=token, max_age=SESSION_TTL_SECONDS
    )


def _user_payload(user: UserDocument) -> dict[str, object]:
    """Return one identity shape for signup, login and ``GET /me``.

    Built through build_user_context so the payload is exactly what the local
    middleware puts on ``request.state.user``, then serialized through the model
    rather than a dict: ``AuthenticatedUser`` carries Mongo datetimes, which
    ``JSONResponse`` cannot encode, so ``model_dump(mode="json")`` renders them
    as the same isoformat strings the browser used to receive.
    """

    return cast(
        "dict[str, object]",
        build_user_context(user, auth_provider="email").model_dump(mode="json"),
    )


def _registration_closed(email: str) -> Never:
    """Audit and raise the closed-registration rejection."""
    log.audit(
        "signup rejected — registration closed",
        actor=AUDIT_ACTOR_UNAUTHENTICATED,
        email=email,
    )
    raise HTTPException(
        status_code=403,
        detail={
            "code": REGISTRATION_CLOSED,
            "message": "Signing up here needs an invite from this instance's administrator",
        },
    )


def _login_failed(email: str) -> Never:
    """Audit and raise the one invalid-credentials rejection every login failure shares."""
    log.audit(
        "login failed",
        actor=AUDIT_ACTOR_UNAUTHENTICATED,
        email=email,
    )
    raise HTTPException(
        status_code=401,
        detail={
            "code": INVALID_CREDENTIALS,
            "message": "Invalid email or password",
        },
    )


async def _discard_partial_account(user_id: str, credential_id: str | None) -> None:
    """Remove the rows a failed signup created so its email stays free to sign up with.

    Best-effort deliberately: the signup's own failure is the response, so a
    cleanup failure logs loudly instead of masking it. The rows are unreachable
    either way: no session was issued for them.
    """
    try:
        if credential_id is not None:
            await local_credentials_repository.delete(credential_id)
        await user_repository.delete(user_id)
    except Exception as exc:
        log.warning(
            "signup compensating account delete failed",
            user={"id": user_id},
            error=str(exc),
            error_type=type(exc).__name__,
        )


@router.post("/signup", status_code=201)
@limiter.limit("10/minute")
async def signup(request: Request, body: SignupRequest) -> JSONResponse:
    """Create an account and open a session.

    The first account administers the instance. Its gate is an ATOMIC CLAIM (a
    partial unique index on slot=admin), not check-then-create: two concurrent
    first signups both read no admin, Mongo lets precisely one insert land, and
    the loser gets 403 registration_closed with its half-created user row removed.

    Every later account is a member, admitted by a valid invite or, when the
    administrator has opened signup, by anyone; otherwise 403 registration_closed.

    A pre-existing user row with the same email is NOT claimed — knowledge of
    an email address is not proof of ownership, and a migrated WorkOS-era row
    must not be attachable by an attacker (Greptile finding). Such signups are
    refused as closed before any invite is spent.
    """
    email = str(body.email)
    log.set(operation="local_signup", email=email, client_ip=_client_ip(request))

    admin_exists = await local_credentials_repository.admin_exists()
    # Decided before the email check: a spent link must read as spent, not as
    # closed, whoever presents it. Nothing is spent until the account exists.
    admission = await admit_member(body.invite) if admin_exists else None

    if await user_repository.get_by_email(email) is not None:
        # Email already belongs to an existing identity. Attaching a credential
        # would hand that identity to whoever knows the address, which is not
        # ownership proof. Refuse; only brand-new rows can become accounts.
        _registration_closed(email)

    # Hash BEFORE creating any row: hashing after the insert would strand an
    # orphaned user row on hash failure, locking that email out of signup
    # forever. This guard keeps any hash refusal a clean 422, not a 500.
    password_hash = _hash_new_password(body.password)

    # Self-host name is optional, unlike hosted signups. Default to the email
    # local-part so the display name never has to handle null.
    name = body.name or email.split("@")[0]

    if not admin_exists:
        # Fast-path pre-check only — the authoritative gate is the claim below.
        user = await user_repository.create(
            UserDocument(email=email, name=name, role=InstanceRole.ADMIN)
        )
        credential = await local_credentials_repository.try_create(
            LocalCredentialDocument(
                user_id=user.id, password_hash=password_hash, slot=ADMIN_CREDENTIAL_SLOT
            )
        )
        if credential is None:
            # Lost the race — another concurrent signup holds the admin slot now.
            # Remove the user row this request just created so no orphan remains.
            await _discard_partial_account(user.id, None)
            _registration_closed(email)
    else:
        if admission is None:
            _registration_closed(email)
        user = await user_repository.create(
            UserDocument(email=email, name=name, role=InstanceRole.MEMBER)
        )
        # The invite is spent last, so any failure before it leaves the invite live
        # and, with these rows removed, the email free for a retry.
        try:
            credential = await local_credentials_repository.create(
                LocalCredentialDocument(user_id=user.id, password_hash=password_hash)
            )
        except Exception:
            await _discard_partial_account(user.id, None)
            raise
        try:
            await redeem_admission(admission, user.id)
        except Exception:
            await _discard_partial_account(user.id, credential.id)
            raise

    token = await issue_session_token(user.id, credential.token_version)
    log.audit("account created", actor=user.id, mode="local", role=user.role)

    response = JSONResponse(status_code=201, content={"user": _user_payload(user)})
    _set_session_cookie(response, token, request=request)
    log.set(outcome="success")
    return response


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest) -> JSONResponse:
    """Verify email + password and open a session.

    Every failure — unknown email, missing credential, wrong password — returns
    the same body with the same status AND burns the same bcrypt work, so the
    endpoint can neither enumerate accounts nor distinguish them by latency.
    """
    email = str(body.email)
    log.set(operation="local_login", email=email, client_ip=_client_ip(request))

    user = await user_repository.get_by_email(email)
    stored = await local_credentials_repository.get_by_user_id(user.id) if user else None
    # A removed member fails exactly like an unknown account.
    credential = stored if stored is not None and stored.disabled_at is None else None

    if user is None or credential is None:
        # Equalize cost with the wrong-password path below.
        _burn_one_verification(body.password)
        _login_failed(email)
    if not verify_password(body.password, credential.password_hash):
        _login_failed(email)

    token = await issue_session_token(user.id, credential.token_version)
    log.audit("logged in", actor=user.id, mode="local")

    response = JSONResponse(content={"user": _user_payload(user)})
    _set_session_cookie(response, token, request=request)
    log.set(outcome="success")
    return response


@router.patch("/password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user_id: str = Depends(get_user_id),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    """Rotate the caller's own password after re-verifying the current one.

    Not in the middleware's ``exclude_paths`` — a live local session is
    required to even reach this handler. The current-password verify runs the
    same bcrypt path as login and fails with the same uniform
    ``invalid_credentials`` shape (401): whether the credential is missing or
    the password is wrong must stay indistinguishable. No timing equalizer is
    burned for a missing credential — unlike login, the caller already holds
    an authenticated session, so there is no account left to enumerate.

    Deliberately narrow failure semantics: a wrong current password is a
    401 (the client renders it inline next to that field), while an over-cap
    or too-short NEW password is rejected on the wire as a 422 before any
    verification runs.

    On success the credential's ``token_version`` is bumped and a fresh JWT
    (``ver`` = new version) is returned as a ``Set-Cookie`` so the caller's
    current session survives while every other previously issued JWT — whose
    ``ver`` no longer matches — is revoked. Previous sessions remain valid for
    up to 30 days only if password rotation never happened; after a rotation
    they are rejected on the next request.
    """
    log.set(operation="local_change_password", client_ip=_client_ip(request))

    credential = await local_credentials_repository.get_by_user_id(user_id)

    if credential is None or not verify_password(body.current_password, credential.password_hash):
        log.audit("password change rejected", actor=user_id)
        raise HTTPException(
            status_code=401,
            detail={
                "code": INVALID_CREDENTIALS,
                "message": "Current password is incorrect",
            },
        )

    # Hash BEFORE touching the stored row: bcrypt >= 5 refuses over-cap input,
    # and a failed hash must leave the old (working) credential untouched.
    password_hash = _hash_new_password(body.new_password)

    new_version = credential.token_version + 1
    updated = await local_credentials_repository.update(
        credential.id,
        LocalCredentialUpdate(password_hash=password_hash, token_version=new_version),
    )
    if updated is None:
        # Unreachable in practice (single admin holding a live session), but a
        # vanished row must never be reported as success.
        raise HTTPException(
            status_code=500,
            detail={"message": "Password update did not persist"},
        )

    log.audit("password changed", actor=user_id)
    # Rotate the caller's session so they stay logged in while every other
    # session (old ``ver``) is revoked.
    new_token = await issue_session_token(user_id, new_version)
    response = JSONResponse(content={"status": "ok"})
    _set_session_cookie(response, new_token, request=request)
    log.set(outcome="success")
    return response
