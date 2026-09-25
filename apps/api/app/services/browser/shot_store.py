"""Step screenshots on local disk, served back through a short capability code.

The object store is the normal home for a step frame, but it needs credentials
this repo does not require to run. Without them a run used to produce no frame
at all: no photo on a bot, no row in the task history, and no recap link, since
a recap refuses to promise frames it cannot show.

So when no object store is configured the frames go to a local directory and a
short code maps to that run, exactly as the live view and the recap page already
do. The code is the capability, the same as theirs, and the URL it produces is
an ordinary one, so nothing downstream has to know which backend served it.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
import secrets
import shutil
import tempfile
import time
from time import perf_counter

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_REPLAY_CODE_TTL_SECONDS,
    BROWSER_SHOT_CODE_KEY_PREFIX,
    BROWSER_SHOT_SESSION_KEY_PREFIX,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.browser.links import browser_link_base
from shared.py.wide_events import log

# Disposable progress artifacts for a local run, so the system temp dir is the
# honest home: nothing here outlives the machine, and nothing else wants it.
SHOT_ROOT = Path(tempfile.gettempdir()) / "gaia-browser-shots"

_SHOT_SUFFIX = ".png"


def shot_path(session_id: str, index: int) -> Path:
    """Where one run's step frame lives on disk."""
    return SHOT_ROOT / session_id / f"step_{index}{_SHOT_SUFFIX}"


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


def _prune_expired() -> None:
    """Delete every run whose frames outlived the recap code that serves them."""
    cutoff = time.time() - BROWSER_REPLAY_CODE_TTL_SECONDS
    for run in SHOT_ROOT.iterdir():
        # A run starting at the same moment may have pruned this one first.
        with contextlib.suppress(FileNotFoundError):
            if run.stat().st_mtime < cutoff:
                shutil.rmtree(run)


def _write(png: bytes, session_id: str, index: int) -> None:
    path = shot_path(session_id, index)
    if not path.parent.exists() and SHOT_ROOT.exists():
        # Once per run, when its first frame lands: the directory never grows past the recap window.
        _prune_expired()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


async def store_step_screenshot(png: bytes, session_id: str, index: int) -> str:
    """Write one step frame to disk and return the URL that serves it back."""
    size_bytes = len(png)
    started = perf_counter()
    # Disk is blocking, and this runs on the browser loop's own event loop.
    await asyncio.to_thread(_write, png, session_id, index)
    code = await _code_for(session_id)
    store_ms = round((perf_counter() - started) * 1000)
    log.set_ns(
        "browser",
        session_id=session_id,
        shot_backend="local",
        shot_bytes=size_bytes,
        shot_store_ms=store_ms,
    )
    log.info(
        f"{LogTag.BROWSER} Browser step screenshot stored",
        step_index=index,
        backend="local",
        size_bytes=size_bytes,
        store_ms=store_ms,
    )
    return f"{browser_link_base()}/shots/{code}/{index}{_SHOT_SUFFIX}"
