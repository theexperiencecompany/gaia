"""Stress: race-for-claim on the one-tap platform link code.

Real code under test: redeem_link_code
(app/api/v1/endpoints/bot_links.py) and the code store it claims through
(app/services/platform_link_code_service.py). Redis is an in-process fake
whose commands have no await between check and write, mirroring Redis's
single-threaded command atomicity, so the race resolves deterministically.

Two deliveries of the same handoff are ordinary, not exotic: Telegram resends
/start and mobile clients re-fire the deep link, and nothing on the bot side
dedupes the update. The invariant is that N of them run the link's side effects
exactly once — one greeting on the outbound queue, one transcript write — and
that a redemption which *failed* leaves the code redeemable, because the retry
the failure asks for is the same code.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints.bot_links import redeem_link_code
from app.db.redis import redis_cache
from app.models.bot_models import RedeemLinkCodeRequest
from app.models.platform_models import PlatformLinkCompletion, PlatformLinkResult
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.platform_link_code_service import mint_platform_link_code
from app.utils.errors import AppError
from shared.py.wide_events import log_context

pytestmark = pytest.mark.stress

MODULE = "app.api.v1.endpoints.bot_links"
REDEEMERS = 20
PREFS = OnboardingPreferences(profession="founder", needs=[OnboardingNeed.INBOX])
BUBBLES = ["Hey. I'm with you on Telegram now.", "One tap and your inbox sorts itself."]


class _FakeRedis:
    """In-process Redis stand-in: atomic SETEX/SET-NX/GETDEL/DELETE on a dict.

    Every command completes without an await in the middle, which is the
    atomicity the real single-threaded Redis gives — so of N concurrent
    claimants exactly one can observe the winning result.
    """

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self._keys.get(name)

    async def setex(self, key: str, time: int, value: str) -> bool:
        self._keys[key] = value
        return True

    async def set(
        self, name: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and name in self._keys:
            return None
        self._keys[name] = value
        return True

    async def getdel(self, name: str) -> str | None:
        return self._keys.pop(name, None)

    async def delete(self, *names: str) -> int:
        return sum(int(self._keys.pop(name, None) is not None) for name in names)

    async def ping(self) -> bool:
        return True


def _body(code: str) -> RedeemLinkCodeRequest:
    return RedeemLinkCodeRequest(platform="telegram", platform_user_id="TG42", code=code)


def _request() -> Any:
    """Build a bot request whose headers carry nothing to cross-check the body against."""
    request = AsyncMock()
    request.state.bot_platform = None
    request.state.bot_platform_user_id = None
    return request


async def _yielding_completion(*_args: Any, **_kwargs: Any) -> PlatformLinkCompletion:
    """Run the winner's critical section, yielding so the twins get scheduled mid-write."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return PlatformLinkCompletion(
        link=PlatformLinkResult(
            status="linked",
            platform="telegram",
            platform_user_id="TG42",
            connected_at="2026-09-01T00:00:00Z",
            is_new_link=True,
        ),
        first_contact_delivered=True,
    )


@pytest.fixture
def fake_redis():
    with patch.object(redis_cache, "redis", _FakeRedis()):
        yield


class TestLinkCodeRedemptionRace:
    async def test_concurrent_redemptions_of_one_code_complete_exactly_once(self, fake_redis):
        code = await mint_platform_link_code("user1", PREFS)
        complete = AsyncMock(side_effect=_yielding_completion)
        persist = AsyncMock()
        with (
            patch(f"{MODULE}.require_bot_api_key", new_callable=AsyncMock),
            patch(f"{MODULE}.require_platform_plan", new_callable=AsyncMock),
            patch(f"{MODULE}.get_user_by_id", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.build_first_contact", new_callable=AsyncMock, return_value=BUBBLES),
            patch(f"{MODULE}.complete_platform_link", complete),
            patch(f"{MODULE}._persist_first_contact", persist),
            patch(
                "app.services.platform_link_service.PlatformLinkService.get_user_by_platform_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            async with log_context("redeem_link_code_race"):
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        *[redeem_link_code(_request(), _body(code)) for _ in range(REDEEMERS)],
                        return_exceptions=True,
                    ),
                    timeout=10,
                )

        # The link's side effects — the greeting on the outbound queue, the
        # analytics event, the transcript write — hang off these two, and a
        # user gets introduced to GAIA once.
        assert complete.await_count == 1
        assert persist.await_count == 1
        # Nobody is told their live link expired: the twins that lost the claim
        # answer with the success the winner is delivering.
        assert [r for r in responses if isinstance(r, Exception)] == []
        assert all(r.linked for r in responses)

    async def test_a_failed_redemption_leaves_the_code_redeemable(self, fake_redis):
        """The retry a refusal asks for is the same code."""
        code = await mint_platform_link_code("user1", PREFS)
        complete = AsyncMock(side_effect=_yielding_completion)
        plan = AsyncMock(side_effect=AppError(message="needs Pro", status_code=429))
        with (
            patch(f"{MODULE}.require_bot_api_key", new_callable=AsyncMock),
            patch(f"{MODULE}.require_platform_plan", plan),
            patch(f"{MODULE}.get_user_by_id", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.build_first_contact", new_callable=AsyncMock, return_value=BUBBLES),
            patch(f"{MODULE}.complete_platform_link", complete),
            patch(f"{MODULE}._persist_first_contact", new_callable=AsyncMock),
            patch(
                "app.services.platform_link_service.PlatformLinkService.get_user_by_platform_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            async with log_context("redeem_link_code_race"):
                with pytest.raises(AppError):
                    await redeem_link_code(_request(), _body(code))
                # The user subscribes and taps the very same link again.
                plan.side_effect = None
                response = await redeem_link_code(_request(), _body(code))

        assert response.linked is True
        assert complete.await_count == 1
