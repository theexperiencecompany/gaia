"""The middleware stack rides the graph's chat LLM — no separate model lane.

Summarization and the compaction digest receive the same ``chat_llm`` instance
the conversation runs on; per-request routing happens via the ambient
configurable, exactly like the model node's ``llm.with_config(...)``. These
tests pin that wiring so a separate resolution path can't creep back in.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.factory import (
    create_comms_middleware,
    create_executor_middleware,
    create_middleware_stack,
    create_subagent_middleware,
)
from app.agents.middleware.style_guard import StyleGuardMiddleware
from app.agents.middleware.subagent import SubagentMiddleware
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

    def test_no_chat_llm_drops_summarization_and_the_digest_tier(self, monkeypatch) -> None:
        warnings: list[str] = []

        class _StubLog:
            def warning(self, msg: str, **kw: object) -> None:
                warnings.append(msg)

            def error(self, *a: object, **k: object) -> None:
                pass

            def debug(self, *a: object, **k: object) -> None:
                pass

            def set(self, *a: object, **k: object) -> None:
                pass

            def info(self, *a: object, **k: object) -> None:
                pass

        from app.agents.middleware import factory as factory_mod

        monkeypatch.setattr(factory_mod, "log", _StubLog())
        stack = create_middleware_stack(chat_llm=None)

        assert not any(isinstance(mw, WorkspaceArchivingSummarizationMiddleware) for mw in stack)
        compactor = next(mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware))
        assert compactor.summary_llm is None
        # the operator must be told WHY summarization vanished
        assert any("summarization middleware skipped" in w for w in warnings)

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


class TestCommsStackComposition:
    """Comms is the only tier whose text a person reads, and the only one that
    delegates instead of acting — so what is and is not in its stack is the
    contract, not an implementation detail."""

    def test_the_style_guard_is_the_innermost_middleware(self) -> None:
        """Position is load-bearing: innermost of the wrap_model_call chain means
        it scores the response the model actually produced, not one an outer
        middleware already substituted (the budget wall's stop text, for one, is
        not the model's prose and must not be rewritten)."""
        stack = create_comms_middleware(chat_llm=_fake_llm())

        assert isinstance(stack[-1], StyleGuardMiddleware)
        assert sum(isinstance(mw, StyleGuardMiddleware) for mw in stack) == 1

    def test_comms_can_never_spawn_a_subagent(self) -> None:
        """Comms has no work tools by design — it hands everything to the
        executor. A spawn tool here would let the front door do the work."""
        stack = create_comms_middleware(chat_llm=_fake_llm())

        assert not any(isinstance(mw, SubagentMiddleware) for mw in stack)


class ConfigCapturingModel:
    """Records the configurable passed to with_config(), then delegates.

    Composed (not subclassed) so there is no override to silence; __getattr__
    forwards everything else — ainvoke included — to the wrapped fake.
    """

    def __init__(self, inner: BaseChatModel) -> None:
        self._inner = inner
        self.captured: dict[str, object] = {}

    def with_config(self, **kwargs: Any) -> BaseChatModel:
        self.captured.update(kwargs.get("configurable") or {})
        return self._inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class TestRequestConfigBinding:
    async def test_digest_is_invoked_with_the_request_configurable(self) -> None:
        """awrap_tool_call must bind the request's configurable onto the digest
        call — the same routing the model node performs."""
        inner = BindableToolsFakeModel(responses=[AIMessage(content="digest text")])
        capturing = ConfigCapturingModel(inner)

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=capturing)

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

        assert capturing.captured["provider"] == "custom"
        assert capturing.captured["user_id"] == "u1"
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs["compaction_strategy"] == "llm_summary"


class TestStackConfigurationPropagation:
    """The factory's knobs must land on the middleware that consumes them."""

    @staticmethod
    def _stack(
        **kwargs: Any,
    ) -> tuple[
        LLMAccountingMiddleware | None,
        WorkspaceArchivingSummarizationMiddleware | None,
        WorkspaceCompactionMiddleware | None,
        list,
    ]:
        stack = create_middleware_stack(**kwargs)
        accounting = next((mw for mw in stack if isinstance(mw, LLMAccountingMiddleware)), None)
        summarizer = next(
            (mw for mw in stack if isinstance(mw, WorkspaceArchivingSummarizationMiddleware)),
            None,
        )
        compactor = next(
            (mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware)), None
        )
        return accounting, summarizer, compactor, stack

    def test_thresholds_and_exclusions_reach_compaction(self) -> None:
        _, _, compactor, _ = self._stack(
            chat_llm=_fake_llm(),
            compaction_threshold=0.77,
            max_output_chars=4321,
            compaction_excluded_tools={"tool_a"},
        )
        assert compactor.compaction_threshold == 0.77
        assert compactor.max_output_chars == 4321
        assert compactor.excluded_tools == {"tool_a"}

    def test_summarization_knobs_reach_summarization(self) -> None:
        _, summarizer, _, _ = self._stack(
            chat_llm=_fake_llm(),
            summarization_trigger=("fraction", 0.42),
            summarization_keep=("tokens", 123),
            enable_archive=False,
            summarization_excluded_tools={"tool_b"},
        )
        assert summarizer.trigger == ("fraction", 0.42)
        assert summarizer.keep == ("tokens", 123)
        assert summarizer.enable_archive is False
        assert summarizer.excluded_tools == {"tool_b"}

    def test_accounting_identity_per_agent(self) -> None:
        from app.agents.middleware.accounting import LLMAccountingMiddleware
        from app.constants.llm import EXECUTOR_RECURSION_LIMIT

        stack = create_executor_middleware(chat_llm=_fake_llm())
        accounting = next(mw for mw in stack if isinstance(mw, LLMAccountingMiddleware))
        assert accounting.agent_name == "executor_agent"
        assert accounting.recursion_limit == EXECUTOR_RECURSION_LIMIT

    def test_a_subagent_meters_under_its_own_name(self) -> None:
        """Every integration subagent shares one middleware factory. Without its
        own name they all meter as ``provider_subagent``, so ~35 subagents
        collapse into one bucket and per-subagent cost and cache behaviour cannot
        be told apart."""
        from app.agents.middleware.accounting import LLMAccountingMiddleware

        stack = create_subagent_middleware(
            agent_name="gmail_agent", subagent_llm=_fake_llm(), enable_subagent=False
        )
        accounting = next(mw for mw in stack if isinstance(mw, LLMAccountingMiddleware))
        assert accounting.agent_name == "gmail_agent"

    def test_an_unnamed_subagent_still_meters_as_the_generic_bucket(self) -> None:
        """The spawn factory builds sub-subagent stacks with no name of their own;
        they keep the generic bucket rather than crashing or going unattributed."""
        from app.agents.middleware.accounting import LLMAccountingMiddleware

        stack = create_subagent_middleware(subagent_llm=_fake_llm(), enable_subagent=False)
        accounting = next(mw for mw in stack if isinstance(mw, LLMAccountingMiddleware))
        assert accounting.agent_name == "provider_subagent"

    def test_subagent_exclusions_are_the_union(self) -> None:
        from app.agents.middleware.factory import (
            CODING_TOOL_NAMES,
            SELF_OFFLOADING_TOOL_NAMES,
            SPAWN_SUBAGENT_TOOL,
        )

        stack = create_subagent_middleware(subagent_llm=_fake_llm(), enable_subagent=False)
        compactor = next(mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware))
        assert compactor.excluded_tools == (
            CODING_TOOL_NAMES | SPAWN_SUBAGENT_TOOL | SELF_OFFLOADING_TOOL_NAMES
        )

    def test_comms_accounting_name(self) -> None:
        from app.agents.middleware.accounting import LLMAccountingMiddleware

        stack = create_comms_middleware(chat_llm=_fake_llm())
        accounting = next(mw for mw in stack if isinstance(mw, LLMAccountingMiddleware))
        assert accounting.agent_name == "comms_agent"

    def test_disabled_flags_leave_no_middleware(self) -> None:
        _, summarizer, compactor, _ = self._stack(
            chat_llm=_fake_llm(), enable_summarization=False, enable_compaction=False
        )
        assert summarizer is None and compactor is None


class TestBuildGraphChatLlmPassThrough:
    async def test_comms_graph_hands_its_llm_to_the_middleware(self) -> None:
        """build_comms_graph must forward chat_llm into create_comms_middleware —
        the summarizer inside comms rides the conversation's model."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agents.core.graph_builder import build_graph as bg
        from tests.e2e._harness.graph_run import scripted_model

        captured: dict = {}
        real_create_comms = bg.create_comms_middleware

        def spy(chat_llm=None):
            captured["chat_llm"] = chat_llm
            return real_create_comms(chat_llm=chat_llm)

        def _capture(**kwargs):
            captured_mw = kwargs
            return MagicMock(compile=MagicMock(return_value=MagicMock())), captured_mw

        from app.agents.tools.core.registry import init_tool_registry
        from app.core.lazy_loader import providers

        if not providers.is_initialized("tool_registry"):
            init_tool_registry()

        from langgraph.store.memory import InMemoryStore

        llm = scripted_model(["hi"])
        with (
            patch.object(bg, "get_tools_store", AsyncMock(return_value=InMemoryStore())),
            patch.object(bg, "get_checkpointer_manager", AsyncMock(return_value=None)),
            patch.object(bg, "create_agent", new=MagicMock(return_value=MagicMock())),
            patch.object(bg, "create_comms_middleware", new=spy),
        ):
            async with bg.build_comms_graph(chat_llm=llm, in_memory_checkpointer=True) as _:
                pass

        assert captured["chat_llm"] is llm
