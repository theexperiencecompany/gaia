"""Sync helper that flips MongoDB user_integrations status when Composio
reports the upstream connected account is dead (error 1810 or 401 from
the provider). Without this the UI keeps showing 'connected' until the
user manually clicks Reconnect."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

import redis as sync_redis

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.config.settings import settings
from app.constants.cache import OAUTH_STATUS_KEY
from app.db.mongodb.collections import get_sync_collection
from shared.py.wide_events import log

# Composio assigns stable numeric error codes; 1810 = "No connected account
# found for user X for toolkit Y". Code-number match avoids the text-wording
# brittleness of matching on the english message.
_COMPOSIO_DEAD_ACCOUNT_CODE = re.compile(r"\b1810\b")


def looks_like_disconnect(payload: Any) -> bool:
    """True iff payload (dict / Exception / str) carries Composio code 1810."""
    if payload is None:
        return False

    if isinstance(payload, dict):
        if payload.get("successful") is True:
            return False
        text = " ".join(
            str(v) for v in (payload.get("error"), payload.get("message"), payload.get("data")) if v
        )
    else:
        text = str(payload)

    if not text:
        return False
    return bool(_COMPOSIO_DEAD_ACCOUNT_CODE.search(text))


def _resolve_integration_id(toolkit: str | None) -> str | None:
    if not toolkit:
        return None
    target = toolkit.upper()
    for integration in OAUTH_INTEGRATIONS:
        cfg = integration.composio_config
        if cfg and cfg.toolkit and cfg.toolkit.upper() == target:
            return integration.id
    return None


def _clear_status_cache_sync(user_id: str) -> None:
    redis_url = getattr(settings, "REDIS_URL", None) or getattr(settings, "REDIS_URI", None)
    if not redis_url:
        return
    try:
        client = sync_redis.Redis.from_url(redis_url, socket_timeout=2)
        client.delete(f"{OAUTH_STATUS_KEY}:{user_id}")
    except Exception as e:  # noqa: BLE001 - best-effort cache clear
        log.warning(f"desync_handler: failed to clear status cache for {user_id}: {e}")


def mark_disconnected_sync(user_id: str | None, toolkit: str | None) -> bool:
    """Flip user_integrations.status connected→created. Returns True if a row was updated."""
    if not user_id or not toolkit:
        return False

    integration_id = _resolve_integration_id(toolkit)
    if not integration_id:
        return False

    try:
        result = get_sync_collection("user_integrations").update_one(
            {"user_id": user_id, "integration_id": integration_id, "status": "connected"},
            {
                "$set": {
                    "status": "created",
                    "disconnected_at": datetime.now(UTC),
                    "disconnect_reason": "composio_account_inactive",
                }
            },
        )
    except Exception as e:  # noqa: BLE001 - never break tool call on side-effect
        log.warning(f"desync_handler: mongo update failed for {user_id}/{integration_id}: {e}")
        return False

    if result.matched_count == 0:
        return False

    log.info(
        f"desync_handler: flipped {user_id} integration {integration_id} "
        "to 'created' after Composio reported account dead"
    )
    _clear_status_cache_sync(user_id)
    return True


__all__ = ["looks_like_disconnect", "mark_disconnected_sync"]
