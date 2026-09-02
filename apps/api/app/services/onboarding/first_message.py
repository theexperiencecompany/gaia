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

NEED_PHRASES: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: "my inbox",
    OnboardingNeed.CALENDAR: "my calendar",
    OnboardingNeed.BRIEFINGS: "my daily briefings",
    OnboardingNeed.TODOS: "my todos",
    OnboardingNeed.MEMORY: "remembering everything",
    OnboardingNeed.RESEARCH: "research",
    OnboardingNeed.AUTOMATION: "automating my routines",
    OnboardingNeed.REACH: "reaching me wherever I am",
}


def _join(phrases: list[str]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return f"{', '.join(phrases[:-1])}, and {phrases[-1]}"


_VOWELS = frozenset("aeiou")


def _profession_phrase(profession: str | None) -> str | None:
    if not profession:
        return None
    cleaned = profession.strip()
    key = cleaned.lower()
    if key in PROFESSION_PHRASES:
        return PROFESSION_PHRASES[key]
    if key == "other":
        return None
    # Free-form professions: users onboarded before the fixed Q1 list, and the
    # settings page, both store arbitrary text here.
    article = "an" if key[0] in _VOWELS else "a"
    return f"{article} {cleaned}"


def compose_first_message(preferences: OnboardingPreferences) -> str:
    """The opening line the user sends GAIA, built from Q1 (profession) and Q2 (needs)."""
    parts = ["Hi!"]

    profession = _profession_phrase(preferences.profession)
    if profession:
        parts.append(f"I'm {profession}.")

    needs = [NEED_PHRASES[need] for need in preferences.needs or []]
    if needs:
        parts.append(f"I could use help with {_join(needs)}.")

    parts.append("Who are you?")
    return " ".join(parts)
