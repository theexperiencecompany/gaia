"""Quotes: someone's own words from the user's apps, cut verbatim at a sentence's end.

Every message, comment or reply a scout read with its author is a quote, cut to its
first whole sentences within the quote's length; words that cannot be cut cleanly there
are not quoted, so a quote never ends mid-thought or carries an ellipsis GAIA added.
"""

from collections.abc import Mapping
import re

from app.constants.briefing import QUOTE_MAX_CHARS, QUOTE_MIN_CHARS
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_pool_models import QuoteSpan

# A sentence ends at ., ! or ? (a closing quote or bracket may follow) before whitespace.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*(?=\s|$)")


def verbatim_span(text: str) -> str | None:
    """Return the text's leading whole sentences within the quote length, or None when none fit."""
    words = " ".join(text.split())
    if len(words) <= QUOTE_MAX_CHARS:
        return words if len(words) >= QUOTE_MIN_CHARS else None
    ends = [m.end() for m in _SENTENCE_END.finditer(words) if m.end() <= QUOTE_MAX_CHARS]
    if not ends or ends[-1] < QUOTE_MIN_CHARS:
        return None
    return words[: ends[-1]]


def quote_spans(items: Mapping[int, BriefCandidate]) -> list[QuoteSpan]:
    """Return a quote for each pool item holding a person's own words, numbered q1 up."""
    quotes: list[QuoteSpan] = []
    for item_id, item in items.items():
        signal = item.signal
        if signal is None or signal.text is None or not signal.people:
            continue
        span = verbatim_span(signal.text)
        if span is None:
            continue
        quotes.append(
            QuoteSpan(
                id=f"q{len(quotes) + 1}",
                text=span,
                author=signal.people[0],
                source=signal.integration_id,
                app=signal.app,
                url=signal.url,
                item_id=item_id,
            )
        )
    return quotes
