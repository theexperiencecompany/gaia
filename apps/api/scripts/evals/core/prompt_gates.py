"""Deterministic gates whose rules AND inputs come from the shipped prompt.

A rule the prompt states as an absolute is decidable by reading the reply, so
handing it to an LLM judge buys nothing and costs a non-reproducible verdict.
This module derives inputs from the prompt too: it reads the six banned
phrases out of the live banned_bot_phrases clause rather than carrying a
copy, so a seventh phrase added to COMMS_AGENT_PROMPT extends the gate with
no eval change. If the rule's shape changes so the list can no longer be read
out of it, extraction raises instead of silently gating on nothing.

Each gate has the (CaseRun) -> (score, reason) shape a suite's score()
already consumes, so wiring one in is a single line.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import re

from scripts.evals.core.prompt_contracts import ClauseResolutionError, resolve
from scripts.evals.core.types import CaseRun

#: Exempt because "agent"/"tool" are ordinary English (e.g. "a travel agent")
#: and would false-positive on innocent replies; the judge criterion from the
#: same clause still covers them. Every other quoted term is gated automatically.
_AMBIGUOUS_IN_ENGLISH = frozenset({"agent", "tool"})

_QUOTED = re.compile(r'"([^"]+)"')
_PARENTHESISED_CHAR = re.compile(r"\((.)\)")
# Backticks optional: the rule has written the tags bare and in backticks over
# time. The angle-bracketed lowercase shape is what identifies a channel tag, so
# matching on that survives either style.
_TAG = re.compile(r"`?(<[a-z_]+>)`?")


def _collapse(text: str) -> str:
    """Normalize whitespace and case so a wrapped prompt phrase still matches an unwrapped reply."""
    return " ".join(text.split()).lower()


def _assistant_text(run: CaseRun) -> str:
    """Join everything the assistant said, falling back to run.text when there is no per-message transcript.

    A join of empty messages is "\\n" — truthy but empty — so the fallback
    tests for real content, not truthiness: grading nothing must never pass a
    gate vacuously.
    """
    said = "\n".join(
        str(message.get("content") or "")
        for message in run.messages
        if message.get("role") == "assistant"
    )
    return said if said.strip() else run.text


def _require(found: list[str], ref: str, shape: str) -> list[str]:
    if not found:
        raise ClauseResolutionError(
            f"clause {ref!r} still resolves, but its inputs can no longer be read out of it: "
            f"expected {shape}, found none. The rule was reworded, so this gate would now check "
            f"nothing. Re-derive the extraction against the new wording (or drop the gate) "
            f"instead of leaving it passing vacuously."
        )
    return found


@lru_cache(maxsize=1)
def banned_phrases() -> tuple[str, ...]:
    """Return the literal chatbot phrases the prompt bans, read out of the prompt."""
    ref = "comms.banned_bot_phrases"
    found = _require(_QUOTED.findall(resolve(ref)), ref, "double-quoted phrases")
    return tuple(_collapse(phrase) for phrase in found)


@lru_cache(maxsize=1)
def banned_dashes() -> tuple[str, ...]:
    """Return the prompt's banned dash characters (em dash —, en dash –)."""
    ref = "comms.no_dashes"
    found = _require(
        _PARENTHESISED_CHAR.findall(resolve(ref)), ref, "parenthesised single characters"
    )
    letters = [character for character in found if character.isalnum()]
    if letters:
        raise ClauseResolutionError(
            f"clause {ref!r} now yields alphanumeric characters {letters} where it used to name "
            f"the banned dashes. The rule's shape changed — re-derive the extraction."
        )
    return tuple(found)


@lru_cache(maxsize=1)
def internal_terms() -> tuple[str, ...]:
    """Return the ONE ENTITY rule's forbidden internal-machinery words, minus ordinary-English exceptions."""
    ref = "comms.one_entity"
    found = _require(_QUOTED.findall(resolve(ref)), ref, "double-quoted internal terms")
    gated = [term for term in found if term.lower() not in _AMBIGUOUS_IN_ENGLISH]
    if not gated:
        raise ClauseResolutionError(
            f"clause {ref!r} now quotes only terms this gate treats as ordinary English "
            f"({found}), so it would check nothing. Re-derive the extraction."
        )
    return tuple(gated)


@lru_cache(maxsize=1)
def channel_tags() -> tuple[str, ...]:
    """Return the internal channel tags the prompt says must never reach a reply."""
    ref = "comms.never_reproduce_internal_tags"
    found = _require(_TAG.findall(resolve(ref)), ref, "angle-bracketed <tag> names")
    return tuple(found)


def dash_discipline(run: CaseRun) -> tuple[float, str]:
    """No em dash or en dash anywhere in the assistant's output.

    COMMS_AGENT_PROMPT states it as an absolute with no exceptions ("Not in
    chat replies, not in anything you write"), which makes it the single most
    mechanically checkable rule in the prompt — and it had no gate at all.
    """
    said = _assistant_text(run)
    hits = sorted({dash for dash in banned_dashes() if dash in said})
    if hits:
        return 0.0, f"used banned dash character(s) {hits} (prompt bans them outright)"
    return 1.0, f"none of {list(banned_dashes())} present"


def banned_bot_phrases(run: CaseRun) -> tuple[float, str]:
    """None of the phrases the prompt lists as "they scream chatbot"."""
    said = _collapse(_assistant_text(run))
    hits = [phrase for phrase in banned_phrases() if phrase in said]
    if hits:
        return 0.0, f"said banned chatbot phrase(s): {hits}"
    return 1.0, f"none of the {len(banned_phrases())} banned phrases present"


def internal_machinery(run: CaseRun) -> tuple[float, str]:
    """Fail if internal machinery is named to the user, per the ONE ENTITY rule.

    Matched with non-letter boundaries so call_executor counts as naming the
    executor, while executors in ordinary prose does not slip past.
    """
    said = _assistant_text(run)
    hits = [
        term
        for term in internal_terms()
        if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", said, flags=re.IGNORECASE)
    ]
    if hits:
        return 0.0, f"named internal machinery to the user: {hits}"
    return 1.0, f"none of {list(internal_terms())} named"


def internal_tags(run: CaseRun) -> tuple[float, str]:
    """Fail if any internal channel tag appears in a user-facing reply.

    Matched open OR closed: a model that echoes only </executor_result> at
    the end of an otherwise clean reply has still leaked the plumbing.
    """
    said = _assistant_text(run)
    hits = [tag for tag in channel_tags() if tag in said or f"</{tag.strip('<>')}>" in said]
    if hits:
        return 0.0, f"reproduced internal channel tag(s): {hits}"
    return 1.0, f"none of {list(channel_tags())} reproduced"


#: Gate name -> check. Suites wire these in the same way ``emoji_discipline`` is
#: wired today; the name is what shows up in the score bag and the report.
PROMPT_GATES: dict[str, Callable[[CaseRun], tuple[float, str]]] = {
    "dash_discipline": dash_discipline,
    "banned_bot_phrases": banned_bot_phrases,
    "internal_machinery": internal_machinery,
    "internal_tags": internal_tags,
}
