"""Chat constants."""

from enum import Enum

# Sized so small files (images, short PDFs) come through in full; only large
# multi-page summaries truncate, with the full text in the `<file>.summary.md` sidecar.


#: tool_data entry a subagent's streamed work is grouped under (mirrored as
#: SUBAGENT_GROUP_TOOL_NAME in @gaia/shared/chat).
SUBAGENT_GROUP_TOOL_NAME = "subagent_group"
#: The tool call that opens a browser run, and the prefix of the group its actions stream under.
BROWSER_TASK_TOOL_NAME = "browser_task"
BROWSER_GROUP_PREFIX = "browser:"
#: Cards whose calls in one item render as one card holding every call's data.
GROUPED_TOOL_CARDS = frozenset(
    {
        "approval_request",
        "search_results",
        "reddit_data",
        "integration_connection_required",
        "integration_list_data",
        "device_approval_required",
        "rate_limit_data",
        "email_fetch_data",
        "email_compose_data",
        "email_sent_data",
        "artifact_data",
        "memory_data",
        "browser_task_data",
    }
)


#: The web app's path to one conversation.
CONVERSATION_PATH = "/c/{conversation_id}"


class ConversationSource(str, Enum):
    """Client or channel a conversation originated from."""

    WEB = "web"
    MOBILE = "mobile"
    DESKTOP = "desktop"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    IMESSAGE = "imessage"
    #: A turn spoken on a voice call; its reply is read aloud.
    VOICE = "voice"
    WORKFLOW_SYSTEM = "workflow_system"
    BACKGROUND = "background"

    @classmethod
    def coerce(cls, value: "ConversationSource | str | None") -> "ConversationSource | None":
        """Parse a raw source value (e.g. a stored string) into the enum.

        Returns None for blank or unrecognised values so callers can compare on
        enum members instead of raw strings.
        """
        try:
            return cls(value)
        except ValueError:
            return None

    @property
    def display_name(self) -> str:
        """How this channel is spelled in user-facing copy and in prompts.

        value.capitalize() is wrong for half of these ("Whatsapp", "Imessage"),
        so the ones with real casing are named explicitly.
        """
        return _SOURCE_DISPLAY_NAMES.get(self, self.value.capitalize())


#: Only the channels whose brand casing differs from value.capitalize().
_SOURCE_DISPLAY_NAMES: dict["ConversationSource", str] = {
    ConversationSource.WHATSAPP: "WhatsApp",
    ConversationSource.IMESSAGE: "iMessage",
}


class SourceCategory(str, Enum):
    """Generalized origin of a graph invocation.

    Coarser than ConversationSource: every channel rolls up to one of these so
    traces and tools branch on origin without enumerating every platform.
    """

    BG = "bg"  # autonomous background work (workflows, scheduled todos, sweeps)
    UI = "ui"  # first-party clients (web, mobile, desktop)
    BOT = "bot"  # messaging-platform bots (whatsapp, telegram, discord, slack)

    @classmethod
    def from_source(cls, source: "ConversationSource | str | None") -> "SourceCategory":
        """Map a specific ConversationSource to its category.

        Unknown or unset sources fall back to BG: only the silent background
        paths leave the source blank.
        """
        channel = ConversationSource.coerce(source)
        if channel in _UI_SOURCES:
            return cls.UI
        if channel in BOT_CONVERSATION_SOURCES:
            return cls.BOT
        return cls.BG


# Which channels belong to each category, and the single source of truth for
# "which sources are messaging-platform bots" — used by delivery routing and the
# web conversation-list filter. Members are enums, so comparisons never use str.
_UI_SOURCES: frozenset[ConversationSource] = frozenset(
    {
        ConversationSource.WEB,
        ConversationSource.MOBILE,
        ConversationSource.DESKTOP,
        ConversationSource.VOICE,
    }
)
BOT_CONVERSATION_SOURCES: frozenset[ConversationSource] = frozenset(
    {
        ConversationSource.WHATSAPP,
        ConversationSource.TELEGRAM,
        ConversationSource.DISCORD,
        ConversationSource.SLACK,
        ConversationSource.IMESSAGE,
    }
)

# Max characters of an uploaded file's summary inlined into the turn context.
# Small files (images, short PDFs) come through in full; only large multi-page
# summaries truncate, with the full text in the <file>.summary.md sidecar.
UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS = 4000

# Upper bound for a single incoming chat message, rejected at the request
# boundary. Generous on purpose: the web composer converts pastes over ~10k
# chars into .txt attachments, so normal traffic never gets near this.
MAX_MESSAGE_LENGTH = 50_000

# A conversation's messages, one document per entry ordered by seq; its head
# (the conversations document) holds log_head and the not-yet-flushed outbox.
CONVERSATION_ENTRIES_COLLECTION = "conversation_entries"

# Conditional head writes lost to a concurrent append before one gives up loudly.
CONVERSATION_APPEND_MAX_ATTEMPTS = 64
CONVERSATION_APPEND_JITTER_SECONDS = 0.004

# The newest entries a whole-conversation read (get, sync, recent) returns: the
# window clients saw when the old build capped every thread at 600 messages.
CONVERSATION_READ_LIMIT = 600

# Named in every refusal of a conversation the entries migration has not reached.
CONVERSATION_ENTRIES_MIGRATION_SCRIPT = "scripts.migrate_conversation_entries"
# One row per conversation the entries migration's last pass failed on, cleared when a pass succeeds.
CONVERSATION_MIGRATION_FAILURES_COLLECTION = "conversation_migration_failures"
# One row per element of an embedded array the entries migration moved off a head too full to take the log pointer.
CONVERSATION_ARCHIVED_MESSAGES_COLLECTION = "conversation_archived_messages"
# Named in every refusal of a log entry still holding a field this stack renamed.
ENTRY_RENAMES_MIGRATION_SCRIPT = "scripts.migrate_approval_vocabulary"

# The tool_data card a session artifact rides on: written by the coding tools, read off the reply.
ARTIFACT_CARD = "artifact_data"
# The tool_data card a tool call, or the thinking between calls, shows on.
TOOL_CALLS_CARD = "tool_calls_data"
# The tool_data card take_screenshot shows the captured screen on.
SCREENSHOT_CARD = "screenshot_data"

# No real reply opens with this many empty bubbles; past it a reply that is still
# only breaks is a runaway (3,998 of them, ~100 s, in production) and is stopped.
MAX_LEADING_MESSAGE_BREAKS = 8

# Shown to the model, never stored, on the retry of an empty completion: the
# history may hold the empty replies it is copying.
EMPTY_COMPLETION_RETRY_NOTICE = (
    "[System notice: your previous attempt at this reply produced no visible text. "
    "Reply to the conversation in words.]"
)
