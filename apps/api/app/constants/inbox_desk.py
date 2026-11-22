"""The Inbox desk: the one GAIA task per user that triages mail, owns its threads and briefs each morning."""

from datetime import timedelta
from enum import StrEnum
from typing import Final

INBOX_DESK_TITLE: Final[str] = "Inbox desk"
INBOX_DESK_RECURRENCE: Final[str] = "0 8 * * *"
PROVISION_INBOX_DESK_TASK: Final[str] = "provision_inbox_desk"
# Automated senders the desk's fetch leaves out: GitHub and other
# notifications land in Primary, and this cut a live 24h window from 224 messages to 10 people.
INBOX_DESK_AUTOMATED_SENDERS: Final[tuple[str, ...]] = (
    "noreply",
    "no-reply",
    "notifications",
    "notification",
    "mailer-daemon",
    "donotreply",
)
# Every inbox tab but Promotions and Social, minus automated senders: group-delivered
# work threads land in Forums, which a Primary-only fetch never read.
INBOX_DESK_MAIL_FILTER: Final[str] = "in:inbox -category:promotions -category:social " + " ".join(
    f"-from:{sender}" for sender in INBOX_DESK_AUTOMATED_SENDERS
)
# The desk's second fetch: mail the user may have to act on, which banks and billing send
# from the automated senders the Primary filter leaves out. Step 5 still classifies each one.
INBOX_DESK_ACTION_MAIL_TERMS: Final[tuple[str, ...]] = (
    "declined",
    "(insufficient funds)",
    "(payment failed)",
    "(payment unsuccessful)",
    "(security alert)",
    "(unusual activity)",
    "expiring",
    "expires",
    "suspended",
    "overdue",
    "(past due)",
    "(action required)",
)
# Routine sign-in notices and codes ask nothing of the user, so the action fetch leaves them out.
INBOX_DESK_ROUTINE_SIGN_IN_TERMS: Final[tuple[str, ...]] = (
    "(new sign-in)",
    "(new login)",
    "(new device)",
    "(verification code)",
    "(security code)",
    "(login code)",
    "(sign-in code)",
)
# A security problem is fetched whatever else its subject says, sign-in words included.
INBOX_DESK_SECURITY_PROBLEM_TERMS: Final[tuple[str, ...]] = (
    "blocked",
    "locked",
    "suspicious",
    "unrecognised",
    "unrecognized",
    "compromised",
    "(password changed)",
    "(password was changed)",
    "(recovery changed)",
    "(recovery email)",
    "(recovery phone)",
    "(two-factor enabled)",
    "(two-factor removed)",
    "(2-step verification)",
    "(security settings)",
    "(password updated)",
    "(turned off)",
    "disabled",
)
# Gmail's (a b) is every word, so no quote reaches the prompt's quoted query, and no brace
# reaches the run prompt's str.format.
INBOX_DESK_ACTION_MAIL_FILTER: Final[str] = (
    "in:inbox ((("
    + " OR ".join(f"subject:{term}" for term in INBOX_DESK_ACTION_MAIL_TERMS)
    + ") "
    + " ".join(f"-subject:{term}" for term in INBOX_DESK_ROUTINE_SIGN_IN_TERMS)
    + ") OR ("
    + " OR ".join(f"subject:{term}" for term in INBOX_DESK_SECURITY_PROBLEM_TERMS)
    + "))"
)
# The desk's briefing is read in seconds: words per item, per summary under an item,
# and lines per capped section.
INBOX_DESK_BRIEFING_ITEM_MAX_WORDS: Final[int] = 12
INBOX_DESK_SUMMARY_MAX_WORDS: Final[int] = 25
INBOX_DESK_NEEDS_YOU_MAX_ITEMS: Final[int] = 5
INBOX_DESK_FYI_MAX_LINES: Final[int] = 5
# Days a high-confidence pattern must hold before the desk suggests a Gmail change from it.
INBOX_DESK_SUGGEST_AFTER_DAYS: Final[int] = 3
# Heads the desk's Current State line naming each question it already asked once.
INBOX_DESK_ASKED_ONCE: Final[str] = "Asked once"


class InboxDeskAsk(StrEnum):
    """What the desk does only once the user says yes, each asked at most once ever."""

    SUMMARIES = "summaries"
    TODOS = "todos"


# First retry delay of a failed provisioning; each further try doubles it.
INBOX_DESK_PROVISION_RETRY_DELAY: Final[timedelta] = timedelta(minutes=2)
