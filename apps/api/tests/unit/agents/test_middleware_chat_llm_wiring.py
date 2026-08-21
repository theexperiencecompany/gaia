"""The middleware stack rides the graph's chat LLM — no separate model lane.

Summarization and the compaction digest receive the same ``chat_llm`` instance
the conversation runs on; per-request routing happens via the ambient
configurable, exactly like the model node's ``llm.with_config(...)``. These
tests pin that wiring so a separate resolution path can't creep back in.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.factory import (
    create_comms_middleware,
    create_executor_middleware,
    create_middleware_stack,
    create_subagent_middleware,
)
from app.agents.middleware.summarization import (
    WorkspaceArchivingSummarizationMiddleware,
)
from app.services.storage import JuiceFSUnavailable
from tests.helpers import BindableToolsFakeModel


def _fake_llm() -> BaseChatModel:
    llm = BindableToolsFakeModel(responses=[])
    # Fractional-window middleware reads this at construction, exactly as it
    # does for the real chat LLM (init_*_llm pin it there).
    llm.profile = {"max_input_tokens": 100_000}
    return llm


class TestChatLlmWiring:
    def test_summarization_and_compaction_share_the_chat_llm(self) -> None:
        llm = _fake_llm()
        stack = create_middleware_stack(chat_llm=llm)

        summarizer = next(
            mw for mw in stack if isinstance(mw, WorkspaceArchivingSummarizationMiddleware)
        )
        compactor = next(mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware))
        assert summarizer.model is llm
        assert compactor.summary_llm is llm

    def test_no_chat_llm_drops_summarization_and_the_digest_tier(self) -> None:
        stack = create_middleware_stack(chat_llm=None)

        assert not any(
            isinstance(mw, WorkspaceArchivingSummarizationMiddleware) for mw in stack
        )
        compactor = next(mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware))
        assert compactor.summary_llm is None

    def test_executor_stack_takes_chat_llm(self) -> None:
        llm = _fake_llm()
        stack = create_executor_middleware(chat_llm=llm)
        compactor = next(mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware))
        assert compactor.summary_llm is llm

    def test_comms_gets_summarization_on_the_chat_llm_and_never_compaction(self) -> None:
        llm = _fake_llm()
        stack = create_comms_middleware(chat_llm=llm)

        summarizer = next(
            mw for mw in stack if isinstance(mw, WorkspaceArchivingSummarizationMiddleware)
        )
        assert summarizer.model is llm
        assert not any(isinstance(mw, WorkspaceCompactionMiddleware) for mw in stack)

    def test_subagent_stack_rides_its_own_llm(self) -> None:
        llm = _fake_llm()
        stack = create_subagent_middleware(subagent_llm=llm, enable_subagent=False)
        compactor = next(mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware))
        assert compactor.summary_llm is llm


class TestRequestConfigBinding:
    async def test_digest_is_invoked_with_the_request_configurable(self) -> None:
        """awrap_tool_call must bind the request's configurable onto the digest
        call — the same routing the model node performs."""
        captured: dict = {}

        class CapturingFake(BindableToolsFakeModel):
            def with_config(self, *, configurable=None, **kwargs):  # type: ignore[override]
                captured.update(configurable or {})
                return super().with_config(configurable=configurable, **kwargs)

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_fake_llm())
        # swap in a fresh capturing fake after construction-time token counting
        mw.summary_llm = CapturingFake(responses=[AIMessage(content="digest text")])

        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(
                config={
                    "configurable": {
                        "user_id": "u1",
                        "vfs_session_id": "conv1",
                        "provider": "custom",
                    }
                }
            ),
            state={"messages": []},
        )

        async def handler(_req):
            return ToolMessage(content="x" * 5000, tool_call_id="call_1", name="search")

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=JuiceFSUnavailable("no mount"),
        ):
            result = await mw.awrap_tool_call(request, handler)

        assert captured["provider"] == "custom"
        assert captured["user_id"] == "u1"
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs["compaction_strategy"] == "llm_summary"
