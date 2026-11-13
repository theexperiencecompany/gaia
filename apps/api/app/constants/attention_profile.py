"""The attention profile a user starts with: answers that err toward telling them."""

from typing import Final

#: (question, answer) pairs. A learned answer may make the Judge quieter for a category the user
#: named; the seed never does, so a user who has told GAIA nothing is told too much, not too little.
DEFAULT_ATTENTION_PROFILE: Final[tuple[tuple[str, str], ...]] = (
    (
        "What is worth waking you up or interrupting a meeting for?",
        "Family health or safety, my home (leaks, alarms), money actually leaving or being blocked, travel on the day of travel, a person waiting on me right now, a hard deadline that closes before I'd normally see it, and anything I explicitly said to ping me the moment it happens.",
    ),
    (
        "If a deadline closes before you'd normally check your messages, do you want to hear about it in time even if it's early or late?",
        "Yes, always in time. Missing a real deadline is worse than an extra message.",
    ),
    (
        "During a call or meeting, what should come through?",
        "Only things about that meeting or the people in it, or real emergencies. Everything else after.",
    ),
    (
        "When you ask me to watch something or ping you when it changes, do you want it straight away?",
        "Yes, that's why I asked. If I said 'the moment', even at night.",
    ),
    (
        "Money alerts: which ones matter?",
        "Fraud checks, failed or declined payments, anything that triggers a late fee or service cut-off, and large unexpected debits. Routine statements and small receipts can wait for the summary.",
    ),
    (
        "Mistakes you make on my behalf (wrong recipient, wrong booking)?",
        "Tell me as soon as you notice, while it can still be fixed.",
    ),
    (
        "Anything private you should be careful with on my lock screen or in groups?",
        "Health, money, and anything about family or relationships. Keep previews generic.",
    ),
    (
        "Weekends and holidays?",
        "Keep work out unless it's an emergency or something I'm waiting on. Personal and family things are fine.",
    ),
)
