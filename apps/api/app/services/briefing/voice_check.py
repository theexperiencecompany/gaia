"""Check the brief's prose against its items and shown counts before rendering.

The model writes the prose; code builds the items and the [COUNTS] it is shown. Prose
that claims a need, an event, a count or a person neither shows contradicts the page; prose that
counts zeros or names pipeline vocabulary reads like a report, not a person. The message must
also mention everything waiting on the user and every event today. All of it is rejected
(service.py regenerates once, then fails loud).
"""

from collections.abc import Sequence
from dataclasses import dataclass
import re

from app.constants.briefing import MAX_BRIEF_MESSAGE_CHARS
from app.models.briefing_models import BriefingItemKind, BriefingPayload
from app.models.scout_models import Signal, SignalImportance

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
# Any figure in what the model was shown, as digits or a word: each one is true to voice.
_FIGURE = re.compile(r"\d+|\b(?:" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)
_NEEDS_CLAIM = re.compile(
    r"\bneeds? (?:you|your)\b|\bwaiting on you\b|\byour (?:call|review|approval|reply)\b",
    re.IGNORECASE,
)
# A negation in the phrase's own clause ("nothing needs you", "0 things need you") denies it.
_NEGATED_CLAUSE = re.compile(
    r"\b(?:no|not|none|nothing|nobody|no one|zero|0)\b|n't\b", re.IGNORECASE
)
_CLAUSE_BREAK = re.compile(r"[.;:,!?]|\b(?:but|and|while|though|yet)\b", re.IGNORECASE)
# Pipeline vocabulary the reader never sees as such.
_INTERNAL_TERM = re.compile(r"\b(?:held results?|lanes?|sections?)\b", re.IGNORECASE)
_EVENT_CLAIM = re.compile(r"\b(?:events?|meetings?|calls? (?:at|with))\b", re.IGNORECASE)
_EMPTY_CALENDAR = re.compile(
    r"\b(?:no|nothing|zero|0|clear|free|empty)\b[^.;]*\b(?:events?|meetings?|calendar)\b",
    re.IGNORECASE,
)
# A name: a capitalised word inside a sentence, or a possessive one opening it.
_NAME = re.compile(r"(?<=[a-z,;] )([A-Z][a-z]+)|^([A-Z][a-z]+)'s\b|(?<=[.;:] )([A-Z][a-z]+)'s\b")
_WORD = re.compile(r"[a-z]+")
_DASH = re.compile("[–—]")
# A link the message carries, written bare or as a markdown target.
_URL = re.compile(r"https?://[^\s)\]>]+")
# What a sentence leaves on the end of a bare link it carries.
_LINK_TRAILING_PUNCTUATION = ".,;:!?"
# A title's identifying words: long enough to carry meaning, compared on a short stem so
# "approve" covers "approval" and "invoices" covers "invoice".
_KEY_WORD_MIN_CHARS = 4
_KEY_WORD_STEM_CHARS = 5
_COMMON_WORDS = frozenset(
    {"about", "after", "from", "have", "into", "just", "more", "need", "needs", "over"}
    | {"that", "their", "them", "then", "this", "today", "with", "your"}
)
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


@dataclass(frozen=True)
class VoicedCounts:
    """The counts the model is shown as [COUNTS]: the only figures besides the items it may voice."""

    waiting_on_you: int
    done: int
    in_progress: int
    while_away: int
    open_todos: int

    def shown(self) -> list[tuple[str, int]]:
        """Label each non-zero count; a zero is never handed to the model to recite."""
        labelled = (
            ("waiting on you", self.waiting_on_you),
            ("done", self.done),
            ("in progress", self.in_progress),
            ("while you were away", self.while_away),
            ("your open todos", self.open_todos),
        )
        return [(label, n) for label, n in labelled if n]


def _figures_in(text: str) -> set[int]:
    return {
        _NUMBER_WORDS[token] if token in _NUMBER_WORDS else int(token)
        for token in (match.lower() for match in _FIGURE.findall(text))
    }


def _allowed_counts(payload: BriefingPayload, corpus: str) -> set[int]:
    items = [item for section in payload.sections for item in section.items]
    by_kind = [sum(1 for i in items if i.kind == kind) for kind in ("lookback", "gaia", "note")]
    needs_you = sum(1 for i in items if i.kind in _NEEDS_YOU_KINDS)
    tallies = payload.tallies
    done = [tallies.done_by_you, tallies.done_by_gaia, tallies.done_by_you + tallies.done_by_gaia]
    return {len(items), needs_you, len(payload.calendar), *by_kind, *done, *_figures_in(corpus)}


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


def _prose_contradictions(
    prose: str,
    payload: BriefingPayload,
    counts: VoicedCounts,
    context: str,
    signals: Sequence[Signal],
) -> list[str]:
    """Return every claim in prose that the items, signals, shown counts and context do not support."""
    corpus = f"{_corpus(payload)} {context}"
    items = [item for section in payload.sections for item in section.items]
    problems: list[str] = []
    # A link's digits and path are its address, not a count or a name the prose voices.
    prose = _URL.sub("", prose)  # pragma: no mutate — stand-in text carries no count or name

    needed = any(i.kind in _NEEDS_YOU_KINDS for i in items) or bool(signals)
    if _claims_a_need(prose) and not needed:
        problems.append("the prose says something needs the user, but no item needs them")
    if _EVENT_CLAIM.search(prose) and not payload.calendar and not _EMPTY_CALENDAR.search(prose):
        problems.append("the prose mentions an event, but today's calendar is empty")

    allowed = _allowed_counts(payload, corpus) | {n for _, n in counts.shown()}
    voiced = [
        _NUMBER_WORDS[token] if token in _NUMBER_WORDS else int(token)
        for token in (match.group(1).lower() for match in _COUNT.finditer(prose))
    ]
    # A 0 quoted from a title ("Blocked 0") is the title, not a count of nothing.
    if 0 in voiced and not re.search(r"(?<!\d)0(?!\d)", corpus):
        problems.append("the prose counts 0; leave out what is not there instead of counting it")
    for count in voiced:
        if count and count not in allowed:
            problems.append(f"the prose counts {count}, which no item count matches")

    lowered = corpus.lower()
    for match in _INTERNAL_TERM.finditer(prose):
        if match.group(0).lower() not in lowered:
            problems.append(f"the prose names the internal term {match.group(0)!r}")

    corpus_words = set(_WORD.findall(lowered))
    for match in _NAME.finditer(prose):
        name = next(group for group in match.groups() if group)
        if name not in _NOT_NAMES and name.lower() not in corpus_words:
            problems.append(f"the prose names {name!r}, who is in no item or event")
    return problems


def voice_contradictions(
    headline: str,
    lede: str,
    payload: BriefingPayload,
    counts: VoicedCounts,
    *,
    context: str,
    signals: Sequence[Signal] = (),
) -> list[str]:
    """Return every claim in the headline or lede that the facts the model was shown do not support.

    context is the rest of what the model was shown (facts, goals, replies, yesterday).
    """
    return _prose_contradictions(f"{headline}. {lede}", payload, counts, context, signals)


def _key_stems(text: str) -> set[str]:
    return {
        word[:_KEY_WORD_STEM_CHARS]
        for word in _WORD.findall(text.lower())
        if len(word) >= _KEY_WORD_MIN_CHARS and word not in _COMMON_WORDS
    }


def _mentions(said: set[str], text: str) -> bool:
    return not _key_stems(text) or bool(_key_stems(text) & said)


def voiced_signals(message: str, signals: Sequence[Signal]) -> list[Signal]:
    """Return the signals the message speaks of, by their link or their title's words."""
    said = _key_stems(message)
    return [s for s in signals if (s.url and s.url in message) or (_key_stems(s.title) & said)]


def _unmentioned(message: str, payload: BriefingPayload, signals: Sequence[Signal]) -> list[str]:
    """Name each needs-you item, event and important signal the message never speaks of."""
    said = _key_stems(message)
    needs = [
        item.text
        for section in payload.sections
        for item in section.items
        if item.kind in _NEEDS_YOU_KINDS
    ]
    problems = [
        f"the message never mentions {text!r}, which is waiting on the user"
        for text in needs
        if _key_stems(text) and not _key_stems(text) & said
    ]
    problems += [
        f"the message never mentions today's {event.title!r}"
        for event in payload.calendar
        if _key_stems(event.title) and not _key_stems(event.title) & said
    ]
    problems += [
        f"the message never mentions {s.title!r} in {s.app}, which is important"
        for s in signals
        if s.importance is SignalImportance.HIGH and not _mentions(said, s.title)
    ]
    return problems


def _foreign_links(message: str, context: str) -> list[str]:
    """Name each link in the message that nothing the model was shown carries."""
    return [
        f"the message links to {url}, which no fact carries"
        for url in (
            match.group(0).rstrip(_LINK_TRAILING_PUNCTUATION) for match in _URL.finditer(message)
        )
        if url not in context
    ]


def message_contradictions(
    message: str,
    payload: BriefingPayload,
    counts: VoicedCounts,
    *,
    context: str,
    require_coverage: bool,
    signals: Sequence[Signal] = (),
) -> list[str]:
    """Return every way the written message breaks the facts, the length cap or the house style.

    context is the rest of what the model was shown; a name or number from it is true. A
    link must be one a fact carries. require_coverage holds the message to every needs-you item,
    event and important signal; a winback or wind-down note is one short line and is exempt.
    """
    problems = _prose_contradictions(message, payload, counts, context, signals)
    problems += _foreign_links(message, context)
    if _DASH.search(message):
        problems.append("the message uses an em or en dash; use commas, periods or parentheses")
    if len(message) > MAX_BRIEF_MESSAGE_CHARS:
        problems.append(
            f"the message runs {len(message)} characters; keep it under {MAX_BRIEF_MESSAGE_CHARS}"
        )
    if require_coverage:
        problems += _unmentioned(message, payload, signals)
    return problems
