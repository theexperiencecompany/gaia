"""Push Notification Constants."""

from enum import StrEnum
import re
from typing import Final, Literal

# Maximum devices a user can register for push notifications
MAX_DEVICES_PER_USER = 10

# Expo push token format: ExponentPushToken[xxx] or ExpoPushToken[xxx]
EXPO_TOKEN_PATTERN = re.compile(r"^Expo(nent)?PushToken\[[a-zA-Z0-9_-]+\]$")


class NotificationChannel(StrEnum):
    """Every surface a notification can be delivered on.

    Single source of truth: the preference model, the endpoint, the repository
    writes and the delivery-time preference lookup all derive from these members,
    so a channel cannot be honoured by delivery while staying invisible in the API.
    """

    INAPP = "inapp"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    SLACK = "slack"
    IMESSAGE = "imessage"
    EMAIL = "email"


# Internal delivery routes, never named by the user or the notify tool, so they are
# not NotificationChannel members (that enum is what preferences and the tool expose).
#: Expo push to the user's registered phones.
CHANNEL_TYPE_PUSH: Final = "push"
#: A Notice in the conversation the fact belongs to.
CHANNEL_TYPE_CONVERSATION: Final = "conversation"
#: The push category the mobile app answers with approve/deny buttons.
APPROVAL_PUSH_CATEGORY: Final = "hil_approval"
#: The title a pending approval's push carries.
APPROVAL_PUSH_TITLE: Final = "GAIA needs your approval"
#: The link under an approval sent to a chat app, which opens the chat it was asked in.
APPROVAL_CHAT_LINK_LABEL: Final = "Approve or decline it in GAIA"

# External channel types a notification can be delivered on
EXTERNAL_NOTIFICATION_CHANNELS = (
    NotificationChannel.TELEGRAM,
    NotificationChannel.DISCORD,
    NotificationChannel.WHATSAPP,
    NotificationChannel.SLACK,
    NotificationChannel.IMESSAGE,
)

# Every channel type a notification may name explicitly (the tool validates
# against this). One naming none is routed by ``NotificationOrchestrator._route``.
NOTIFICATION_CHANNEL_TYPES = (NotificationChannel.INAPP, *EXTERNAL_NOTIFICATION_CHANNELS)

# Channels the user can switch on and off. inapp is excluded: it is always
# delivered, so it has no preference to store.
USER_CONFIGURABLE_CHANNELS = (*EXTERNAL_NOTIFICATION_CHANNELS, NotificationChannel.EMAIL)

# Default enabled state for every user-configurable channel
DEFAULT_CHANNEL_PREFERENCES: dict[str, bool] = {
    channel.value: True for channel in USER_CONFIGURABLE_CHANNELS
}

# Default order in which a proactive message picks its ONE chat platform. It
# lands on the first platform in this list that the user has linked and enabled,
# never on every linked platform (``users.chat_channel_priority`` overrides it).
DEFAULT_CHAT_CHANNEL_PRIORITY: tuple[str, ...] = (
    NotificationChannel.TELEGRAM,
    NotificationChannel.WHATSAPP,
    NotificationChannel.IMESSAGE,
    NotificationChannel.SLACK,
    NotificationChannel.DISCORD,
)

# How long a message the user sent on a platform keeps it "the one they're on":
# inside this window a proactive message follows them there instead of the order above.
PRESENCE_ACTIVE_WINDOW_SECONDS = 3 * 60 * 60

# How long the per-surface "last wrote here" stamps are kept, so the agent can
# still say "last seen on WhatsApp 6 days ago". The window above decides delivery.
PRESENCE_RETENTION_SECONDS = 30 * 24 * 60 * 60


class ProactiveMessageClass(StrEnum):
    """What a message GAIA sends on its own initiative is, which decides if quiet hours hold it."""

    #: GAIA's own news (a workflow result, a todo run's report, a nudge, a
    #: notification): held until the user's quiet hours end.
    ROUTINE = "routine"
    #: A reminder the user set for this time: it arrives when they asked, quiet hours or not.
    USER_TIMED = "user_timed"
    #: A reply to something the user just did (the hello after linking a chat app): expected now.
    USER_TRIGGERED = "user_triggered"
    #: The result of a run the trigger gate let through quiet hours as urgent.
    URGENT = "urgent"


#: Classes delivered even inside the user's quiet hours.
QUIET_HOURS_EXEMPT: frozenset[ProactiveMessageClass] = frozenset(
    {
        ProactiveMessageClass.USER_TIMED,
        ProactiveMessageClass.USER_TRIGGERED,
        ProactiveMessageClass.URGENT,
    }
)


# ARQ task that delivers a proactive chat message held for quiet hours, and the
# prefix of its per-message job id.
DEFERRED_CHAT_MESSAGE_TASK = "deliver_deferred_chat_message"
DEFERRED_CHAT_MESSAGE_JOB_PREFIX = "deferred-chat-message:"

# In-app route a notification action redirects to. Shared so the memory-backfill
# and Gmail-personalization notifications can't drift onto different pages.
MEMORY_SETTINGS_URL = "/settings/memory"

# Workflow-completion copy: first-person and casual. Each entry is (title, body);
# {title} is the workflow name, one pair picked per run. In-app (web) heads-up
# with a "View Results" button, so bodies never claim a place like "in your chat".
WORKFLOW_DONE_COPY: tuple[tuple[str, str], ...] = (
    ("sorted {title} for you", "it's all ready whenever you are 🙌"),
    ("{title} is done", "had a proper look, everything's ready for you"),
    ("just wrapped up {title}", "pulled it all together, take a peek"),
    ("handled {title} for you", "all done end to end, give it a look"),
    ("finished {title}", "got everything ready for you to check out"),
    ("{title}: all set", "took care of it, here's what I found"),
)


def pick_workflow_done_copy(workflow_id: str, title: str, salt: str) -> tuple[str, str]:
    """Pick one human completion title/body, rotating per run, no RNG.

    salt (a per-run value such as a timestamp) only seeds the rotation so the
    same workflow doesn't always read identically; it is never shown to the user.
    """
    seed = sum(ord(c) for c in f"{workflow_id}{salt}")
    title_tmpl, body = WORKFLOW_DONE_COPY[seed % len(WORKFLOW_DONE_COPY)]
    return title_tmpl.format(title=title), body


# A photo caption's limit on Telegram and WhatsApp; post_to_platform_chat carries
# the rest of a longer caption as follow-up text.
CHAT_CAPTION_MAX_CHARS = 1024


class NotificationKind(StrEnum):
    """What a notification is about, stored as its details' kind; a channel may render each its own way."""

    #: The daily brief: its email is the edition.
    BRIEFING_DAILY = "briefing_daily"
    #: The weekly recap: its email is the edition.
    BRIEFING_WEEKLY = "briefing_weekly"
    #: A quiet day's note: no edition, so every channel renders it as a plain notification.
    BRIEFING_NOTE = "briefing_note"
    #: One todo: its run's result, or what its health check found.
    TODO = "todo"
    #: A scheduled todo that used up its attempts.
    TODO_FAILED = "todo_failed"
    #: An event a todo watches fired.
    TODO_TRIGGER_FIRED = "todo_trigger_fired"
    #: The digest of todos left idle.
    DORMANT_TODOS = "dormant_todos"
    #: A reminder came due.
    REMINDER = "reminder"
    #: A workflow run finished; its result is in the conversation.
    WORKFLOW_COMPLETED = "workflow_completed"
    #: A workflow run errored or was stopped by a limit.
    WORKFLOW_FAILED = "workflow_failed"
    #: A workflow paused until the integrations it needs are connected.
    WORKFLOW_PAUSED = "workflow_paused"
    #: An integration's connection expired and paused the workflows using it.
    INTEGRATION_EXPIRED = "integration_expired"
    #: Connecting an integration set up its system workflows.
    SYSTEM_WORKFLOWS_PROVISIONED = "system_workflows_provisioned"
    #: The user's memory was seeded from past conversations.
    MEMORY_READY = "memory_ready"
    #: GAIA personalised itself from the user's Gmail.
    GMAIL_PERSONALIZED = "gmail_personalized"
    #: A gated action waits on the user's approval.
    APPROVAL = "approval"


#: The kinds a brief's notification takes.
BriefNotificationKind = Literal[
    NotificationKind.BRIEFING_DAILY,
    NotificationKind.BRIEFING_WEEKLY,
    NotificationKind.BRIEFING_NOTE,
]
