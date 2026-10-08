"""Settings, profile, account and feature-flag events."""

from datetime import timedelta
from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

FlagFallbackReason = Literal[
    "posthog_unconfigured", "evaluation_error", "flag_unevaluated", "killed", "user_choice"
]


class SettingsChatChannelPriorityUpdated(ServerEvent):
    """A user reordered which platform GAIA texts first; platform names and count only."""

    event: ClassVar[str] = "settings:chat_channel_priority_updated"
    budget_per_user_day: ClassVar[int] = 50

    first: Identifier
    count: int


class SettingsNotificationsToggled(ServerEvent):
    """A user changed which notification channels are on."""

    event: ClassVar[str] = "settings:notifications_toggled"
    budget_per_user_day: ClassVar[int] = 10

    changed_channel_count: int
    channels_enabled: list[Identifier]
    channels_disabled: list[Identifier]


class SettingsPreferencesChanged(ServerEvent):
    """A user changed a preference: onboarding answers, voice, or approval behaviour."""

    event: ClassVar[str] = "settings:preferences_changed"
    budget_per_user_day: ClassVar[int] = 50

    setting: Literal[
        "onboarding_preferences", "voice", "voice_star", "hil_approvals", "tool_approval"
    ]
    fields: list[Identifier] | None = None
    has_custom_instructions: bool | None = None
    voice_id: Identifier | None = None
    is_starred: bool | None = None
    mode: Identifier | None = None
    tool_name: Identifier | None = None
    require_approval: bool | None = None


class SettingsDesktopPreferenceChanged(WebEvent):
    """A desktop-only preference changed over Electron IPC, which never reaches the API."""

    event: ClassVar[str] = "settings:desktop_preference_changed"
    budget_per_user_day: ClassVar[int] = 50

    setting: Literal["popup_shortcut", "app_icon"]
    app_icon_id: Identifier | None = None


class ProfileUpdated(ServerEvent):
    """A user updated their profile."""

    event: ClassVar[str] = "profile:updated"
    budget_per_user_day: ClassVar[int] = 10

    changed_field_count: int
    has_picture_upload: bool | None = None


class ProfileLinkCopied(WebEvent):
    """A user copied their public profile card link."""

    event: ClassVar[str] = "profile:link_copied"
    budget_per_user_day: ClassVar[int] = 10

    holo_card_id: Identifier


class AccountSettingChanged(ServerEvent):
    """The agent changed an account setting through its account tools."""

    event: ClassVar[str] = "account:setting_changed"
    budget_per_user_day: ClassVar[int] = 10

    area: Literal["notifications", "preferences", "custom_instructions", "voice"]


class FeatureDiscovered(WebEvent):
    """A user used a feature for the first time."""

    event: ClassVar[str] = "feature:discovered"
    budget_per_user_day: ClassVar[int] = 10

    feature: Literal["voice_agent", "workflows"]


class FeatureToggled(ServerEvent):
    """A user switched a user-facing flag in Settings."""

    event: ClassVar[str] = "feature:toggled"
    budget_per_user_day: ClassVar[int] = 50

    flag: Identifier
    enabled: bool


class FeatureFlagEvaluated(ServerEvent):
    """A flag resolved on a path PostHog never saw; the complement of $feature_flag_called."""

    event: ClassVar[str] = "feature_flag:evaluated"
    budget_per_user_day: ClassVar[int] = 10
    # Once per user, flag and reason a day; outlives the day it keys.
    at_most_once_ttl: ClassVar[timedelta | None] = timedelta(hours=48)

    flag: Identifier
    enabled: bool
    fallback_reason: FlagFallbackReason
