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
from langchain_core.tools import BaseTool, tool

from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.agents.middleware.factory import (
    CODING_TOOL_NAMES,
    SELF_OFFLOADING_TOOL_NAMES,
    SPAWN_SUBAGENT_TOOL,
    AccountingOptions,
    ContextOptions,
    LoopGuardOptions,
    SubagentStackOptions,
    create_comms_middleware,
    create_executor_middleware,
    create_middleware_stack,
    create_subagent_middleware,
)
from app.agents.middleware.hil_approval import HILApprovalMiddleware
from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.agents.middleware.media import MediaDescriptionMiddleware
from app.agents.middleware.style_guard import StyleGuardMiddleware
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.middleware.subagent_join import SubagentJoinMiddleware
from app.agents.middleware.summarization import (
    WorkspaceArchivingSummarizationMiddleware,
)
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.constants.llm import EXECUTOR_RECURSION_LIMIT
from app.services.storage import JuiceFSUnavailable
from tests.helpers import BindableToolsFakeModel

COMPACTION_EXCLUSIONS = CODING_TOOL_NAMES | SPAWN_SUBAGENT_TOOL | SELF_OFFLOADING_TOOL_NAMES


def _fake_llm() -> BaseChatModel:
    llm = BindableToolsFakeModel(responses=[])
    # Fractional-window middleware reads this at construction, exactly as it
    # does for the real chat LLM (init_*_llm pin it there).
    llm.profile = {"max_input_tokens": 100_000}
    return llm


@tool
def _spawnable_tool(query: str) -> str:
    """A stand-in for a real tool handed to spawned subagents."""
    return query


def _types(stack: list) -> list[type]:
    return [type(mw) for mw in stack]


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
        stack = create_subagent_middleware(subagent=SubagentStackOptions(enabled=False, llm=llm))
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
            context=ContextOptions(
                compaction_threshold=0.77,
                max_output_chars=4321,
                compaction_excluded_tools={"tool_a"},
            ),
        )
        assert compactor.compaction_threshold == 0.77
        assert compactor.max_output_chars == 4321
        assert compactor.excluded_tools == {"tool_a"}

    def test_summarization_knobs_reach_summarization(self) -> None:
        _, summarizer, _, _ = self._stack(
            chat_llm=_fake_llm(),
            context=ContextOptions(
                summarization_trigger=("fraction", 0.42),
                summarization_keep=("tokens", 123),
                archive=False,
                summarization_excluded_tools={"tool_b"},
            ),
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
            agent_name="gmail_agent",
            subagent=SubagentStackOptions(enabled=False, llm=_fake_llm()),
        )
        accounting = next(mw for mw in stack if isinstance(mw, LLMAccountingMiddleware))
        assert accounting.agent_name == "gmail_agent"

    def test_an_unnamed_subagent_still_meters_as_the_generic_bucket(self) -> None:
        """The spawn factory builds sub-subagent stacks with no name of their own;
        they keep the generic bucket rather than crashing or going unattributed."""
        from app.agents.middleware.accounting import LLMAccountingMiddleware

        stack = create_subagent_middleware(
            subagent=SubagentStackOptions(enabled=False, llm=_fake_llm())
        )
        accounting = next(mw for mw in stack if isinstance(mw, LLMAccountingMiddleware))
        assert accounting.agent_name == "provider_subagent"

    def test_subagent_exclusions_are_the_union(self) -> None:
        from app.agents.middleware.factory import (
            CODING_TOOL_NAMES,
            SELF_OFFLOADING_TOOL_NAMES,
            SPAWN_SUBAGENT_TOOL,
        )

        stack = create_subagent_middleware(
            subagent=SubagentStackOptions(enabled=False, llm=_fake_llm())
        )
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
            chat_llm=_fake_llm(), context=ContextOptions(summarize=False, compact=False)
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


class TestSpawnWiring:
    """Every SubagentStackOptions field must land on SubagentMiddlewareConfig.

    A field that silently falls back to the config's default is not a cosmetic
    slip: the spawned subagent then runs on the wrong model, with the wrong
    registry, or with a tool the parent deliberately excluded.
    """

    @staticmethod
    def _wired() -> tuple[
        SubagentMiddleware, BaseChatModel, ToolRuntimeConfig, dict[str, BaseTool]
    ]:
        subagent_llm = _fake_llm()
        runtime = ToolRuntimeConfig(initial_tool_names=["read"], enable_retrieve_tools=False)
        registry = {"spawnable": _spawnable_tool}
        stack = create_middleware_stack(
            chat_llm=_fake_llm(),
            subagent=SubagentStackOptions(
                enabled=True,
                llm=subagent_llm,
                tools=[_spawnable_tool],
                registry=registry,
                excluded_tools={"handoff"},
                tool_space="gmail",
                tool_runtime_config=runtime,
                join=True,
            ),
        )
        spawner = next((mw for mw in stack if isinstance(mw, SubagentMiddleware)), None)
        assert isinstance(spawner, SubagentMiddleware)
        return spawner, subagent_llm, runtime, registry

    def test_every_spawn_field_reaches_the_middleware(self) -> None:
        spawner, subagent_llm, runtime, registry = self._wired()

        assert spawner._llm is subagent_llm
        assert spawner._available_tools == [_spawnable_tool]
        assert spawner._tool_registry == registry
        # SubagentMiddleware adds spawn_subagent itself; the caller's exclusion
        # must survive alongside it rather than replace or be replaced by it.
        assert spawner._excluded_tools == {"handoff", "spawn_subagent"}
        assert spawner._tool_space == "gmail"
        assert spawner._tool_runtime_config is runtime
        assert callable(spawner._spawn_middleware_factory)

    def test_the_full_stack_is_this_exact_sequence(self) -> None:
        """Order is the contract: accounting observes every model call from the
        outside, the HIL gate wraps every tool call before any side effect, and
        the loop guard sits innermost where it sees raw tool results."""
        stack = create_middleware_stack(
            chat_llm=_fake_llm(),
            subagent=SubagentStackOptions(enabled=True, join=True),
        )

        assert _types(stack) == [
            LLMAccountingMiddleware,
            HILApprovalMiddleware,
            SubagentMiddleware,
            WorkspaceArchivingSummarizationMiddleware,
            WorkspaceCompactionMiddleware,
            MediaDescriptionMiddleware,
            LoopGuardMiddleware,
            SubagentJoinMiddleware,
        ]

    def test_the_spawn_factory_builds_a_child_that_cannot_spawn_again(self) -> None:
        """A sub-subagent must not get spawn rights of its own — otherwise a
        spawn tree can recurse without bound."""
        spawner, *_ = self._wired()

        child = spawner._spawn_middleware_factory("gmail")

        assert _types(child) == [
            LLMAccountingMiddleware,
            HILApprovalMiddleware,
            WorkspaceCompactionMiddleware,
            MediaDescriptionMiddleware,
            LoopGuardMiddleware,
        ]

    def test_the_spawn_factory_hands_the_child_its_space(self, monkeypatch) -> None:
        """The child stack is built for the space the spawn runs in; a default
        space would scope its retrieval to the wrong tool set."""
        from app.agents.middleware import factory as factory_mod

        captured: dict[str, Any] = {}

        def spy(**kwargs: Any) -> list:
            captured.update(kwargs)
            return []

        spawner, *_ = self._wired()
        monkeypatch.setattr(factory_mod, "create_subagent_middleware", spy)

        assert spawner._spawn_middleware_factory("gmail") == []
        assert captured == {"subagent": SubagentStackOptions(enabled=False, tool_space="gmail")}


class TestLoopGuardWiring:
    @staticmethod
    def _guard(**kwargs: Any) -> LoopGuardMiddleware:
        stack = create_middleware_stack(chat_llm=_fake_llm(), **kwargs)
        guard = next((mw for mw in stack if isinstance(mw, LoopGuardMiddleware)), None)
        assert isinstance(guard, LoopGuardMiddleware)
        return guard

    def test_hard_stop_is_off_unless_asked_for(self) -> None:
        """Warn-only is the default: a hard stop abandons a tool call, which is
        only safe on an unattended run."""
        assert self._guard().hard_stop is False
        assert self._guard(loop_guard=LoopGuardOptions(hard_stop=True)).hard_stop is True

    def test_disabling_the_loop_guard_leaves_it_out(self) -> None:
        stack = create_middleware_stack(
            chat_llm=_fake_llm(), loop_guard=LoopGuardOptions(enabled=False)
        )
        assert not any(isinstance(mw, LoopGuardMiddleware) for mw in stack)


def _spy_on_stack(monkeypatch) -> dict[str, Any]:
    """Capture the arguments a tier factory hands to create_middleware_stack."""
    from app.agents.middleware import factory as factory_mod

    captured: dict[str, Any] = {}

    def spy(**kwargs: Any) -> list:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(factory_mod, "create_middleware_stack", spy)
    return captured


class TestExecutorStackComposition:
    """The executor is the only tier that both spawns subagents and must collect
    them, so its stack composition is the contract other tiers are defined against."""

    @staticmethod
    def _executor(chat_llm: BaseChatModel, subagent_llm: BaseChatModel, runtime, registry) -> list:
        return create_executor_middleware(
            chat_llm=chat_llm,
            subagent_llm=subagent_llm,
            subagent_tools=[_spawnable_tool],
            subagent_registry=registry,
            subagent_excluded_tools={"handoff"},
            subagent_tool_runtime_config=runtime,
        )

    def test_the_executor_stack_is_this_exact_sequence(self) -> None:
        stack = self._executor(_fake_llm(), _fake_llm(), ToolRuntimeConfig(), {})

        assert _types(stack) == [
            LLMAccountingMiddleware,
            HILApprovalMiddleware,
            SubagentMiddleware,
            WorkspaceArchivingSummarizationMiddleware,
            WorkspaceCompactionMiddleware,
            MediaDescriptionMiddleware,
            LoopGuardMiddleware,
            SubagentJoinMiddleware,
        ]

    def test_the_executor_spawn_wiring_reaches_the_middleware(self) -> None:
        subagent_llm = _fake_llm()
        runtime = ToolRuntimeConfig(initial_tool_names=["bash"])
        registry = {"spawnable": _spawnable_tool}

        stack = self._executor(_fake_llm(), subagent_llm, runtime, registry)
        spawner = next(mw for mw in stack if isinstance(mw, SubagentMiddleware))

        assert spawner._llm is subagent_llm
        assert spawner._available_tools == [_spawnable_tool]
        assert spawner._tool_registry == registry
        assert spawner._excluded_tools == {"handoff", "spawn_subagent"}
        assert spawner._tool_runtime_config is runtime

    def test_the_executor_compacts_everything_but_the_self_bounded_tools(self) -> None:
        """The exclusion set is a union, not any one of its three parts: coding
        tools are already capped, spawn_subagent returns a digest, and the
        self-offloading fetchers write their own file format compaction would
        clobber."""
        stack = self._executor(_fake_llm(), _fake_llm(), ToolRuntimeConfig(), {})
        compactor = next(mw for mw in stack if isinstance(mw, WorkspaceCompactionMiddleware))

        assert compactor.excluded_tools == COMPACTION_EXCLUSIONS

    def test_the_executor_delegates_the_exact_options(self, monkeypatch) -> None:
        captured = _spy_on_stack(monkeypatch)
        chat_llm = _fake_llm()
        subagent_llm = _fake_llm()
        runtime = ToolRuntimeConfig(initial_tool_names=["bash"])
        registry = {"spawnable": _spawnable_tool}

        self._executor(chat_llm, subagent_llm, runtime, registry)

        assert captured == {
            "agent_name": "executor_agent",
            "chat_llm": chat_llm,
            "accounting": AccountingOptions(recursion_limit=EXECUTOR_RECURSION_LIMIT),
            "subagent": SubagentStackOptions(
                enabled=True,
                llm=subagent_llm,
                tools=[_spawnable_tool],
                registry=registry,
                excluded_tools={"handoff"},
                tool_runtime_config=runtime,
                join=True,
            ),
            "context": ContextOptions(compaction_excluded_tools=COMPACTION_EXCLUSIONS),
        }


class TestCommsAndSubagentDelegation:
    def test_comms_delegates_the_exact_options(self, monkeypatch) -> None:
        """Comms never spawns and never compacts — both are off by explicit
        value, not by accident of a default."""
        captured = _spy_on_stack(monkeypatch)
        llm = _fake_llm()

        create_comms_middleware(chat_llm=llm)

        assert captured == {
            "agent_name": "comms_agent",
            "chat_llm": llm,
            "subagent": SubagentStackOptions(enabled=False),
            "context": ContextOptions(compact=False),
        }

    def test_the_comms_stack_is_this_exact_sequence(self) -> None:
        assert _types(create_comms_middleware(chat_llm=_fake_llm())) == [
            LLMAccountingMiddleware,
            HILApprovalMiddleware,
            WorkspaceArchivingSummarizationMiddleware,
            MediaDescriptionMiddleware,
            LoopGuardMiddleware,
            StyleGuardMiddleware,
        ]

    def test_a_subagent_summarizes_its_own_history(self) -> None:
        """Compaction bounds one tool output, not the accumulated history. Without
        summarization a subagent run grows unbounded to the recursion limit — in
        production that averaged 91k input tokens per call against 43k elsewhere."""
        llm = _fake_llm()

        stack = create_subagent_middleware(subagent=SubagentStackOptions(enabled=False, llm=llm))
        summarizer = next(
            (mw for mw in stack if isinstance(mw, WorkspaceArchivingSummarizationMiddleware)), None
        )

        assert isinstance(summarizer, WorkspaceArchivingSummarizationMiddleware)
        assert summarizer.model is llm

    def test_a_subagent_delegates_the_exact_options(self, monkeypatch) -> None:
        captured = _spy_on_stack(monkeypatch)
        llm = _fake_llm()
        options = SubagentStackOptions(enabled=True, llm=llm, tool_space="gmail")

        create_subagent_middleware(agent_name="gmail_agent", subagent=options)

        assert captured == {
            "agent_name": "gmail_agent",
            "chat_llm": llm,
            "subagent": options,
            "context": ContextOptions(
                summarize=True, compact=True, compaction_excluded_tools=COMPACTION_EXCLUSIONS
            ),
        }
