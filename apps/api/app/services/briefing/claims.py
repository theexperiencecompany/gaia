"""Hold what the message says about one fact to that fact: its state, app and dates are its own.

A sentence that credits GAIA ("I finished") or the user ("you finished") with done work it
names, by slot or title, must credit whoever its lines say finished it. A sentence about exactly one fact (it links or slots that fact alone) may not call a failed item
a success, a finished one a failure, or something still waiting on the user done, nor call
another app's item a GAIA todo; nor may it type a figure (a date, a time, an amount) that only
another fact's time or words hold. A figure in another fact's title names that fact ("the
Mercury 2FA setup"), so it is never pinned on this one. A sentence that negates ("not yet",
"hasn't") is left alone: it may be saying the item is not there yet.

A sentence's cause, goal and duration claims are held to the facts it names, by slot, title or
most of a title's words (one that opens on "that" or "it" and names none speaks of the last
one's): a cause word ("blocking") only where a named fact's own line uses it, a goal only of
its linked todos, and how long something has stood ("still", "for a while") only of facts whose
lines carry a date.
"""

import re

from app.constants.briefing import DEPENDENCY_CLAIMS, DURATION_CLAIMS, GAIA_APP_NAME
from app.constants.todos import TodoCompleter
from app.models.brief_item_models import ItemState
from app.services.briefing.slots import (
    BriefFact,
    SlotValues,
    figures_in,
    referenced_facts,
    sentences,
    unslotted,
)

_SAYS_DONE = re.compile(
    r"\b(?:done|finished|completed|succeeded|successful(?:ly)?|resolved|fixed|submitted|sorted)\b",
    re.IGNORECASE,
)
_SAYS_FAILED = re.compile(r"\b(?:failed|failing|broke|broken|bounced|rejected)\b", re.IGNORECASE)
_SAYS_GAIA_TODO = re.compile(rf"\b{GAIA_APP_NAME}\s+todos?\b", re.IGNORECASE)
_FINISHED = (
    r"(?:\s+(?:just|also|already))?\s+"
    r"(?:finished|completed|wrapped up|closed|did|knocked out|handled|got through|sorted)\b"
)
#: Who a sentence credits with finishing what it names, as the pattern that finds the credit.
_CREDITS: dict[TodoCompleter, re.Pattern[str]] = {
    TodoCompleter.GAIA: re.compile(rf"\b(?:I|I've|I have|{GAIA_APP_NAME}){_FINISHED}", re.I),
    TodoCompleter.USER: re.compile(rf"\b(?:you|you've|you have){_FINISHED}", re.I),
}
_CREDITED_AS = {TodoCompleter.GAIA: "GAIA", TodoCompleter.USER: "the user"}
_SAY_CREDITED = {TodoCompleter.GAIA: "GAIA finished them", TodoCompleter.USER: "they finished them"}
_DEPENDENCY_RE = re.compile(rf"\b({'|'.join(DEPENDENCY_CLAIMS)})\b", re.IGNORECASE)
_SAYS_GOAL = re.compile(r"\bgoals?\b", re.IGNORECASE)
_DURATION_RE = re.compile(rf"\b(?:{'|'.join(DURATION_CLAIMS)})\b", re.IGNORECASE)
# "Still running" is what a started item is, and "run it again" offers an act: neither says how long.
_NOT_HOW_LONG = re.compile(
    r"\bstill\s+(?:running|in progress|moving|going)\b"
    r"|\b(?:run|rerun|try|retry|send|resend|check|ask|look)\b(?:\s+[\w']+){0,2}?\s+again\b",
    re.IGNORECASE,
)
# What dates a fact in its own words: an age, a day or a month.
_DATES = re.compile(
    r"\b(?:ago|since|yesterday|last (?:week|month|year)|\d+ (?:days?|weeks?|months?)"
    r"|january|february|march|april|june|july|august|september|october|november|december"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\.? \d{1,2}|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]*")
# What joins a claim word to the rest of its word ("daily-" of "daily-goals").
_WORD_START_RE = re.compile(r"[\w-]*$")
_WORD_END_RE = re.compile(r"[\w-]*")
_STOPWORDS = frozenset({"the", "and", "for", "your", "you", "with", "from", "into", "this", "that"})
#: How many of a title's words a sentence must say to name its fact without the whole title.
_LOOSE_NAME_WORDS = 2
# A sentence that opens on one of these and names no fact speaks of the last sentence's.
_POINTS_BACK = re.compile(
    r"^\W*(?:that|this|it|its|which|these|those|they|both|each)\b", re.IGNORECASE
)
_NEGATES = re.compile(r"\b(?:not|no longer|never|yet)\b|n't\b", re.IGNORECASE)

#: The claims each item state cannot carry, as the pattern that finds them.
_CONTRADICTED_BY: dict[ItemState, re.Pattern[str]] = {
    ItemState.FAILED: _SAYS_DONE,
    ItemState.LOOKBACK: _SAYS_FAILED,
    ItemState.YOU: _SAYS_DONE,
}


def _said_of(fact: BriefFact) -> frozenset[str]:
    """Return the figures a fact's time and words hold: what it says, as against what names it."""
    return figures_in([w for w in (fact.time, fact.words) if w])


def _in_own_words(word: str, fact: BriefFact) -> bool:
    return (
        fact.words is not None
        and re.search(rf"\b{re.escape(word)}\b", fact.words, re.IGNORECASE) is not None
    )


def _named(sentence: str, values: SlotValues) -> set[int]:
    """Return every fact a sentence speaks of: by a slot, or by its title in the prose's words."""
    words = unslotted(sentence).replace("\u2019", "'").casefold()
    slotted = referenced_facts(sentence)
    return {
        fact_id
        for fact_id, fact in values.facts.items()
        if fact_id in slotted or fact.title.casefold() in words
    }


def _credit_problems(field: str, sentence: str, values: SlotValues) -> list[str]:
    """Name a sentence crediting one side with done work only the other side finished."""
    plain = sentence.replace("\u2019", "'")
    by = {fact_id: values.facts[fact_id].done_by for fact_id in _named(sentence, values)}
    problems: list[str] = []
    for credited, pattern in _CREDITS.items():
        if not pattern.search(plain) or credited in by.values():
            continue
        (other,) = set(_CREDITS) - {credited}
        wrong = sorted(fact_id for fact_id, closer in by.items() if closer is other)
        if wrong:
            problems.append(
                f"the {field} credits {_CREDITED_AS[credited]} with facts "
                f"{', '.join(map(str, wrong))}, but {_CREDITED_AS[other]} finished them; "
                f"say {_SAY_CREDITED[other]}, as their lines do"
            )
    return problems


def claim_problems(field: str, text: str, values: SlotValues) -> list[str]:
    """Name each sentence whose credit, state or figures contradict the facts it is about."""
    problems: list[str] = []
    for sentence in sentences(text):
        problems += _credit_problems(field, sentence, values)
        about = referenced_facts(sentence)
        if len(about) != 1:
            continue
        (fact_id,) = about
        fact = values.facts.get(fact_id)
        if fact is None:
            continue
        if fact.kind is not None and not _NEGATES.search(sentence):
            pattern = _CONTRADICTED_BY.get(fact.kind)
            said = pattern.search(sentence) if pattern is not None else None
            # A word the fact's own line says ("have you completed ...?") is quoted, not claimed.
            if said is not None and not _in_own_words(said.group(0), fact):
                problems.append(
                    f"the {field} says fact {fact_id} {said.group(0)!r}, but its state is "
                    f"{fact.kind.label.lower()}; say where it stands as its line does"
                )
        if fact.app not in (None, GAIA_APP_NAME) and _SAYS_GAIA_TODO.search(sentence):
            problems.append(
                f"the {field} calls fact {fact_id} a GAIA todo, but it is a {fact.app} item; "
                "name its app as its line does"
            )
        own = figures_in([fact.title]) | _said_of(fact) | {str(fact.count)}
        others = {
            word
            for other_id, other in values.facts.items()
            if other_id != fact_id
            for word in _said_of(other) - figures_in([other.title])
        }
        typed = figures_in([unslotted(sentence)]) - own
        problems += [
            f"the {field} says {word!r} of fact {fact_id}, but that is another fact's, "
            f"not fact {fact_id}'s; say only what its own line holds"
            for word in sorted(typed & others)
        ]
    return problems


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.casefold()) if len(w) > 2 and w not in _STOPWORDS}


def _loosely_named(sentence: str, values: SlotValues) -> set[int]:
    """Return the facts a sentence names in its own words: most of a title's words, two at least."""
    said = _content_words(unslotted(sentence))
    named: set[int] = set()
    for fact_id, fact in values.facts.items():
        title = _content_words(fact.title)
        if title and len(title & said) >= min(len(title), _LOOSE_NAME_WORDS):
            named.add(fact_id)
    return named


def _about_each(text: str, values: SlotValues) -> list[tuple[str, set[int]]]:
    """Pair each sentence with the facts it names, by slot, title or its words; else the last one's.

    Only a sentence that points back ("that", "it") takes the last one's facts; any other that
    names none is about no fact.
    """
    pairs: list[tuple[str, set[int]]] = []
    last: set[int] = set()
    for sentence in sentences(text):
        named = _named(sentence, values) or _loosely_named(sentence, values)
        if not named and _POINTS_BACK.search(sentence):
            named = last
        pairs.append((sentence, named))
        last = named or last
    return pairs


def _own_line(fact: BriefFact) -> str:
    return " ".join(w for w in (fact.title, fact.words) if w)


def _claims_beyond_lines(
    pattern: re.Pattern[str], sentence: str, about: set[int], values: SlotValues
) -> list[str]:
    """Return each claim the sentence makes outside its named facts' own words, which it quotes.

    A claim is taken with the whole words around it ("daily-goals"), so a title that holds the
    word ("the daily-goals check-in") is its fact's name, not a claim.
    """
    lines = " ".join(_own_line(values.facts[i]) for i in about).casefold()
    claims: list[str] = []
    for said in pattern.finditer(sentence):
        head = _WORD_START_RE.findall(sentence[: said.start()])[0]
        tail = _WORD_END_RE.findall(sentence[said.end() :])[0]
        whole = f"{head}{said.group(0)}{tail}".casefold()
        if not re.search(rf"(?<![\w-]){re.escape(whole)}(?![\w-])", lines):
            claims.append(said.group(0).casefold())
    return claims


def dependency_problems(field: str, text: str, values: SlotValues) -> list[str]:
    """Name each cause or dependency a sentence states in a word no fact it names uses in its line."""
    problems: list[str] = []
    for sentence, about in _about_each(text, values):
        for claim in dict.fromkeys(c.casefold() for c in _DEPENDENCY_RE.findall(sentence)):
            grounded = re.compile(rf"\b{re.escape(claim)}\b", re.IGNORECASE)
            # A sentence about no fact is held to every fact's line, as a frequency claim is.
            lines = [values.facts[i] for i in about] if about else list(values.facts.values())
            if not any(grounded.search(_own_line(fact)) for fact in lines):
                problems.append(
                    f"the {field} says {claim!r}: that one thing causes, blocks or gates another, "
                    "and no fact it names says so; state each fact on its own, as its line does"
                )
    return problems


def goal_problems(field: str, text: str, values: SlotValues) -> list[str]:
    """Name each sentence that speaks of a goal and of an item that is not the goal's linked work."""
    problems: list[str] = []
    for sentence, about in _about_each(text, values):
        if not _claims_beyond_lines(_SAYS_GOAL, sentence, about, values):
            continue
        unlinked = sorted(i for i in about if not values.facts[i].goal_work)
        if unlinked:
            problems.append(
                f"the {field} ties facts {', '.join(map(str, unlinked))} to a goal, but they are "
                "not linked to one; only a goal's linked todos are its work, so name them in a sentence that does not speak of the goal"
            )
    return problems


def _dated(fact: BriefFact) -> bool:
    """Whether a fact's line carries a date: its time, an earlier brief's showing, an age in its words."""
    return fact.time is not None or fact.seen_before or bool(_DATES.search(fact.words or ""))


def duration_problems(field: str, text: str, values: SlotValues) -> list[str]:
    """Name each sentence saying how long something stood of a fact whose line carries no date."""
    problems: list[str] = []
    for sentence, about in _about_each(text, values):
        claims = _claims_beyond_lines(
            _DURATION_RE, _NOT_HOW_LONG.sub(" ", unslotted(sentence)), about, values
        )
        if not claims:
            continue
        claim = claims[0]
        # A sentence about no fact speaks of the day or a goal, whose lines carry their dates.
        undated = sorted(i for i in about if not _dated(values.facts[i]))
        if undated:
            problems.append(
                f"the {field} says {claim!r} of facts {', '.join(map(str, undated))}, but their "
                "lines carry no date; say how long something stood only where its line dates it"
            )
    return problems
