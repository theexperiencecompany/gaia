"""Support and feedback events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier


class SupportFormSubmitted(ServerEvent):
    """A user submitted a support request; lengths and counts only, never the text."""

    event: ClassVar[str] = "support:form_submitted"

    request_type: Identifier
    title_length: int
    description_length: int
    attachment_count: int


class FeedbackMessageSubmitted(ServerEvent):
    """A user rated an assistant reply and the score was recorded."""

    event: ClassVar[str] = "feedback:message_submitted"

    is_positive: bool
