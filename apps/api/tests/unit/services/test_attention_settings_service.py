"""The one write path for attention settings: what it stores, reports and skips."""

from datetime import time
from unittest.mock import AsyncMock, patch

from app.models.attention_settings_models import AttentionSettings
from app.services.attention_settings_service import set_attention_settings
from shared.py.analytics.catalog.settings import SettingsAttentionUpdated

USER = "6812f0b3c9a14e2b7d5a91cc"
MODULE = "app.services.attention_settings_service"


async def test_a_changed_setting_is_stored_and_reported_by_name() -> None:
    changed = AttentionSettings(max_unsolicited_per_day=2, checkin_times=[time(9, 0)])
    with (
        patch(f"{MODULE}.attention_settings_repository") as repo,
        patch(f"{MODULE}.capture") as capture,
    ):
        repo.read = AsyncMock(return_value=AttentionSettings())
        repo.save = AsyncMock()
        await set_attention_settings(USER, changed)

    repo.save.assert_awaited_once_with(USER, changed)
    event = capture.call_args.args[1]
    assert event == SettingsAttentionUpdated(
        changed=["budget", "checkin_times"], max_unsolicited_per_day=2
    )


async def test_saving_what_is_already_stored_writes_and_reports_nothing() -> None:
    with (
        patch(f"{MODULE}.attention_settings_repository") as repo,
        patch(f"{MODULE}.capture") as capture,
    ):
        repo.read = AsyncMock(return_value=AttentionSettings())
        repo.save = AsyncMock()
        await set_attention_settings(USER, AttentionSettings())

    repo.save.assert_not_awaited()
    capture.assert_not_called()


def test_two_check_ins_at_one_time_are_refused() -> None:
    import pytest

    with pytest.raises(ValueError, match="distinct"):
        AttentionSettings(checkin_times=[time(9, 0), time(9, 0)])
