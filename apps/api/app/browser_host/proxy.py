"""Per-session CDP filtering proxy: browser-use sees only its own context.

browser-use attaches to ``WS /cdp/{session_id}`` believing it owns the whole
browser. It does not — one Chromium holds every user's context. This proxy sits
between browser-use and Chromium's single root websocket and enforces the
illusion of a private browser:

  * ``Target.getTargets`` responses are trimmed to this session's context,
  * cross-context ``attachedToTarget`` / ``targetCreated`` / ``targetInfoChanged``
    events are dropped so browser-use can never attach to another user's page,
  * ``Target.createTarget`` requests are pinned to this context so new tabs
    stay inside it,
  * navigations are allowlisted to http/https, so a prompt-injected page cannot
    steer the browser at ``file://`` or ``chrome://``,
  * ``setDownloadBehavior`` is refused, so the deny the host set at context
    creation cannot be undone from this socket.

Everything else passes through untouched, and any traffic bumps the session's
activity clock so the idle reaper leaves an in-use session alone.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

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


# The agent follows attacker-influenced links, so navigation is allowlisted to the
# schemes a web task legitimately needs. This has to happen here rather than in
# Chromium: `Network.setBlockedURLs` filters subresources only and does not stop a
# top-level navigation, so `file:///etc/passwd` and `chrome://` are refused before
# Chromium ever sees the command.
_ALLOWED_NAVIGATION_SCHEMES = frozenset({"http", "https"})
_NAVIGATION_METHODS = frozenset({"Page.navigate", "Target.createTarget"})
# Chromium's inert blank page — the one non-web URL the host itself opens.
_BLANK_URL = "about:blank"
# The load signal that closes a navigation's timing (see metrics.py).
_LOAD_EVENT_METHOD = "Page.loadEventFired"
# CDP's implementation-defined server-error code, used for a refused command.
_CDP_REFUSED_CODE = -32000

# Downloads are denied per browser context at creation (see chromium.py), and that
# deny is only as strong as this socket: browser-use's DownloadsWatchdog sends
# ``Browser.setDownloadBehavior`` with ``behavior: "allow"`` on every run, and a
# client that passed its own ``browserContextId`` would re-enable downloads for
# its session. Refused outright — browser-use's call site already swallows the
# failure with a warning, so nothing legitimate breaks.
_REFUSED_METHODS = frozenset(
    {
        "Browser.setDownloadBehavior",
        "Page.setDownloadBehavior",
        # The host owns the context lifecycle: every session lives in exactly the one
        # context it created, counted by the capacity/reaper/recovery accounting. A
        # client minting or disposing its own contexts would escape that accounting —
        # un-capped, un-reaped memory growth on the single shared Chromium, and (on
        # the dispose side) the ability to kill a sibling session's isolation.
        "Target.createBrowserContext",
        "Target.disposeBrowserContext",
    }
)

# Refusal messages, keyed by method.
_REFUSAL_REASONS: dict[str, str] = {
    "Browser.setDownloadBehavior": "downloads are denied for this session",
    "Page.setDownloadBehavior": "downloads are denied for this session",
    "Target.createBrowserContext": "the host owns context lifecycle (one context per session)",
    "Target.disposeBrowserContext": "the host owns context lifecycle (one context per session)",
}


def _refused_navigation_url(message: dict[str, Any]) -> str | None:
    """The URL to refuse when this command navigates outside http(s), else ``None``."""
    if message.get("method") not in _NAVIGATION_METHODS:
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    url = params.get("url")
    if not isinstance(url, str) or not url or url == _BLANK_URL:
        return None
    scheme = urlsplit(url).scheme.lower()
    # An empty scheme is a relative/implicit URL, which Chromium resolves against
    # the current http(s) document — only an explicit foreign scheme is a refusal.
    if scheme and scheme not in _ALLOWED_NAVIGATION_SCHEMES:
        return url
    return None


def _refusal_reason(message: dict[str, Any]) -> str | None:
    """Why this client command must not reach Chromium, or ``None`` to forward it."""
    method = message.get("method")
    if method in _REFUSED_METHODS:
        return f"{method} refused: {_REFUSAL_REASONS[method]}"
    url = _refused_navigation_url(message)
    if url is not None:
        return f"navigation to {url} refused: only http and https are allowed"
    return None


def _refusal_reply(message_id: int | None, reason: str) -> str:
    """A CDP error reply, so a refused command fails the caller instead of hanging it."""
    return json.dumps({"id": message_id, "error": {"code": _CDP_REFUSED_CODE, "message": reason}})


def _event_context_id(params: dict[str, Any]) -> str | None:
    target_info = params.get("targetInfo")
    if isinstance(target_info, dict):
        ctx = target_info.get("browserContextId")
        return ctx if isinstance(ctx, str) else None
    return None


def _rewrite_upstream(message: dict[str, Any], context_id: str, gettargets_ids: set[int]) -> str:
    """Client -> Chromium: pin ``createTarget`` to this context; track getTargets ids."""
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
    return json.dumps(message)


def _is_load_event(text: str) -> bool:
    """Whether this downstream frame is ``Page.loadEventFired``.

    The substring test is a guard, not the answer: it keeps the common frame off
    the JSON parser (``_filter_downstream`` already parses every frame, and this
    would double that cost) while the parse below is what actually decides.
    """
    if _LOAD_EVENT_METHOD not in text:
        return False
    message = json.loads(text)
    return bool(message.get("method") == _LOAD_EVENT_METHOD)


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
            """Forward one upstream-cleaned frame from the client to Chromium."""
            while True:
                raw = await client_ws.receive_text()
                host.touch(session.session_id)
                message = json.loads(raw)
                reason = _refusal_reason(message)
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
                await chromium_ws.send(
                    _rewrite_upstream(message, session.context_id, gettargets_ids)
                )

        async def chromium_to_client() -> None:
            """Forward one frame from Chromium back to the client."""
            async for raw in chromium_ws:
                host.touch(session.session_id)
                text = raw if isinstance(raw, str) else raw.decode()
                if _is_load_event(text):
                    host.note_navigation_finished(session.session_id)
                forward = _filter_downstream(text, session.context_id, gettargets_ids)
                if forward is not None:
                    await client_ws.send_text(forward)

        await pump_until_first_close(client_to_chromium(), chromium_to_client())
    log.set(browser={"session_id": session.session_id, "operation": "cdp_proxy_closed"})
    log.info(f"{LogTag.BROWSER} browser cdp proxy closed")
