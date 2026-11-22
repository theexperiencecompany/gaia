"""How a gated call reads to the user: one natural sentence, its closing verb, and the facts to show.

Keyed by the same tool names as hil_destructive_tools.py. A tool without an entry
falls back to its humanised name, a title-like argument and its short arguments
(services/hil/describe.py), so this table only needs the tools people meet most.
"""

from dataclasses import dataclass
from enum import StrEnum


class DetailRole(StrEnum):
    """What an argument is to the action, which decides where the sentence places it."""

    RECIPIENTS = "recipients"
    TITLE = "title"
    PLACE = "place"
    WHEN = "when"
    CONTENT = "content"
    OTHER = "other"


# How a question opens unless its tool says otherwise: "OK to email bob@x.com?".
HIL_DEFAULT_ASK = "OK to"

# Roles the sentence names, so their values are not repeated as detail lines.
HIL_SENTENCE_ROLES = frozenset(
    {DetailRole.RECIPIENTS, DetailRole.TITLE, DetailRole.PLACE, DetailRole.WHEN}
)


@dataclass(frozen=True)
class DetailField:
    """One labelled fact, read from every listed argument key that has a value."""

    label: str
    keys: tuple[str, ...]
    role: DetailRole = DetailRole.OTHER


@dataclass(frozen=True)
class ToolDescription:
    """The plain-language phrasing of one gated tool.

    phrase is the sentence in parts; a part's {role} slot fills from the field with that
    role, and a part whose slot has no value is left out ("add", " {title}", " for {when}").
    """

    action: str
    phrase: tuple[str, ...]
    confirm: str
    fields: tuple[DetailField, ...] = ()
    ask: str = HIL_DEFAULT_ASK


_EMAIL_TO = DetailField("To", ("recipient_email", "extra_recipients"), DetailRole.RECIPIENTS)
_EMAIL_CC = DetailField("Cc", ("cc",))
_EMAIL_SUBJECT = DetailField("Subject", ("subject",), DetailRole.TITLE)
_EMAIL_BODY = DetailField("Message", ("body",), DetailRole.CONTENT)
_INSTRUCTIONS = DetailField("New instructions", ("content",), DetailRole.CONTENT)
_TODO_DUE = DetailField("Due date", ("due_date",), DetailRole.WHEN)
_TODO_PRIORITY = DetailField("Priority", ("priority",))
_TODO_LABELS = DetailField("Labels", ("labels",))
_TODO_NOTES = DetailField("Notes", ("description",), DetailRole.CONTENT)
_EVENTS = "events[]."

HIL_TOOL_DESCRIPTIONS: dict[str, ToolDescription] = {
    "GMAIL_SEND_EMAIL": ToolDescription(
        "Send an email",
        ("email", " {recipients}", " about {title}"),
        "send it",
        (_EMAIL_TO, _EMAIL_CC, _EMAIL_SUBJECT, _EMAIL_BODY),
    ),
    "GMAIL_REPLY_TO_THREAD": ToolDescription(
        "Reply to an email",
        ("reply", " to {recipients}"),
        "send it",
        (_EMAIL_TO, DetailField("Message", ("message_body", "body"), DetailRole.CONTENT)),
    ),
    "GMAIL_FORWARD_MESSAGE": ToolDescription(
        "Forward an email",
        ("forward the email", " to {recipients}"),
        "forward it",
        (
            DetailField("To", ("recipient_email",), DetailRole.RECIPIENTS),
            DetailField("Note", ("additional_text",), DetailRole.CONTENT),
        ),
    ),
    "GMAIL_SEND_DRAFT": ToolDescription(
        "Send a saved email draft", ("send your saved draft",), "send it"
    ),
    "GMAIL_DELETE_MESSAGE": ToolDescription(
        "Permanently delete an email", ("permanently delete an email",), "delete it"
    ),
    "GMAIL_DELETE_THREAD": ToolDescription(
        "Permanently delete an email thread", ("permanently delete an email thread",), "delete it"
    ),
    "GMAIL_BATCH_DELETE_MESSAGES": ToolDescription(
        "Permanently delete several emails", ("permanently delete several emails",), "delete them"
    ),
    "GOOGLECALENDAR_CUSTOM_CREATE_EVENT": ToolDescription(
        "Add a calendar event",
        ("add", " {title}", " to your calendar", " for {when}"),
        "add it",
        (
            DetailField("Event", (f"{_EVENTS}summary",), DetailRole.TITLE),
            DetailField("When", (f"{_EVENTS}start_datetime",), DetailRole.WHEN),
            DetailField("Guests", (f"{_EVENTS}attendees",)),
            DetailField("Where", (f"{_EVENTS}location",)),
        ),
        ask="Want me to",
    ),
    "GOOGLECALENDAR_DELETE_EVENT": ToolDescription(
        "Delete a calendar event", ("delete an event from your calendar",), "delete it"
    ),
    "create_todo": ToolDescription(
        "Add a todo",
        ("add", " {title}", " to your todos", " for {when}"),
        "add it",
        (
            DetailField("Title", ("title",), DetailRole.TITLE),
            _TODO_DUE,
            _TODO_PRIORITY,
            _TODO_LABELS,
            _TODO_NOTES,
        ),
        ask="Want me to",
    ),
    "update_todo": ToolDescription(
        "Update a todo",
        ("update a todo",),
        "update it",
        (
            DetailField("New title", ("title",)),
            _TODO_DUE,
            _TODO_PRIORITY,
            DetailField("Done", ("completed",)),
            _TODO_LABELS,
            _TODO_NOTES,
        ),
    ),
    "delete_todo": ToolDescription("Delete a todo", ("delete a todo",), "delete it"),
    "TWITTER_CREATION_OF_A_POST": ToolDescription(
        "Post on X",
        ("post on X",),
        "post it",
        (DetailField("Post", ("text",), DetailRole.CONTENT),),
    ),
    "update_user_instructions": ToolDescription(
        "Change your saved instructions for GAIA",
        ("change your saved instructions",),
        "save them",
        (DetailField("Applies to", ("scope",)), _INSTRUCTIONS),
    ),
    "update_integration_instructions": ToolDescription(
        "Change GAIA's instructions for an integration",
        ("change my instructions", " for {place}"),
        "save them",
        (DetailField("Integration", ("integration_id",), DetailRole.PLACE), _INSTRUCTIONS),
    ),
}

# Argument keys a tool with no entry names in its sentence, first match wins.
HIL_FALLBACK_TITLE_KEYS = ("title", "name", "summary", "subject")
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
# Lead and joiner of the re-ask after a yes with a change: "Updated priority to high".
HIL_CHANGE_LEAD = "Updated"
HIL_CHANGE_JOIN = " and "
# The re-ask itself: "Updated priority to high — still OK to add it?".
HIL_REASK = "{change} \u2014 still OK to {confirm}?"
