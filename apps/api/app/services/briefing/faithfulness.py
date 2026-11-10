"""Check the daily brief's rendered prose against its facts with one cheap structured call."""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.prompts.brief_faithfulness_prompts import BRIEF_FAITHFULNESS_PROMPT
from app.constants.briefing import BRIEF_FAITHFULNESS_LABEL


@dataclass(frozen=True)
class CheckedProse:
    """The brief's prose as the check reads it: slots filled, each filled value bracketed."""

    headline: str
    lede: str
    caption: str
    message: str


class UnsupportedClaims(BaseModel):
    """The checker's answer: every claim in the brief the facts do not support."""

    claims: list[str] = Field(
        description="Each unsupported claim in quotes, then what the facts say instead; empty when all hold"
    )


async def unsupported_claims(user_id: str, facts: str, prose: CheckedProse) -> list[str]:
    """Return each claim in the rendered prose that the facts the writer was shown do not support."""
    answer = await ainvoke_structured(
        UnsupportedClaims,
        BRIEF_FAITHFULNESS_PROMPT.format(
            facts=facts,
            headline=prose.headline,
            lede=prose.lede,
            caption=prose.caption,
            message=prose.message,
        ),
        label=BRIEF_FAITHFULNESS_LABEL,
        config=metered_config(user_id),
    )
    return [claim for claim in (c.strip() for c in answer.claims) if claim]
