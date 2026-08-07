"""Device lifecycle: pairing, refresh-token rotation, server registration, listing.

Pairing follows RFC 8628 (device authorization grant): the daemon starts a
request and polls; the user approves it in a signed-in browser by its short
``user_code``. On approval a :class:`Device` row is created and a long-lived
refresh credential is issued. The daemon exchanges that credential (rotating it
each time) for short-lived connect JWTs.
"""

from __future__ import annotations

from datetime import UTC, datetime
import secrets
from urllib.parse import quote
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.device_bridge import (
    DEVICE_CATEGORY,
    DEVICE_CODE_BYTES,
    DEVICE_PAIRING_PREFIX,
    DEVICE_REFRESH_RETRY_PREFIX,
    DEVICE_TRANSPORT,
    DEVICE_USER_CODE_PREFIX,
    PAIRING_POLL_INTERVAL_SECONDS,
    PAIRING_TTL_SECONDS,
    REFRESH_TOKEN_RETRY_GRACE_SECONDS,
    USER_CODE_ALPHABET,
    USER_CODE_LENGTH,
)
from app.constants.log_tags import LogTag
from app.db.postgresql import get_db_session
from app.db.redis import get_and_delete_cache, get_cache, redis_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.helpers.mcp_helpers import get_frontend_url
from app.models.device import (
    Device,
    DeviceMCPServer,
    DeviceServerStatus,
    DeviceStatus,
)
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig
from app.schemas.device.responses import PollPairingResponse, StartPairingResponse
from app.services.device.bridge import request_revoke
from app.services.device.device_auth import (
    generate_refresh_token,
    hash_refresh_token,
)
from app.services.integrations.user_integrations import (
    add_user_integration,
    invalidate_user_integration_caches,
    remove_user_integration,
)
from shared.py.wide_events import log

PAIRING_VERIFICATION_PATH = "/settings/devices/approve"


class PairingError(Exception):
    """Raised when a pairing action can't proceed (unknown/expired/denied code)."""


def _pairing_key(device_code: str) -> str:
    return f"{DEVICE_PAIRING_PREFIX}{device_code}"


def _user_code_key(user_code: str) -> str:
    return f"{DEVICE_USER_CODE_PREFIX}{user_code}"


def _refresh_retry_key(token_hash: str) -> str:
    return f"{DEVICE_REFRESH_RETRY_PREFIX}{token_hash}"


def _generate_user_code() -> str:
    raw = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


async def start_pairing(
    name: str, platform: str | None, daemon_version: str | None
) -> StartPairingResponse:
    """Create a pending pairing and return the codes for the daemon."""
    device_code = secrets.token_urlsafe(DEVICE_CODE_BYTES)
    user_code = _generate_user_code()

    record = {
        "status": "pending",
        "name": name,
        "platform": platform,
        "daemon_version": daemon_version,
        "user_code": user_code,
        "device_id": None,
        # "refresh_token" is a schema placeholder overwritten on approval, not a
        # hardcoded credential (bandit B105 false positive).
        "refresh_token": None,  # nosec B105
    }
    stored = await set_cache(_pairing_key(device_code), record, ttl=PAIRING_TTL_SECONDS)
    code_stored = await set_cache(
        _user_code_key(user_code), {"device_code": device_code}, ttl=PAIRING_TTL_SECONDS
    )
    if not (stored and code_stored):
        raise PairingError("Could not start pairing (Redis unavailable)")

    # Do not log the user_code — it is the credential that authorizes approving
    # this pending pairing.
    log.set(device={"operation": "start_pairing"})
    base = get_frontend_url().rstrip("/")
    return StartPairingResponse(
        device_code=device_code,
        user_code=user_code,
        # Prefill the code so an approver just confirms; they must still be signed
        # in and click Approve (the code alone grants nothing).
        verification_url=f"{base}{PAIRING_VERIFICATION_PATH}?code={quote(user_code)}",
        expires_in=PAIRING_TTL_SECONDS,
        interval=PAIRING_POLL_INTERVAL_SECONDS,
    )


async def lookup_pending_by_user_code(user_code: str) -> dict | None:
    """Resolve a browser-typed ``user_code`` to its pending pairing record."""
    mapping = await get_cache(_user_code_key(user_code.strip().upper()))
    if not isinstance(mapping, dict):
        return None
    device_code = mapping.get("device_code")
    if not device_code:
        return None
    record = await get_cache(_pairing_key(device_code))
    if not isinstance(record, dict) or record.get("status") != "pending":
        return None
    return {"device_code": device_code, **record}


async def approve_pairing(user_id: str, user_code: str) -> tuple[str, str]:
    """Approve a pending pairing for ``user_id``; create the device + refresh token.

    Returns ``(device_id, name)`` rather than the ``Device`` row itself: both
    values are already known locally (they're what we just inserted), and the
    row would come back detached — accessing its attributes after the session
    below closes raises ``DetachedInstanceError`` (``session.commit()``
    expires every mapped attribute; see ``rotate_refresh_token``'s identical
    capture-before-return pattern).
    """
    normalized = user_code.strip().upper()
    pending = await lookup_pending_by_user_code(normalized)
    if not pending:
        raise PairingError("Pairing code is invalid or expired")

    device_code = pending["device_code"]
    device_id = str(uuid.uuid4())
    name = pending.get("name") or "Device"
    refresh_token = generate_refresh_token()

    device = Device(
        id=device_id,
        user_id=user_id,
        name=name,
        platform=pending.get("platform"),
        daemon_version=pending.get("daemon_version"),
        status=DeviceStatus.ACTIVE,
        refresh_token_hash=hash_refresh_token(refresh_token),
    )
    async with get_db_session() as session:
        session.add(device)
        await session.commit()

    record = {**pending}
    record.pop("device_code", None)
    record["status"] = "approved"
    record["device_id"] = device_id
    record["refresh_token"] = refresh_token
    await set_cache(_pairing_key(device_code), record, ttl=PAIRING_TTL_SECONDS)
    # The user_code is spent — drop the reverse lookup so it can't be reused.
    await get_and_delete_cache(_user_code_key(normalized))

    log.set(device={"operation": "approve_pairing", "device_id": device_id}, user={"id": user_id})
    return device_id, name


async def poll_pairing(device_code: str) -> PollPairingResponse:
    """Daemon poll. On ``approved`` the pairing is consumed and won't poll again."""
    record = await get_cache(_pairing_key(device_code))
    if not isinstance(record, dict):
        return PollPairingResponse(status="expired")

    status = record.get("status")
    if status != "approved":
        return PollPairingResponse(status="pending")

    # Consume the pairing so the refresh token is handed out exactly once.
    await redis_cache.delete(_pairing_key(device_code))
    return PollPairingResponse(
        status="approved",
        device_id=record.get("device_id"),
        refresh_token=record.get("refresh_token"),
    )


async def rotate_refresh_token(refresh_token: str) -> tuple[str, str, str]:
    """Validate + rotate a refresh credential. Returns ``(device_id, user_id, new_refresh_token)``.

    Reuse detection: a token matching ``previous_refresh_token_hash`` (already
    rotated away) means it was captured and replayed — the device is revoked and
    the exchange rejected. A brief post-rotation grace window (see
    ``REFRESH_TOKEN_RETRY_GRACE_SECONDS``) exempts the common lost-response case:
    the daemon exchanges on every dial and persists the new token only after the
    HTTP response lands, so a dropped response (or a crash before persist) leaves
    it holding the old token. Within the window the just-consumed credential is
    replayed its *same* replacement instead of bricking a healthy device.
    """
    token_hash = hash_refresh_token(refresh_token)

    # Lost-response retry: hand back the identical replacement so the daemon and
    # server stay in sync. Keyed by the consumed token's hash; expires after the
    # grace window, after which a match on ``previous_refresh_token_hash`` below
    # is treated as genuine reuse.
    cached = await get_cache(_refresh_retry_key(token_hash))
    if isinstance(cached, dict) and cached.get("new_token"):
        device_id = str(cached["device_id"])
        # Enforce revocation on the retry path too: a device revoked inside the
        # grace window must be rejected here, not handed the idempotent replay.
        if await get_active_device(device_id) is None:
            raise PairingError("Device has been revoked")
        return device_id, str(cached["user_id"]), str(cached["new_token"])

    async with get_db_session() as session:
        current = (
            await session.execute(select(Device).where(Device.refresh_token_hash == token_hash))
        ).scalar_one_or_none()

        if current is None:
            replayed = (
                await session.execute(
                    select(Device).where(Device.previous_refresh_token_hash == token_hash)
                )
            ).scalar_one_or_none()
            if replayed is not None and replayed.status == DeviceStatus.ACTIVE:
                # Capture before commit: AsyncSession forbids the implicit
                # lazy-load a post-commit attribute access on `replayed` would
                # otherwise trigger (session.commit() expires every mapped
                # attribute, including the primary key) — it raises
                # MissingGreenlet instead of transparently refetching.
                replayed_id = replayed.id
                replayed_user_id = replayed.user_id
                replayed.status = DeviceStatus.REVOKED
                integration_ids = await _device_server_integration_ids(session, replayed_id)
                await session.commit()
                # Same teardown as an explicit revoke: otherwise the device drops
                # out of the ACTIVE-only list with its integrations left dangling
                # and any live tunnel stays up until the connect JWT expires.
                await _teardown_revoked_device(replayed_user_id, replayed_id, integration_ids)
                log.warning(
                    f"{LogTag.API} Device refresh-token reuse detected — revoking device",
                    device_id=replayed_id,
                )
            raise PairingError("Refresh token is invalid")

        if current.status != DeviceStatus.ACTIVE:
            raise PairingError("Device has been revoked")

        new_token = generate_refresh_token()
        current.previous_refresh_token_hash = current.refresh_token_hash
        current.refresh_token_hash = hash_refresh_token(new_token)
        current.last_seen_at = datetime.now(UTC)
        # Capture identifiers while the row is still loaded; commit expires the
        # instance, and the caller only needs these two fields — so we avoid the
        # extra full-row SELECT that session.refresh() would issue.
        device_id, user_id = current.id, current.user_id
        await session.commit()

    await set_cache(
        _refresh_retry_key(token_hash),
        {"device_id": device_id, "user_id": user_id, "new_token": new_token},
        ttl=REFRESH_TOKEN_RETRY_GRACE_SECONDS,
    )
    return device_id, user_id, new_token


async def get_active_device(device_id: str) -> Device | None:
    async with get_db_session() as session:
        device = (
            await session.execute(select(Device).where(Device.id == device_id))
        ).scalar_one_or_none()
        if device is None or device.status != DeviceStatus.ACTIVE:
            return None
        return device


async def register_device_server(
    user_id: str, device_id: str, server_key: str, display_name: str
) -> DeviceMCPServer:
    """Register (idempotently) one MCP server a device exposes.

    Creates a device-managed integration the first time so the agent can reach
    the server's tools; re-registration (daemon restart) reuses the existing one.
    """
    async with get_db_session() as session:
        existing = (
            await session.execute(
                select(DeviceMCPServer).where(
                    DeviceMCPServer.device_id == device_id,
                    DeviceMCPServer.server_key == server_key,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.display_name = display_name
            existing.status = DeviceServerStatus.CONNECTED
            existing.error_message = None
            await session.commit()
            await session.refresh(existing)
            await _ensure_server_integration(user_id, existing)
            return existing

        integration_id = str(uuid.uuid4())
        server = DeviceMCPServer(
            device_id=device_id,
            user_id=user_id,
            integration_id=integration_id,
            server_key=server_key,
            display_name=display_name,
            status=DeviceServerStatus.CONNECTED,
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)

    await _create_server_integration(user_id, device_id, server_key, display_name, integration_id)
    return server


def _device_server_url(device_id: str, server_key: str) -> str:
    """Synthetic URL that carries routing info through the existing mcp_config shape."""
    return f"device://{device_id}/{server_key}"


async def _create_server_integration(
    user_id: str, device_id: str, server_key: str, display_name: str, integration_id: str
) -> None:
    integration = Integration(
        integration_id=integration_id,
        name=display_name,
        description=f"Local MCP server on your device ({server_key})",
        category=DEVICE_CATEGORY,
        managed_by="mcp",
        source="custom",
        is_public=False,
        created_by=user_id,
        icon_url=None,
        display_priority=0,
        is_featured=False,
        mcp_config=MCPConfig(
            server_url=_device_server_url(device_id, server_key),
            requires_auth=False,
            auth_type="none",
            transport=DEVICE_TRANSPORT,
        ),
        created_at=datetime.now(UTC),
        published_at=None,
        clone_count=0,
    )
    await integration_repository.create(integration)
    await add_user_integration(user_id, integration_id, initial_status="connected")
    await invalidate_user_integration_caches(user_id)


async def _ensure_server_integration(user_id: str, server: DeviceMCPServer) -> None:
    """Recreate the integration doc if it was deleted out from under a known server."""
    doc = await integration_repository.get(server.integration_id)
    if doc is None:
        await _create_server_integration(
            user_id,
            server.device_id,
            server.server_key,
            server.display_name,
            server.integration_id,
        )


async def list_devices(user_id: str) -> list[Device]:
    async with get_db_session() as session:
        result = await session.execute(
            select(Device)
            .where(Device.user_id == user_id, Device.status == DeviceStatus.ACTIVE)
            .order_by(Device.created_at.desc())
        )
        return list(result.scalars().all())


async def list_device_servers(device_ids: list[str]) -> dict[str, list[DeviceMCPServer]]:
    if not device_ids:
        return {}
    async with get_db_session() as session:
        result = await session.execute(
            select(DeviceMCPServer).where(DeviceMCPServer.device_id.in_(device_ids))
        )
        grouped: dict[str, list[DeviceMCPServer]] = {}
        for server in result.scalars().all():
            grouped.setdefault(server.device_id, []).append(server)
        return grouped


async def _device_server_integration_ids(session: AsyncSession, device_id: str) -> list[str]:
    """Integration ids of every MCP server a device exposes (for revoke teardown)."""
    return list(
        (
            await session.execute(
                select(DeviceMCPServer.integration_id).where(DeviceMCPServer.device_id == device_id)
            )
        ).scalars()
    )


async def _teardown_revoked_device(
    user_id: str, device_id: str, integration_ids: list[str]
) -> None:
    """Post-revocation cleanup: drop the device's server integrations and fan out a
    revoke so whichever pod owns the live socket closes it immediately."""
    for integration_id in integration_ids:
        await integration_repository.delete(integration_id)
        await remove_user_integration(user_id, integration_id)
    await request_revoke(device_id)


async def revoke_device(user_id: str, device_id: str) -> bool:
    """Revoke a device: mark revoked, tear down its server integrations, drop its socket."""
    async with get_db_session() as session:
        device = (
            await session.execute(
                select(Device).where(Device.id == device_id, Device.user_id == user_id)
            )
        ).scalar_one_or_none()
        if device is None:
            return False
        device.status = DeviceStatus.REVOKED
        integration_ids = await _device_server_integration_ids(session, device_id)
        await session.commit()

    await _teardown_revoked_device(user_id, device_id, integration_ids)
    log.set(device={"operation": "revoke", "device_id": device_id}, user={"id": user_id})
    return True
