"""Composes the user's opening message from their onboarding answers.

Deterministic and LLM-free: the same answers always produce the same text, so
the web (skip path) and every bot adapter hand GAIA an identical first turn.
The text is written as the USER would write it — it is sent as their turn.
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

# Q2 chips describe the user's week (needOptions in apps/web onboarding
# constants), so each phrase is that statement in the first person. Together
# they read as one sentence: "I'm drowning in email and follow-ups slip through."
NEED_PHRASES: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: "I'm drowning in email",
    OnboardingNeed.CALENDAR: "my week is back-to-back meetings",
    OnboardingNeed.BRIEFINGS: "I start every day behind",
    OnboardingNeed.TODOS: "follow-ups slip through",
    OnboardingNeed.MEMORY: "I repeat myself a lot",
    OnboardingNeed.RESEARCH: "research eats my evenings",
    OnboardingNeed.AUTOMATION: "I do the same chores every single day",
    OnboardingNeed.REACH: "I want you wherever I am",
}


def _join(phrases: list[str]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return f"{', '.join(phrases[:-1])}, and {phrases[-1]}"


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
    parts = ["Hey."]

    profession = _profession_sentence(preferences.profession)
    if profession:
        parts.append(profession)

    needs = [NEED_PHRASES[need] for need in preferences.needs or []]
    # "Something else" is their own words, so it stays its own sentence rather
    # than being bent into the list's grammar.
    other = preferences.other_need
    if needs:
        parts.append(_sentence(_join(needs)))
        if other:
            parts.append(f"Also, {other.rstrip('.!')}.")
    elif other:
        parts.append(_sentence(other))

    # Not "who are you": that asks for a self-description, and the reply it gets
    # back is a persona blurb. Asking where to start gets a first real move.
    parts.append("Where do we start?")
    return " ".join(parts)
