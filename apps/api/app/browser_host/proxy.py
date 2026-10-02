"""Per-session CDP filtering proxy: browser-use sees and touches only its own context.

browser-use attaches to WS /cdp/{session_id} believing it owns the whole
browser; one engine actually holds every user's context. This proxy enforces:

  * getTargets replies and target events are trimmed to this session's context,
  * a command naming a browser context names this one: context-scoped commands
    that omit it are pinned to it, and any other context is refused,
  * browser-wide commands (close, crash, listing, minting or disposing
    contexts, download policy) are refused,
  * navigations go to explicit http(s) URLs only, whose host resolves public.

The live view and the host's own page session share this connection but own
their sessions on the mux, so their frames never reach this client.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from app.browser_host.pumps import pump_until_first_close
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

# Network.setBlockedURLs filters subresources only and does not stop a top-level
# navigation, so file:///etc/passwd and chrome:// are refused here, before the engine.
_ALLOWED_NAVIGATION_SCHEMES = frozenset({"http", "https"})
_NAVIGATE_METHOD = "Page.navigate"
_CREATE_TARGET_METHOD = "Target.createTarget"
_NAVIGATION_METHODS = frozenset({_NAVIGATE_METHOD, _CREATE_TARGET_METHOD})
# The engine's inert blank page, the one non-web URL the host itself opens.
_BLANK_URL = "about:blank"
# The load signal that closes a navigation's timing (see metrics.py).
_LOAD_EVENT_METHOD = "Page.loadEventFired"
# CDP's implementation-defined server-error code, used for a refused command.
_CDP_REFUSED_CODE = -32000
_CONTEXT_PARAM = "browserContextId"
_TARGET_INFOS = "targetInfos"
# Commands that act on the browser's default context when they name none: pinned
# to this session's, or they would read and write a jar every tenant shares.
_CONTEXT_DEFAULTED_METHODS = frozenset(
    {
        _CREATE_TARGET_METHOD,
        "Storage.getCookies",
        "Storage.setCookies",
        "Storage.clearCookies",
        "Browser.grantPermissions",
        "Browser.resetPermissions",
        "Browser.setPermission",
    }
)
_ACTIVATE_TARGET_METHOD = "Target.activateTarget"
# Frames the engine may get ahead of a slow client by before the proxy gives up on
# it: the mux sink cannot block, and a dropped frame desynchronises the client for good.
_DOWNSTREAM_BACKLOG_LIMIT = 10_000

_CONTEXT_LIFECYCLE_REFUSAL = "the host owns context lifecycle (one context per session)"
_BROWSER_WIDE_REFUSAL = "it reaches past this session's browser context"
# Every method this proxy refuses outright, keyed to the reason the client is
# told: one table, so a method can never be refused without one.
_REFUSAL_REASONS: dict[str, str] = {
    # Downloads are denied per context at creation; browser-use's DownloadsWatchdog would undo it.
    "Browser.setDownloadBehavior": "downloads are denied for this session",
    "Page.setDownloadBehavior": "downloads are denied for this session",
    # A client minting contexts grows memory unreaped; one disposing them could end a sibling's.
    "Target.createBrowserContext": _CONTEXT_LIFECYCLE_REFUSAL,
    "Target.disposeBrowserContext": _CONTEXT_LIFECYCLE_REFUSAL,
    "Target.getBrowserContexts": _BROWSER_WIDE_REFUSAL,
    "Browser.close": _BROWSER_WIDE_REFUSAL,
    "Browser.crash": _BROWSER_WIDE_REFUSAL,
    "Browser.crashGpuProcess": _BROWSER_WIDE_REFUSAL,
}


class _ClientTooSlow(RuntimeError):
    """Raised when the client falls further behind the engine than the backlog allows."""


def _navigation_url(message: dict[str, Any]) -> str | None:
    """Return the URL a navigation command opens, or None when it is not one or opens the blank page."""
    if message.get("method") not in _NAVIGATION_METHODS:
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    url = params.get("url")
    # An empty URL opens the blank page too.
    if not isinstance(url, str) or not url or url == _BLANK_URL:
        return None
    return url


def _refused_navigation_url(message: dict[str, Any]) -> str | None:
    """Return the URL to refuse when this command navigates anywhere but an explicit http(s) URL."""
    url = _navigation_url(message)
    if url is None:
        return None
    # CDP navigations take absolute URLs only; a scheme-less string is not resolved
    # against the current page, so it is refused like any foreign scheme.
    if urlsplit(url).scheme.lower() not in _ALLOWED_NAVIGATION_SCHEMES:
        return url
    return None


def _foreign_context(message: dict[str, Any], context_id: str) -> str | None:
    """Return the browser context a command names when it is not this session's."""
    params = message.get("params")
    if not isinstance(params, dict) or message.get("method") in _CONTEXT_DEFAULTED_METHODS:
        return None
    named = params.get(_CONTEXT_PARAM)
    return str(named) if named is not None and named != context_id else None


def _refusal_reason(message: dict[str, Any], context_id: str) -> str | None:
    """Why this client command must not reach the engine, or None to forward it."""
    method = message.get("method")
    if isinstance(method, str) and method in _REFUSAL_REASONS:
        return f"{method} refused: {_REFUSAL_REASONS[method]}"
    foreign = _foreign_context(message, context_id)
    if foreign is not None:
        return f"{method} refused: browser context {foreign} is not this session's"
    url = _refused_navigation_url(message)
    if url is not None:
        return f"navigation to {url} refused: only http and https URLs are allowed"
    return None


async def _refused_private_target(message: dict[str, Any]) -> str | None:
    """Why this navigation must not reach the engine: its host resolves to a non-public address.

    The engine resolves the name again itself, so this cannot stop DNS rebinding;
    Obscura's own resolver guard and the egress firewall are what hold there, and
    for the in-page redirects and subresources that never pass this proxy.
    """
    url = _navigation_url(message)
    if url is None:
        return None
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
        ctx = target_info.get(_CONTEXT_PARAM)
        return ctx if isinstance(ctx, str) else None
    return None


def _rewrite_upstream(
    message: dict[str, Any], context_id: str, gettargets_ids: set[int]
) -> dict[str, Any]:
    """Client -> engine: pin context-scoped commands to this context; track getTargets ids."""
    method = message.get("method")
    if method == "Target.getTargets":
        message_id = message.get("id")
        if isinstance(message_id, int):
            gettargets_ids.add(message_id)
    elif method in _CONTEXT_DEFAULTED_METHODS:
        params = message.setdefault("params", {})
        # Pinned even over a client-supplied id: a foreign or leaked one would act
        # inside another tenant's context.
        if isinstance(params, dict):
            params[_CONTEXT_PARAM] = context_id
    return message


def _filter_downstream(
    message: dict[str, Any], context_id: str, gettargets_ids: set[int]
) -> dict[str, Any] | None:
    """Engine -> client: trim getTargets, drop cross-context events. None = drop."""
    message_id = message.get("id")
    if isinstance(message_id, int) and message_id in gettargets_ids:
        gettargets_ids.discard(message_id)
        result = message.get("result")
        if isinstance(result, dict) and isinstance(result.get(_TARGET_INFOS), list):
            result[_TARGET_INFOS] = [
                ti for ti in result[_TARGET_INFOS] if ti.get(_CONTEXT_PARAM) == context_id
            ]
        return message

    method = message.get("method")
    if method in _CONTEXT_SCOPED_EVENTS:
        event_ctx = _event_context_id(message.get("params", {}))
        if event_ctx is not None and event_ctx != context_id:
            return None
    return message


def _note_command(host: ChromiumHost, session: HostSession, message: dict[str, Any]) -> None:
    """Record what a forwarded command tells the host: navigation timing, a new page, a tab brought forward."""
    method = message.get("method")
    if method == _NAVIGATE_METHOD:
        host.note_navigation_started(session.session_id)
    elif method == _CREATE_TARGET_METHOD:
        host.note_page_created(session.session_id)
    elif method == _ACTIVATE_TARGET_METHOD:
        target_id = (message.get("params") or {}).get("targetId")
        if isinstance(target_id, str):
            host.note_focus(session.session_id, target_id)


class _Bridge:
    """One client socket bridged to its session's engine connection, filtered to one context."""

    def __init__(self, host: ChromiumHost, session: HostSession, client_ws: WebSocket) -> None:
        self.host = host
        self.session = session
        self.client_ws = client_ws
        self.gettargets_ids: set[int] = set()
        self.downstream: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=_DOWNSTREAM_BACKLOG_LIMIT
        )
        self.overflowed = asyncio.Event()

    def enqueue(self, frame: dict[str, Any]) -> None:
        """Hand a frame to the drain task; runs inside the mux read loop, so it never awaits."""
        try:
            self.downstream.put_nowait(frame)
        except asyncio.QueueFull:
            self.overflowed.set()

    async def client_to_engine(self) -> None:
        """Forward each client command, refused or rewritten for this context."""
        while True:
            message = json.loads(await self.client_ws.receive_text())
            reason = _refusal_reason(message, self.session.context_id)
            reason = reason or await _refused_private_target(message)
            if reason is not None:
                await self._refuse(message, reason)
                continue
            _note_command(self.host, self.session, message)
            await self.session.mux.forward(
                _rewrite_upstream(message, self.session.context_id, self.gettargets_ids),
                self.enqueue,
            )

    async def engine_to_client(self) -> None:
        """Forward each queued engine frame this context may see back to the client."""
        while True:
            frame = await self.downstream.get()
            if frame.get("method") == _LOAD_EVENT_METHOD:
                self.host.note_navigation_finished(self.session.session_id)
            forward = _filter_downstream(frame, self.session.context_id, self.gettargets_ids)
            if forward is not None:
                await self.client_ws.send_text(json.dumps(forward))

    async def give_up_on_a_slow_client(self) -> None:
        await self.overflowed.wait()
        raise _ClientTooSlow(f"client fell {_DOWNSTREAM_BACKLOG_LIMIT} frames behind the engine")

    async def _refuse(self, message: dict[str, Any], reason: str) -> None:
        log.warning(
            f"{LogTag.BROWSER} browser cdp command refused",
            error_type="RefusedCdpCommand",
            browser={
                "session_id": self.session.session_id,
                "method": message.get("method"),
                "reason": reason,
            },
        )
        refused_id = message.get("id")
        await self.client_ws.send_text(
            _refusal_reply(refused_id if isinstance(refused_id, int) else None, reason)
        )


async def run_cdp_proxy(host: ChromiumHost, session: HostSession, client_ws: WebSocket) -> None:
    """Bridge a browser-use client socket to the session's engine connection, filtered to one context."""
    bridge = _Bridge(host, session, client_ws)
    unsubscribe = session.mux.subscribe(bridge.enqueue)
    try:
        await pump_until_first_close(
            bridge.client_to_engine(),
            bridge.engine_to_client(),
            bridge.give_up_on_a_slow_client(),
            session.mux.wait_closed(),
            sockets=(client_ws,),
        )
    finally:
        unsubscribe()
    log.set(browser={"session_id": session.session_id, "operation": "cdp_proxy_closed"})
    log.info(f"{LogTag.BROWSER} browser cdp proxy closed")
