"""The one structured grading call the live-chat harnesses share.

Eight call sites across five scripts spelled out the same four lines — build a
structured runnable at temperature 0, invoke it, label it, allow two attempts
under a per-script timeout. The rubric text differs every time and stays with the
script that owns it; the *plumbing* does not differ at all, and having it copied
eight times is how ``max_attempts`` ends up at 2 in seven places and 1 in the
eighth without anyone noticing that one suite grades less reliably than the rest.

Temperature is fixed at 0 by default because a judge that varies run to run turns
a regression into a coin flip. ``simulate`` is the deliberate exception: the
adversarial harness needs its *simulated user* warm, or a difficult person stops
being difficult in new ways.
"""

from __future__ import annotations

from typing import TypeVar, cast

from pydantic import BaseModel

from app.agents.llm.client import LLMInvokeOptions, ainvoke_llm, background_structured_runnable

VerdictT = TypeVar("VerdictT", bound=BaseModel)

#: Every copy used two. A judge failure is a provider blip, not a verdict, and
#: the scripts already report an ungraded row rather than scoring it 0.
DEFAULT_MAX_ATTEMPTS = 2


def criteria_block(criteria: dict[str, str]) -> str:
    """Rubric dict rendered as the ``- key: ask`` list the prompts interpolate.

    The key is also the column header in the report, so rendering it here keeps
    what the judge was asked and what the founder reads in the same order.
    """
    return "\n".join(f"- {key}: {text}" for key, text in criteria.items())


async def judge(
    verdict_model: type[VerdictT],
    prompt: str,
    *,
    label: str,
    timeout: float,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    temperature: float = 0.0,
) -> VerdictT:
    """Grade ``prompt`` into ``verdict_model`` on the background lane.

    ``label`` is what shows up in the trace, so it stays required and per-script:
    collapsing eight judges into one name would make the cost of a run
    unattributable to the suite that spent it.
    """
    # ``ainvoke_llm`` is annotated to return ``Any``; the structured runnable is
    # built from ``verdict_model``, so the parse is correct by construction.
    return cast(
        VerdictT,
        await ainvoke_llm(
            background_structured_runnable(verdict_model, temperature=temperature),
            prompt,
            label=label,
            options=LLMInvokeOptions(max_attempts=max_attempts, timeout=timeout),
        ),
    )


async def simulate(
    move_model: type[VerdictT],
    prompt: str,
    *,
    label: str,
    timeout: float,
    temperature: float,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> VerdictT:
    """Same plumbing, warm on purpose: this generates behaviour, not a verdict.

    Separate from :func:`judge` so a temperature above 0 is never something a
    grading call can acquire by passing an argument — reaching for a different
    function is the point at which someone asks whether it should be warm.
    """
    return await judge(
        move_model,
        prompt,
        label=label,
        timeout=timeout,
        max_attempts=max_attempts,
        temperature=temperature,
    )
