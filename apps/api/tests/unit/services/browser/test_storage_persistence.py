"""Tests for encrypted browser-login persistence — save/load/forget and the
encryption-key contract.

The storage layer Fernet-encrypts a Playwright storage_state per (user, domain);
load/save round-trip through the repository, and forget removes the record.
These pin the happy paths plus the fail-loud behavior on a missing/invalid key
(never a silent fallback).
"""

from unittest.mock import AsyncMock, MagicMock

from cryptography.fernet import Fernet
import pytest

from app.services.browser import storage_persistence as sp
from app.services.browser.storage_persistence import (
    domain_of,
    load_storage_state,
    save_storage_state,
)


@pytest.fixture(autouse=True)
def _key_and_state(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(sp.settings, "BROWSER_STATE_ENCRYPTION_KEY", key)
    monkeypatch.setattr(sp.settings, "BROWSER_PERSIST_LOGINS", True)
    sp._cipher = None
    return key


def _storage_state() -> dict:
    return {
        "cookies": [{"name": "sid", "value": "abc", "domain": "example.com", "path": "/"}],
        "origins": [],
    }


def test_domain_of():
    assert domain_of("https://sub.Example.com/path") == "sub.example.com"
    assert domain_of("example.com") == "example.com"
    assert domain_of("") is None
    assert domain_of(None) is None
    assert domain_of("https://[::1") is None  # unparseable (unbalanced IPv6 bracket)


async def test_save_then_load_round_trips_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict = {}
    monkeypatch.setattr(
        sp.browser_profile_repository,
        "upsert_storage_state_blob",
        AsyncMock(side_effect=lambda u, d, b: store.__setitem__((u, d), b)),
    )
    monkeypatch.setattr(
        sp.browser_profile_repository,
        "get_for_domain",
        AsyncMock(side_effect=lambda u, d: MagicMock(storage_state_blob=store.get((u, d)))),
    )

    await save_storage_state("u1", "example.com", _storage_state())
    blob = store[("u1", "example.com")]
    # At rest it's the encrypted blob, not the raw cookies.
    assert "sid" not in blob

    loaded = await load_storage_state("u1", "example.com")
    assert loaded["cookies"][0]["name"] == "sid"


async def test_load_none_when_nothing_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sp.browser_profile_repository, "get_for_domain", AsyncMock(return_value=None)
    )
    assert await load_storage_state("u1", "example.com") is None


async def test_load_none_without_user_or_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    get_for_domain = AsyncMock()
    monkeypatch.setattr(sp.browser_profile_repository, "get_for_domain", get_for_domain)

    # Missing user_id alone is enough to short-circuit, even with a valid domain.
    assert await load_storage_state("", "example.com") is None
    # Missing domain alone is enough to short-circuit, even with a valid user_id.
    assert await load_storage_state("u1", None) is None

    get_for_domain.assert_not_awaited()


async def test_save_noop_without_user_or_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    upsert = AsyncMock()
    monkeypatch.setattr(sp.browser_profile_repository, "upsert_storage_state_blob", upsert)
    await save_storage_state("", "example.com", _storage_state())
    await save_storage_state("u1", None, _storage_state())
    upsert.assert_not_awaited()


async def test_save_noop_when_persistence_opted_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp.settings, "BROWSER_PERSIST_LOGINS", False)
    upsert = AsyncMock()
    monkeypatch.setattr(sp.browser_profile_repository, "upsert_storage_state_blob", upsert)
    await save_storage_state("u1", "example.com", _storage_state())
    upsert.assert_not_awaited()


def test_missing_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp.settings, "BROWSER_STATE_ENCRYPTION_KEY", None)
    sp._cipher = None
    with pytest.raises(ValueError) as exc_info:
        sp._get_cipher()
    assert str(exc_info.value) == "BROWSER_STATE_ENCRYPTION_KEY not configured in Infisical"
    # No cipher gets cached on the failure path.
    assert sp._cipher is None


def test_invalid_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp.settings, "BROWSER_STATE_ENCRYPTION_KEY", "not-a-fernet-key")
    sp._cipher = None
    with pytest.raises(ValueError) as exc_info:
        sp._get_cipher()
    assert str(exc_info.value) == (
        "BROWSER_STATE_ENCRYPTION_KEY is not a valid Fernet key "
        "(must be 32 url-safe base64-encoded bytes): "
        "Fernet key must be 32 url-safe base64-encoded bytes."
    )
    # No cipher gets cached on the failure path.
    assert sp._cipher is None


async def test_forget_deletes_and_returns_count(monkeypatch: pytest.MonkeyPatch) -> None:
    delete = AsyncMock(return_value=1)
    monkeypatch.setattr(sp.browser_profile_repository, "delete_for_user", delete)
    deleted = await sp.forget_browser_logins("u1", "example.com")
    assert deleted == 1
    delete.assert_awaited_once_with("u1", "example.com")
    # no user -> 0 without a repository call
    monkeypatch.setattr(sp.browser_profile_repository, "delete_for_user", AsyncMock())
    assert await sp.forget_browser_logins("", "example.com") == 0


def test_cipher_is_cached(_key_and_state: str) -> None:
    c1 = sp._get_cipher()
    c2 = sp._get_cipher()
    assert c1 is c2


@pytest.mark.unit
class TestCookieAppliesToHost:
    def test_leading_dot_matches_registrable_and_subdomains(self) -> None:
        assert sp._cookie_applies_to_host(".google.com", "google.com")
        assert sp._cookie_applies_to_host(".google.com", "accounts.google.com")
        assert sp._cookie_applies_to_host(".google.com", "mail.google.com")

    def test_leading_dot_does_not_match_a_different_registrable(self) -> None:
        # notgoogle.com must NOT match .google.com — endswith without the dot bug.
        assert not sp._cookie_applies_to_host(".google.com", "notgoogle.com")
        assert not sp._cookie_applies_to_host(".google.com", "evilgoogle.com")

    def test_host_only_matches_only_the_exact_host(self) -> None:
        assert sp._cookie_applies_to_host("accounts.google.com", "accounts.google.com")
        assert not sp._cookie_applies_to_host("accounts.google.com", "mail.google.com")
        assert not sp._cookie_applies_to_host("accounts.google.com", "google.com")


@pytest.mark.unit
class TestSplitStorageStateByHost:
    def test_apex_site_keyed_by_its_host(self) -> None:
        state = {
            "cookies": [{"name": "s", "value": "1", "domain": ".github.com"}],
            "origins": [{"origin": "https://github.com", "localStorage": []}],
        }
        slices = sp.split_storage_state_by_host(state)  # type: ignore[arg-type]
        assert set(slices) == {"github.com"}
        assert slices["github.com"]["cookies"][0]["name"] == "s"
        assert slices["github.com"]["origins"][0]["origin"] == "https://github.com"

    def test_shared_domain_cookie_lands_in_every_subdomain_slice(self) -> None:
        state = {
            "cookies": [
                {"name": "SID", "value": "shared", "domain": ".google.com"},
                {"name": "host_only", "value": "acc", "domain": "accounts.google.com"},
            ],
            "origins": [
                {"origin": "https://accounts.google.com", "localStorage": []},
                {"origin": "https://mail.google.com", "localStorage": []},
            ],
        }
        slices = sp.split_storage_state_by_host(state)  # type: ignore[arg-type]
        assert set(slices) == {"google.com", "accounts.google.com", "mail.google.com"}

        # The shared .google.com session cookie must be seeded on every host a
        # task might start on — otherwise a Gmail task starting on mail.google.com
        # loads a slice with no session and silently isn't logged in.
        for host in ("google.com", "accounts.google.com", "mail.google.com"):
            names = {c["name"] for c in slices[host]["cookies"]}
            assert "SID" in names, host

        # The host-only cookie stays put — it must NOT leak into mail's slice.
        assert "host_only" in {c["name"] for c in slices["accounts.google.com"]["cookies"]}
        assert "host_only" not in {c["name"] for c in slices["mail.google.com"]["cookies"]}

    def test_a_host_with_neither_cookie_nor_origin_is_dropped(self) -> None:
        state = {"cookies": [], "origins": []}
        assert sp.split_storage_state_by_host(state) == {}  # type: ignore[arg-type]


@pytest.mark.unit
class TestImportBrowserProfile:
    async def test_saves_one_login_per_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        saved: dict[tuple[str, str], object] = {}
        monkeypatch.setattr(
            sp.browser_profile_repository,
            "upsert_storage_state_blob",
            AsyncMock(side_effect=lambda u, d, b: saved.__setitem__((u, d), b)),
        )
        state = {
            "cookies": [
                {"name": "a", "value": "1", "domain": ".github.com"},
                {"name": "b", "value": "2", "domain": ".x.com"},
            ],
            "origins": [],
        }
        imported = await sp.import_browser_profile("user-1", state)  # type: ignore[arg-type]

        assert {host for host, _ in imported} == {"github.com", "x.com"}
        assert {d for _, d in saved} == {"github.com", "x.com"}

    async def test_persist_opt_out_saves_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sp.settings, "BROWSER_PERSIST_LOGINS", False)
        upsert = AsyncMock()
        monkeypatch.setattr(sp.browser_profile_repository, "upsert_storage_state_blob", upsert)
        state = {"cookies": [{"name": "a", "value": "1", "domain": ".github.com"}], "origins": []}
        await sp.import_browser_profile("user-1", state)  # type: ignore[arg-type]
        upsert.assert_not_awaited()
