"""How a gated call reads to the user: plain action, closing verb, and which arguments to show.

Keyed by the same tool names as hil_destructive_tools.py. A tool without an entry
falls back to its humanised name and its short scalar/list arguments
(services/hil/describe.py), so this table only needs the tools people meet most.
"""

from dataclasses import dataclass
from enum import StrEnum


class DetailRole(StrEnum):
    """What an argument is to the action, which decides where the headline places it."""

    RECIPIENTS = "recipients"
    TITLE = "title"
    PLACE = "place"
    CONTENT = "content"
    OTHER = "other"


@dataclass(frozen=True)
class DetailField:
    """One labelled detail line, read from the first argument key that has a value."""

    label: str
    keys: tuple[str, ...]
    role: DetailRole = DetailRole.OTHER


@dataclass(frozen=True)
class ToolDescription:
    """The plain-language phrasing of one gated tool."""

    action: str
    confirm: str
    fields: tuple[DetailField, ...] = ()
    # Joins a PLACE detail to the headline: "Delete a calendar event from Work".
    place_word: str = "in"


_EMAIL_TO = DetailField("To", ("recipient_email", "extra_recipients"), DetailRole.RECIPIENTS)
_EMAIL_SUBJECT = DetailField("Subject", ("subject",), DetailRole.TITLE)
_INSTRUCTIONS = DetailField("New instructions", ("content",), DetailRole.CONTENT)

HIL_TOOL_DESCRIPTIONS: dict[str, ToolDescription] = {
    "GMAIL_SEND_EMAIL": ToolDescription(
        "Send an email",
        "send it",
        (_EMAIL_TO, _EMAIL_SUBJECT, DetailField("Message", ("body",), DetailRole.CONTENT)),
    ),
    "GMAIL_REPLY_TO_THREAD": ToolDescription(
        "Reply to an email",
        "send it",
        (_EMAIL_TO, DetailField("Message", ("message_body", "body"), DetailRole.CONTENT)),
    ),
    "GMAIL_FORWARD_MESSAGE": ToolDescription(
        "Forward an email",
        "forward it",
        (
            DetailField("To", ("recipient_email",), DetailRole.RECIPIENTS),
            DetailField("Note", ("additional_text",), DetailRole.CONTENT),
        ),
    ),
    "GMAIL_SEND_DRAFT": ToolDescription("Send a saved email draft", "send it"),
    "GMAIL_DELETE_MESSAGE": ToolDescription("Permanently delete an email", "delete it"),
    "GMAIL_DELETE_THREAD": ToolDescription("Permanently delete an email thread", "delete it"),
    "GMAIL_BATCH_DELETE_MESSAGES": ToolDescription(
        "Permanently delete several emails", "delete them"
    ),
    "GOOGLECALENDAR_DELETE_EVENT": ToolDescription(
        "Delete a calendar event",
        "delete it",
        (DetailField("Calendar", ("calendar_id",), DetailRole.PLACE),),
        place_word="from",
    ),
    "TWITTER_CREATION_OF_A_POST": ToolDescription(
        "Post on X", "post it", (DetailField("Post", ("text",), DetailRole.CONTENT),)
    ),
    "update_user_instructions": ToolDescription(
        "Change your saved instructions for GAIA",
        "save them",
        (DetailField("Applies to", ("scope",)), _INSTRUCTIONS),
    ),
    "update_integration_instructions": ToolDescription(
        "Change GAIA's instructions for an integration",
        "save them",
        (DetailField("Integration", ("integration_id",), DetailRole.PLACE), _INSTRUCTIONS),
        place_word="for",
    ),
}

# Closing verb for a tool with no entry.
HIL_DEFAULT_CONFIRM = "go ahead"
# Detail lines a card or prompt shows at most.
HIL_DESCRIPTION_MAX_DETAILS = 3
# A content preview is cut here, with an ellipsis.
HIL_DESCRIPTION_PREVIEW_CHARS = 100
# A plain value (an address, a title) is cut here.
HIL_DESCRIPTION_VALUE_CHARS = 80
# A list value shows this many items, then "and N more".
HIL_DESCRIPTION_MAX_LIST_ITEMS = 4
