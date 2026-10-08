"""Only a catalog event owned by the caller's surface, for a typed identity, reaches PostHog."""

from unittest.mock import MagicMock, patch

import pytest

from shared.py.analytics import PlatformIdentity, PostHogAnalytics, UserId, check_capture
from shared.py.analytics.catalog.base import Surface
from shared.py.analytics.catalog.chat import ChatMessageSubmitted
from shared.py.analytics.catalog.voice import VoiceSessionStarted

USER_ID = "6812f0b3c9a14e2b7d5a91cc"


@pytest.mark.parametrize(
    "raw", ["system", "someone@example.com", "", "6812F0B3C9A14E2B7D5A91CC", "abc"]
)
def test_a_user_id_is_only_ever_a_mongo_object_id(raw: str) -> None:
    with pytest.raises(ValueError, match="ObjectId"):
        UserId(raw)


def test_a_platform_identity_is_platform_colon_id() -> None:
    assert PlatformIdentity("telegram", "12345").distinct_id == "telegram:12345"
    with pytest.raises(ValueError):
        PlatformIdentity("", "12345")
    with pytest.raises(ValueError):
        PlatformIdentity("telegram", " ")


def test_a_raw_event_name_cannot_be_captured() -> None:
    with pytest.raises(TypeError, match="catalog event model"):
        check_capture(UserId(USER_ID), "voice:session_started", Surface.VOICE)  # type: ignore[arg-type]  # the wrong type is the point: capture must refuse it at runtime


def test_a_raw_string_identity_cannot_be_captured() -> None:
    with pytest.raises(TypeError, match="UserId or PlatformIdentity"):
        check_capture(USER_ID, VoiceSessionStarted(room="voice_1"), Surface.VOICE)  # type: ignore[arg-type]  # the wrong type is the point: capture must refuse it at runtime


def test_a_surface_cannot_emit_another_surfaces_event() -> None:
    event = ChatMessageSubmitted(source="web", has_files=False)
    with pytest.raises(TypeError, match="server event; voice may not emit it"):
        check_capture(UserId(USER_ID), event, Surface.VOICE)


def test_voice_capture_refuses_a_raw_string_even_without_a_token() -> None:
    """The check runs before the no-token early return, so local dev catches misuse too."""
    analytics = PostHogAnalytics(project_token="")
    with pytest.raises(TypeError):
        analytics.capture(UserId(USER_ID), "voice:session_started")  # type: ignore[arg-type]  # the wrong type is the point: capture must refuse it at runtime


def test_voice_capture_sends_the_event_name_identity_and_properties() -> None:
    client = MagicMock()
    with patch("shared.py.analytics.client.Posthog", return_value=client):
        analytics = PostHogAnalytics(project_token="phc_test")
    analytics.capture(UserId(USER_ID), VoiceSessionStarted(room="voice_1"))

    kwargs = client.capture.call_args.kwargs
    assert kwargs["event"] == "voice:session_started"
    assert kwargs["distinct_id"] == USER_ID
    assert kwargs["properties"]["room"] == "voice_1"
