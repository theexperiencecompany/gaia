"""
Push Notification Constants
"""

import re

# Maximum devices a user can register for push notifications
MAX_DEVICES_PER_USER = 10

# Expo push token format: ExponentPushToken[xxx] or ExpoPushToken[xxx]
EXPO_TOKEN_PATTERN = re.compile(r"^Expo(nent)?PushToken\[[a-zA-Z0-9_-]+\]$")

# Notification channel type identifiers
CHANNEL_TYPE_INAPP = "inapp"
CHANNEL_TYPE_TELEGRAM = "telegram"
CHANNEL_TYPE_DISCORD = "discord"
CHANNEL_TYPE_WHATSAPP = "whatsapp"
CHANNEL_TYPE_SLACK = "slack"
CHANNEL_TYPE_IMESSAGE = "imessage"
CHANNEL_TYPE_EMAIL = "email"

# External channel types that are auto-injected based on platform links
EXTERNAL_NOTIFICATION_CHANNELS = (
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_IMESSAGE,
)

# All channel types that are auto-injected when no channels are explicitly specified.
# inapp is always available; telegram/discord/whatsapp/slack/imessage respect user
# preferences; email is auto-injected for every user with a known email address
# (also pref-gated).
ALL_AUTO_INJECTED_CHANNELS = (
    CHANNEL_TYPE_INAPP,
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_IMESSAGE,
    CHANNEL_TYPE_EMAIL,
)

# Default enabled state for external channels. Email defaults on so daily
# briefings/weekly digests reach a user's inbox until they opt out.
DEFAULT_CHANNEL_PREFERENCES: dict[str, bool] = {
    CHANNEL_TYPE_TELEGRAM: True,
    CHANNEL_TYPE_DISCORD: True,
    CHANNEL_TYPE_WHATSAPP: True,
    CHANNEL_TYPE_SLACK: True,
    CHANNEL_TYPE_IMESSAGE: True,
    CHANNEL_TYPE_EMAIL: True,
}

# Default order in which a briefing picks its ONE chat platform. The daily brief
# lands on the first platform in this list that the user has linked and enabled,
# not on every linked platform (users.briefing_channel_priority overrides it).
DEFAULT_CHAT_CHANNEL_PRIORITY: tuple[str, ...] = (
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_DISCORD,
)

# Notification metadata "kind" values that select an email template. Anything
# else (including unset) falls back to the plain-notification template.
NOTIFICATION_KIND_BRIEFING_DAILY = "briefing_daily"
NOTIFICATION_KIND_BRIEFING_WEEKLY = "briefing_weekly"

# Todo-lifecycle notification kinds (plain template; used for filtering/analytics).
NOTIFICATION_KIND_TODO_NEEDS_YOU = "todo_needs_you"
# A genuinely time-critical signal alert (see the daily-briefing-run spec's
# urgent-signal requirement): gated by urgency, not by count.
NOTIFICATION_KIND_URGENT_SIGNAL = "urgent_signal"

# An urgent alert unread this long is treated as ignored: the maintenance sweep
# writes a rejection-strike memory signal for its signal_kind so the model
# learns the user's urgency bar.
URGENT_ALERT_IGNORE_HOURS = 48

# Per-sweep cap on ignore-strike processing (cheap Mongo scan, bounded anyway).
URGENT_STRIKE_SWEEP_LIMIT = 200
NOTIFICATION_KIND_TODO_DONE = "todo_done"

# Workflow-completion notification copy. GAIA texts like a friend (first person,
# casual), not a status bar. Each entry is (title, body); {title} is the workflow
# name. One pair is picked per run so repeats don't read like a robot. This is the
# in-app (web) heads-up and it carries a "View Results" button, so bodies stay warm
# and channel-agnostic: they never claim a specific place ("in your chat"), since a
# web user has no external chat and reaches the result through the button.
WORKFLOW_DONE_COPY: tuple[tuple[str, str], ...] = (
    ("sorted {title} for you", "it's all ready whenever you are 🙌"),
    ("{title} is done", "had a proper look — everything's ready for you"),
    ("just wrapped up {title}", "pulled it all together, take a peek"),
    ("handled {title} for you", "all done end to end, give it a look"),
    ("finished {title}", "got everything ready for you to check out"),
    ("{title}: all set", "took care of it, here's what I found"),
)


def pick_workflow_done_copy(workflow_id: str, title: str, salt: str) -> tuple[str, str]:
    """Pick one human completion title/body, rotating per run, no RNG.

    ``salt`` (a per-run value such as a timestamp) only seeds the rotation so the
    same workflow doesn't always read identically; it is never shown to the user.
    """
    seed = sum(ord(c) for c in f"{workflow_id}{salt}")
    title_tmpl, body = WORKFLOW_DONE_COPY[seed % len(WORKFLOW_DONE_COPY)]
    return title_tmpl.format(title=title), body
