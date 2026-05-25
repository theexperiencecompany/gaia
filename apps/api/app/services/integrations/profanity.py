"""Lightweight, dependency-free profanity check for user-facing names/descriptions.

Replaces ``alt-profanity-check``, which pulled in scikit-learn + scipy + pandas
+ numpy (hundreds of MB of native libraries) just to run a binary classifier on
a short string. For validating integration names/descriptions a curated word
list with leetspeak normalization is more than sufficient and adds zero
dependencies.

TODO: Replace this wordlist heuristic with an LLM call for more robust,
context-aware moderation (catches obfuscation, slurs, and intent the static
list misses). Keep it on the publish path only (not hot-path), and guard for
latency/cost + a cheap fallback to this wordlist if the LLM is unavailable.
"""

from __future__ import annotations

import re

# Common offensive terms (substring/leet matched after normalization). Kept
# intentionally small and maintainable — this gates public integration names,
# not a content-moderation pipeline.
_PROFANITY: frozenset[str] = frozenset(
    {
        "fuck",
        "shit",
        "bitch",
        "cunt",
        "asshole",
        "bastard",
        "dick",
        "pussy",
        "slut",
        "whore",
        "nigger",
        "nigga",
        "faggot",
        "fag",
        "retard",
        "rape",
        "cum",
        "cock",
        "wank",
        "twat",
        "douche",
        "jerkoff",
        "motherfucker",
        "bollocks",
        "bugger",
        "prick",
        "spastic",
        "nazi",
        "kike",
        "spic",
        "chink",
        "coon",
        "dyke",
        "tranny",
    }
)

# Leetspeak / obfuscation normalization so "f.u.c.k", "sh1t", "@ss" are caught.
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Terms long enough to match safely as substrings of the separator-collapsed
# text (this is what catches "f u c k" / "f.u.c.k"). Short terms are excluded
# here because they appear inside benign words (e.g. "cum" in "document",
# "fag" in many) and would block legitimate names; they are still caught as
# exact tokens via the ``tokens & _PROFANITY`` check below.
_COLLAPSED_SUBSTRING_TERMS: frozenset[str] = frozenset(
    term for term in _PROFANITY if len(term) >= 4
)


def contains_profanity(text: str | None) -> bool:
    """Return True if ``text`` contains a profane term (leet/spacing tolerant)."""
    if not text:
        return False
    lowered = text.lower().translate(_LEET)
    # Collapse separators so "f u c k" / "f-u-c-k" normalize to "fuck".
    collapsed = _NON_ALNUM.sub("", lowered)
    spaced = _NON_ALNUM.sub(" ", lowered)
    tokens = set(spaced.split())
    if tokens & _PROFANITY:
        return True
    return any(word in collapsed for word in _COLLAPSED_SUBSTRING_TERMS)
