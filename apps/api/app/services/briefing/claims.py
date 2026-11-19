"""Hold what the message says about one fact to that fact: its state, app and dates are its own.

A sentence about exactly one fact (it links or slots that fact alone) may not call a failed item
a success, a finished one a failure, or something still waiting on the user done, nor call
another app's item a GAIA todo; nor may it type a figure (a date, a time, an amount) that only
another fact's time or words hold. A figure in another fact's title names that fact ("the
Mercury 2FA setup"), so it is never pinned on this one. A sentence that negates ("not yet",
"hasn't") is left alone: it may be saying the item is not there yet.
"""

import re

from app.constants.briefing import GAIA_APP_NAME
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
    return re.search(rf"\b{re.escape(word)}\b", fact.words or "", re.IGNORECASE) is not None


def claim_problems(field: str, text: str, values: SlotValues) -> list[str]:
    """Name each sentence whose state or figures contradict the one fact it is about."""
    problems: list[str] = []
    for sentence in sentences(text):
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
