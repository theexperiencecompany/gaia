"""Per-user encrypted browser login persistence.

A session's Playwright storage_state (cookies plus localStorage) is
Fernet-encrypted with settings.BROWSER_STATE_ENCRYPTION_KEY and saved per
(user_id, domain) when a session ends, then loaded to seed the next session
on that domain. Cookie, token and localStorage values are never logged, only
counts and the domain.
"""

import json
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from playwright.sync_api import StorageState, StorageStateCookie

from app.config.settings import settings
from app.constants.browser import BrowserLoginSource
from app.constants.log_tags import LogTag
from app.db.repositories.browser_profiles import browser_profile_repository
from app.models.browser_models import BrowserLoginProvenance, BrowserProfileDocument
from app.services.browser.storage_state_types import OriginState
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
            ) from e
    return _cipher


def _cookie_count(state: StorageState) -> int:
    return len(state.get("cookies", []))


def _origin_count(state: StorageState) -> int:
    return len(state.get("origins", []))


def _encrypt_state(state: StorageState) -> str:
    return _get_cipher().encrypt(json.dumps(state).encode()).decode()


def _decrypt_state(blob: str) -> StorageState:
    decrypted: StorageState = json.loads(_get_cipher().decrypt(blob.encode()).decode())
    return decrypted


def _domain_candidates(domain: str) -> list[str]:
    """Return the host, then each parent domain down to the registrable pair (www.a.example.com -> a.example.com -> example.com).

    An imported profile lands under a cookie's own domain, so a task starting at a
    subdomain finds the parent-domain login it applies to.
    """
    labels = domain.lower().split(".")
    return [".".join(labels[i:]) for i in range(max(len(labels) - 1, 1))]


async def _saved_profile_for(user_id: str, domain: str) -> BrowserProfileDocument | None:
    for candidate in _domain_candidates(domain):
        record = await browser_profile_repository.get_for_domain(user_id, candidate)
        if record is not None:
            return record
    return None


async def load_storage_state(user_id: str, domain: str | None) -> StorageState | None:
    """Load and decrypt the saved storage_state for user_id+domain, or the nearest parent domain.

    Returns None when there's nothing to seed with (no user, no domain, or
    no saved record) rather than an empty dict, so callers can distinguish
    "seed with this" from "start fresh".
    """
    if not user_id or not domain:
        return None
    record = await _saved_profile_for(user_id, domain)
    if record is None:
        return None
    try:
        state: StorageState = _decrypt_state(record.storage_state_blob)
    except (InvalidToken, ValueError) as exc:
        # A key rotation or a restored DB leaves a blob nobody can read again;
        # that is "nothing to seed with", exactly what this function already
        # promises, so drop the dead row instead of failing every task forever.
        log.warning(
            f"{LogTag.BROWSER} Saved browser login unreadable, starting fresh",
            domain=domain,
            error_type=type(exc).__name__,
        )
        await browser_profile_repository.delete_for_user(user_id, record.domain)
        return None
    log.info(
        f"{LogTag.BROWSER} Loaded saved browser login",
        domain=domain,
        cookie_count=_cookie_count(state),
        origin_count=_origin_count(state),
    )
    return state


async def save_storage_state(
    user_id: str,
    domain: str | None,
    state: StorageState,
    provenance: BrowserLoginProvenance | None = None,
) -> None:
    """Encrypt and upsert state for user_id plus domain.

    No-op without a user and domain to key on, or when
    settings.BROWSER_PERSIST_LOGINS is off. Only the import path records a
    provenance; the task-end save leaves it None.
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
        cookie_count=_cookie_count(state),
        origin_count=_origin_count(state),
    )


async def forget_browser_logins(user_id: str, domain: str | None = None) -> int:
    """Delete saved logins for user_id, optionally scoped to one domain.

    Return the number of records deleted. The settings-UI path
    (profiles.forget_saved_login) delegates here, the one canonical implementation.
    """
    if not user_id:
        return 0
    deleted = await browser_profile_repository.delete_for_user(user_id, domain)
    log.info(f"{LogTag.BROWSER} Forgot browser logins", domain=domain, deleted_count=deleted)
    return deleted


def _cookie_applies_to_host(cookie_domain: str, host: str) -> bool:
    """Apply browser cookie-domain semantics: a leading-dot domain covers the registrable host and every subdomain, a host-only domain covers only the exact host."""
    cookie_domain = cookie_domain.lower()
    host = host.lower()
    if cookie_domain.startswith("."):
        suffix = cookie_domain[1:]
        return host == suffix or host.endswith(f".{suffix}")
    return cookie_domain == host


def _cookie_host(cookie: StorageStateCookie) -> str | None:
    """Return the registrable host a cookie is scoped to (leading dot stripped, lowercased), or None if it has none."""
    domain = cookie.get("domain")
    if not domain:
        return None
    return domain.lower().removeprefix(".") or None


def _origin_host(origin: OriginState) -> str | None:
    """Lowercased host of an origin entry, or None when it has no usable URL."""
    return domain_of(origin.get("origin"))


def _cookie_scopes_to(cookie: StorageStateCookie, host: str) -> bool:
    domain = cookie.get("domain")
    return bool(domain) and _cookie_applies_to_host(domain, host)


def _hosts_in(state: StorageState) -> set[str]:
    """Return every host state holds a cookie or localStorage for."""
    hosts = {host for cookie in state.get("cookies", []) if (host := _cookie_host(cookie))}
    return hosts | {host for origin in state.get("origins", []) if (host := _origin_host(origin))}


def overlay_storage_state(
    base: StorageState | None, live: StorageState, held_hosts: set[str]
) -> StorageState:
    """Lay live over base, with live the whole truth for every host it covers.

    Covered means a host live has a cookie or origin for, or one of held_hosts, the
    sites the live browser is known to have had open. A base cookie a browser would
    send to a covered host, or a covered origin's localStorage, is dropped rather than
    merged, since its absence from live may be a logout; base fills only the rest.
    """
    if base is None:
        return live
    covered = _hosts_in(live) | held_hosts
    return StorageState(
        cookies=[
            cookie
            for cookie in base.get("cookies", [])
            if not any(_cookie_scopes_to(cookie, host) for host in covered)
        ]
        + live.get("cookies", []),
        origins=[
            origin for origin in base.get("origins", []) if _origin_host(origin) not in covered
        ]
        + live.get("origins", []),
    )


def storage_state_for_host(state: StorageState, host: str) -> StorageState:
    """Return host's own slice of state: every cookie a browser would send to it, and its localStorage."""
    return StorageState(
        cookies=[c for c in state.get("cookies", []) if _cookie_scopes_to(c, host)],
        origins=[o for o in state.get("origins", []) if _origin_host(o) == host],
    )


def split_storage_state_by_host(state: StorageState) -> dict[str, StorageState]:
    """Split one browser export into per-host slices keyed the way reuse loads them.

    The store keys on the exact hostname a task starts at (domain_of), so each
    host gets every cookie that applies to it (a leading-dot cookie lands in
    the registrable host and each subdomain) plus its own localStorage.
    """
    return {host: storage_state_for_host(state, host) for host in _hosts_in(state)}


async def import_browser_profile(
    user_id: str,
    state: StorageState,
    source_browser: str | None = None,
    source_ip: str | None = None,
) -> list[tuple[str, int]]:
    """Split an uploaded profile per host and persist each slice as a saved login.

    Return (host, cookie_count) for every host stored, with import provenance
    (browser and client IP) on each per-host doc. Honour the same
    BROWSER_PERSIST_LOGINS opt-out as save_storage_state.
    """
    provenance = BrowserLoginProvenance(
        source=BrowserLoginSource.IMPORT,
        source_browser=source_browser,
        source_ip=source_ip,
    )
    slices = split_storage_state_by_host(state)
    imported: list[tuple[str, int]] = []
    for host, host_state in slices.items():
        await save_storage_state(user_id, host, host_state, provenance)
        imported.append((host, _cookie_count(host_state)))
    log.info(
        f"{LogTag.BROWSER} Imported browser profile",
        host_count=len(imported),
        cookie_count=_cookie_count(state),
    )
    return imported
