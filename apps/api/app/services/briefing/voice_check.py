"""Check the brief's headline and lede against its own items before anything renders.

The model writes the prose; code builds the items. Prose that claims a need, an
event, a count or a person the items do not show is a contradiction the reader sees
on the same page, so it is rejected (service.py regenerates once, then fails loud).
"""

import re

from app.models.briefing_models import BriefingItemKind, BriefingPayload

_NEEDS_YOU_KINDS: frozenset[BriefingItemKind] = frozenset({"you", "failed"})

_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
# A count: a bare integer or number word, not a clock time ("11:00", "4pm"), a year or a
# figure inside a token ("Q4").
_COUNT = re.compile(
    r"(?<![\w:.])(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")(?![\w:])(?!\s*(?:am|pm)\b)",
    re.IGNORECASE,
)
_NEEDS_CLAIM = re.compile(
    r"\bneeds? (?:you|your)\b|\bwaiting on you\b|\byour (?:call|review|approval|reply)\b",
    re.IGNORECASE,
)
# A negation in the phrase's own clause ("nothing needs you", "0 things need you") denies it.
_NEGATED_CLAUSE = re.compile(
    r"\b(?:no|not|none|nothing|nobody|no one|zero|0)\b|n't\b", re.IGNORECASE
)
_CLAUSE_BREAK = re.compile(r"[.;:,!?]|\b(?:but|and|while|though|yet)\b", re.IGNORECASE)
_EVENT_CLAIM = re.compile(r"\b(?:events?|meetings?|calls? (?:at|with))\b", re.IGNORECASE)
_EMPTY_CALENDAR = re.compile(
    r"\b(?:no|nothing|zero|0|clear|free|empty)\b[^.;]*\b(?:events?|meetings?|calendar)\b",
    re.IGNORECASE,
)
# A name: a capitalised word inside a sentence, or a possessive one opening it.
_NAME = re.compile(r"(?<=[a-z,;] )([A-Z][a-z]+)|^([A-Z][a-z]+)'s\b|(?<=[.;:] )([A-Z][a-z]+)'s\b")
_WORD = re.compile(r"[a-z]+")
_NOT_NAMES = frozenset(
    {
        "GAIA",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    }
)


def _allowed_counts(payload: BriefingPayload) -> set[int]:
    items = [item for section in payload.sections for item in section.items]
    by_kind = [sum(1 for i in items if i.kind == kind) for kind in ("lookback", "gaia", "note")]
    needs_you = sum(1 for i in items if i.kind in _NEEDS_YOU_KINDS)
    tallies = payload.tallies
    done = [tallies.done_by_you, tallies.done_by_gaia, tallies.done_by_you + tallies.done_by_gaia]
    in_text = {int(n) for n in re.findall(r"\d+", _corpus(payload))}
    return {len(items), needs_you, len(payload.calendar), *by_kind, *done, *in_text}


def _corpus(payload: BriefingPayload) -> str:
    items = [item.text for section in payload.sections for item in section.items]
    events = [part for e in payload.calendar for part in (e.title, e.location) if part]
    return " ".join(items + events)


def _claims_a_need(prose: str) -> bool:
    """Report whether a needs-you phrase is asserted, not denied by a negation in its clause."""
    for match in _NEEDS_CLAIM.finditer(prose):
        clause = _CLAUSE_BREAK.split(prose[: match.start()])[-1]
        if not _NEGATED_CLAUSE.search(clause):
            return True
    return False


def voice_contradictions(headline: str, lede: str, payload: BriefingPayload) -> list[str]:
    """Return every claim in the headline or lede that the payload's items do not support."""
    prose = f"{headline}. {lede}"
    items = [item for section in payload.sections for item in section.items]
    problems: list[str] = []

    if _claims_a_need(prose) and not any(i.kind in _NEEDS_YOU_KINDS for i in items):
        problems.append("the prose says something needs the user, but no item needs them")
    if _EVENT_CLAIM.search(prose) and not payload.calendar and not _EMPTY_CALENDAR.search(prose):
        problems.append("the prose mentions an event, but today's calendar is empty")

    allowed = _allowed_counts(payload)
    for match in _COUNT.finditer(prose):
        token = match.group(1).lower()
        count = _NUMBER_WORDS[token] if token in _NUMBER_WORDS else int(token)
        if count not in allowed:
            problems.append(f"the prose counts {count}, which no item count matches")

    corpus_words = set(_WORD.findall(_corpus(payload).lower()))
    for match in _NAME.finditer(prose):
        name = next(group for group in match.groups() if group)
        if name not in _NOT_NAMES and name.lower() not in corpus_words:
            problems.append(f"the prose names {name!r}, who is in no item or event")
    return problems
