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
from app.constants.browser import BrowserLoginSource
from app.constants.log_tags import LogTag
from app.db.repositories.browser_profiles import browser_profile_repository
from app.models.browser_models import BrowserLoginProvenance
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


async def save_storage_state(
    user_id: str,
    domain: str | None,
    state: StorageState,
    provenance: BrowserLoginProvenance | None = None,
) -> None:
    """Encrypt and persist ``state`` for ``user_id``+``domain`` (upsert).

    No-op when there's no user/domain to key on, or when the user has opted
    out of login persistence (``settings.BROWSER_PERSIST_LOGINS``). ``provenance``
    is recorded only on the import path; the task-end save leaves it ``None``.
    """
    if not user_id or not domain:
        return
    persist_logins: bool = settings.BROWSER_PERSIST_LOGINS
    if not persist_logins:
        return
    blob = _encrypt_state(state)
    await browser_profile_repository.upsert_storage_state_blob(user_id, domain, blob, provenance)
    log.info(
        f"{LogTag.BROWSER} Saved browser login",
        domain=domain,
        cookie_count=len(state.get("cookies", [])),
        origin_count=len(state.get("origins", [])),
    )


async def forget_browser_logins(user_id: str, domain: str | None = None) -> int:
    """Delete saved logins for ``user_id``, optionally scoped to one ``domain``.

    Returns the number of records deleted. This is the storage-layer primitive
    exercised by the contract test; the settings-UI path
    (``profiles.forget_saved_login``) delegates here so there is one canonical
    implementation.
    """
    if not user_id:
        return 0
    deleted = await browser_profile_repository.delete_for_user(user_id, domain)
    log.info(f"{LogTag.BROWSER} Forgot browser logins", domain=domain, deleted_count=deleted)
    return deleted


def _cookie_applies_to_host(cookie_domain: str, host: str) -> bool:
    """Playwright/browser cookie-domain semantics: a leading-dot domain
    (``.google.com``) applies to that registrable host and every subdomain; a
    host-only domain applies only to the exact host."""
    cookie_domain = cookie_domain.lower()
    host = host.lower()
    if cookie_domain.startswith("."):
        suffix = cookie_domain[1:]
        return host == suffix or host.endswith(f".{suffix}")
    return cookie_domain == host


def split_storage_state_by_host(state: StorageState) -> dict[str, StorageState]:
    """Split one browser export into per-host slices keyed the way reuse loads them.

    The store keys on the exact hostname a task starts at (``domain_of``), so an
    export that mixes many sites' cookies must be split to that grain. Each host
    that appears — as an origin, a host-only cookie, or a leading-dot cookie's
    registrable host — gets a slice carrying every cookie that applies to it
    (shared ``.example.com`` cookies land in each of ``example.com`` and its
    subdomains) plus its own localStorage. A host with no cookies or origins is
    dropped rather than saved empty.
    """
    cookies = state.get("cookies", [])
    origins = state.get("origins", [])

    hosts: set[str] = set()
    for origin in origins:
        host = urlparse(origin.get("origin", "")).hostname
        if host:
            hosts.add(host.lower())
    for cookie in cookies:
        domain = cookie.get("domain", "").lower()
        hosts.add(domain.removeprefix("."))
    hosts.discard("")

    slices: dict[str, StorageState] = {}
    for host in hosts:
        host_cookies = [c for c in cookies if _cookie_applies_to_host(c.get("domain", ""), host)]
        host_origins = [
            o for o in origins if (urlparse(o.get("origin", "")).hostname or "").lower() == host
        ]
        if host_cookies or host_origins:
            slices[host] = StorageState(cookies=host_cookies, origins=host_origins)
    return slices


async def import_browser_profile(
    user_id: str,
    state: StorageState,
    source_browser: str | None = None,
    source_ip: str | None = None,
) -> list[tuple[str, int]]:
    """Split an uploaded profile per host and persist each slice as a saved login.

    Returns ``(host, cookie_count)`` for every host actually stored, so the caller
    can report what landed. Records provenance (source "import" plus the browser
    and client IP) on each per-host doc. Honours the same ``BROWSER_PERSIST_LOGINS``
    opt-out as ``save_storage_state`` (each call no-ops when it is off)."""
    provenance = BrowserLoginProvenance(
        source=BrowserLoginSource.IMPORT,
        source_browser=source_browser,
        source_ip=source_ip,
    )
    slices = split_storage_state_by_host(state)
    imported: list[tuple[str, int]] = []
    for host, host_state in slices.items():
        await save_storage_state(user_id, host, host_state, provenance)
        imported.append((host, len(host_state.get("cookies", []))))
    log.info(
        f"{LogTag.BROWSER} Imported browser profile",
        host_count=len(imported),
        cookie_count=len(state.get("cookies", [])),
    )
    return imported
