"""Notification model invariants.

The channel set is defined once, in NotificationChannel. These tests stop the
preference model, the stored defaults and the enum from drifting apart, which is
how imessage and email ended up honoured by delivery while invisible to the API.
"""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.constants.notifications import (
    DEFAULT_CHANNEL_PREFERENCES,
    DEFAULT_CHAT_CHANNEL_PRIORITY,
    DEFAULT_QUIET_HOURS_END,
    DEFAULT_QUIET_HOURS_START,
    EXTERNAL_NOTIFICATION_CHANNELS,
    USER_CONFIGURABLE_CHANNELS,
    NotificationChannel,
)
from app.models.notification.notification_models import (
    ChannelPreferences,
    ChannelPreferencesUpdate,
    QuietHours,
    default_quiet_hours,
)

CONFIGURABLE_CHANNEL_VALUES = {channel.value for channel in USER_CONFIGURABLE_CHANNELS}


class TestChannelSetIsSingleSourced:
    def test_configurable_channels_are_every_channel_but_inapp(self):
        assert {channel.value for channel in NotificationChannel} - {
            NotificationChannel.INAPP.value
        } == CONFIGURABLE_CHANNEL_VALUES

    def test_defaults_cover_every_configurable_channel(self):
        assert set(DEFAULT_CHANNEL_PREFERENCES) == CONFIGURABLE_CHANNEL_VALUES

    def test_response_model_exposes_every_configurable_channel(self):
        assert set(ChannelPreferences.model_fields) == CONFIGURABLE_CHANNEL_VALUES

    def test_update_model_accepts_every_configurable_channel(self):
        assert set(ChannelPreferencesUpdate.model_fields) == CONFIGURABLE_CHANNEL_VALUES

    def test_update_model_omits_unset_channels(self):
        update = ChannelPreferencesUpdate(imessage=False)
        assert update.model_dump(exclude_none=True) == {"imessage": False}

    def test_default_chat_priority_covers_every_chat_platform(self):
        """A platform missing from the default order is skipped: iMessage-only users got nothing."""
        assert set(DEFAULT_CHAT_CHANNEL_PRIORITY) == {
            channel.value for channel in EXTERNAL_NOTIFICATION_CHANNELS
        }


class TestQuietHours:
    @pytest.mark.parametrize(
        ("hour", "quiet"),
        [(21, False), (22, True), (23, True), (0, True), (7, True), (8, False), (12, False)],
    )
    def test_the_default_window_spans_midnight(self, hour: int, quiet: bool) -> None:
        assert default_quiet_hours().contains_hour(hour) is quiet

    def test_the_default_window_is_the_named_constant(self) -> None:
        assert default_quiet_hours() == QuietHours(
            start_hour=DEFAULT_QUIET_HOURS_START, end_hour=DEFAULT_QUIET_HOURS_END
        )

    @pytest.mark.parametrize(("hour", "quiet"), [(12, False), (13, True), (16, True), (17, False)])
    def test_a_same_day_window_ends_before_its_end_hour(self, hour: int, quiet: bool) -> None:
        assert QuietHours(start_hour=13, end_hour=17).contains_hour(hour) is quiet

    def test_covers_reads_the_instant_on_the_users_clock(self) -> None:
        utc_evening = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)

        assert default_quiet_hours().covers(utc_evening, "Asia/Kolkata") is True
        assert default_quiet_hours().covers(utc_evening, "UTC") is False

    def test_an_empty_window_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="different hours"):
            QuietHours(start_hour=9, end_hour=9)

    @pytest.mark.parametrize("hour", [-1, 24])
    def test_an_hour_outside_the_clock_is_rejected(self, hour: int) -> None:
        with pytest.raises(ValidationError):
            QuietHours(start_hour=hour, end_hour=8)
