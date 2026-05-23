"""Lightweight, dependency-free profanity check for user-facing names/descriptions.

Replaces ``alt-profanity-check``, which pulled in scikit-learn + scipy + pandas
+ numpy (hundreds of MB of native libraries) just to run a binary classifier on
a short string. For validating integration names/descriptions a curated word
list with leetspeak normalization is more than sufficient and adds zero
dependencies.
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
    return any(word in collapsed for word in _PROFANITY)
