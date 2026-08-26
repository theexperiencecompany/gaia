"""Local-mode auth endpoints (``AUTH_MODE="local"``, self-hosting).

Mounted at ``/auth`` by ``app/api/v1/routes.py``; ``signup`` and ``login`` are
public (the coordinator lists them in the middleware's ``exclude_paths``),
while ``password`` and ``logout`` require a live local session.
A self-host instance has exactly one administrator: the first signup creates
it, every later signup is refused with ``registration_closed``.
"""

from datetime import datetime
from typing import Never, cast

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.api.v1.middleware.rate_limiter import limiter
from app.config.settings import settings
from app.constants.auth import AUDIT_ACTOR_UNAUTHENTICATED
from app.constants.error_codes import INVALID_CREDENTIALS, REGISTRATION_CLOSED
from app.db.repositories.local_credentials import local_credentials_repository
from app.db.repositories.users import user_repository
from app.models.auth_models import (
    ChangePasswordRequest,
    LocalCredentialDocument,
    LocalCredentialUpdate,
    LoginRequest,
    SignupRequest,
)
from app.models.user_models import AuthenticatedUser, UserDocument, user_to_legacy_dict
from app.utils.auth_utils import build_user_context
from app.utils.local_auth_utils import (
    LOCAL_SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    issue_session_token,
)
from shared.py.wide_events import log

router = APIRouter()

# OWASP-recommended baseline for interactive logins (~250ms per verify).
_BCRYPT_ROUNDS = 12

# Lazily-built digest used to equalize failure cost in login: an unknown email
# would otherwise return in ~0ms while a wrong password pays a full bcrypt
# verify, letting response timing reveal whether an account exists.
_dummy_digest: bytes | None = None


def _burn_one_verification(password: str) -> None:
    """Run one real bcrypt verify against a fixed digest — pure latency."""
    global _dummy_digest
    if _dummy_digest is None:
        _dummy_digest = bcrypt.hashpw(b"gaia-timing-equalizer", bcrypt.gensalt(_BCRYPT_ROUNDS))
    try:
        bcrypt.checkpw(password.encode(), _dummy_digest)
    except ValueError:
        # bcrypt >= 5 refuses inputs past its 72-byte cap without doing any
        # work — there is no verification left to burn. The real path also
        # fails fast on the same input, so skipping the burn keeps both
        # failure routes equally cheap; the caller turns this into the
        # uniform invalid-credentials response.
        return


def _client_ip(request: Request) -> str | None:
    """Best-effort caller IP for the audit trail on credential endpoints."""
    return request.client.host if request.client else None


def _set_session_cookie(
    response: JSONResponse, token: str, *, request: Request | None = None
) -> None:
    """Cookie options mirror the WorkOS session cookie in middleware/auth.py.

    ``Secure`` follows the request's actual transport (X-Forwarded-Proto /
    scheme), not ENV: a self-host instance behind a TLS proxy must mark the
    cookie Secure, while a plain-HTTP LAN instance must not (browsers drop
    Secure cookies over http, which would break login entirely).
    """
    secure = False
    if request is not None:
        forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        secure = forwarded == "https" or request.url.scheme == "https"
    response.set_cookie(
        key=LOCAL_SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def _clear_session_cookie(response: JSONResponse) -> None:
    response.delete_cookie(
        key=LOCAL_SESSION_COOKIE,
        httponly=True,
        path="/",
        secure=settings.ENV == "production",
        samesite="lax",
    )


def _user_payload(user: UserDocument) -> dict[str, object]:
    """Same shape the local middleware stores on ``request.state.user``, so a
    client sees one identity shape from signup, login and ``GET /me``.

    JSON-safe on purpose: the legacy dict carries Mongo datetimes (created_at
    etc.) that ``JSONResponse`` cannot encode — isoformat strings keep the
    same information in the browser-facing payload.
    """

    def _jsonable(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: _jsonable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_jsonable(v) for v in value]
        return value

    return cast(
        "dict[str, object]",
        _jsonable(dict(build_user_context(user_to_legacy_dict(user), auth_provider="email"))),
    )


def _registration_closed(email: str) -> Never:
    """Audit and raise the single-admin rejection (shared by the pre-check and
    a lost atomic-claim race)."""
    log.audit(
        "signup rejected — registration closed",
        actor=AUDIT_ACTOR_UNAUTHENTICATED,
        email=email,
    )
    raise HTTPException(
        status_code=403,
        detail={
            "error_code": REGISTRATION_CLOSED,
            "message": "An administrator account already exists on this instance",
        },
    )


async def _delete_user_best_effort(user_id: str) -> None:
    """Remove the user row this request created moments ago after losing the
    registration claim race.

    Best-effort deliberately: the rejection itself is already decided by Mongo,
    so a transient cleanup failure must not mask the correct 403 with a 500 —
    it logs loudly instead (same posture as users.touch_last_active). The row
    is unreachable garbage either way: its id was never returned and no session
    was issued for it.
    """
    try:
        await user_repository.delete(user_id)
    except Exception as exc:
        log.warning(
            "signup-race compensating user delete failed",
            user={"id": user_id},
            error=str(exc),
            error_type=type(exc).__name__,
        )


@router.post("/signup", status_code=201)
@limiter.limit("10/minute")
async def signup(request: Request, body: SignupRequest) -> JSONResponse:
    """Create the instance administrator account and open a session.

    Refused with 403 ``registration_closed`` once any credential exists — a
    self-hosted GAIA is single-admin. The gate is an ATOMIC CLAIM (a unique
    index on the constant ``slot`` discriminator admits exactly one document),
    not check-then-create: two concurrent signups on a fresh instance both read
    zero credentials, but Mongo lets precisely one insert land and the loser
    deterministically gets 403 — its half-created user row is removed again.

    A pre-existing user row with the same email is NOT claimed — knowledge of
    an email address is not proof of ownership, and a migrated WorkOS-era row
    must not be attachable by an attacker (Greptile finding). Such signups are
    refused as closed; only brand-new user rows can become the admin.
    """
    email = str(body.email)
    log.set(operation="local_signup", email=email, client_ip=_client_ip(request))

    # Fast-path pre-check only — the authoritative gate is the claim below.
    if await local_credentials_repository.any_exists():
        _registration_closed(email)

    if await user_repository.get_by_email(email) is not None:
        # Email already belongs to an existing (e.g. WorkOS-era) identity.
        # Attaching a credential to it would hand that identity to whoever
        # knows the address — knowledge of an email is not ownership proof
        # (Greptile finding). Refuse; only brand-new rows can become admin.
        _registration_closed(email)

    # Hash BEFORE creating any row: bcrypt >= 5 raises ValueError past its
    # 72-byte input cap, and hashing after the insert would strand an orphaned
    # user row on failure — locking that email out of signup forever via the
    # existing-identity gate. Request validation enforces the cap; this guard
    # keeps any hash refusal a clean 422 rather than a 500 with debris.
    try:
        password_hash = bcrypt.hashpw(
            body.password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
        ).decode()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Password must be at most 72 bytes (UTF-8 encoded)"},
        ) from exc

    user = await user_repository.create(
        UserDocument(
            email=email,
            # Hosted signups always carry a WorkOS profile name; self-host
            # name is optional. Default to the email local-part so the
            # display name (greetings, founder letter, holo card) never
            # has to handle null.
            name=body.name or email.split("@", 1)[0],
        )
    )

    credential = await local_credentials_repository.try_create(
        LocalCredentialDocument(user_id=user.id, password_hash=password_hash)
    )
    if credential is None:
        # Lost the race — another concurrent signup holds the admin slot now.
        # Remove the user row this request just created so no orphan remains.
        await _delete_user_best_effort(user.id)
        _registration_closed(email)

    token = await issue_session_token(user.id)
    log.audit("account created", actor=user.id, mode="local")

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
    credential = await local_credentials_repository.get_by_user_id(user.id) if user else None

    try:
        verified = (
            bcrypt.checkpw(body.password.encode(), credential.password_hash.encode())
            if user is not None and credential is not None
            else False
        )
    except ValueError:
        # bcrypt >= 5 refuses to process passwords past its 72-byte cap.
        # That is a wrong-password-shaped outcome, not a server error — fold
        # it into the uniform 401 below (request validation normally rejects
        # such passwords earlier with 422).
        verified = False
    if not verified:
        if user is None or credential is None:
            # Equalize cost with the wrong-password path above.
            _burn_one_verification(body.password)
        log.audit(
            "login failed",
            actor=AUDIT_ACTOR_UNAUTHENTICATED,
            email=email,
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": INVALID_CREDENTIALS,
                "message": "Invalid email or password",
            },
        )

    token = await issue_session_token(user.id)
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
    """
    log.set(operation="local_change_password", client_ip=_client_ip(request))

    credential = await local_credentials_repository.get_by_user_id(user_id)

    try:
        verified = (
            bcrypt.checkpw(body.current_password.encode(), credential.password_hash.encode())
            if credential is not None
            else False
        )
    except ValueError:
        # bcrypt >= 5 refuses inputs past its 72-byte cap — a
        # wrong-password-shaped outcome, folded into the uniform 401 below
        # exactly like login (request validation normally rejects such
        # input earlier with a 422).
        verified = False
    if not verified or credential is None:
        log.audit("password change rejected", actor=user_id)
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": INVALID_CREDENTIALS,
                "message": "Current password is incorrect",
            },
        )

    # Hash BEFORE touching the stored row: bcrypt >= 5 refuses over-cap input,
    # and a failed hash must leave the old (working) credential untouched.
    try:
        password_hash = bcrypt.hashpw(
            body.new_password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
        ).decode()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Password must be at most 72 bytes (UTF-8 encoded)"},
        ) from exc

    updated = await local_credentials_repository.update(
        credential.id, LocalCredentialUpdate(password_hash=password_hash)
    )
    if updated is None:
        # Unreachable in practice (single admin holding a live session), but a
        # vanished row must never be reported as success.
        raise HTTPException(
            status_code=500,
            detail={"message": "Password update did not persist"},
        )

    log.audit("password changed", actor=user_id)
    response = JSONResponse(status_code=200, content={"status": "ok"})
    log.set(outcome="success")
    return response


@router.post("/logout")
async def logout() -> JSONResponse:
    """Clear the session cookie. Idempotent — clearing an absent cookie still
    reports local mode so clients can branch uniformly."""
    log.set(operation="local_logout")
    response = JSONResponse(content={"mode": "local"})
    _clear_session_cookie(response)
    log.set(outcome="success")
    return response
