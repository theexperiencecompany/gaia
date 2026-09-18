"""Per-session CDP filtering proxy: browser-use sees only its own context.

browser-use attaches to WS /cdp/{session_id} believing it owns the whole
browser; one engine actually holds every user's context. This proxy enforces:

  * Target.getTargets responses are trimmed to this session's context,
  * cross-context attachedToTarget / targetCreated / targetInfoChanged
    events are dropped,
  * Target.createTarget requests are pinned to this context,
  * navigations are allowlisted to http/https (no file:// or chrome://),
  * setDownloadBehavior is refused, so the per-context deny cannot be undone.

Everything else passes through, and any traffic bumps the session's activity
clock. The live view shares this engine connection but claims its own page
session on the mux, so its frames never reach this client.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from app.browser_host.pumps import pump_until_first_close
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.utils.url_safety import assert_public_http_url
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


# Navigation is allowlisted to the schemes a web task needs. It must happen here:
# Network.setBlockedURLs filters subresources only and does not stop a top-level
# navigation, so file:///etc/passwd and chrome:// are refused before Chromium sees them.
_ALLOWED_NAVIGATION_SCHEMES = frozenset({"http", "https"})
_NAVIGATION_METHODS = frozenset({"Page.navigate", "Target.createTarget"})
# Chromium's inert blank page — the one non-web URL the host itself opens.
_BLANK_URL = "about:blank"
# The load signal that closes a navigation's timing (see metrics.py).
_LOAD_EVENT_METHOD = "Page.loadEventFired"
# CDP's implementation-defined server-error code, used for a refused command.
_CDP_REFUSED_CODE = -32000
# The mux sink is sync and cannot block, so a full queue could only drop a frame,
# and a dropped reply or event desynchronises the client's protocol state forever.
_DOWNSTREAM_QUEUE_UNBOUNDED = 0

# Every method this proxy refuses, keyed to the reason the client is told: one
# table, so a method can never be refused without one. Downloads are denied per
# context at creation (chromium.py) and browser-use's DownloadsWatchdog would undo it.
_REFUSAL_REASONS: dict[str, str] = {
    "Browser.setDownloadBehavior": "downloads are denied for this session",
    "Page.setDownloadBehavior": "downloads are denied for this session",
    # The host owns the context lifecycle (capacity/reaper/recovery accounting).
    # A client minting contexts would grow memory un-capped and un-reaped; one
    # disposing them could kill a sibling session's isolation.
    "Target.createBrowserContext": "the host owns context lifecycle (one context per session)",
    "Target.disposeBrowserContext": "the host owns context lifecycle (one context per session)",
}


def _navigation_url(message: dict[str, Any]) -> str | None:
    """Return the URL a navigation command opens, or None when it is not one or opens nothing."""
    if message.get("method") not in _NAVIGATION_METHODS:
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    url = params.get("url")
    if not isinstance(url, str) or not url or url == _BLANK_URL:
        return None
    return url


def _refused_navigation_url(message: dict[str, Any]) -> str | None:
    """Return the URL to refuse when this command navigates outside http(s), else None."""
    url = _navigation_url(message)
    if url is None:
        return None
    scheme = urlsplit(url).scheme.lower()
    # An empty scheme is a relative/implicit URL, which Chromium resolves against
    # the current http(s) document — only an explicit foreign scheme is a refusal.
    if scheme and scheme not in _ALLOWED_NAVIGATION_SCHEMES:
        return url
    return None


def _refusal_reason(message: dict[str, Any]) -> str | None:
    """Why this client command must not reach Chromium, or None to forward it."""
    method = message.get("method")
    if isinstance(method, str) and method in _REFUSAL_REASONS:
        return f"{method} refused: {_REFUSAL_REASONS[method]}"
    url = _refused_navigation_url(message)
    if url is not None:
        return f"navigation to {url} refused: only http and https are allowed"
    return None


async def _refused_private_target(message: dict[str, Any]) -> str | None:
    """Why this navigation must not reach Chromium: its host resolves to a non-public address.

    Resolved right before the command is forwarded, so DNS rebinding cannot slip
    an address past an earlier check. The first line of SSRF defence for a
    model- or user-supplied URL; the deployment egress firewall stays the second,
    because in-page redirects and subresources never pass through this proxy.
    """
    if settings.BROWSER_HOST_ALLOW_PRIVATE_NETWORK:
        return None
    url = _navigation_url(message)
    if url is None or urlsplit(url).scheme.lower() not in _ALLOWED_NAVIGATION_SCHEMES:
        return None  # relative URLs stay on the current document; foreign schemes are refused above
    try:
        await assert_public_http_url(url)
    except ValueError as exc:
        return f"navigation to {url} refused: {exc}"
    return None


def _refusal_reply(message_id: int | None, reason: str) -> str:
    """Build a CDP error reply, so a refused command fails the caller instead of hanging it."""
    return json.dumps({"id": message_id, "error": {"code": _CDP_REFUSED_CODE, "message": reason}})


def _event_context_id(params: dict[str, Any]) -> str | None:
    target_info = params.get("targetInfo")
    if isinstance(target_info, dict):
        ctx = target_info.get("browserContextId")
        return ctx if isinstance(ctx, str) else None
    return None


def _rewrite_upstream(
    message: dict[str, Any], context_id: str, gettargets_ids: set[int]
) -> dict[str, Any]:
    """Client -> engine: pin createTarget to this context; track getTargets ids."""
    method = message.get("method")
    if method == "Target.getTargets":
        message_id = message.get("id")
        if isinstance(message_id, int):
            gettargets_ids.add(message_id)
    elif method == "Target.createTarget":
        params = message.setdefault("params", {})
        # Always pin to THIS session's context — even when the client supplied
        # its own browserContextId (a foreign/leaked id would otherwise create a
        # page inside another tenant's context).
        if isinstance(params, dict):
            params["browserContextId"] = context_id
    return message


def _filter_downstream(
    message: dict[str, Any], context_id: str, gettargets_ids: set[int]
) -> dict[str, Any] | None:
    """Engine -> client: trim getTargets, drop cross-context events. None = drop."""
    message_id = message.get("id")
    if isinstance(message_id, int) and message_id in gettargets_ids:
        gettargets_ids.discard(message_id)
        result = message.get("result")
        if isinstance(result, dict) and isinstance(result.get("targetInfos"), list):
            result["targetInfos"] = [
                ti for ti in result["targetInfos"] if ti.get("browserContextId") == context_id
            ]
        return message

    method = message.get("method")
    if method in _CONTEXT_SCOPED_EVENTS:
        event_ctx = _event_context_id(message.get("params", {}))
        if event_ctx is not None and event_ctx != context_id:
            return None
    return message


async def run_cdp_proxy(host: ChromiumHost, session: HostSession, client_ws: WebSocket) -> None:
    """Bridge a browser-use client socket to the session's engine connection, filtered to one context."""
    gettargets_ids: set[int] = set()
    downstream: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_DOWNSTREAM_QUEUE_UNBOUNDED)

    def enqueue(frame: dict[str, Any]) -> None:
        """Hand a frame to the drain task; runs inside the mux read loop, so it never awaits."""
        downstream.put_nowait(frame)

    async def client_to_engine() -> None:
        """Forward one upstream-cleaned frame from the client to the engine."""
        while True:
            raw = await client_ws.receive_text()
            host.touch(session.session_id)
            message = json.loads(raw)
            reason = _refusal_reason(message) or await _refused_private_target(message)
            if reason is not None:
                log.warning(
                    f"{LogTag.BROWSER} browser cdp command refused",
                    error_type="RefusedCdpCommand",
                    browser={"session_id": session.session_id, "reason": reason},
                )
                refused_id = message.get("id")
                await client_ws.send_text(
                    _refusal_reply(refused_id if isinstance(refused_id, int) else None, reason)
                )
                continue
            if message.get("method") == "Page.navigate":
                host.note_navigation_started(session.session_id)
            elif message.get("method") == "Target.createTarget":
                host.note_page_created(session.session_id)
            await session.mux.forward(
                _rewrite_upstream(message, session.context_id, gettargets_ids), enqueue
            )

    async def engine_to_client() -> None:
        """Forward one queued frame from the engine back to the client."""
        while True:
            frame = await downstream.get()
            host.touch(session.session_id)
            if frame.get("method") == _LOAD_EVENT_METHOD:
                host.note_navigation_finished(session.session_id)
            forward = _filter_downstream(frame, session.context_id, gettargets_ids)
            if forward is not None:
                await client_ws.send_text(json.dumps(forward))

    unsubscribe = session.mux.subscribe(enqueue)
    try:
        await pump_until_first_close(
            client_to_engine(), engine_to_client(), session.mux.wait_closed()
        )
    finally:
        unsubscribe()
    log.set(browser={"session_id": session.session_id, "operation": "cdp_proxy_closed"})
    log.info(f"{LogTag.BROWSER} browser cdp proxy closed")
