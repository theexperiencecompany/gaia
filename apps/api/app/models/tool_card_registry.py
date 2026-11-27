"""Every tool card's payload model, keyed by the tool_name its entries carry.

A card is stored and streamed as a ToolDataEntry whose data is its payload model's JSON. The
registry is the one owner of that pairing: a tool streams its card through it, and the OpenAPI
export publishes ToolDataEntry as the union of these cards so every client reads a generated
type per tool.
"""

from collections.abc import Mapping
from typing import Annotated, Final

from pydantic import Field, JsonValue, TypeAdapter

from app.models.artifact_models import ArtifactEvent
from app.models.brief_view_models import BriefCard
from app.models.calendar_models import (
    CalendarEventDisplay,
    CalendarListCard,
    GoogleCalendarEventResource,
)
from app.models.desktop_card_models import ScreenshotCard
from app.models.device_card_models import DeviceApprovalCard, DeviceOnboardingCard
from app.models.integration_card_models import (
    ConnectOptionsData,
    IntegrationConnectionData,
    IntegrationListCard,
)
from app.models.integrations.weather import WeatherReport
from app.models.mail_card_models import (
    ContactCard,
    EmailComposeCard,
    EmailListItem,
    EmailSentDraftCard,
    EmailThreadCard,
)
from app.models.mcp_app_models import McpAppData
from app.models.memory_card_models import MemoryCardData
from app.models.notification.notification_card_models import (
    NotificationListCard,
    SentNotificationCard,
)
from app.models.openui_artifact_models import ArtifactCard
from app.models.rate_limit_card_models import RateLimitCardData
from app.models.reddit_card_models import RedditCardData
from app.models.search_card_models import SearchResultsData
from app.models.stream_events import (
    ApprovalRequestEntryData,
    SubagentGroupCardData,
    ToolCallsCardData,
)
from app.models.support_models import SupportTicketDraft
from app.models.todo_card_models import TodoCardData
from app.models.todo_progress_card_models import TodoProgressCardData
from app.models.twitter_card_models import TwitterSearchCard, TwitterUserCard
from app.models.workflow_card_models import WorkflowCreatedData, WorkflowDraftData
from app.schemas.browser import BrowserCardSnapshot

#: Each card's data type: its payload model, or a list or union of payload models.
TOOL_CARDS: Final[Mapping[str, object]] = {
    "artifact_data": ArtifactEvent,
    "artifact_done": ArtifactCard,
    "screenshot_data": ScreenshotCard,
    "browser_task_data": Annotated[BrowserCardSnapshot, Field(discriminator="kind")],
    "mcp_app": McpAppData,
    "tool_calls_data": ToolCallsCardData,
    "approval_request": ApprovalRequestEntryData,
    "subagent_group": SubagentGroupCardData,
    "todo_progress": TodoProgressCardData,
    "briefing_data": BriefCard,
    "email_compose_data": list[EmailComposeCard],
    "email_fetch_data": list[EmailListItem],
    "email_thread_data": EmailThreadCard,
    "email_sent_data": list[EmailComposeCard | EmailSentDraftCard],
    "contacts_data": list[ContactCard],
    "calendar_fetch_data": list[CalendarEventDisplay] | list[GoogleCalendarEventResource],
    "calendar_list_fetch_data": list[CalendarListCard],
    "people_search_data": list[ContactCard],
    "todo_data": TodoCardData,
    "search_results": SearchResultsData,
    "weather_data": WeatherReport,
    "support_ticket_data": list[SupportTicketDraft],
    "notification_data": NotificationListCard,
    "send_notification_data": SentNotificationCard,
    "memory_data": MemoryCardData,
    "rate_limit_data": RateLimitCardData,
    "integration_connection_required": IntegrationConnectionData,
    "integration_list_data": IntegrationListCard,
    "connect_options": ConnectOptionsData,
    "device_onboarding_required": DeviceOnboardingCard,
    "device_approval_required": DeviceApprovalCard,
    "reddit_data": RedditCardData,
    "twitter_user_data": list[TwitterUserCard],
    "twitter_search_data": TwitterSearchCard,
    "workflow_draft": WorkflowDraftData,
    "workflow_created": WorkflowCreatedData,
}

_ADAPTERS: Final[Mapping[str, TypeAdapter[object]]] = {
    name: TypeAdapter(data) for name, data in TOOL_CARDS.items()
}


def tool_card_data(tool_name: str, data: object) -> JsonValue:
    """Return a card's data as the JSON its published schema names; refuses data of another tool's shape."""
    adapter = _ADAPTERS[tool_name]
    dumped: JsonValue = adapter.dump_python(
        adapter.validate_python(data), mode="json", by_alias=True
    )
    return dumped


def tool_card(tool_name: str, data: object) -> dict[str, JsonValue]:
    """Return the stream chunk that carries a tool's card under its tool name."""
    return {tool_name: tool_card_data(tool_name, data)}
