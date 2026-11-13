"""Reading and changing how much GAIA tells a user unprompted: one write path for the settings page and for comms."""

from typing import Literal

from app.db.repositories.attention_settings import attention_settings_repository
from app.models.attention_settings_models import AttentionSettings
from app.services.analytics_service import capture
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsAttentionUpdated

ChangedSetting = Literal["budget", "checkin_times", "dnd", "rules"]


def _changed(before: AttentionSettings, after: AttentionSettings) -> list[ChangedSetting]:
    changed: list[ChangedSetting] = []
    if before.max_unsolicited_per_day != after.max_unsolicited_per_day:
        changed.append("budget")
    if before.checkin_times != after.checkin_times:
        changed.append("checkin_times")
    if before.dnd_until != after.dnd_until:
        changed.append("dnd")
    if before.rules != after.rules:
        changed.append("rules")
    return changed


async def get_attention_settings(user_id: str) -> AttentionSettings:
    """Return the user's settings: their own, or the defaults when they never changed one."""
    return await attention_settings_repository.read(user_id)


async def set_attention_settings(user_id: str, settings: AttentionSettings) -> AttentionSettings:
    """Store the user's settings and report what changed; nothing is written or reported when nothing did."""
    before = await attention_settings_repository.read(user_id)
    changed = _changed(before, settings)
    if not changed:
        return settings
    await attention_settings_repository.save(user_id, settings)
    capture(
        UserId(user_id),
        SettingsAttentionUpdated(
            changed=changed, max_unsolicited_per_day=settings.max_unsolicited_per_day
        ),
    )
    return settings
