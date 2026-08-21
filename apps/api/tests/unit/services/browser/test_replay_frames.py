"""Regression: the recap slideshow derived image URLs it never checked existed.

`render_replay_page` built `{R2}/browser_steps/{session}/step_{i}.png` for every
step from a count, so any step whose screenshot upload failed showed a broken
image in the shared recap link. Same root cause as the task-history thumbnails.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_REPLAY_CODE_TTL_SECONDS,
)
from app.schemas.browser import ReplayRecord
from app.services.browser import replay as replay_module
from app.services.browser.replay import (
    create_replay_link,
    mint_replay_code,
    render_replay_page,
    resolve_replay_code,
)


class _FakeRedisCache:
    """Records every set/get call so tests can assert the exact key/value/ttl used."""

    def __init__(self, get_return: ReplayRecord | None = None) -> None:
        self.get_return = get_return
        self.set_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    async def set(
        self, key: str, value: object, ttl: int = 3600, model: type[Any] | None = None
    ) -> bool:
        self.set_calls.append({"key": key, "value": value, "ttl": ttl, "model": model})
        return True

    async def get(self, key: str, model: type[Any] | None = None) -> Any:
        self.get_calls.append({"key": key, "model": model})
        return self.get_return


@pytest.mark.unit
def test_page_shows_only_the_screenshots_that_uploaded() -> None:
    record = ReplayRecord(
        session_id="s1", steps=3, shots=["https://cdn/1.png", "https://cdn/3.png"]
    )

    page = render_replay_page(record)

    assert "https://cdn/1.png" in page
    assert "https://cdn/3.png" in page
    # The step that never uploaded must not be conjured from the session id.
    assert "browser_steps/s1/step_2.png" not in page


@pytest.mark.unit
def test_codes_minted_before_urls_were_stored_still_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.browser.replay.settings.R2_PUBLIC_BASE_URL", "https://cdn")

    page = render_replay_page(ReplayRecord(session_id="s1", steps=2))

    assert "browser_steps/s1/step_1.png" in page
    assert "browser_steps/s1/step_2.png" in page


@pytest.mark.unit
def test_no_placeholder_survives_rendering() -> None:
    page = render_replay_page(ReplayRecord(session_id="s1", steps=1, shots=["https://cdn/1.png"]))

    assert "__URLS__" not in page


@pytest.mark.unit
def test_fallback_r2_base_strips_only_a_trailing_slash_not_trailing_x_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # rstrip("/") mutated to rstrip("XX/XX") would also eat trailing "X"
    # characters, which a bare trailing-slash fixture can't tell apart.
    monkeypatch.setattr("app.services.browser.replay.settings.R2_PUBLIC_BASE_URL", "https://cdnX")

    page = render_replay_page(ReplayRecord(session_id="s1", steps=1))

    assert "https://cdnX/browser_steps/s1/step_1.png" in page


@pytest.mark.unit
def test_fallback_urls_strip_a_trailing_slash_from_the_r2_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.browser.replay.settings.R2_PUBLIC_BASE_URL", "https://cdn/")

    page = render_replay_page(ReplayRecord(session_id="s1", steps=1))

    assert "https://cdn/browser_steps/s1/step_1.png" in page
    # A dropped rstrip would double the slash between host and path.
    assert "https://cdn//browser_steps" not in page


@pytest.mark.unit
def test_fallback_urls_have_no_host_when_r2_base_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.browser.replay.settings.R2_PUBLIC_BASE_URL", None)

    page = render_replay_page(ReplayRecord(session_id="s1", steps=1))

    assert '"/browser_steps/s1/step_1.png"' in page


@pytest.mark.unit
def test_fallback_step_numbering_is_one_indexed_and_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.browser.replay.settings.R2_PUBLIC_BASE_URL", "https://cdn")

    page = render_replay_page(ReplayRecord(session_id="s1", steps=3))

    assert "browser_steps/s1/step_1.png" in page
    assert "browser_steps/s1/step_2.png" in page
    assert "browser_steps/s1/step_3.png" in page
    # An off-by-one on either bound of range(1, steps + 1) would add or drop a step.
    assert "browser_steps/s1/step_0.png" not in page
    assert "browser_steps/s1/step_4.png" not in page


@pytest.mark.unit
def test_empty_shots_list_falls_back_to_derived_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.browser.replay.settings.R2_PUBLIC_BASE_URL", "https://cdn")

    page = render_replay_page(ReplayRecord(session_id="s1", steps=2, shots=[]))

    # An empty list is falsy, same as no shots stored at all: `or` must fall through.
    assert "browser_steps/s1/step_1.png" in page
    assert "browser_steps/s1/step_2.png" in page


@pytest.mark.unit
def test_real_shots_are_embedded_as_a_json_array_of_exact_urls() -> None:
    record = ReplayRecord(
        session_id="s1", steps=2, shots=["https://cdn/a.png", "https://cdn/b.png"]
    )

    page = render_replay_page(record)

    assert '["https://cdn/a.png", "https://cdn/b.png"]' in page


@pytest.mark.unit
def test_closing_script_tags_in_urls_are_escaped_for_safe_embedding() -> None:
    record = ReplayRecord(session_id="s1", steps=1, shots=["https://cdn/</script>.png"])

    page = render_replay_page(record)

    # The raw closing sequence must never appear inside the inlined <script> block.
    assert "</script>.png" not in page
    assert "<\\/script>.png" in page


@pytest.mark.unit
async def test_mint_replay_code_stores_the_record_under_the_replay_prefixed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    code = await mint_replay_code("s1", 3, ["https://cdn/1.png"])

    assert len(fake_cache.set_calls) == 1
    call = fake_cache.set_calls[0]
    assert call["key"] == f"browser:replay:{code}"
    assert call["value"] == ReplayRecord(session_id="s1", steps=3, shots=["https://cdn/1.png"])
    assert call["ttl"] == BROWSER_REPLAY_CODE_TTL_SECONDS
    assert call["model"] is ReplayRecord


@pytest.mark.unit
async def test_mint_replay_code_defaults_missing_shots_to_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    await mint_replay_code("s1", 2)

    stored = fake_cache.set_calls[0]["value"]
    assert isinstance(stored, ReplayRecord)
    assert stored.shots == []


@pytest.mark.unit
async def test_mint_replay_code_returns_the_token_urlsafe_result_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A test that only checks the stored key was derived from the function's own
    # return value can't tell a real token from a swapped-out `None` — both sides
    # of the assertion would still agree. Pin against an independently known value.
    monkeypatch.setattr(replay_module.secrets, "token_urlsafe", lambda n: "fixed-token")
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    code = await mint_replay_code("s1", 1)

    assert code == "fixed-token"
    assert fake_cache.set_calls[0]["key"] == "browser:replay:fixed-token"


@pytest.mark.unit
async def test_mint_replay_code_requests_the_configured_entropy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_entropy: list[int | None] = []
    monkeypatch.setattr(
        replay_module.secrets,
        "token_urlsafe",
        lambda n: requested_entropy.append(n) or "token",
    )
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    await mint_replay_code("s1", 1)

    assert requested_entropy == [BROWSER_LIVE_CODE_ENTROPY_BYTES]


@pytest.mark.unit
async def test_resolve_replay_code_looks_up_the_replay_prefixed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ReplayRecord(session_id="s1", steps=1)
    fake_cache = _FakeRedisCache(get_return=record)
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    result = await resolve_replay_code("abc123")

    assert result is record
    assert fake_cache.get_calls == [{"key": "browser:replay:abc123", "model": ReplayRecord}]


@pytest.mark.unit
async def test_resolve_replay_code_returns_none_for_an_unknown_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cache = _FakeRedisCache(get_return=None)
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    assert await resolve_replay_code("missing") is None


@pytest.mark.unit
async def test_create_replay_link_returns_none_when_no_screenshots_uploaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay_module.settings, "R2_PUBLIC_BASE_URL", "https://cdn")
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    assert await create_replay_link("s1", []) is None
    # Nothing to replay means no code should ever be minted.
    assert fake_cache.set_calls == []


@pytest.mark.unit
async def test_create_replay_link_returns_none_when_r2_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay_module.settings, "R2_PUBLIC_BASE_URL", None)
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    assert await create_replay_link("s1", ["https://cdn/1.png"]) is None
    assert fake_cache.set_calls == []


@pytest.mark.unit
async def test_create_replay_link_builds_a_replays_url_from_the_minted_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay_module.settings, "R2_PUBLIC_BASE_URL", "https://cdn")
    monkeypatch.setattr(
        replay_module.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io/"
    )
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    link = await create_replay_link("s1", ["https://cdn/1.png", "https://cdn/2.png"])

    assert link is not None
    # A trailing slash on the base must not survive into a double slash before "replays".
    assert link.startswith("https://browser.heygaia.io/replays/")
    assert "//replays" not in link
    stored = fake_cache.set_calls[0]["value"]
    assert stored.shots == ["https://cdn/1.png", "https://cdn/2.png"]
    # The step count carried on the record must be derived from the real shots, not guessed.
    assert stored.steps == 2


@pytest.mark.unit
async def test_create_replay_link_base_strips_only_a_trailing_slash_not_trailing_x_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # rstrip("/") mutated to rstrip("XX/XX") would also eat trailing "X"
    # characters, which a bare trailing-slash fixture can't tell apart.
    monkeypatch.setattr(replay_module.settings, "R2_PUBLIC_BASE_URL", "https://cdn")
    monkeypatch.setattr(
        replay_module.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io/boX"
    )
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    link = await create_replay_link("s1", ["https://cdn/1.png"])

    assert link is not None
    assert link.startswith("https://browser.heygaia.io/boX/replays/")


@pytest.mark.unit
async def test_create_replay_link_falls_back_to_host_when_no_live_view_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay_module.settings, "R2_PUBLIC_BASE_URL", "https://cdn")
    monkeypatch.setattr(replay_module.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(replay_module.settings, "HOST", "https://api.heygaia.io")
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(replay_module, "redis_cache", fake_cache)

    link = await create_replay_link("s1", ["https://cdn/1.png"])

    assert (
        link
        == f"https://api.heygaia.io/replays/{fake_cache.set_calls[0]['key'].removeprefix('browser:replay:')}"
    )
