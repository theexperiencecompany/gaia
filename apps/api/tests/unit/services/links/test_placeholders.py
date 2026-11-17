"""A link placeholder: what a model may carry instead of a URL, and where it turns back into one.

The live-link read is mocked at the repository seam; the same round trip over
real Mongo is in tests/integration/real/test_links_real.py.
"""

import base64
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.models.short_link_models import ShortLink, ShortLinkTargetType
from app.services.links.placeholders import (
    PLACEHOLDER_PREFIX,
    link_placeholder,
    releasable_end,
    resolve_link_placeholders,
)

OWNER = "507f1f77bcf86cd799439011"
FILE = ShortLinkTargetType.SESSION_ARTIFACT
FILE_ID = "conv-1/reports/Q3 plan (final).html"
TOKEN = link_placeholder(FILE, FILE_ID)


@pytest.fixture
def live() -> Iterator[AsyncMock]:
    with patch(
        "app.services.links.placeholders.short_link_repository.get_live_for_target",
        AsyncMock(
            return_value=ShortLink(
                slug="abcdefghijk", user_id=OWNER, target_type=FILE, target_id=FILE_ID
            )
        ),
    ) as read:
        yield read


def _url() -> str:
    return f"{settings.SHORTLINK_BASE_URL}/abcdefghijk"


class TestPlaceholder:
    def test_a_placeholder_names_no_url_and_survives_any_target_id(self) -> None:
        assert TOKEN.startswith(PLACEHOLDER_PREFIX)
        assert settings.SHORTLINK_BASE_URL not in TOKEN
        assert " " not in TOKEN and "/" not in TOKEN

    async def test_it_resolves_to_its_targets_live_link_under_the_owner(
        self, live: AsyncMock
    ) -> None:
        assert await resolve_link_placeholders(OWNER, f"Here: {TOKEN}.") == f"Here: {_url()}."
        live.assert_awaited_once_with(OWNER, FILE, FILE_ID)

    async def test_a_markdown_link_keeps_its_label(self, live: AsyncMock) -> None:
        text = f"[the report]({TOKEN})"
        assert await resolve_link_placeholders(OWNER, text) == f"[the report]({_url()})"

    async def test_a_target_no_longer_shared_loses_its_link_but_keeps_its_label(
        self, live: AsyncMock
    ) -> None:
        live.return_value = None
        text = f"Open [the report]({TOKEN}) or {TOKEN}."
        assert await resolve_link_placeholders(OWNER, text) == "Open the report or ."

    @pytest.mark.parametrize("token", [f"{PLACEHOLDER_PREFIX}!!!", f"{PLACEHOLDER_PREFIX}bm9wZQ"])
    async def test_a_token_naming_no_target_reads_nothing(
        self, live: AsyncMock, token: str
    ) -> None:
        await resolve_link_placeholders(OWNER, f"x {token}")
        live.assert_not_awaited()

    async def test_without_a_user_nothing_resolves(self, live: AsyncMock) -> None:
        assert await resolve_link_placeholders(None, TOKEN) == TOKEN
        live.assert_not_awaited()


class TestReleasableEnd:
    @pytest.mark.parametrize(
        ("text", "held"),
        [
            ("plain text", ""),
            ("see g", "g"),
            ("see gaia-li", "gaia-li"),
            (f"see {TOKEN}", TOKEN),
            ("see [the report", "[the report"),
            ("see [the report]", "[the report]"),
            ("see [the report](gaia-l", "[the report](gaia-l"),
            (f"see [the report]({TOKEN}", f"[the report]({TOKEN}"),
        ],
    )
    def test_a_tail_that_may_still_be_a_placeholder_is_held(self, text: str, held: str) -> None:
        assert text[releasable_end(text) :] == held

    @pytest.mark.parametrize(
        "text",
        [
            f"see {TOKEN} now",
            f"see [the report]({TOKEN}) now",
            "see [1] and more",
            "see [docs](https://example.com",
        ],
    )
    def test_a_settled_tail_goes_out_whole(self, text: str) -> None:
        assert releasable_end(text) == len(text)


def _token(raw: str) -> str:
    return PLACEHOLDER_PREFIX + base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()


@pytest.mark.parametrize("target_id", ["t1", "t12", "t123"])
async def test_a_placeholder_carries_no_padding_and_resolves_whole(
    live: AsyncMock, target_id: str
) -> None:
    token = link_placeholder(FILE, target_id)
    assert "=" not in token
    assert await resolve_link_placeholders(OWNER, f"({token})") == f"({_url()})"
    live.assert_awaited_once_with(OWNER, FILE, target_id)


@pytest.mark.parametrize(
    "raw",
    [f"{FILE.value}:", "nope:t1", f"{FILE.value}t1", ":t1"],
)
async def test_a_token_naming_no_known_target_reads_nothing(live: AsyncMock, raw: str) -> None:
    await resolve_link_placeholders(OWNER, f"x {_token(raw)}")
    live.assert_not_awaited()
