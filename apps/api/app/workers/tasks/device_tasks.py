"""Background tasks for paired bridge devices."""

import asyncio
from typing import Any

from app.constants.log_tags import LogTag
from app.models.device import DeviceMCPServer
from app.services.device.device_service import (
    get_active_device,
    list_device_servers,
    record_device_server_sync,
)
from app.services.mcp.mcp_client import MCPClient, get_mcp_client
from shared.py.wide_events import log


async def _warm_one_server(client: MCPClient, device_id: str, server: DeviceMCPServer) -> bool:
    """Warm-connect one server, containing every failure on its own row.

    Returns True on success. A failure records the error on the server's row
    (not swallowed) and returns False — one server must never stop the others.
    """
    try:
        await client.ensure_connected(server.integration_id)
        await record_device_server_sync(server.integration_id, error=None)
        return True
    except Exception as e:
        # One server failing must not stop the others; the failure is recorded
        # on its row, not swallowed.
        await record_device_server_sync(server.integration_id, error=f"{type(e).__name__}: {e}")
        log.warning(
            f"{LogTag.MCP} Device server warm-connect failed",
            device_id=device_id,
            server_key=server.server_key,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def warm_device_servers(
    ctx: dict[str, Any],  # noqa: ARG001 -- ARQ injects ctx positionally into every task
    device_id: str,
    server_keys: list[str] | None = None,
) -> str:
    """Connect a device's MCP servers so their tools are indexed and discoverable.

    Registration only records a server; nothing indexes its tools until a session
    opens. This runs that connect off the request path (the device spawn can take
    the full open timeout), recording each outcome on the server row so the UI can
    show a tool count or an error instead of an optimistic "connected".
    """
    device = await get_active_device(device_id)
    if device is None:
        return "device inactive"

    servers = (await list_device_servers([device_id])).get(device_id, [])
    if server_keys is not None:
        wanted = set(server_keys)
        servers = [s for s in servers if s.server_key in wanted]

    client = await get_mcp_client(device.user_id)
    # Servers warm-connect concurrently: a serial loop lets one slow spawn (up
    # to the full open timeout) delay every server behind it. Each coroutine
    # contains its own failures, so one bad server cannot fail the batch.
    warmed_flags = await asyncio.gather(
        *(_warm_one_server(client, device_id, server) for server in servers)
    )
    warmed = sum(1 for ok in warmed_flags if ok)
    failed = len(warmed_flags) - warmed

    log.set(
        device={"operation": "warm_servers", "device_id": device_id},
        warmed=warmed,
        failed=failed,
    )
    return f"warmed={warmed} failed={failed}"
