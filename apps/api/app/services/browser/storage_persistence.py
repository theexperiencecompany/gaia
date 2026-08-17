"""Per-user encrypted browser login persistence.

A browser session's storage_state (Playwright format: ``{cookies, origins}``,
covering cookies + localStorage) is Fernet-encrypted and saved per (user_id,
domain) when a session ends, and loaded back to seed the next session on that
domain — so a user doesn't have to log in again on every task.

Encryption follows the same lazy-cipher, Infisical-key pattern as
``app/services/mcp/mcp_token_store.py``: a Fernet key from
``settings.BROWSER_STATE_ENCRYPTION_KEY``, a clear error if it's missing or
invalid. storage_state contents (cookies, tokens, localStorage values) are
never logged — only counts and the domain.
"""

import json
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from playwright.sync_api import StorageState

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.repositories.browser_profiles import browser_profile_repository
from shared.py.wide_events import log

_cipher: Fernet | None = None


def domain_of(url: str | None) -> str | None:
    """Lowercased hostname of a URL, used as the profile key. None if not a URL."""
    if not url:
        return None
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _get_cipher() -> Fernet:
    """Get the Fernet cipher for storage_state encryption (lazy init)."""
    global _cipher
    if _cipher is None:
        key: str | None = settings.BROWSER_STATE_ENCRYPTION_KEY
        if not key:
            raise ValueError("BROWSER_STATE_ENCRYPTION_KEY not configured in Infisical")
        try:
            # Fernet expects a URL-safe base64-encoded 32-byte key.
            _cipher = Fernet(key.encode())
        except Exception as e:
            raise ValueError(
                "BROWSER_STATE_ENCRYPTION_KEY is not a valid Fernet key "
                f"(must be 32 url-safe base64-encoded bytes): {e}"
            )
    return _cipher


def _encrypt_state(state: StorageState) -> str:
    return _get_cipher().encrypt(json.dumps(state).encode()).decode()


def _decrypt_state(blob: str) -> StorageState:
    decrypted: StorageState = json.loads(_get_cipher().decrypt(blob.encode()).decode())
    return decrypted


async def load_storage_state(user_id: str, domain: str | None) -> StorageState | None:
    """Load and decrypt the saved storage_state for ``user_id``+``domain``.

    Returns ``None`` when there's nothing to seed with (no user, no domain, or
    no saved record) rather than an empty dict, so callers can distinguish
    "seed with this" from "start fresh".
    """
    if not user_id or not domain:
        return None
    record = await browser_profile_repository.get_for_domain(user_id, domain)
    if record is None:
        return None
    state = _decrypt_state(record.storage_state_blob)
    log.info(
        f"{LogTag.BROWSER} Loaded saved browser login",
        domain=domain,
        cookie_count=len(state.get("cookies", [])),
        origin_count=len(state.get("origins", [])),
    )
    return state


async def save_storage_state(user_id: str, domain: str | None, state: StorageState) -> None:
    """Encrypt and persist ``state`` for ``user_id``+``domain`` (upsert).

    No-op when there's no user/domain to key on, or when the user has opted
    out of login persistence (``settings.BROWSER_PERSIST_LOGINS``).
    """
    if not user_id or not domain:
        return
    persist_logins: bool = settings.BROWSER_PERSIST_LOGINS
    if not persist_logins:
        return
    blob = _encrypt_state(state)
    await browser_profile_repository.upsert_storage_state_blob(user_id, domain, blob)
    log.info(
        f"{LogTag.BROWSER} Saved browser login",
        domain=domain,
        cookie_count=len(state.get("cookies", [])),
        origin_count=len(state.get("origins", [])),
    )


async def forget_browser_logins(user_id: str, domain: str | None = None) -> int:
    """Delete saved logins for ``user_id``, optionally scoped to one ``domain``.

    Returns the number of records deleted.
    """
    if not user_id:
        return 0
    deleted = await browser_profile_repository.delete_for_user(user_id, domain)
    log.info(f"{LogTag.BROWSER} Forgot browser logins", domain=domain, deleted_count=deleted)
    return deleted
