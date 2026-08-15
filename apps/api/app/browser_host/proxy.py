"""Per-session CDP filtering proxy: browser-use sees only its own context.

browser-use attaches to ``WS /cdp/{session_id}`` believing it owns the whole
browser. It does not — one Chromium holds every user's context. This proxy sits
between browser-use and Chromium's single root websocket and enforces the
illusion of a private browser:

  * ``Target.getTargets`` responses are trimmed to this session's context,
  * cross-context ``attachedToTarget`` / ``targetCreated`` / ``targetInfoChanged``
    events are dropped so browser-use can never attach to another user's page,
  * ``Target.createTarget`` requests are pinned to this context so new tabs
    stay inside it.

Everything else passes through untouched, and any traffic bumps the session's
activity clock so the idle reaper leaves an in-use session alone.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import websockets

from app.browser_host.pumps import pump_until_first_close
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from fastapi import WebSocket

    from app.browser_host.chromium import ChromiumHost, HostSession

# Downstream events that leak other contexts unless filtered by browserContextId.
_CONTEXT_SCOPED_EVENTS = frozenset(
    {
        "Target.attachedToTarget",
        "Target.targetCreated",
        "Target.targetInfoChanged",
    }
)


def _event_context_id(params: dict[str, Any]) -> str | None:
    target_info = params.get("targetInfo")
    if isinstance(target_info, dict):
        ctx = target_info.get("browserContextId")
        return ctx if isinstance(ctx, str) else None
    return None


def _rewrite_upstream(raw: str, context_id: str, gettargets_ids: set[int]) -> str:
    """Client -> Chromium: pin ``createTarget`` to this context; track getTargets ids."""
    message = json.loads(raw)
    method = message.get("method")
    if method == "Target.getTargets":
        message_id = message.get("id")
        if isinstance(message_id, int):
            gettargets_ids.add(message_id)
    elif method == "Target.createTarget":
        params = message.setdefault("params", {})
        if isinstance(params, dict) and not params.get("browserContextId"):
            params["browserContextId"] = context_id
            return json.dumps(message)
    return raw


def _filter_downstream(raw: str, context_id: str, gettargets_ids: set[int]) -> str | None:
    """Chromium -> client: trim getTargets, drop cross-context events. None = drop."""
    message = json.loads(raw)

    message_id = message.get("id")
    if isinstance(message_id, int) and message_id in gettargets_ids:
        gettargets_ids.discard(message_id)
        result = message.get("result")
        if isinstance(result, dict) and isinstance(result.get("targetInfos"), list):
            result["targetInfos"] = [
                ti for ti in result["targetInfos"] if ti.get("browserContextId") == context_id
            ]
            return json.dumps(message)
        return raw

    method = message.get("method")
    if method in _CONTEXT_SCOPED_EVENTS:
        event_ctx = _event_context_id(message.get("params", {}))
        if event_ctx is not None and event_ctx != context_id:
            return None
    return raw


async def run_cdp_proxy(host: ChromiumHost, session: HostSession, client_ws: WebSocket) -> None:
    """Bridge a browser-use client socket to Chromium, filtered to one context."""
    gettargets_ids: set[int] = set()
    async with websockets.connect(
        host.root_ws_url, max_size=None, ping_interval=None
    ) as chromium_ws:

        async def client_to_chromium() -> None:
            while True:
                raw = await client_ws.receive_text()
                host.touch(session.session_id)
                await chromium_ws.send(_rewrite_upstream(raw, session.context_id, gettargets_ids))

        async def chromium_to_client() -> None:
            async for raw in chromium_ws:
                host.touch(session.session_id)
                text = raw if isinstance(raw, str) else raw.decode()
                forward = _filter_downstream(text, session.context_id, gettargets_ids)
                if forward is not None:
                    await client_ws.send_text(forward)

        await pump_until_first_close(client_to_chromium(), chromium_to_client())
    log.set(browser={"session_id": session.session_id, "operation": "cdp_proxy_closed"})
    log.info(f"{LogTag.BROWSER} browser cdp proxy closed")
