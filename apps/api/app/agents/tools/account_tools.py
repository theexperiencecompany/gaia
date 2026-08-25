"""Account-center mutation tools — the ONLY way the agent changes account state.

The ``account/`` workspace files are read-only projections; these tools are the
write path. Each is registered with an ``always_gate`` HIL stamp so it asks the
user for confirmation regardless of their approval mode or per-tool overrides —
these are settings on the user's own account, not workflow steps.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.agents.tools.core.mutations import define_mutation_tool
from app.decorators import enforce_rate_limit
from app.services.account_fs import schedule_account_sync
from app.services.account_settings import (
    select_voice,
    set_custom_instructions,
    set_notification_channels,
    set_preferences,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.platform_link_service import (
    disconnect_platform_account,
    start_platform_connect,
)
from shared.py.wide_events import log

HIL_CONFIRM_NOTE = (
    "The user is always asked to confirm before this runs. Tell them what you "
    "are about to change first."
)


class UpdateNotificationSettingsArgs(BaseModel):
    telegram: bool | None = Field(default=None, description="Enable/disable Telegram notifications")
    discord: bool | None = Field(default=None, description="Enable/disable Discord notifications")
    whatsapp: bool | None = Field(default=None, description="Enable/disable WhatsApp notifications")
    slack: bool | None = Field(default=None, description="Enable/disable Slack notifications")
    email: bool | None = Field(default=None, description="Enable/disable email notifications")


class UpdatePreferencesArgs(BaseModel):
    response_style: str | None = Field(
        default=None,
        description="Response style: brief, detailed, casual, professional, or a custom label",
    )
    timezone: str | None = Field(
        default=None,
        description="Home timezone as an IANA identifier, e.g. 'America/New_York', 'Asia/Kolkata'",
    )


class UpdateCustomInstructionsArgs(BaseModel):
    instructions: str = Field(
        description="Standing instructions applied to every conversation (max 500 chars). "
        "Pass an empty string to clear them."
    )


class SetSelectedVoiceArgs(BaseModel):
    voice: str = Field(
        description="Voice name (case-insensitive) or ElevenLabs voice id from "
        "account/voices/catalog.json"
    )


class ManageLinkedAccountArgs(BaseModel):
    platform: Literal["telegram", "whatsapp", "discord", "slack", "imessage"] = Field(
        description="The platform to manage"
    )
    action: Literal["generate_link", "disconnect"] = Field(
        description="'generate_link' starts connecting the platform (returns a URL or "
        "instructions); 'disconnect' removes an existing link"
    )
    phone: str | None = Field(
        default=None,
        description="REQUIRED for imessage generate_link: the user's phone number in "
        "E.164 format (e.g. +15551234567); ask the user for it first",
    )


# Rate-limit key for agent-initiated connect flows — minting link credentials
# gets the same conservative posture as the bot endpoint's limiter.
LINK_GENERATION_FEATURE_KEY = "account_platform_connect"


update_notification_settings = define_mutation_tool(
    name="update_notification_settings",
    area="notifications",
    description=(
        "Change which channels the user receives notifications on (email, telegram, "
        "discord, whatsapp, slack). Only the flags you pass change; others are left as-is. "
        + HIL_CONFIRM_NOTE
    ),
    args_model=UpdateNotificationSettingsArgs,
    apply=set_notification_channels,
    event=AnalyticsEvents.ACCOUNT_SETTING_CHANGED,
    resync=schedule_account_sync,
)

update_preferences = define_mutation_tool(
    name="update_preferences",
    area="preferences",
    description=(
        "Change the user's response style and/or home timezone. Only the values you "
        "pass change. Timezone must be a valid IANA identifier. " + HIL_CONFIRM_NOTE
    ),
    args_model=UpdatePreferencesArgs,
    apply=set_preferences,
    event=AnalyticsEvents.ACCOUNT_SETTING_CHANGED,
    resync=schedule_account_sync,
)

update_custom_instructions = define_mutation_tool(
    name="update_custom_instructions",
    area="custom_instructions",
    description=(
        "Replace the user's standing custom instructions for every conversation. "
        "Pass an empty string to clear them. " + HIL_CONFIRM_NOTE
    ),
    args_model=UpdateCustomInstructionsArgs,
    apply=set_custom_instructions,
    event=AnalyticsEvents.ACCOUNT_SETTING_CHANGED,
    resync=schedule_account_sync,
)

set_selected_voice = define_mutation_tool(
    name="set_selected_voice",
    area="voice",
    description=(
        "Switch the voice used for spoken replies. Pass a voice name or id from "
        "account/voices/catalog.json. " + HIL_CONFIRM_NOTE
    ),
    args_model=SetSelectedVoiceArgs,
    apply=select_voice,
    event=AnalyticsEvents.ACCOUNT_SETTING_CHANGED,
    resync=schedule_account_sync,
)


async def _manage_linked_account(
    user_id: str, *, platform: str, action: str, phone: str | None = None
) -> str:
    if action == "generate_link":
        await enforce_rate_limit(user_id, LINK_GENERATION_FEATURE_KEY)
        flow = await start_platform_connect(user_id, platform, phone=phone)
        parts = [f"To connect your {platform} account:"]
        if flow.instructions:
            parts.append(flow.instructions)
        if flow.action_link:
            parts.append(f"Open: {flow.action_link}")
        if flow.auth_url:
            parts.append(f"Open this URL to authorize: {flow.auth_url}")
        return "\n".join(parts)

    await disconnect_platform_account(user_id, platform)
    capture_context_event(
        AnalyticsEvents.ACCOUNT_PLATFORM_DISCONNECTED,
        {"area": "linked_accounts"},
    )
    schedule_account_sync(user_id)
    log.set(action="disconnect", platform=platform)
    return (
        f"{platform} disconnected. Its status file under "
        f"account/linked-accounts/ will show it as not connected."
    )


manage_linked_account = define_mutation_tool(
    name="manage_linked_account",
    area="linked_accounts",
    description=(
        "Connect or disconnect one of the user's messaging platforms (telegram, whatsapp, "
        "discord, slack, imessage). generate_link returns a URL or instructions the user "
        "follows to connect (no approval needed). DISCONNECTING always asks the user to "
        "confirm first."
    ),
    args_model=ManageLinkedAccountArgs,
    apply=_manage_linked_account,
)


tools = [
    update_notification_settings,
    update_preferences,
    update_custom_instructions,
    set_selected_voice,
    manage_linked_account,
]
