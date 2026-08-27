"""Counts the LLM tells in a reply, with no model in the loop.

Every construction here was measured in production before it was coded: 42 real
assistant turns carried 25 negation antitheses, 16 of the mirror form, 7 "here's
the thing", bold emphasis in 25 of 67 messages, and a median of 1,235 characters
answering a 119-character user. A grid of 72 generated replies over the same
queries added two more that appeared at every temperature and reasoning effort,
which is what marks them as prompt-driven: a closing sales hook in 44 of them,
and the bold-led listicle template. This module turns all of that into a number
so a prompt change can be shown to move it rather than asserted to.

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

#: One bolded fragment is one tell, so spans are counted rather than the two
#: markers that delimit each one.
BOLD_EMPHASIS_PATTERN = re.compile(r"\*\*[^*\n]+\*\*")

#: The offer half of the sales close: a question offering to do the next thing.
#: On its own this is a legitimate nudge (plain "want me to draft it?" is fine)
#: and must NOT count as a violation. It only becomes the closing-hook tell when
#: paired with CLOSING_HOOK_JUSTIFICATION_PATTERN below (see has_closing_hook).
CLOSING_HOOK_PATTERN = re.compile(
    r"\b(?:want me to|want (?:me |you )?to|do you want me to|should i|shall i|need me to)\b"
    r"[^?\n]{0,160}\?",
    re.I,
)

#: The justification clause the model bolts onto the offer to argue the reader
#: into saying yes, e.g. "...? that's the one move that actually starts this."
#: This reflexive shape (offer + argument-for-yes), not the bare offer, was
#: measured in 44 of 72 generated replies on real production queries at every
#: temperature and reasoning effort tried, which is what marks it as
#: prompt-driven rather than sampling noise or an ordinary clarifying question.
CLOSING_HOOK_JUSTIFICATION_PATTERN = re.compile(
    r"\b(?:that's|that is|it's|it is|this is|which is|because|since)\b"
    r"[^.\n]*?\b(?:the one|the move|the piece|actually|highest|biggest|fastest|"
    r"what matters|what actually|makes the rest|starts this|the real|"
    r"the thing that|the only)\b",
    re.I,
)

#: The listicle template: three or more bold-led blocks, whether numbered steps
#: with bold headers or bold-headed paragraphs. Either shape turns a chat reply
#: into a generated document.
BOLD_LED_BLOCK_PATTERN = re.compile(r"^\s*(?:\d+[.)]\s*)?\*\*[^*\n]+\*\*", re.M)
TEMPLATE_SHAPE_MIN_BLOCKS = 3

#: Lenient on purpose: production replies truncate the sentinel mid-token
#: ("<NEW_MESSAGE_B", "<NEW_MESSAGE_BREA") when the model is cut off, and a
#: truncated sentinel still marks an intended split. Longest alternative first
#: so a whole sentinel never matches as a short one.
BUBBLE_SENTINEL_PATTERN = re.compile(r"<NEW_MESSAGE_(?:BREAK|BREA|BRE|BR|B)>?")

PARAGRAPH_SEPARATOR_PATTERN = re.compile(r"\n\s*\n")

EM_DASH = "—"

#: Enough of the sentence around an em dash to quote it back to the model. A
#: bare "—" told to rewrite says nothing about which clause to fix.
EM_DASH_CONTEXT_PATTERN = re.compile(rf"[^\n]{{0,30}}{EM_DASH}[^\n]{{0,30}}")

#: The scored fields, in scoring order. Single source of truth for both
#: ``total_violations`` and ``violation_snippets``, which drifted apart the
#: moment they each listed the detectors themselves.
VIOLATION_FIELDS: tuple[str, ...] = (
    "negation_antithesis",
    "em_dash",
    "banned_phrases",
    "bold_emphasis",
    "preamble",
    "closing_hook",
    "template_shape",
)


@dataclass(frozen=True)
class AiIsmScore:
    """Tell counts for one reply, plus the shape numbers that give them scale."""

    negation_antithesis: int
    em_dash: int
    banned_phrases: int
    bold_emphasis: int
    preamble: int
    closing_hook: int
    template_shape: int
    bubbles: int
    chars: int
    paragraphs: int

    @property
    def total_violations(self) -> int:
        return sum(int(getattr(self, field)) for field in VIOLATION_FIELDS)


def _count(patterns: tuple[re.Pattern[str], ...], text: str) -> int:
    return sum(len(pattern.findall(text)) for pattern in patterns)


def count_bubbles(text: str) -> int:
    """Bubbles the reply would be delivered as: non-empty sentinel-separated parts."""
    return sum(1 for part in BUBBLE_SENTINEL_PATTERN.split(text) if part.strip())


def has_closing_hook(text: str) -> bool:
    """Whether the reply signs off with the reflexive closing hook, not a plain offer.

    A plain offer ending in "?" ("want me to draft it?") is a legitimate nudge
    and does not count. Only the reflexive shape counts: an offer question
    followed by a justification clause arguing for saying yes, e.g. "want me to
    draft the win-back email right now? that's the one move that actually
    starts this." The justification clause may trail the "?" on the same line,
    or sit on the next non-blank line. Only the last non-empty line (or the
    pair of the last two) can be the closing position: the same offer asked
    mid-reply is ordinary conversation, not a sign-off.
    """
    lines = [line for line in BUBBLE_SENTINEL_PATTERN.sub("\n", text).splitlines() if line.strip()]
    if not lines:
        return False
    last_line = lines[-1]
    match = CLOSING_HOOK_PATTERN.search(last_line)
    if match and CLOSING_HOOK_JUSTIFICATION_PATTERN.search(last_line[match.end() :]):
        return True
    if len(lines) >= 2 and CLOSING_HOOK_PATTERN.search(lines[-2]):
        if CLOSING_HOOK_JUSTIFICATION_PATTERN.search(last_line):
            return True
    return False


def score_reply(text: str) -> AiIsmScore:
    """Score one assistant reply. Pure: same text in, same counts out."""
    return AiIsmScore(
        negation_antithesis=_count(NEGATION_ANTITHESIS_PATTERNS, text),
        em_dash=text.count(EM_DASH),
        banned_phrases=_count(BANNED_PHRASE_PATTERNS, text)
        + len(LET_ME_OPENER_PATTERN.findall(text)),
        bold_emphasis=len(BOLD_EMPHASIS_PATTERN.findall(text)),
        preamble=_count(PREAMBLE_PATTERNS, text),
        closing_hook=int(has_closing_hook(text)),
        template_shape=int(len(BOLD_LED_BLOCK_PATTERN.findall(text)) >= TEMPLATE_SHAPE_MIN_BLOCKS),
        bubbles=count_bubbles(text),
        chars=len(text),
        paragraphs=sum(1 for block in PARAGRAPH_SEPARATOR_PATTERN.split(text) if block.strip()),
    )


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> list[str]:
    return [match.group(0).strip() for pattern in patterns for match in pattern.finditer(text)]


def _closing_hook_snippets(non_blank_lines: list[str]) -> list[str]:
    """The offer+justification span(s) that make the closing position a reflexive hook."""
    if not non_blank_lines:
        return []
    last_line = non_blank_lines[-1]
    match = CLOSING_HOOK_PATTERN.search(last_line)
    if match:
        trailing = last_line[match.end() :]
        justification = CLOSING_HOOK_JUSTIFICATION_PATTERN.search(trailing)
        if justification:
            return [f"{match.group(0)}{trailing[: justification.end()]}".strip()]
    if len(non_blank_lines) >= 2:
        prev_match = CLOSING_HOOK_PATTERN.search(non_blank_lines[-2])
        justification = CLOSING_HOOK_JUSTIFICATION_PATTERN.search(last_line)
        if prev_match and justification:
            return [prev_match.group(0).strip(), justification.group(0).strip()]
    return []


def violation_snippets(text: str) -> dict[str, list[str]]:
    """The offending fragments per detector, for a correction note that quotes them.

    Only detectors that actually fired appear. Counts alone ("2 banned phrases")
    leave the model guessing which words to drop; the fragment is what makes the
    instruction actionable.
    """
    non_blank = [
        line for line in BUBBLE_SENTINEL_PATTERN.sub("\n", text).splitlines() if line.strip()
    ]
    found: dict[str, list[str]] = {
        "negation_antithesis": _matches(NEGATION_ANTITHESIS_PATTERNS, text),
        "em_dash": _matches((EM_DASH_CONTEXT_PATTERN,), text),
        "banned_phrases": _matches(BANNED_PHRASE_PATTERNS, text)
        + _matches((LET_ME_OPENER_PATTERN,), text),
        "bold_emphasis": _matches((BOLD_EMPHASIS_PATTERN,), text),
        "preamble": _matches(PREAMBLE_PATTERNS, text),
        # Only the reflexive shape (offer + justification clause) in the closing
        # position counts; a plain offer is a legitimate nudge, not a tell.
        "closing_hook": _closing_hook_snippets(non_blank),
        "template_shape": _matches((BOLD_LED_BLOCK_PATTERN,), text)
        if len(BOLD_LED_BLOCK_PATTERN.findall(text)) >= TEMPLATE_SHAPE_MIN_BLOCKS
        else [],
    }
    return {detector: snippets for detector, snippets in found.items() if snippets}
