"""A context's cookies and localStorage in Playwright's storage_state shape, in and out.

Cookies are the context's own (one CDP read or write covers every site). The
localStorage of an origin lives in its documents, so it is seeded by an init
script on the session's own page and read from every page open at dump time. An
origin a page is open on is reported even when its storage is empty, so a cleared
store can be told from one nobody looked at.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from playwright.sync_api import StorageState, StorageStateCookie

from app.browser_host.cdp_mux import (
    CdpCommandError,
    CdpFrame,
    CdpMux,
    CDPTimeoutError,
    cdp_attach,
    cdp_call,
    cdp_detach,
)
from app.constants.log_tags import LogTag
from app.services.browser.storage_state_types import LocalStorageEntry, OriginState
from shared.py.wide_events import log

# One page's localStorage read; pages are read at once, and one that cannot
# answer in this long is left out rather than holding up the whole dump.
_PAGE_STORAGE_TIMEOUT_SECONDS = 5.0
# What location.origin reads on a page with no web origin (about:blank, data:).
_OPAQUE_ORIGIN = "null"

_LOCAL_STORAGE_DUMP_JS = (
    "(() => ({ origin: location.origin, localStorage: Object.keys(localStorage)"
    ".map(k => ({ name: k, value: localStorage.getItem(k) })) }))()"
)


def _cdp_cookie_to_storage_state(cookie: dict[str, Any]) -> StorageStateCookie:
    """CDP Network.Cookie -> Playwright storage_state cookie shape."""
    out: StorageStateCookie = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie["path"],
        # Required fields of CDP's Network.Cookie: the engine always sends them.
        "expires": cookie["expires"],
        "httpOnly": cookie["httpOnly"],
        "secure": cookie["secure"],
    }
    same_site = cookie.get("sameSite")
    if same_site:
        out["sameSite"] = same_site
    return out


def _storage_state_cookie_to_cdp(cookie: StorageStateCookie) -> dict[str, Any]:
    """Playwright storage_state cookie -> CDP Storage.setCookies param."""
    out: dict[str, Any] = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie.get("path", "/"),
        "secure": cookie.get("secure", False),
        "httpOnly": cookie.get("httpOnly", False),
    }
    expires = cookie.get("expires")
    # -1 marks a session cookie; only a positive epoch is a real expiry.
    if expires is not None and expires > 0:
        out["expires"] = expires
    same_site = cookie.get("sameSite")
    if same_site:
        out["sameSite"] = same_site
    return out


def build_local_storage_restore_js(origin: str, entries: list[LocalStorageEntry]) -> str:
    """Build the restore counterpart of the dump for one origin.

    Writes only on the matching origin and only keys the page has not set, so a
    value the page updated is never clobbered and every navigation can re-run it.
    """
    return (
        "(() => {"
        f" if (location.origin !== {json.dumps(origin)}) return;"
        f" const entries = {json.dumps(entries)};"
        " for (const e of entries) {"
        " if (localStorage.getItem(e.name) === null) localStorage.setItem(e.name, e.value); } })()"
    )


async def seed_storage_state(
    mux: CdpMux, context_id: str, page_session: str, storage_state: StorageState
) -> None:
    """Restore saved cookies into the context and saved localStorage onto its page.

    The init scripts belong to page_session, which stays attached for the
    session's life: a detached session's scripts stop running. Covers the
    session's own page; a tab opened later is not seeded, unlike cookies.
    """
    cookies: list[StorageStateCookie] = storage_state.get("cookies") or []
    if cookies:
        await cdp_call(
            mux,
            "Storage.setCookies",
            {
                "browserContextId": context_id,
                "cookies": [_storage_state_cookie_to_cdp(c) for c in cookies],
            },
        )
    for origin in storage_state.get("origins") or []:
        if origin.get("localStorage"):
            await cdp_call(
                mux,
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": build_local_storage_restore_js(
                        origin["origin"], origin["localStorage"]
                    )
                },
                session_id=page_session,
            )


async def dump_storage_state(
    mux: CdpMux, context_id: str, own_page: tuple[str, str]
) -> StorageState:
    """Read the context's cookies and the localStorage of every page open in it.

    own_page is the session's (target id, host page session), read without a new attach.
    """
    raw = await cdp_call(mux, "Storage.getCookies", {"browserContextId": context_id})
    cookies = [_cdp_cookie_to_storage_state(c) for c in raw["cookies"]]
    targets = await cdp_call(mux, "Target.getTargets")
    page_ids = [
        ti["targetId"]
        for ti in targets["targetInfos"]
        if ti["type"] == "page" and ti.get("browserContextId") == context_id
    ]
    read = await asyncio.gather(*(_page_origin(mux, target_id, own_page) for target_id in page_ids))
    return {"cookies": cookies, "origins": [origin for origin in read if origin is not None]}


async def _page_origin(
    mux: CdpMux, target_id: str, own_page: tuple[str, str]
) -> OriginState | None:
    """Read one page's origin and localStorage; None for an opaque origin or a page that cannot answer."""
    try:
        if target_id == own_page[0]:
            value = await _read_page_storage(mux, own_page[1])
        else:
            page_session = await cdp_attach(
                mux, target_id, _ignore_frame, timeout=_PAGE_STORAGE_TIMEOUT_SECONDS
            )
            try:
                value = await _read_page_storage(mux, page_session)
            finally:
                await cdp_detach(mux, page_session, timeout=_PAGE_STORAGE_TIMEOUT_SECONDS)
    except (CDPTimeoutError, CdpCommandError) as exc:
        log.warning(
            f"{LogTag.BROWSER} browser page left out of the storage dump",
            error_type=type(exc).__name__,
        )
        return None
    if not isinstance(value, dict):
        return None
    origin = value.get("origin")
    if not isinstance(origin, str) or origin == _OPAQUE_ORIGIN:
        return None
    entries = value.get("localStorage")
    return {"origin": origin, "localStorage": entries if isinstance(entries, list) else []}


async def _read_page_storage(mux: CdpMux, page_session: str) -> object:
    result = await cdp_call(
        mux,
        "Runtime.evaluate",
        {"expression": _LOCAL_STORAGE_DUMP_JS, "returnByValue": True},
        session_id=page_session,
        timeout=_PAGE_STORAGE_TIMEOUT_SECONDS,
    )
    return result["result"].get("value")


def _ignore_frame(_frame: CdpFrame) -> None:
    """Own a page session the dump attaches only to read: its events are of no use to it."""
