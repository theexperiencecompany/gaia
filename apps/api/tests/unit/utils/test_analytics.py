"""``track`` is the single server-side emitter for product analytics.

Two things it must never do: break the product path it is called from, and
attribute an event to anything other than GAIA's own stable user id. It
swallows every capture failure to satisfy the first, which makes the
``log.warning`` the only trace a drop ever leaves — so that warning, and the
fields identifying WHICH event was lost, are the behaviour under test.
"""

from typing import Any

import pytest

from app.utils.analytics import track
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

USER_ID = "507f1f77bcf86cd799439011"


class FakePostHog:
    """Records captures verbatim; raises on demand to exercise the drop path."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.captures: list[dict[str, Any]] = []

    def capture(self, **kwargs: Any) -> None:
        if self.error is not None:
            raise self.error
        self.captures.append(kwargs)


@pytest.fixture
def posthog(monkeypatch: pytest.MonkeyPatch) -> FakePostHog:
    fake = FakePostHog()
    _install(monkeypatch, fake)
    return fake


class FakeProviders:
    """Keyed on the provider name, so asking for the wrong one finds nothing.

    A stub that answers regardless of its argument would make the ``"posthog"``
    lookup key untestable — every event would still be captured if the code
    asked for a provider that does not exist.
    """

    def __init__(self, client: object | None) -> None:
        self._registry = {"posthog": client} if client is not None else {}

    def is_available(self, name: str) -> bool:
        return name in self._registry

    def get(self, name: str) -> object | None:
        return self._registry.get(name)


def _install(monkeypatch: pytest.MonkeyPatch, client: object | None) -> None:
    monkeypatch.setattr("app.utils.analytics.providers", FakeProviders(client))


class TestCapture:
    def test_the_event_is_attributed_to_the_gaia_user_id(self, posthog: FakePostHog) -> None:
        track(USER_ID, "briefing:sent", {"kind": "daily"})

        assert posthog.captures == [
            {"distinct_id": USER_ID, "event": "briefing:sent", "properties": {"kind": "daily"}}
        ]

    def test_no_properties_sends_an_empty_dict_not_none(self, posthog: FakePostHog) -> None:
        """PostHog rejects a null properties payload, so the `or {}` is load-bearing."""
        track(USER_ID, "briefing:sent")

        assert posthog.captures[0]["properties"] == {}

    def test_nothing_is_captured_when_posthog_is_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, None)

        track(USER_ID, "briefing:sent")  # must not raise


class TestDropsAreVisible:
    async def test_a_capture_failure_is_swallowed_and_names_the_lost_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, FakePostHog(error=RuntimeError("posthog is down")))

        async with captured_wide_event("analytics_test") as event:
            track(USER_ID, "briefing:sent", {"kind": "daily"})

        assert event["warnings"] == [
            {
                "msg": "analytics.capture_failed",
                "event": "briefing:sent",
                "error": "posthog is down",
            }
        ]
