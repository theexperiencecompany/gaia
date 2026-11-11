"""Check a brief's rendered text, composed or voiced, against its facts with one cheap structured call."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, metered_config
from app.agents.prompts.brief_faithfulness_prompts import BRIEF_FAITHFULNESS_PROMPT
from app.constants.briefing import BRIEF_FAITHFULNESS_LABEL, BRIEF_FAITHFULNESS_TEMPERATURE
from app.services.briefing.slots import FILLED_CLOSE, FILLED_OPEN
from shared.py.wide_events import log

#: What a claim's fact is when the specific it names is in no fact at all.
ABSENT: Literal["absent"] = "absent"
#: How the check judges one specific against the facts.
Verdict = Literal["holds", "contradicted", "absent"]


@dataclass(frozen=True)
class CheckedProse:
    """The brief's model-written text as the check reads it: slots filled, each filled value bracketed.

    fields name each string ("headline", "block 2 heading") beside its text, in reading order.
    """

    fields: tuple[tuple[str, str], ...]

    def written(self) -> str:
        """Lay the fields out as the check reads them, a multi-line one under its name."""
        return "\n".join(
            f"{name}:\n{text}" if "\n" in text else f"{name}: {text}" for name, text in self.fields
        )


class UnsupportedClaim(BaseModel):
    """One specific the brief states that the facts contradict or do not hold."""

    quote: str = Field(description="The brief's own words that state the specific, verbatim")
    fact: int | Literal["absent"] = Field(
        description=(
            "The id of the fact the claim contradicts, or absent when the person, event, "
            "deadline, count or state it names is in no fact"
        )
    )
    truth: str = Field(description="What the facts say instead, in a few words")

    def problem(self) -> str:
        """Say the claim the way the writer's retry names it."""
        where = "no fact holds it" if self.fact == ABSENT else f"fact {self.fact} says otherwise"
        return f'"{self.quote}": {where}; {self.truth}'


class CheckedSpecific(BaseModel):
    """One specific the brief states, judged against the facts."""

    quote: str = Field(description="The brief's own words stating the specific, copied verbatim")
    verdict: Verdict = Field(
        description=(
            "holds: a fact says it, in any words, loosely or vaguely; contradicted: a fact says "
            "otherwise; absent: it names a person, event, deadline, count or outcome no fact holds"
        )
    )
    fact: int | None = Field(
        description="The id of the fact it holds to or contradicts; null when absent"
    )
    truth: str = Field(description="What the facts say about it, in a few words")


class UnsupportedClaims(BaseModel):
    """The checker's answer: every specific the brief states, each judged."""

    specifics: list[CheckedSpecific] = Field(
        description=(
            "Every person, count, time, event, deadline, state and outcome the brief states, "
            "each judged. Not a specific, so never listed: vagueness (a few, several), a "
            "synonym (released for shipped), tone, wit, ordering, an offer or question, "
            "something left out, or a value in ⟦ ⟧."
        )
    )


def _claim(specific: CheckedSpecific) -> UnsupportedClaim:
    fact = specific.fact if specific.verdict == "contradicted" and specific.fact else ABSENT
    return UnsupportedClaim(quote=specific.quote, fact=fact, truth=specific.truth)


def _verbatim(quote: str, prose: CheckedProse) -> bool:
    """Whether the brief holds the quote; a quote the brief never wrote is not its claim."""
    written = " ".join(
        " ".join(text for _, text in prose.fields)
        .replace(FILLED_OPEN, "")
        .replace(FILLED_CLOSE, "")
        .split()
    ).casefold()
    return (
        " ".join(quote.replace(FILLED_OPEN, "").replace(FILLED_CLOSE, "").split()).casefold()
        in written
    )


async def unsupported_claims(
    user_id: str, facts: str, prose: CheckedProse
) -> list[UnsupportedClaim]:
    """Return each specific in the rendered prose that the facts contradict or do not hold.

    A claim quoting words the brief never wrote misreads the facts as the brief; it is logged
    and dropped.
    """
    answer = await ainvoke_structured(
        UnsupportedClaims,
        BRIEF_FAITHFULNESS_PROMPT.format(facts=facts, brief=prose.written()),
        label=BRIEF_FAITHFULNESS_LABEL,
        config=metered_config(user_id),
        options=StructuredCallOptions(temperature=BRIEF_FAITHFULNESS_TEMPERATURE, schema_held=True),
    )
    claims = [_claim(s) for s in answer.specifics if s.verdict != "holds"]
    unquoted = [c.quote for c in claims if not _verbatim(c.quote, prose)]
    if unquoted:
        log.warning("briefing.faithfulness_unquoted", quotes=unquoted)
    return [c for c in claims if _verbatim(c.quote, prose)]
