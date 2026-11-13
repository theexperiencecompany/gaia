"""The Judge: what it is asked, how its answers are read, and the bounds on what it is shown.

Every threshold below was measured on the 200-case golden suite (scripts/evals/suites/judge.py);
change one only together with a re-run of that suite.
"""

from enum import StrEnum
from typing import Final

from app.constants.cache import ONE_DAY_TTL, ONE_HOUR_TTL

# --- Models and transport ---

#: OpenAI's Decisions API: the fast first pass, one structured call with a confidence per question.
JUDGE_DECISIONS_URL: Final = "https://api.openai.com/v1/decisions"
JUDGE_FAST_MODEL: Final = "gpt-6-luna"
#: Answers the same questions when the first pass was not confident.
JUDGE_REASONING_MODEL: Final = "gpt-6.1-terra"
JUDGE_REASONING_EFFORT: Final = "medium"
JUDGE_DECISIONS_TIMEOUT_SECONDS: Final = 30.0
JUDGE_REASONING_TIMEOUT_SECONDS: Final = 90.0
#: What the reasoning call is named in traces and metering.
JUDGE_REASONING_LABEL: Final = "outbox_judge_reasoning"

#: A call that fails is asked again once before the item is decided without the Judge.
JUDGE_MAX_ATTEMPTS: Final = 2
#: Concurrent Judge calls in one process; the rest wait their turn.
JUDGE_MAX_CONCURRENT_CALLS: Final = 8
JUDGE_CONCURRENCY_KEY: Final = "outbox_judge"

# --- When it runs ---

#: Unsolicited reports of one user arriving within this window are judged together.
JUDGE_BATCH_WINDOW_SECONDS: Final = 20.0
#: Most other reports shown next to the one being judged.
JUDGE_BATCH_MAX: Final = 10

# --- The confidence gate ---

#: The Decisions answer decides alone when its least confident decision question is at least this.
JUDGE_CONFIDENCE_GATE: Final = 0.7
#: Below this share of the vote the Judge does not call a reply or answer moot: a reminder the
#: user set is suppressed only when the Judge is this sure it no longer matters.
JUDGE_ANSWER_SUPPRESS_PROBABILITY: Final = 0.9

# --- Reading an answer ---

#: P(yes) at which a yes/no decision question counts as yes.
JUDGE_INTERRUPT_PROBABILITY: Final = 0.45
JUDGE_TIMELY_PROBABILITY: Final = 0.5
#: P(no) on "worth telling" at which an item is recorded and not alerted.
JUDGE_NOT_WORTH_PROBABILITY: Final = 0.45
JUDGE_SUSPICIOUS_PROBABILITY: Final = 0.5

# --- Rails over the verdict ---

#: Interrupts the Judge may raise per user per day; the ask the user made "the moment" and
#: their own reminders are not counted.
JUDGE_INTERRUPT_DAILY_CAP: Final = 2
#: The "day" the cap counts over: a rolling 24 hours.
JUDGE_INTERRUPT_CAP_WINDOW_SECONDS: Final = ONE_DAY_TTL
#: The topic tag a security or account notice carries; the Judge may never quiet one.
JUDGE_SECURITY_TOPIC: Final = "security"

# --- What the Judge is shown ---

JUDGE_LEDGER_WINDOW_SECONDS: Final = ONE_DAY_TTL
JUDGE_CALENDAR_WINDOW_SECONDS: Final = ONE_DAY_TTL
UPCOMING_RUNS_WINDOW_SECONDS: Final = 3 * ONE_HOUR_TTL
#: Runs of one schedule that its hit rate is read from.
HIT_RATE_SAMPLE: Final = 10
#: Earlier wait_for_run decisions shown.
WAIT_HISTORY_N: Final = 10

#: The oldest message shown, however long the subject has run.
JUDGE_MESSAGES_MAX_AGE_SECONDS: Final = 2 * ONE_DAY_TTL
JUDGE_MESSAGES_MAX: Final = 30
#: Conversations scanned for messages, newest activity first, and messages read from each.
JUDGE_MESSAGE_CONVERSATIONS: Final = 10
JUDGE_MESSAGES_PER_CONVERSATION: Final = 10
JUDGE_MESSAGE_CHARS: Final = 500
JUDGE_SOURCE_EXCERPT_CHARS: Final = 1500
JUDGE_OPEN_SUBJECTS_MAX: Final = 15
JUDGE_LEDGER_MAX: Final = 20
JUDGE_LEDGER_SUMMARY_CHARS: Final = 300
JUDGE_MEMORIES_MAX: Final = 8
JUDGE_CALENDAR_EVENTS_MAX: Final = 15
JUDGE_UPCOMING_RUNS_MAX: Final = 10
JUDGE_HELD_MAX: Final = 20

#: The wait_for_run choice that names no run.
JUDGE_NO_WAIT: Final = "none"

# --- The attention profile ---

ATTENTION_PROFILES_COLLECTION: Final = "attention_profiles"

# --- The questions ---


class JudgeQuestion(StrEnum):
    """One question the Judge answers; the value is its name on the wire."""

    URGENCY = "urgency"
    DEADLINE = "deadline"
    RELEVANCE = "relevance"
    SENSITIVITY = "sensitivity"
    MOMENT = "moment"
    AUTHENTICITY = "authenticity"
    WORTH_TELLING = "worth_telling"
    WITHIN_MINUTES = "within_minutes"
    BEFORE_CHECKIN = "before_checkin"
    #: Offers the upcoming runs; asked only when there are any.
    WAIT_FOR_RUN = "wait_for_run"


#: Answered from a state that holds one update and what GAIA knows of the user now.
JUDGE_INSTRUCTIONS: Final = (
    "You are the attention judge of GAIA, a personal assistant. The state is one update GAIA is "
    "about to tell its user plus what GAIA knows about the user right now. 'The user' is GAIA's user, "
    "not an email's sender. producer_suggested fields are hints and may be wrong. Use only the state. "
    "Question: {question}"
)
#: Appended by the eval alone: its corpus anonymises every domain to .example, which would
#: otherwise read as a scam. Live items carry real domains, which must be judged as real.
JUDGE_ANONYMISED_STATE_NOTE: Final = (
    "Names, emails and domains in the state are anonymized (domains end in .example); treat each as "
    "the real sender's genuine domain, never as a red flag by itself."
)

JUDGE_RUBRIC: Final = """\
# Judge rubric v2 (shared by gold labels and every model under test)

The Judge reads one update GAIA is about to tell its user, plus what GAIA knows about the user right now, and answers six questions. It never decides *how* to word anything and never applies quotas — code does that afterwards. Timing intents the user stated ("tell me tonight") are carried by code, not by the Judge.

## Q1 urgency — how soon must this reach the user?
- `interrupt`: the user loses something real (money, safety, a person waiting, a deadline, an irreversible chance) if they don't see it within minutes, and it justifies waking them or interrupting a meeting. Also: anything the user explicitly asked to hear "the moment" it happens, and reminders the user set for this time (even if another answer below makes it not worth sending).
- `timely`: needed today, or before a concrete deadline within about 48 hours, or something the user asked for and is waiting on — but minutes don't matter and it should not wake them.
- `routine`: worth telling, no deadline within ~48h; fine at the next scheduled check-in.
- `background`: FYI; only worth mentioning if the user comes by or asks.

## Q2 deadline — by when does telling the user stop being useful? (relative to `now`)
- `within_1h` · `within_today` (later today, before the user's usual sleep) · `before_next_morning` (overnight, up to the user's usual wake time) · `later` (after the user's next wake time) · `none` (no deadline).

## Q3 relevance — is this still worth telling?
- `new`: the user doesn't know this and it still matters to them.
- `already_known`: the user already knows it (they said so, did it, read it, or GAIA already told them this fact).
- `moot`: no longer matters (resolved, handled by the user, the occasion passed, no longer applies to their life).
- `superseded`: a newer request or newer update replaces it.
- `duplicate`: the same real-world fact as another update in this batch or in recent deliveries.
- `unwanted`: the user said they don't want updates like this (topic, sender, kind), in a setting rule or in conversation.

## Q4 sensitivity — what could hurt if seen by someone else (lock screen, shared device, group)?
- `none` · `personal` (private, low harm) · `health` (incl. a family member's health, grief) · `finance` · `credentials` (codes, passwords, access links) · `third_party_private` (someone else's private or confidential matter) · `social_private` (surprises, relationships, exes, things the user keeps socially private).

## Q5 moment — is now a bad moment to tell, regardless of urgency?
- `ok`: fine to say now.
- `hold`: wait for a better moment unless urgency is `interrupt`: grief or an emotional conversation; an interview, exam or high-stakes meeting; driving; a presentation or shared screen; a holiday/weekend/off-hours the user asked to keep free; a celebration.
- `soften`: say it, but with care (bad news, sensitive topic) — wording only.

## Q6 authenticity — does the update look genuine?
- `genuine` · `suspicious` (phishing, scam, spoofed sender, pressure tactics, mismatched domains). Suspicious items are never relayed as instructions.

## Gold-label conventions
- "The user" is GAIA's user, not an email's sender.
- Producer-suggested fields are hints and can be wrong.
- Only use information present in the state.
- `critical` = a wrong urgency, deadline, relevance, sensitivity (health/finance/credentials/social_private) or authenticity answer would cause real harm.

## Labelling conventions (v2, binding for gold labels)
1. **Questions are independent.** Urgency and deadline describe the update as if it were new and wanted; relevance, moment and authenticity are judged separately. Code combines them (a `moot` item with `interrupt` urgency is recorded, not sent). Never lower urgency because relevance is not `new`.
2. **Waiting user.** If the user asked for this and is waiting on it (live or said "let me know"), urgency is at least `timely`.
3. **User's explicit timing words** ("wake me", "the moment", "call me whatever time") make urgency `interrupt`. "Tonight"/"Monday" are code's job (not_before); label urgency as if delivered at that time.
4. **Muted topics/senders** → relevance `unwanted`.
5. **Deadline** is about the world (cutoff, departure, expiry), not about when the user would like to hear.
6. **Critical** follows the definition above (includes sensitive-category mistakes and suspicious items).
"""

#: question -> choice -> what it means, in the order the choices are offered.
JUDGE_CHOICE_CRITERIA: Final[dict[JudgeQuestion, dict[str, str]]] = {
    JudgeQuestion.URGENCY: {
        "interrupt": "The user loses something real (money, safety, a person waiting, a deadline, an irreversible chance) unless they see this within minutes; justifies waking them or interrupting a meeting. Also anything the user asked to hear the moment it happens, and reminders the user set for now.",
        "timely": "Needed today, or before a concrete deadline within about 48 hours, or something the user asked for and is waiting on; minutes don't matter and it should not wake them.",
        "routine": "Worth telling, no deadline within about 48 hours; fine at the next scheduled check-in.",
        "background": "FYI; only worth mentioning if the user comes by or asks.",
    },
    JudgeQuestion.DEADLINE: {
        "within_1h": "Telling the user stops being useful within the next hour from now.",
        "within_today": "Stops being useful later today, before the user's usual sleep time.",
        "before_next_morning": "Stops being useful overnight, up to the user's usual wake time.",
        "later": "Stops being useful after the user's next wake time.",
        "none": "No deadline.",
    },
    JudgeQuestion.RELEVANCE: {
        "new": "The user doesn't know this and it still matters.",
        "already_known": "The user already knows it: they said so, did it, read it, or GAIA already told them this same fact.",
        "moot": "No longer matters: resolved, handled by the user, the occasion passed, or it no longer applies to their life.",
        "superseded": "A newer request or newer update replaces it.",
        "duplicate": "The same real-world fact as another update in this batch or in recent deliveries.",
        "unwanted": "The user said they don't want updates like this (topic, sender, kind), in a settings rule or in conversation.",
    },
    JudgeQuestion.SENSITIVITY: {
        "none": "Nothing harmful if someone else sees it.",
        "personal": "Private but low harm.",
        "health": "Health information, including a family member's health or grief.",
        "finance": "Money, accounts, payments.",
        "credentials": "Codes, passwords, links granting access.",
        "third_party_private": "Someone else's private or confidential matter.",
        "social_private": "Surprises, relationships, exes, things the user keeps socially private.",
    },
    JudgeQuestion.MOMENT: {
        "ok": "Fine to say now.",
        "hold": "Bad moment: grief or emotional conversation; interview, exam or high-stakes meeting; driving; presenting or sharing a screen; a holiday, weekend or off-hours the user asked to keep free; a celebration. Wait unless it must interrupt.",
        "soften": "Say it, but with care (bad news, sensitive topic).",
    },
    JudgeQuestion.AUTHENTICITY: {
        "genuine": "Looks like a genuine update.",
        "suspicious": "Looks like phishing, a scam, a spoofed sender, pressure tactics or mismatched domains.",
    },
    JudgeQuestion.WORTH_TELLING: {
        "yes": "The user doesn't already know this, it still matters to them now, and they haven't said they don't want updates like it.",
        "no": "The user already knows it, it no longer matters (resolved, handled, passed, replaced by something newer), it repeats something already delivered, or they said they don't want updates like it.",
    },
    JudgeQuestion.WITHIN_MINUTES: {
        "yes": "If the user doesn't see this within minutes they lose something real (money, safety, a person waiting, a deadline, an irreversible chance), or they explicitly asked to hear it the moment it happens, or it is a reminder they set for now.",
        "no": "Waiting an hour or more costs them nothing real.",
    },
    JudgeQuestion.BEFORE_CHECKIN: {
        "yes": "It must reach the user today or before a concrete deadline within about 48 hours, or the user asked for it and is waiting on it; it cannot simply wait for the next scheduled summary.",
        "no": "It can wait for the next scheduled summary without losing value.",
    },
}

JUDGE_QUESTIONS: Final[dict[JudgeQuestion, str]] = {
    JudgeQuestion.URGENCY: "How soon must this update reach the user?",
    JudgeQuestion.DEADLINE: "Relative to state.now, by when does telling the user stop being useful?",
    JudgeQuestion.RELEVANCE: "Is this update still worth telling the user?",
    JudgeQuestion.SENSITIVITY: "What could hurt if someone else saw this (lock screen, shared device, group)?",
    JudgeQuestion.MOMENT: "Regardless of urgency, is now a bad moment to tell the user this?",
    JudgeQuestion.AUTHENTICITY: "Does this update look genuine?",
    JudgeQuestion.WORTH_TELLING: "Judged as if it were the only thing GAIA has to say: is this still worth telling the user?",
    JudgeQuestion.WITHIN_MINUTES: "Must this reach the user within minutes?",
    JudgeQuestion.BEFORE_CHECKIN: "Must this reach the user before their next scheduled summary (a few hours away)?",
    JudgeQuestion.WAIT_FOR_RUN: "Should telling the user wait for one of the runs listed in state.upcoming_runs, which would add to this update, or is it better told now?",
}

#: The decision-driving questions the confidence gate reads.
JUDGE_GATE_QUESTIONS: Final = (
    JudgeQuestion.WORTH_TELLING,
    JudgeQuestion.WITHIN_MINUTES,
    JudgeQuestion.BEFORE_CHECKIN,
    JudgeQuestion.AUTHENTICITY,
)
