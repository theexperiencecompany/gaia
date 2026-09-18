"""Device lifecycle: pairing, refresh-token rotation, server registration, listing.

Pairing follows RFC 8628 (device authorization grant): the daemon starts a
request and polls; the user approves it in a signed-in browser by its short
user_code. On approval a :class:Device row is created and a long-lived
refresh credential is issued. The daemon exchanges that credential (rotating it
each time) for short-lived connect JWTs.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import secrets
from urllib.parse import quote
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.cache import DEVICE_MANIFEST_CACHE_PREFIX, ONE_DAY_TTL
from app.constants.device_bridge import (
    DEVICE_CATEGORY,
    DEVICE_CODE_BYTES,
    DEVICE_PAIRING_PREFIX,
    DEVICE_REFRESH_RETRY_PREFIX,
    DEVICE_TRANSPORT,
    DEVICE_USER_CODE_PREFIX,
    DEVICE_WARMUP_COALESCE_PREFIX,
    DEVICE_WARMUP_COALESCE_SECONDS,
    FRAME_SERVER_REMOVE,
    MAX_ACTIVE_DEVICES_PER_USER,
    PAIRING_POLL_INTERVAL_SECONDS,
    PAIRING_TTL_SECONDS,
    REFRESH_TOKEN_RETRY_GRACE_SECONDS,
    USER_CODE_ALPHABET,
    USER_CODE_LENGTH,
    DeviceServerKind,
)
from app.constants.log_tags import LogTag
from app.db.postgresql import get_db_session
from app.db.redis import get_and_delete_cache, get_cache, redis_cache, set_cache
from app.db.repositories.cache import CachePolicy, bump_generation, read_generation
from app.db.repositories.integrations import integration_repository
from app.helpers.integration_helpers import dedup_server_url_key
from app.helpers.mcp_helpers import get_frontend_url
from app.models.device import (
    Device,
    DeviceMCPServer,
    DeviceServerStatus,
    DeviceStatus,
)
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig
from app.schemas.device.manifest import DeviceManifestEntry
from app.schemas.device.responses import PollPairingResponse, StartPairingResponse
from app.services.device.bridge import request_revoke, send_down
from app.services.device.device_auth import (
    generate_refresh_token,
    hash_refresh_token,
)
from app.services.integrations.user_integrations import (
    add_user_integration,
    invalidate_user_integration_caches,
    remove_user_integration,
)
from app.utils.errors import create_error
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
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


def build_device_approve_url(user_code: str) -> str:
    """Build the signed-in approval page URL with the pairing code prefilled.

    The user, not the agent, must be signed in to confirm linking the device.
    """
    base = get_frontend_url().rstrip("/")
    return f"{base}{PAIRING_VERIFICATION_PATH}?code={quote(user_code.strip().upper())}"


async def lookup_pending_by_user_code(user_code: str) -> dict | None:
    """Resolve a browser-typed user_code to its pending pairing record."""
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


async def _create_device(
    user_id: str,
    name: str,
    platform: str | None,
    daemon_version: str | None,
    client: str | None,
) -> tuple[str, str]:
    """Create an ACTIVE device for user_id and mint its refresh credential.

    The one place a device row is inserted, shared by the browser-approval and
    desktop self-pair flows, so the per-user active-device cap is enforced once
    for both. Returns (device_id, refresh_token); the caller captures these
    before the session closes rather than reading them off the expired row.
    """
    device_id = str(uuid.uuid4())
    refresh_token = generate_refresh_token()
    device = Device(
        id=device_id,
        user_id=user_id,
        name=name,
        platform=platform,
        daemon_version=daemon_version,
        client=client,
        status=DeviceStatus.ACTIVE,
        refresh_token_hash=hash_refresh_token(refresh_token),
    )
    async with get_db_session() as session:
        active_count = (
            await session.execute(
                select(func.count())
                .select_from(Device)
                .where(Device.user_id == user_id, Device.status == DeviceStatus.ACTIVE)
            )
        ).scalar_one()
        if active_count >= MAX_ACTIVE_DEVICES_PER_USER:
            raise create_error(
                message="Device limit reached",
                why=f"You already have {MAX_ACTIVE_DEVICES_PER_USER} active devices.",
                fix="Revoke a device you no longer use, then pair this one again.",
                status_code=409,
            )
        session.add(device)
        await session.commit()
    await _invalidate_device_manifest(user_id)
    return device_id, refresh_token


async def approve_pairing(user_id: str, user_code: str) -> tuple[str, str]:
    """Approve a pending pairing for user_id; create the device + refresh token.

    Returns (device_id, name) rather than the Device row itself, since the row
    comes back detached after the session below closes (session.commit()
    expires every mapped attribute, so accessing it raises DetachedInstanceError).
    """
    normalized = user_code.strip().upper()
    pending = await lookup_pending_by_user_code(normalized)
    if not pending:
        raise PairingError("Pairing code is invalid or expired")

    device_code = pending["device_code"]
    name = pending.get("name") or "Device"
    # CLI-paired devices keep client NULL for now (client-aware tooling is a
    # later task); only the desktop self-pair path stamps a client.
    device_id, refresh_token = await _create_device(
        user_id, name, pending.get("platform"), pending.get("daemon_version"), client=None
    )

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


async def self_pair_device(
    user_id: str,
    name: str,
    platform: str,
    client: str,
    daemon_version: str | None,
) -> tuple[str, str]:
    """Pair a device for an already-authenticated user in one call.

    A UX collapse of the browser start→approve→poll flow for a host that already
    holds the user's session (the desktop app): no user_code round-trip. The
    refresh token is returned inline, since the same caller both pairs and stores
    it. Returns (device_id, refresh_token).
    """
    device_id, refresh_token = await _create_device(
        user_id, name, platform, daemon_version, client=client
    )
    log.set(device={"operation": "self_pair", "device_id": device_id}, user={"id": user_id})
    return device_id, refresh_token


async def poll_pairing(device_code: str) -> PollPairingResponse:
    """Daemon poll. On approved the pairing is consumed and won't poll again."""
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
    """Validate + rotate a refresh credential. Returns (device_id, user_id, new_refresh_token).

    A token matching previous_refresh_token_hash means it was captured and
    replayed — the device is revoked and the exchange rejected. Within a brief
    post-rotation grace window (REFRESH_TOKEN_RETRY_GRACE_SECONDS), a lost HTTP
    response is instead handed the same replacement rather than bricking the device.
    """
    token_hash = hash_refresh_token(refresh_token)

    # Lost-response retry, keyed by the consumed token's hash; expires after the
    # grace window, after which a match below is treated as genuine reuse.
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
                # Capture before commit: session.commit() expires every mapped
                # attribute, and a post-commit access would raise MissingGreenlet
                # rather than transparently refetch.
                replayed_id = replayed.id
                replayed_user_id = replayed.user_id
                replayed.status = DeviceStatus.REVOKED
                integration_ids = await _device_server_integration_ids(session, replayed_id)
                await session.commit()
                # Same teardown as an explicit revoke: otherwise the device drops
                # out of the ACTIVE-only list with its integrations left dangling
                # and any live tunnel stays up until the connect JWT expires.
                await _invalidate_device_manifest(replayed_user_id)
                await _teardown_revoked_device(replayed_user_id, replayed_id, integration_ids)
                log.warning(
                    f"{LogTag.API} Device refresh-token reuse detected — revoking device",
                    device_id=replayed_id,
                )
                # Audited here, not in the route: this is where the revocation
                # lands. The caller only sees a generic PairingError, so a
                # handler-level record could not tell reuse from an unknown token.
                log.audit(
                    "device revoked",
                    actor=replayed_user_id,
                    resource=replayed_id,
                    reason="refresh_token_reuse",
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
    user_id: str,
    device_id: str,
    server_key: str,
    display_name: str,
    kind: DeviceServerKind = "stdio",
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
            existing.kind = kind
            existing.status = DeviceServerStatus.CONNECTED
            existing.error_message = None
            await session.commit()
            await _invalidate_device_manifest(user_id)
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
            kind=kind,
            status=DeviceServerStatus.CONNECTED,
        )
        session.add(server)
        await session.commit()
        await _invalidate_device_manifest(user_id)
        await session.refresh(server)

    await _create_server_integration(user_id, device_id, server_key, display_name, integration_id)
    return server


def _device_server_url(device_id: str, server_key: str) -> str:
    """Synthetic URL that carries routing info through the existing mcp_config shape."""
    return f"device://{device_id}/{server_key}"


async def _device_display_name(device_id: str) -> str:
    """Return the paired device's name, or a fallback if the row is gone (self-heal races)."""
    async with get_db_session() as session:
        name = (
            await session.execute(select(Device.name).where(Device.id == device_id))
        ).scalar_one_or_none()
    return name or "this device"


async def _create_server_integration(
    user_id: str, device_id: str, server_key: str, display_name: str, integration_id: str
) -> None:
    device_name = await _device_display_name(device_id)
    # Synthetic device:// URL, so the dedup key is total — but compute it through
    # the same canonical helper as every other custom integration.
    device_url = _device_server_url(device_id, server_key)
    integration = Integration(
        integration_id=integration_id,
        name=display_name,
        # The subagent's discovery description inherits this: it's how the agent
        # learns the server is on the user's machine, reached via these tools
        # (not run_on_device). Names the device to match the manifest.
        description=(
            f'MCP server hosted on your device "{device_name}". Its tools run '
            f"locally on that machine, not the cloud sandbox."
        ),
        category=DEVICE_CATEGORY,
        managed_by="mcp",
        source="custom",
        is_public=False,
        created_by=user_id,
        icon_url=None,
        display_priority=0,
        is_featured=False,
        mcp_config=MCPConfig(
            server_url=device_url,
            server_url_normalized=dedup_server_url_key(device_url),
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


async def _remove_server_cloud_mirror(user_id: str, integration_id: str) -> None:
    """Drop a device server's cloud-side mirror: the integration doc, user link, and caches.

    The Postgres row is deleted by callers, not here.
    """
    await integration_repository.delete(integration_id)
    await remove_user_integration(user_id, integration_id)
    await invalidate_user_integration_caches(user_id)


async def _send_server_remove(device_id: str, server_key: str) -> None:
    """Tell the daemon to drop a server from its local config (best-effort).

    Delivered only if the device is online; on a miss the HELLO reconcile on the
    next connect is the backstop, unless the daemon still has it configured.
    """
    try:
        await send_down(device_id, {"t": FRAME_SERVER_REMOVE, "key": server_key})
    except Exception as e:
        log.warning(
            f"{LogTag.API} Failed to send server-remove to device",
            device_id=device_id,
            server_key=server_key,
            error=str(e),
            error_type=type(e).__name__,
        )


async def deregister_device_server(
    user_id: str, device_id: str, server_key: str, *, notify_device: bool
) -> bool:
    """Fully remove one device MCP server: Postgres row plus cloud mirror.

    Deleting the Postgres row is what stops _ensure_server_integration from
    resurrecting the doc. Returns False if the server was already gone.
    """
    async with get_db_session() as session:
        server = (
            await session.execute(
                select(DeviceMCPServer).where(
                    DeviceMCPServer.device_id == device_id,
                    DeviceMCPServer.server_key == server_key,
                )
            )
        ).scalar_one_or_none()
        if server is None:
            return False
        integration_id = server.integration_id
        await session.delete(server)
        await session.commit()

    await _invalidate_device_manifest(user_id)
    await _remove_server_cloud_mirror(user_id, integration_id)
    if notify_device:
        await _send_server_remove(device_id, server_key)
    return True


async def deregister_device_server_for_integration(
    integration_id: str, *, notify_device: bool
) -> bool:
    """Delete the Postgres server row behind an integration.

    Its Mongo mirror is torn down by the integration-delete path that calls
    this; used when a device integration is deleted from the integrations page.
    Returns False if not a device server.
    """
    async with get_db_session() as session:
        server = (
            await session.execute(
                select(DeviceMCPServer).where(DeviceMCPServer.integration_id == integration_id)
            )
        ).scalar_one_or_none()
        if server is None:
            return False
        device_id, server_key = server.device_id, server.server_key
        server_user_id = server.user_id
        await session.delete(server)
        await session.commit()

    await _invalidate_device_manifest(server_user_id)
    if notify_device:
        await _send_server_remove(device_id, server_key)
    return True


async def reconcile_device_servers(user_id: str, device_id: str, reported_keys: list[str]) -> None:
    """Prune server rows the daemon no longer exposes.

    The device's local config is the source of truth. Driven by the HELLO
    frame the daemon sends on connect.
    """
    reported = set(reported_keys)
    servers = (await list_device_servers([device_id])).get(device_id, [])
    stale = [s for s in servers if s.server_key not in reported]
    for server in stale:
        await deregister_device_server(user_id, device_id, server.server_key, notify_device=False)
    if stale:
        log.set(
            device={"operation": "reconcile_servers", "device_id": device_id},
            pruned=len(stale),
        )


#: Generation scoped so a write orphans the previous manifest key: a read that
#: computed before the write and stores after it lands under the old generation
#: and is never served. The TTL only bounds orphaned keys.
_DEVICE_MANIFEST_POLICY = CachePolicy(prefix=DEVICE_MANIFEST_CACHE_PREFIX, query_ttl=ONE_DAY_TTL)


async def get_device_manifest(user_id: str) -> list[DeviceManifestEntry]:
    """Return the user's active devices and the servers they expose, cached per user.

    Keys are generation scoped: _invalidate_device_manifest bumps the user's
    generation on every structural device/server write, orphaning the old entry.
    build_connected_devices_manifest reads this once per turn instead of paying
    two Postgres queries.
    """
    policy = _DEVICE_MANIFEST_POLICY
    generation = await read_generation(policy, user_id)
    key: str | None = None
    if generation is not None:
        key = policy.query_key(user_id, generation, "manifest", "v1")
        cached = await get_cache(key, model=list[DeviceManifestEntry])
        if cached is not None:
            return cached
    manifest = await _compute_device_manifest(user_id)
    if key is not None:
        await set_cache(key, manifest, ttl=policy.query_ttl, model=list[DeviceManifestEntry])
    return manifest


async def _compute_device_manifest(user_id: str) -> list[DeviceManifestEntry]:
    devices = await list_devices(user_id)
    if not devices:
        return []
    servers_by_device = await list_device_servers([device.id for device in devices])
    return [
        DeviceManifestEntry(
            id=device.id,
            name=device.name,
            platform=device.platform,
            servers=[server.display_name for server in servers_by_device.get(device.id, [])],
        )
        for device in devices
    ]


async def _invalidate_device_manifest(user_id: str) -> None:
    """Orphan the user's cached device manifest after a structural write."""
    await bump_generation(_DEVICE_MANIFEST_POLICY, user_id)


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


async def record_device_server_sync(integration_id: str, *, error: str | None = None) -> None:
    """Stamp a device server's warm-connect outcome (connected+synced, or an error)."""
    async with get_db_session() as session:
        server = (
            await session.execute(
                select(DeviceMCPServer).where(DeviceMCPServer.integration_id == integration_id)
            )
        ).scalar_one_or_none()
        if server is None:
            # Revoked mid-warmup — nothing to record.
            return
        if error is None:
            server.status = DeviceServerStatus.CONNECTED
            server.error_message = None
            server.tools_synced_at = datetime.now(UTC)
        else:
            server.status = DeviceServerStatus.ERROR
            server.error_message = error[:2000]
        await session.commit()


async def enqueue_device_server_warmup(
    device_id: str, server_keys: list[str] | None = None
) -> None:
    """Queue a background warm-connect so a device's MCP tools become discoverable.

    Bursts collapse into one job via a deterministic ARQ job id; repeats past
    the job's life are skipped by a short-TTL SETNX marker instead. Best-effort:
    a Redis outage raises, and the caller falls back to the next connect
    re-driving the warmup.
    """
    scope = ",".join(sorted(server_keys)) if server_keys is not None else "all"
    work_key = hashlib.sha256(scope.encode()).hexdigest()
    marker = f"{DEVICE_WARMUP_COALESCE_PREFIX}{device_id}:{work_key}"
    claimed = await redis_cache.client.set(marker, "1", nx=True, ex=DEVICE_WARMUP_COALESCE_SECONDS)
    if not claimed:
        return
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        "warm_device_servers",
        device_id,
        server_keys,
        _job_id=f"device-warmup:{device_id}:{work_key}",
    )


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
    """Drop the device's server integrations and fan out a revoke to close its live socket."""
    for integration_id in integration_ids:
        await integration_repository.delete(integration_id)
        await remove_user_integration(user_id, integration_id)
    # Drop the device's server rows too, so a revoked device leaves nothing
    # dangling behind (the FK cascade only fires on a hard device delete).
    async with get_db_session() as session:
        await session.execute(delete(DeviceMCPServer).where(DeviceMCPServer.device_id == device_id))
        await session.commit()
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

    await _invalidate_device_manifest(user_id)
    await _teardown_revoked_device(user_id, device_id, integration_ids)
    log.set(device={"operation": "revoke", "device_id": device_id}, user={"id": user_id})
    return True
