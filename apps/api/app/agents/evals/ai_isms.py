"""Counts the LLM tells in a reply, with no model in the loop.

Every construction here was measured in production before it was coded: 42 real
assistant turns carried 25 negation antitheses, 16 of the mirror form, 7 "here's
the thing", bold emphasis in 25 of 67 messages, and a median of 1,235 characters
answering a 119-character user. This module turns that into a number so a prompt
change can be shown to move it rather than asserted to.

It is deliberately NOT the same thing as ``scripts/evals/core/prompt_gates.py``.
Those gates read their inputs out of the shipped prompt and answer "did this
reply obey the rule GAIA currently ships"; they cannot grade a reply produced
under a different prompt, and they cannot see a tell no prompt has ever named.
This module is the opposite: a fixed, prompt-independent yardstick that scores
old and new prompts on the same scale. Keep it free of ``app`` imports so an
offline experiment script can use it without booting settings.
"""

from dataclasses import dataclass
import re

#: Both orders of the negation antithesis. The first is "not X, it's Y"; the
#: second its mirror, "Y, not X", which reads clean enough that it survives
#: every ban written against the first.
NEGATION_ANTITHESIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:isn't|isn’t|is not|not)\s[^.\n]{2,60},\s(?:it's|it’s|that's|that’s|but)\s", re.I
    ),
    re.compile(r"\b[^.\n]{2,40}, not \w", re.I),
)

#: Stock phrases that mark generated text. Distinct from the prompt's own banned
#: list: these are scored whether or not any prompt forbids them.
BANNED_PHRASE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"here'?’?s the thing",
        r"the real (?:question|answer) is",
        r"\bhonestly\b",
        r"real talk",
        r"brutally honest",
        r"good question",
        r"how can i help",
        r"let me know if",
    )
)

#: "Let me ..." as an opener, which is the form that reads like a service desk.
#: "let me know if" is counted by BANNED_PHRASE_PATTERNS, so it is excluded here
#: rather than counted twice.
LET_ME_OPENER_PATTERN = re.compile(r"^\s*let me (?!know\b)[a-z]+", re.I | re.M)

#: Wrappers announcing an answer instead of giving it.
PREAMBLE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.I | re.M)
    for pattern in (
        r"^\s*(?:ok,?\s*)?(?:here'?’?s|here is) what (?:i|we) (?:found|got|have|did)",
        r"^\s*so,? you'?’?re asking",
        r"^\s*to answer your question",
    )
)

BOLD_EMPHASIS_PATTERN = re.compile(r"\*\*")

#: Lenient on purpose: production replies truncate the sentinel mid-token
#: ("<NEW_MESSAGE_B", "<NEW_MESSAGE_BREA") when the model is cut off, and a
#: truncated sentinel still marks an intended split. Longest alternative first
#: so a whole sentinel never matches as a short one.
BUBBLE_SENTINEL_PATTERN = re.compile(r"<NEW_MESSAGE_(?:BREAK|BREA|BRE|BR|B)>?")

PARAGRAPH_SEPARATOR_PATTERN = re.compile(r"\n\s*\n")

EM_DASH = "—"


@dataclass(frozen=True)
class AiIsmScore:
    """Tell counts for one reply, plus the shape numbers that give them scale."""

    negation_antithesis: int
    em_dash: int
    banned_phrases: int
    bold_emphasis: int
    preamble: int
    bubbles: int
    chars: int
    paragraphs: int

    @property
    def total_violations(self) -> int:
        return (
            self.negation_antithesis
            + self.em_dash
            + self.banned_phrases
            + self.bold_emphasis
            + self.preamble
        )


def _count(patterns: tuple[re.Pattern[str], ...], text: str) -> int:
    return sum(len(pattern.findall(text)) for pattern in patterns)


def count_bubbles(text: str) -> int:
    """Bubbles the reply would be delivered as: non-empty sentinel-separated parts."""
    return sum(1 for part in BUBBLE_SENTINEL_PATTERN.split(text) if part.strip())


def score_reply(text: str) -> AiIsmScore:
    """Score one assistant reply. Pure: same text in, same counts out."""
    return AiIsmScore(
        negation_antithesis=_count(NEGATION_ANTITHESIS_PATTERNS, text),
        em_dash=text.count(EM_DASH),
        banned_phrases=_count(BANNED_PHRASE_PATTERNS, text)
        + len(LET_ME_OPENER_PATTERN.findall(text)),
        bold_emphasis=len(BOLD_EMPHASIS_PATTERN.findall(text)),
        preamble=_count(PREAMBLE_PATTERNS, text),
        bubbles=count_bubbles(text),
        chars=len(text),
        paragraphs=sum(1 for block in PARAGRAPH_SEPARATOR_PATTERN.split(text) if block.strip()),
    )
