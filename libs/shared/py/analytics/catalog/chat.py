"""Chat, session and image events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Emoji, Identifier

__all__ = [
    "ChatBackgroundUpdateResolved",
    "ChatComposerPlusMenuClicked",
    "ChatConversationCreated",
    "ChatConversationDeleted",
    "ChatConversationRenamed",
    "ChatConversationStarred",
    "ChatFileDeleted",
    "ChatFileUpdated",
    "ChatFileUploaded",
    "ChatGridIntegrationConnectClicked",
    "ChatMessageCancelled",
    "ChatMessageCompleted",
    "ChatMessagePinned",
    "ChatMessageRefused",
    "ChatMessageSubmitted",
    "ChatMessageUnpinned",
    "ChatSlashCommandCategoryChanged",
    "ChatSlashCommandSelected",
    "ChatToolsButtonClicked",
    "ChatTurnReacted",
    "ChatVoiceModeToggled",
    "ImageDescribed",
    "ImageGenerated",
    "SessionArtifactPinned",
]


class ChatMessageSubmitted(ServerEvent):
    """A chat turn passed every gate and was accepted, from any surface."""

    event: ClassVar[str] = "chat:message_submitted"

    source: Identifier
    has_files: bool
    is_new_conversation: bool | None = None
    message_count: int | None = None
    file_count: int | None = None
    has_selected_tool: bool | None = None
    tool_name: Identifier | None = None
    tool_category: Identifier | None = None
    has_selected_workflow: bool | None = None
    workflow_id: Identifier | None = None
    has_selected_calendar_event: bool | None = None
    is_reply: bool | None = None


class ChatMessageRefused(ServerEvent):
    """A bot turn stopped at a gate; without it a refusal is indistinguishable from silence."""

    event: ClassVar[str] = "chat:message_refused"

    platform: Identifier
    reason: Literal["plan_required", "subscription_required"]


class _ChatTurnEnded(ServerEvent):
    """The properties shared by a turn's two terminal events, completed and cancelled."""

    conversation_id: Identifier
    voice_mode: bool
    is_new_conversation: bool
    delegated: bool
    queued: bool
    ttft_ms: float | None = None
    e2e_ack_ms: float | None = None
    e2e_full_ms: float | None = None
    source: Identifier | None = None


class ChatMessageCompleted(_ChatTurnEnded):
    """A chat turn reached its terminal state; executor-leg timings ride on agent:run_completed."""

    event: ClassVar[str] = "chat:message_completed"


class ChatMessageCancelled(_ChatTurnEnded):
    """A chat turn the user stopped before it finished."""

    event: ClassVar[str] = "chat:message_cancelled"


class ChatBackgroundUpdateResolved(ServerEvent):
    """Comms resolved a background executor update as a message, a one-emoji react, or silence."""

    event: ClassVar[str] = "chat:background_update_resolved"

    outcome: Identifier
    emoji: Emoji | None = None
    delivery: Literal["message", "reaction", "badge", "fallback_text"] | None = None


class ChatTurnReacted(ServerEvent):
    """An interactive turn's reply resolved to a one-emoji react instead of a message."""

    event: ClassVar[str] = "chat:turn_reacted"

    emoji: Emoji


class ChatMessagePinned(ServerEvent):
    """A user pinned a message."""

    event: ClassVar[str] = "chat:message_pinned"


class ChatMessageUnpinned(ServerEvent):
    """A user unpinned a message."""

    event: ClassVar[str] = "chat:message_unpinned"


class ChatConversationCreated(ServerEvent):
    """A conversation was created, by a user or by the system."""

    event: ClassVar[str] = "chat:conversation_created"

    is_system_generated: bool
    is_onboarding_demo: bool | None = None
    system_purpose: Identifier | None = None


class ChatConversationRenamed(ServerEvent):
    """A conversation's description changed, by the user or the auto-title task."""

    event: ClassVar[str] = "chat:conversation_renamed"

    conversation_id: Identifier


class ChatConversationStarred(ServerEvent):
    """A user starred or unstarred a conversation."""

    event: ClassVar[str] = "chat:conversation_starred"

    starred: bool
    conversation_id: Identifier


class ChatConversationDeleted(ServerEvent):
    """A user deleted one conversation (conversation_id) or all of them (count)."""

    event: ClassVar[str] = "chat:conversation_deleted"

    conversation_id: Identifier | None = None
    count: int | None = None


class ChatFileUploaded(ServerEvent):
    """A file upload was stored and indexed."""

    event: ClassVar[str] = "chat:file_uploaded"

    size_bytes: int
    resource_type: Identifier
    content_type: Identifier


class ChatFileUpdated(ServerEvent):
    """A user updated an uploaded file."""

    event: ClassVar[str] = "chat:file_updated"


class ChatFileDeleted(ServerEvent):
    """A user deleted an uploaded file."""

    event: ClassVar[str] = "chat:file_deleted"


class ChatVoiceModeToggled(WebEvent):
    """Voice mode was entered, exited, or blocked by the paywall in the composer."""

    event: ClassVar[str] = "chat:voice_mode_toggled"

    voice_mode_enabled: bool
    conversation_id: Identifier | None = None
    blocked_reason: Literal["upgrade_required"] | None = None


class ChatSlashCommandSelected(WebEvent):
    """A tool was picked from the slash-command dropdown; the typed query is never sent."""

    event: ClassVar[str] = "chat:slash_command_selected"

    tool_name: Identifier
    tool_category: Identifier
    opened_via_button: bool | None = None


class ChatSlashCommandCategoryChanged(WebEvent):
    """A category tab was switched in the slash-command dropdown."""

    event: ClassVar[str] = "chat:slash_command_category_changed"

    category: Identifier
    previous_category: Identifier


class ChatComposerPlusMenuClicked(WebEvent):
    """An item of the composer's plus menu was clicked."""

    event: ClassVar[str] = "chat:composer_plus_menu_clicked"

    item_id: Literal["upload_file"]
    is_mode: bool


class ChatToolsButtonClicked(WebEvent):
    """The composer's tools button was clicked."""

    event: ClassVar[str] = "chat:tools_button_clicked"

    is_open: bool


class ChatGridIntegrationConnectClicked(WebEvent):
    """A connect button on the new-chat integration grid was clicked."""

    event: ClassVar[str] = "chat:grid_integration_connect_clicked"

    integration_id: Identifier
    source: Literal["new_chat_grid"]


class SessionArtifactPinned(ServerEvent):
    """A user pinned a session artifact."""

    event: ClassVar[str] = "session:artifact_pinned"


class ImageGenerated(ServerEvent):
    """An image was generated from a prompt."""

    event: ClassVar[str] = "image:generated"


class ImageDescribed(ServerEvent):
    """Text was extracted from an uploaded image."""

    event: ClassVar[str] = "image:described"
