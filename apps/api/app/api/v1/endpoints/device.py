"""Device bridge REST: pairing, token exchange, server registration, management.

Auth contexts differ per route:
  * ``/device/pair/start|poll`` and ``/device/token`` — no user session (the
    daemon isn't logged in); they self-authenticate via the pairing/refresh
    credential. Excluded from WorkOS middleware.
  * ``/device/servers`` — authenticated by the device connect JWT (the daemon).
  * everything else — a signed-in user session.
"""

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.schemas.device.requests import (
    ApprovePairingRequest,
    DeviceTokenRequest,
    PollPairingRequest,
    RegisterServerRequest,
    StartPairingRequest,
)
from app.schemas.device.responses import (
    DeviceListResponse,
    DevicePairApproveResponse,
    DeviceResponse,
    DeviceRevokeResponse,
    DeviceServerResponse,
    DeviceTokenClaims,
    DeviceTokenResponse,
    PollPairingResponse,
    RegisterServerResponse,
    StartPairingResponse,
)
from app.services.device.bridge import online_device_ids
from app.services.device.device_auth import create_device_token, verify_device_token
from app.services.device.device_service import (
    PairingError,
    approve_pairing,
    get_active_device,
    list_device_servers,
    list_devices,
    poll_pairing,
    register_device_server,
    revoke_device,
    rotate_refresh_token,
    start_pairing,
)
from shared.py.wide_events import log

router = APIRouter(prefix="/device", tags=["Device Bridge"])


async def _current_device(authorization: str = Header(default="")) -> DeviceTokenClaims:
    """Resolve the device from its connect JWT, or 401.

    Re-checks the device is still active (mirrors the WS handler): a revoked
    device must not act on a still-valid connect JWT, or it could re-register the
    server integrations the revoke just deleted, up to the token TTL.
    """
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    info = verify_device_token(token) if token else None
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or missing device token")
    device = await get_active_device(info["device_id"])
    if device is None or device.user_id != info["user_id"]:
        raise HTTPException(status_code=401, detail="Device is not active")
    return info


@router.post("/pair/start")
async def pair_start(payload: StartPairingRequest) -> StartPairingResponse:
    """Start a device pairing request (RFC 8628); returns the codes for the daemon."""
    log.set(device={"operation": "pair_start", "name": payload.name})
    try:
        return await start_pairing(payload.name, payload.platform, payload.daemon_version)
    except PairingError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/pair/poll")
async def pair_poll(payload: PollPairingRequest) -> PollPairingResponse:
    """Daemon polls for the user's browser approval of a pending pairing."""
    return await poll_pairing(payload.device_code)


@router.post("/pair/approve", status_code=200)
async def pair_approve(
    payload: ApprovePairingRequest, user_id: str = Depends(get_user_id)
) -> DevicePairApproveResponse:
    """Approve a pending pairing from the signed-in browser by its short user code."""
    log.set(device={"operation": "pair_approve"}, user={"id": user_id})
    try:
        device_id, name = await approve_pairing(user_id, payload.user_code)
    except PairingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DevicePairApproveResponse(device_id=device_id, name=name)


@router.post("/token")
async def device_token(payload: DeviceTokenRequest) -> DeviceTokenResponse:
    """Exchange (and rotate) the refresh credential for a short-lived connect JWT."""
    try:
        device_id, user_id, new_refresh = await rotate_refresh_token(payload.refresh_token)
    except PairingError as e:
        raise HTTPException(status_code=401, detail=str(e))
    access_token, expires_in = create_device_token(device_id, user_id)
    log.set(device={"operation": "token_exchange", "device_id": device_id})
    return DeviceTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=new_refresh,
    )


@router.post("/servers")
async def register_server(
    payload: RegisterServerRequest, device: DeviceTokenClaims = Depends(_current_device)
) -> RegisterServerResponse:
    """Register (or re-register) one MCP server the device exposes; authed by the device JWT."""
    log.set(
        device={"operation": "register_server", "id": device["device_id"]},
        user={"id": device["user_id"]},
    )
    server = await register_device_server(
        device["user_id"], device["device_id"], payload.server_key, payload.display_name
    )
    return RegisterServerResponse(
        integration_id=server.integration_id, server_key=server.server_key
    )


@router.get("/list")
async def list_user_devices(user_id: str = Depends(get_user_id)) -> DeviceListResponse:
    """List the current user's active devices with their online status and servers."""
    devices = await list_devices(user_id)
    device_ids = [d.id for d in devices]
    online = await online_device_ids(device_ids)
    servers_by_device = await list_device_servers(device_ids)

    responses: list[DeviceResponse] = []
    for device in devices:
        servers = servers_by_device.get(device.id, [])
        responses.append(
            DeviceResponse(
                id=device.id,
                name=device.name,
                platform=device.platform,
                daemon_version=device.daemon_version,
                status=device.status.value,
                online=device.id in online,
                last_seen_at=device.last_seen_at,
                created_at=device.created_at,
                servers=[
                    DeviceServerResponse(
                        server_key=s.server_key,
                        display_name=s.display_name,
                        integration_id=s.integration_id,
                        status=s.status.value,
                        tools_synced_at=s.tools_synced_at,
                    )
                    for s in servers
                ],
            )
        )
    return DeviceListResponse(devices=responses)


@router.delete("/{device_id}", status_code=200)
async def revoke(device_id: str, user_id: str = Depends(get_user_id)) -> DeviceRevokeResponse:
    """Revoke a device and tear down its server integrations."""
    if not await revoke_device(user_id, device_id):
        raise HTTPException(status_code=404, detail="Device not found")
    return DeviceRevokeResponse(device_id=device_id, status="revoked")
