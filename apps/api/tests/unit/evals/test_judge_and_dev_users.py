"""The pure parts of the shared judge and dev-user helpers.

Neither module may reach a model or an API from a test, so what is pinned here is
the shape either one hands to the layer below: the rubric block the prompts
interpolate, the options every judge call now shares, and the auth material a
dev-lane client carries.

The dev-lane assertions are the ones with a history: sending the ``X-Dev-User``
header without the ``dev_bypass_user`` cookie authenticates the REST calls and
401s the chat stream, which reads as an API outage rather than a harness bug.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
import pytest
from scripts.evals.core import judge as judge_mod
from scripts.evals.core.dev_users import DEFAULT_NAME, dev_client
from scripts.evals.core.judge import DEFAULT_MAX_ATTEMPTS, criteria_block, judge, simulate

pytestmark = pytest.mark.unit


class _Verdict(BaseModel):
    ok: bool = True


class TestCriteriaBlock:
    def test_renders_one_dash_line_per_criterion_in_order(self) -> None:
        """The key is also the report's column header, so order is not cosmetic."""
        assert criteria_block({"a_human": "sounds like a person", "b_length": "right length"}) == (
            "- a_human: sounds like a person\n- b_length: right length"
        )

    def test_empty_rubric_renders_empty(self) -> None:
        assert criteria_block({}) == ""


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the two LLM seams so a judge call records its arguments and returns."""
    seen: dict[str, Any] = {}

    def fake_runnable(model: type[BaseModel], temperature: float) -> str:
        seen["model"] = model
        seen["temperature"] = temperature
        return "runnable"

    async def fake_ainvoke(runnable: str, prompt: str, label: str, options: Any) -> _Verdict:
        seen["runnable"] = runnable
        seen["prompt"] = prompt
        seen["label"] = label
        seen["options"] = options
        return _Verdict()

    monkeypatch.setattr(judge_mod, "background_structured_runnable", fake_runnable)
    monkeypatch.setattr(judge_mod, "ainvoke_llm", fake_ainvoke)
    return seen


class TestJudgePlumbing:
    async def test_grades_at_temperature_zero_with_two_attempts(
        self, captured: dict[str, Any]
    ) -> None:
        """A judge that varies run to run turns a regression into a coin flip."""
        await judge(_Verdict, "rubric", label="some_judge", timeout=90.0)
        assert captured["temperature"] == 0.0
        assert captured["options"].max_attempts == DEFAULT_MAX_ATTEMPTS == 2
        assert captured["options"].timeout == 90.0

    async def test_passes_the_verdict_model_prompt_and_label_through(
        self, captured: dict[str, Any]
    ) -> None:
        """The label is per-script on purpose: one shared name would make a run's
        cost unattributable to the suite that spent it."""
        await judge(_Verdict, "the rubric text", label="chat_quality_judge", timeout=1.0)
        assert captured["model"] is _Verdict
        assert captured["prompt"] == "the rubric text"
        assert captured["label"] == "chat_quality_judge"

    async def test_returns_the_parsed_verdict(self, captured: dict[str, Any]) -> None:
        assert isinstance(await judge(_Verdict, "p", label="l", timeout=1.0), _Verdict)

    async def test_simulate_carries_the_warm_temperature_through(
        self, captured: dict[str, Any]
    ) -> None:
        """A deterministic difficult user stops being difficult in new ways."""
        await simulate(_Verdict, "p", label="user_sim", timeout=1.0, temperature=0.8)
        assert captured["temperature"] == 0.8


class TestDevClient:
    def test_carries_both_the_header_and_the_cookie(self) -> None:
        """REST routes read ``X-Dev-User``; the chat stream reads the cookie."""
        client = dev_client("someone@gaia.local")
        assert client.headers["X-Dev-User"] == "someone@gaia.local"
        assert client.cookies["dev_bypass_user"] == "someone@gaia.local"

    def test_default_display_name_is_a_single_shared_constant(self) -> None:
        """Four copies of ``_provision`` each spelled this literal themselves."""
        assert DEFAULT_NAME == "Alex"
