"""Onboarding gate: does ReasoningLevel.OFF really stop the helper model from reasoning?

Run it before changing AUX_MODEL_NAME or OPENROUTER_REASONING_EFFORT:
uv run pytest tests/model_onboarding/test_reasoning_off.py -m model_onboarding -v.

Only a live call answers it: OpenRouter accepts every reasoning object and
the model decides what it honours. deepseek-v4-flash kept reasoning under
{"enabled": false} (111-167 tokens on a short prompt, up to its 8000-token cap
on a browser part judgement, which then timed out at 30 s every time).
"""

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel
import pytest

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured
from app.constants.llm import ReasoningLevel

pytestmark = pytest.mark.model_onboarding

_PROMPT = (
    "A list has 30 numbered items. Decide which of the numbers 1 to 30 are prime, "
    "then set answer to the count."
)


class _Count(BaseModel):
    answer: int = 0


class _ReasoningTokens(AsyncCallbackHandler):
    """Record the reasoning tokens each model call reports."""

    def __init__(self) -> None:
        self.seen: list[int] = []

    async def on_llm_end(self, response: LLMResult, **kwargs: object) -> None:
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                details = usage.get("output_token_details") or {}
                self.seen.append(int(details.get("reasoning", 0) or 0))


async def test_the_helper_model_spends_no_reasoning_tokens_when_reasoning_is_off() -> None:
    recorder = _ReasoningTokens()

    await ainvoke_structured(
        _Count,
        _PROMPT,
        label="onboarding_reasoning_off",
        config={"callbacks": [recorder]},
        options=StructuredCallOptions(timeout=60, reasoning=ReasoningLevel.OFF),
    )

    assert recorder.seen, "the call reported no usage to check"
    assert recorder.seen == [0] * len(recorder.seen), recorder.seen
