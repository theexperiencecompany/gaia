"""Step screenshots kept in Redis, served back through a short capability code.

The object store is the normal home for a step frame, but it needs credentials
this repo does not require to run. Without them the frames are kept in Redis:
the browser worker that captures a frame and the API that serves it are
separate processes (separate containers in compose), and Redis is the store
both already share, so a frame written by one is readable by the other. Each
frame expires with the code that serves it, so nothing needs sweeping.

A short code maps to the run, exactly as the live view and the recap page
already do. The code is the capability, the same as theirs, and the URL it
produces is an ordinary one, so nothing downstream has to know which backend
served it.
"""

from __future__ import annotations

import base64
import secrets
from time import perf_counter

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_REPLAY_CODE_TTL_SECONDS,
    BROWSER_SHOT_CODE_KEY_PREFIX,
    BROWSER_SHOT_FRAME_KEY_PREFIX,
    BROWSER_SHOT_SESSION_KEY_PREFIX,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.browser.links import browser_link_base
from shared.py.wide_events import log

#: Every step frame is the JPEG the page was captured as.
SHOT_SUFFIX = ".jpg"


def _frame_key(session_id: str, index: int) -> str:
    return f"{BROWSER_SHOT_FRAME_KEY_PREFIX}{session_id}:{index}"


async def _code_for(session_id: str) -> str:
    """Return this run's code, minting one the first time a frame is stored.

    One code per run, not per frame, so every step of a run shares a link and the
    recap can be handed out as a single capability.
    """
    session_key = f"{BROWSER_SHOT_SESSION_KEY_PREFIX}{session_id}"
    existing = await redis_cache.get(session_key)
    if isinstance(existing, str):
        return existing
    code = secrets.token_urlsafe(BROWSER_LIVE_CODE_ENTROPY_BYTES)
    await redis_cache.set(session_key, code, ttl=BROWSER_REPLAY_CODE_TTL_SECONDS)
    await redis_cache.set(
        f"{BROWSER_SHOT_CODE_KEY_PREFIX}{code}",
        session_id,
        ttl=BROWSER_REPLAY_CODE_TTL_SECONDS,
    )
    return code


async def resolve_shot_code(code: str) -> str | None:
    """Return the run a shot code opens, or None when it is unknown or expired."""
    session_id = await redis_cache.get(f"{BROWSER_SHOT_CODE_KEY_PREFIX}{code}")
    return session_id if isinstance(session_id, str) else None


async def read_step_screenshot(code: str, index: int) -> bytes | None:
    """Return one stored step frame by its run's code, or None when either is unknown or expired."""
    session_id = await resolve_shot_code(code)
    if session_id is None:
        return None
    log.set(browser={"session_id": session_id})
    frame = await redis_cache.get(_frame_key(session_id, index))
    return base64.b64decode(frame) if isinstance(frame, str) else None


async def store_step_screenshot(jpeg: bytes, session_id: str, index: int) -> str | None:
    """Keep one step frame and return the URL that serves it back, or None when Redis did not take it."""
    size_bytes = len(jpeg)
    started = perf_counter()
    stored = await redis_cache.set(
        _frame_key(session_id, index),
        base64.b64encode(jpeg).decode(),
        ttl=BROWSER_REPLAY_CODE_TTL_SECONDS,
    )
    if not stored:
        return None
    code = await _code_for(session_id)
    store_ms = round((perf_counter() - started) * 1000)
    log.set_ns(
        "browser",
        session_id=session_id,
        shot_backend="redis",
        shot_bytes=size_bytes,
        shot_store_ms=store_ms,
    )
    log.info(
        f"{LogTag.BROWSER} Browser step screenshot stored",
        step_index=index,
        backend="redis",
        size_bytes=size_bytes,
        store_ms=store_ms,
    )
    return f"{browser_link_base()}/shots/{code}/{index}{SHOT_SUFFIX}"
