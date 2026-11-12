"""Chat constants."""

from enum import Enum

# Sized so small files (images, short PDFs) come through in full; only large
# multi-page summaries truncate, with the full text in the `<file>.summary.md` sidecar.


#: tool_data entry a subagent's streamed work is grouped under (mirrored as
#: SUBAGENT_GROUP_TOOL_NAME in @gaia/shared/chat).
SUBAGENT_GROUP_TOOL_NAME = "subagent_group"


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
    {ConversationSource.WEB, ConversationSource.MOBILE, ConversationSource.DESKTOP}
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

# Named in every refusal of a conversation the entries migration has not reached.
CONVERSATION_ENTRIES_MIGRATION_SCRIPT = "app.scripts.migrate_conversation_entries"

# ``MessageModel.type`` of a message the human wrote (the other value is
# ``"bot"``). Named so a stored-message query and the writers agree on the literal.
USER_MESSAGE_TYPE = "user"

# Saved on a reply whose turn died (a crashed process) after the user saw it begin.
TURN_INTERRUPTED = (
    "My reply was cut off before I could finish it. Anything I started for it may "
    "already be done, so check before asking again."
)

# Shown when the model produced no text at all (reasoning-only output,
# max_tokens exhausted mid-thought, a content filter) — a blank bubble reads as "it ignored me".
EMPTY_RESPONSE_FALLBACK = "that didn't come through, say it again?"
