"""Cover the local step-frame backend: disk write, one code per run, code lookup.

Without an object store this is the only thing that produces a real screenshot
URL, so a wrong path, a leaked code or a per-frame code is only discovered by a
user opening a dead link.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_REPLAY_CODE_TTL_SECONDS,
)
from app.services.browser import shot_store

pytestmark = pytest.mark.unit


class _FakeRedisCache:
    """An in-memory stand-in recording every write, so key/value/ttl can be asserted."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.set_calls: list[dict[str, object]] = []
        self.get_calls: list[str] = []

    async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
        self.set_calls.append({"key": key, "value": value, "ttl": ttl})
        self.values[key] = value
        return True

    async def get(self, key: str, model: object = None) -> object:
        self.get_calls.append(key)
        return self.values.get(key)


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> _FakeRedisCache:
    fake = _FakeRedisCache()
    monkeypatch.setattr(shot_store, "redis_cache", fake)
    return fake


@pytest.fixture(autouse=True)
def shot_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Keep every frame inside the test's own directory, never the real temp dir."""
    root = tmp_path / "shots"
    monkeypatch.setattr(shot_store, "SHOT_ROOT", root)
    return root


@pytest.fixture(autouse=True)
def link_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL",
        "https://browser.heygaia.io",
    )


# ---------------------------------------------------------------------------
# shot_path
# ---------------------------------------------------------------------------


def test_shot_path_is_a_png_under_the_runs_own_directory(shot_root: Path) -> None:
    assert shot_store.shot_path("sess-1", 3) == shot_root / "sess-1" / "step_3.png"


def test_shot_path_separates_two_runs(shot_root: Path) -> None:
    assert shot_store.shot_path("a", 1).parent != shot_store.shot_path("b", 1).parent


# ---------------------------------------------------------------------------
# store_step_screenshot
# ---------------------------------------------------------------------------


async def test_frame_is_written_to_disk_with_the_exact_bytes_given(
    cache: _FakeRedisCache, shot_root: Path
) -> None:
    await shot_store.store_step_screenshot(b"\x89PNG-one", "sess-1", 2)

    assert (shot_root / "sess-1" / "step_2.png").read_bytes() == b"\x89PNG-one"


async def test_store_creates_the_runs_directory_when_it_does_not_exist(
    cache: _FakeRedisCache, shot_root: Path
) -> None:
    assert not shot_root.exists()

    await shot_store.store_step_screenshot(b"png", "sess-1", 1)

    assert (shot_root / "sess-1").is_dir()


async def test_store_overwrites_a_reused_index_rather_than_appending(
    cache: _FakeRedisCache, shot_root: Path
) -> None:
    await shot_store.store_step_screenshot(b"first", "sess-1", 1)
    await shot_store.store_step_screenshot(b"second", "sess-1", 1)

    assert (shot_root / "sess-1" / "step_1.png").read_bytes() == b"second"


async def test_returned_url_carries_the_code_and_the_index_not_the_session_id(
    cache: _FakeRedisCache,
) -> None:
    url = await shot_store.store_step_screenshot(b"png", "sess-1", 4)

    code = cache.values["browser:shotsess:sess-1"]
    assert url == f"https://browser.heygaia.io/shots/{code}/4.png"
    # The session id is the thing the code exists to keep out of the link.
    assert "sess-1" not in url


async def test_returned_url_is_built_on_the_shared_browser_link_base(
    cache: _FakeRedisCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL", "https://vhost.test/"
    )

    url = await shot_store.store_step_screenshot(b"png", "sess-1", 1)

    assert url.startswith("https://vhost.test/shots/")
    assert "//shots" not in url


# ---------------------------------------------------------------------------
# one code per run
# ---------------------------------------------------------------------------


async def test_every_step_of_one_run_shares_a_single_code(cache: _FakeRedisCache) -> None:
    urls = [await shot_store.store_step_screenshot(b"png", "sess-1", i) for i in range(1, 4)]

    codes = {url.split("/shots/")[1].split("/")[0] for url in urls}
    assert len(codes) == 1
    # Minting per frame would also re-write the mapping keys on every step.
    assert len(cache.set_calls) == 2


async def test_a_second_run_gets_a_different_code(cache: _FakeRedisCache) -> None:
    first = await shot_store.store_step_screenshot(b"png", "sess-1", 1)
    second = await shot_store.store_step_screenshot(b"png", "sess-2", 1)

    assert first.split("/shots/")[1] != second.split("/shots/")[1]


async def test_minting_stores_both_directions_under_their_own_prefixes(
    cache: _FakeRedisCache,
) -> None:
    await shot_store.store_step_screenshot(b"png", "sess-1", 1)

    code = cache.values["browser:shotsess:sess-1"]
    assert isinstance(code, str)
    assert cache.values[f"browser:shotcode:{code}"] == "sess-1"


async def test_both_mapping_keys_expire_with_the_recap_ttl(cache: _FakeRedisCache) -> None:
    await shot_store.store_step_screenshot(b"png", "sess-1", 1)

    assert [call["ttl"] for call in cache.set_calls] == [
        BROWSER_REPLAY_CODE_TTL_SECONDS,
        BROWSER_REPLAY_CODE_TTL_SECONDS,
    ]


async def test_code_is_minted_with_the_configured_entropy(
    cache: _FakeRedisCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested: list[int] = []
    monkeypatch.setattr(
        shot_store.secrets, "token_urlsafe", lambda n: requested.append(n) or "fixed-code"
    )

    url = await shot_store.store_step_screenshot(b"png", "sess-1", 1)

    assert requested == [BROWSER_LIVE_CODE_ENTROPY_BYTES]
    assert url.endswith("/shots/fixed-code/1.png")


async def test_a_non_string_session_mapping_mints_a_fresh_code(cache: _FakeRedisCache) -> None:
    # Redis can hand back a non-str for a key written by something else; treating
    # that as a code would build a link out of it.
    cache.values["browser:shotsess:sess-1"] = 12345

    url = await shot_store.store_step_screenshot(b"png", "sess-1", 1)

    assert "/shots/12345/" not in url
    assert isinstance(cache.values["browser:shotsess:sess-1"], str)


# ---------------------------------------------------------------------------
# resolve_shot_code
# ---------------------------------------------------------------------------


async def test_resolve_returns_the_run_a_stored_code_opens(cache: _FakeRedisCache) -> None:
    await shot_store.store_step_screenshot(b"png", "sess-1", 1)
    code = cache.values["browser:shotsess:sess-1"]
    assert isinstance(code, str)

    assert await shot_store.resolve_shot_code(code) == "sess-1"
    assert cache.get_calls[-1] == f"browser:shotcode:{code}"


async def test_resolve_returns_none_for_an_unknown_or_expired_code(
    cache: _FakeRedisCache,
) -> None:
    assert await shot_store.resolve_shot_code("never-minted") is None


async def test_resolve_returns_none_when_the_stored_value_is_not_a_session_id(
    cache: _FakeRedisCache,
) -> None:
    cache.values["browser:shotcode:weird"] = {"session_id": "sess-1"}

    assert await shot_store.resolve_shot_code("weird") is None


async def test_resolve_does_not_accept_a_session_id_as_its_own_code(
    cache: _FakeRedisCache,
) -> None:
    await shot_store.store_step_screenshot(b"png", "sess-1", 1)

    assert await shot_store.resolve_shot_code("sess-1") is None
