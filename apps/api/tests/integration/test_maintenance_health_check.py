"""The maintenance sweep's health check, driven through the real one-shot model path.

Real: _health_check_verdict, ainvoke_llm (retry, metering seam). Faked: the
chat model resolve_model returns, which records what it was shown and refuses
to have tools bound.
"""

from __future__ import annotations

from typing import Any, NoReturn
from unittest.mock import patch

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatResult
from pydantic import Field
import pytest

from app.workers.tasks.maintenance_sweep_tasks import _health_check_verdict

PROMPT = "A tracked todo has been dormant for 7 days. Title: Daily Inbox Briefing"
VERDICT = "EXECUTE: draft the briefing from today's inbox"


class _VerdictOnlyModel(FakeMessagesListChatModel):
    """Answers once, records every call, and fails the test if anything binds tools to it."""

    seen: list[tuple[list[BaseMessage], dict[str, Any]]] = Field(default_factory=list)

    def bind_tools(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("the health check bound tools to its model")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append((messages, kwargs))
        return super()._generate(messages, stop, run_manager, **kwargs)


@pytest.mark.integration
async def test_the_health_check_prompt_reaches_a_model_with_no_tools() -> None:
    model = _VerdictOnlyModel(responses=[AIMessage(content=f"  {VERDICT}\n")])

    with patch("app.workers.tasks.maintenance_sweep_tasks.resolve_model", return_value=model):
        verdict = await _health_check_verdict("user-1", PROMPT)

    assert verdict == VERDICT
    [(messages, call_kwargs)] = model.seen
    assert messages == [HumanMessage(content=PROMPT)]
    assert "tools" not in call_kwargs
