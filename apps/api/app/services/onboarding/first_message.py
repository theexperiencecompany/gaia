"""Composes the user's opening message from their onboarding answers.

Deterministic and LLM-free: the same answers always produce the same text, so
the web (skip path) and every bot adapter hand GAIA an identical first turn.
The text is written as the USER would write it — it is sent as their turn.

ONE short line. On WhatsApp and iMessage the user watches this go out under
their own name, so anything longer than a glance reads as words put in their
mouth: job, the pains in a few words each, "Where do we start?".
"""

from app.models.user_models import OnboardingNeed, OnboardingPreferences

# Q1 slugs (professionOptions in apps/web/src/features/onboarding/constants),
# phrased as the user would say them. "other" is deliberately absent: saying
# nothing about yourself beats a made-up self-description.
PROFESSION_PHRASES: dict[str, str] = {
    "founder": "a founder",
    "executive": "an executive",
    "sales": "in sales",
    "product": "in product",
    "creative": "a creative",
    "engineering": "an engineer",
    "marketing": "in marketing",
    "finance": "in finance",
    "student": "a student",
}

# Q2 chips are pains in the user's words (needOptions / roleNeedOptions in
# apps/web onboarding constants), each cut to the few words that name it. They
# are listed, not sentenced: "Inbox out of control, meetings cold." reads like
# something a person actually types, where three first-person clauses joined by
# "and" reads like a paragraph they never wrote.
NEED_PHRASES: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: "inbox out of control",
    OnboardingNeed.CALENDAR: "meetings cold",
    OnboardingNeed.MORNINGS: "mornings behind",
    OnboardingNeed.REMINDERS: "forgetting things",
    OnboardingNeed.GRUNT_WORK: "grunt work every week",
    OnboardingNeed.TOOLS: "too many tools",
    OnboardingNeed.FOUNDER_TEAM_UPDATES: "chasing team updates",
    OnboardingNeed.FOUNDER_COMPETITORS: "no eye on competitors",
    OnboardingNeed.EXECUTIVE_REPORTS: "reports unread",
    OnboardingNeed.EXECUTIVE_DECISIONS: "decisions piling up",
    OnboardingNeed.SALES_LEADS: "leads going cold",
    OnboardingNeed.SALES_CALL_RESEARCH: "research before every call",
    OnboardingNeed.PRODUCT_FEEDBACK: "feedback scattered",
    OnboardingNeed.PRODUCT_SPECS: "specs take forever",
    OnboardingNeed.MARKETING_CONTENT: "content always behind",
    OnboardingNeed.MARKETING_REPORTS: "reports by hand",
    OnboardingNeed.ENGINEERING_PRS: "PRs piling up",
    OnboardingNeed.ENGINEERING_NOTIFICATIONS: "drowning in notifications",
    OnboardingNeed.FINANCE_NUMBERS: "chasing people for numbers",
    OnboardingNeed.FINANCE_REPORTS: "same report every week",
    OnboardingNeed.CREATIVE_REVISIONS: "revisions piling up",
    OnboardingNeed.CREATIVE_DEADLINES: "deadlines sneaking up",
    OnboardingNeed.STUDENT_ASSIGNMENTS: "assignments piling up",
    OnboardingNeed.STUDENT_EXAMS: "never ready for exams",
}


def _join(phrases: list[str]) -> str:
    """The picked pains as one comma list, in tap order.

    Commas, not "and": the list is a handover of what is wrong, and "and" turns
    it into a sentence the user would have had to compose.
    """
    return ", ".join(phrases)


def _sentence(text: str) -> str:
    body = text.rstrip(".!")
    return f"{body[0].upper()}{body[1:]}."


_VOWELS = frozenset("aeiou")

#: A typed job that already opens like a sentence ("I'm a...", "I run...",
#: "We make...") is kept whole; anything else gets "I'm" in front.
_SENTENCE_OPENERS = ("i'm ", "i’m ", "i am ", "i ", "we ", "we're ", "we’re ")
_ARTICLES = ("a ", "an ", "the ")


def _profession_sentence(profession: str | None) -> str | None:
    if not profession:
        return None
    cleaned = profession.strip()
    key = cleaned.lower()
    if key in PROFESSION_PHRASES:
        return f"I'm {PROFESSION_PHRASES[key]}."
    if key == "other":
        return None
    # Free-form professions: the "Other" field, users onboarded before the fixed
    # Q1 list, and the settings page all store arbitrary text here.
    if key.startswith(_SENTENCE_OPENERS):
        return _sentence(cleaned)
    if key.startswith(_ARTICLES):
        return _sentence(f"I'm {cleaned}")
    article = "an" if key[0] in _VOWELS else "a"
    return _sentence(f"I'm {article} {cleaned}")


def compose_first_message(preferences: OnboardingPreferences) -> str:
    """The opening line the user sends GAIA, built from Q1 (profession) and Q2 (needs)."""
    parts: list[str] = []

    profession = _profession_sentence(preferences.profession)
    if profession:
        parts.append(profession)

    needs = [NEED_PHRASES[need] for need in preferences.needs or []]
    # "Something else" is their own words, so it stays its own short clause
    # rather than being bent into the list's grammar.
    other = preferences.other_need
    if needs:
        parts.append(_sentence(_join(needs)))
        if other:
            parts.append(f"Also, {other.rstrip('.!')}.")
    elif other:
        parts.append(_sentence(other))

    # Nothing was picked, so there is no line to open with: greet instead of
    # firing a bare question at someone who has said nothing yet.
    if not parts:
        parts.append("Hey.")

    # Not "who are you": that asks for a self-description, and the reply it gets
    # back is a persona blurb. Asking where to start gets a first real move.
    parts.append("Where do we start?")
    return " ".join(parts)
