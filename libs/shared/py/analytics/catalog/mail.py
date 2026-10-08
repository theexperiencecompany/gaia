"""Email events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "EmailArchived",
    "EmailComposeOpened",
    "EmailDraftComposed",
    "EmailDraftCreated",
    "EmailDraftDeleted",
    "EmailDraftUpdated",
    "EmailLabelApplied",
    "EmailLabelCreated",
    "EmailLabelDeleted",
    "EmailLabelRemoved",
    "EmailLabelUpdated",
    "EmailMarkedRead",
    "EmailMarkedUnread",
    "EmailMovedToInbox",
    "EmailOpened",
    "EmailReplied",
    "EmailSent",
    "EmailStarred",
    "EmailTrashed",
    "EmailUnstarred",
    "EmailUntrashed",
]


class EmailSent(ServerEvent):
    """A user sent a new email or a saved draft."""

    event: ClassVar[str] = "email:sent"

    has_attachments: bool | None = None
    attachment_count: int | None = None
    recipient_count: int | None = None


class EmailReplied(ServerEvent):
    """A user sent an email into an existing thread."""

    event: ClassVar[str] = "email:replied"

    has_attachments: bool
    attachment_count: int


class EmailDraftComposed(ServerEvent):
    """The assistant finished composing a draft; not the web's email:compose_opened modal open."""

    event: ClassVar[str] = "email:draft_composed"


class EmailMarkedRead(ServerEvent):
    """A user marked messages as read."""

    event: ClassVar[str] = "email:marked_read"

    message_count: int


class EmailMarkedUnread(ServerEvent):
    """A user marked messages as unread."""

    event: ClassVar[str] = "email:marked_unread"

    message_count: int


class EmailStarred(ServerEvent):
    """A user starred messages."""

    event: ClassVar[str] = "email:starred"

    message_count: int


class EmailUnstarred(ServerEvent):
    """A user unstarred messages."""

    event: ClassVar[str] = "email:unstarred"

    message_count: int


class EmailTrashed(ServerEvent):
    """A user moved messages to the trash."""

    event: ClassVar[str] = "email:trashed"

    message_count: int


class EmailUntrashed(ServerEvent):
    """A user restored messages from the trash."""

    event: ClassVar[str] = "email:untrashed"

    message_count: int


class EmailArchived(ServerEvent):
    """A user archived messages."""

    event: ClassVar[str] = "email:archived"

    message_count: int


class EmailMovedToInbox(ServerEvent):
    """A user moved messages back to the inbox."""

    event: ClassVar[str] = "email:moved_to_inbox"

    message_count: int


class EmailLabelCreated(ServerEvent):
    """A user created a mail label."""

    event: ClassVar[str] = "email:label_created"


class EmailLabelUpdated(ServerEvent):
    """A user updated a mail label."""

    event: ClassVar[str] = "email:label_updated"


class EmailLabelDeleted(ServerEvent):
    """A user deleted a mail label."""

    event: ClassVar[str] = "email:label_deleted"


class EmailLabelApplied(ServerEvent):
    """A user applied a label to messages."""

    event: ClassVar[str] = "email:label_applied"

    message_count: int


class EmailLabelRemoved(ServerEvent):
    """A user removed a label from messages."""

    event: ClassVar[str] = "email:label_removed"

    message_count: int


class EmailDraftCreated(ServerEvent):
    """A user saved a new draft."""

    event: ClassVar[str] = "email:draft_created"


class EmailDraftUpdated(ServerEvent):
    """A user updated a draft."""

    event: ClassVar[str] = "email:draft_updated"


class EmailDraftDeleted(ServerEvent):
    """A user deleted a draft."""

    event: ClassVar[str] = "email:draft_deleted"


class EmailOpened(WebEvent):
    """A user opened an email in the mail view."""

    event: ClassVar[str] = "email:opened"

    mail_id: Identifier


class EmailComposeOpened(WebEvent):
    """A user opened the compose modal; the server only sees the eventual send."""

    event: ClassVar[str] = "email:compose_opened"
