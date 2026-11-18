"""Hold what the message says about one fact to that fact: its state and its dates are the fact's own.

A sentence about exactly one fact (it links or slots that fact alone) may not call a failed item
a success, a finished one a failure, or something still waiting on the user done; nor may it
type a figure (a date, a time, an amount) that only another fact holds. A sentence that
negates ("not yet", "hasn't") is left alone: it may be saying the item is not there yet.
"""

import re

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
_NEGATES = re.compile(r"\b(?:not|no longer|never|yet)\b|n't\b", re.IGNORECASE)

#: The claims each item state cannot carry, as the pattern that finds them.
_CONTRADICTED_BY: dict[ItemState, re.Pattern[str]] = {
    ItemState.FAILED: _SAYS_DONE,
    ItemState.LOOKBACK: _SAYS_FAILED,
    ItemState.YOU: _SAYS_DONE,
}


def _figures(fact: BriefFact) -> frozenset[str]:
    return figures_in([fact.title, *(w for w in (fact.time, fact.words) if w)])


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
            if said is not None:
                problems.append(
                    f"the {field} says fact {fact_id} {said.group(0)!r}, but its state is "
                    f"{fact.kind.label.lower()}; say where it stands as its line does"
                )
        own = _figures(fact) | {str(fact.count)}
        others = {
            word
            for other_id, other in values.facts.items()
            if other_id != fact_id
            for word in _figures(other)
        }
        typed = figures_in([unslotted(sentence)]) - own
        problems += [
            f"the {field} says {word!r} of fact {fact_id}, but that is another fact's, "
            f"not fact {fact_id}'s; say only what its own line holds"
            for word in sorted(typed & others)
        ]
    return problems
