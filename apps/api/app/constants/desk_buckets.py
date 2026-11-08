"""The email verdict: the yes/no judgments JEV makes about one email, and the desk buckets code derives from them.

JEV answers each judgment as P(true). Code reads it on three bands, yes above 0.7, no
under 0.3 and unsure between, and the decision table in email_verdict turns the bands
into a bucket and a gate skip. reply files a sub-todo and a draft, act an action sub-todo
due on the email's deadline, fyi a briefing line, and junk is only counted.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final, NamedTuple

from app.constants.cache import ONE_DAY_TTL


class DeskBucket(StrEnum):
    """What the desk does with one fetched email; its value is the key the desk reads."""

    REPLY = "reply"
    ACT = "act"
    FYI = "fyi"
    JUNK = "junk"


class Judgment(StrEnum):
    """One yes/no question JEV answers about an email; its value is the question's key."""

    IS_PERSON = "is_person"
    ASKS_USER = "asks_user"
    REPORTS_ISSUE = "reports_issue"
    OFFICIAL = "official"
    RELEVANT = "relevant"
    BULK = "bulk"


class NoulQuestion(NamedTuple):
    """One judgment as JEV reads it: the question, and what a true and a false answer mean."""

    instructions: str
    true: str
    false: str


class Band(StrEnum):
    """Where a P(true) falls: a settled yes, a settled no, or not settled."""

    YES = "yes"
    NO = "no"
    UNSURE = "unsure"


# Typesafe's starting bands for a Noul: yes above, no below, unsure between.
JUDGMENT_YES_OVER: Final = 0.7
JUDGMENT_NO_UNDER: Final = 0.3
# The gate's measured p95 is 370 ms; a slower answer leaves the email for the desk to judge.
EMAIL_VERDICT_JEV_TIMEOUT_SECONDS: Final = 3.0
# JEV calls in flight at once for email verdicts, process-wide.
EMAIL_VERDICT_JEV_LIMIT: Final = 8
EMAIL_VERDICT_JEV_LIMIT_KEY: Final = "email_verdict_jev"
# The sweep after an email's arrival runs within a day; a second day covers one that slips.
EMAIL_VERDICT_TTL_SECONDS: Final = 2 * ONE_DAY_TTL
# Who the user is, as JEV reads it next to every email; a long About-the-user note costs tokens.
EMAIL_VERDICT_PROFILE_MAX_CHARS: Final = 600
# How much of the cleaned body the verdict reads: a notice's deciding sentence (was it the user,
# what to do) often falls past the 300-character event snippet.
EMAIL_VERDICT_BODY_MAX_CHARS: Final = 1_000
# What an arrival skip names as its reason, ahead of the email's sender and subject.
DESK_BUCKET_SKIP_REASONS: Final[Mapping[DeskBucket, str]] = MappingProxyType(
    {DeskBucket.FYI: "FYI", DeskBucket.JUNK: "Junk"}
)

DESK_AUTOMATION: Final = (
    "Inbox desk: when new mail reaches the user's inbox, open a todo for every thread that "
    "needs the user's reply or action, draft replies, and note meetings, bookings and "
    "deadlines. Mail that needs nothing goes, at most, into the next morning briefing."
)

JUDGMENT_QUESTIONS: Final[Mapping[Judgment, NoulQuestion]] = MappingProxyType(
    {
        Judgment.IS_PERSON: NoulQuestion(
            "Did a person write this email to the user individually?",
            "A person wrote this email to the user individually.",
            "It was sent automatically, by a system, to a mailing list, or as templated outreach: "
            "a stranger's pitch or its follow-up that could have gone to anyone.",
        ),
        Judgment.ASKS_USER: NoulQuestion(
            "Does this email ask the user to reply, decide, or do something?",
            "It asks the user to reply, decide, or do something.",
            "It only informs the user; its only ask is a marketing call to action (read, "
            "register, upgrade, buy); or it is an automated step the user started themselves, "
            "such as verifying an address or using a code or reset link.",
        ),
        Judgment.REPORTS_ISSUE: NoulQuestion(
            "Does this email report a problem, decision or deadline the user must deal with?",
            "It reports a problem, decision or deadline the user must deal with, e.g. a payment "
            "failed, a card declined, a security problem, an application decision, expiring "
            "access.",
            "A routine receipt, statement or product update; a sign-in or verification code the "
            "user requested, a new sign-in notice; an alert from the "
            "user's own monitoring; a usage, budget or account-hygiene notice before anything is "
            "cut off; an acknowledgement that something was received.",
        ),
        Judgment.OFFICIAL: NoulQuestion(
            "Is this email an official notice about the user's own case or application?",
            "A government body, embassy, visa centre, court or tax authority writes about the "
            "user's own case or application.",
            "Anything else, including a company's marketing that mentions such a body.",
        ),
        Judgment.RELEVANT: NoulQuestion(
            "Does this email concern the user's work or interests in user.profile?",
            "It concerns the user's work or interests in user.profile.",
            "It is unrelated to the user's work and interests in user.profile.",
        ),
        Judgment.BULK: NoulQuestion(
            "Is this email bulk mail?",
            "It is a newsletter, marketing or promotional email, mass outreach, or a routine "
            "automated notification.",
            "A message written for this user specifically, or a notice about their own account "
            "that needs attention.",
        ),
    }
)
