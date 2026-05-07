"""E2E tests for node-level RetryPolicy on the GAIA agent graph.

WHAT THIS TESTS (REAL GAIA CODE):
- ``_AGENT_RETRY_POLICY`` from ``app.agents.core.graph_builder.build_graph``
  is wired into the ``"agent"`` node via ``create_agent`` from
  ``app.override.langgraph_bigtool.create_agent``.
- When the LLM raises a retryable exception (e.g. ``ResourceExhausted``),
  LangGraph retries the full ``acall_model`` node up to 3 times.
- When the LLM raises a non-retryable exception (e.g. ``ValueError``),
  the error propagates immediately without retrying.
- Without a retry policy, any exception propagates on the first attempt.

Mock surfaces:
- LLM: FailOnceFakeModel (raises on attempt 1, succeeds on attempt 2)
- Store: InMemoryStore (no ChromaDB)
- Checkpointer: MemorySaver (no PostgreSQL)

DELETE ``_AGENT_RETRY_POLICY`` → test_retry_policy_retries_on_resource_exhausted FAILS.
DELETE ``agent_retry_policy=`` kwarg in create_agent wiring → same.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from google.api_core.exceptions import ResourceExhausted
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import PrivateAttr

from app.agents.core.graph_builder.build_graph import _AGENT_RETRY_POLICY
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.override.langgraph_bigtool.create_agent import create_agent
from app.override.langgraph_bigtool.hooks import HookType
from tests.helpers import BindableToolsFakeModel


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FailThenSucceedModel(BindableToolsFakeModel):
    """Fake LLM that raises a configured exception on the first invoke.

    Subsequent invocations delegate to ``FakeMessagesListChatModel._generate``
    and return the pre-programmed response list in order.

    ``_attempt_count`` is a mutable list (not a Pydantic field) so it
    survives ``bind_tools()`` which returns ``self``. LangGraph's node-level
    ``RetryPolicy`` retries the entire node function — meaning ``bind_tools``
    is called again and then ``ainvoke`` is called again — so the counter
    correctly accumulates across retry attempts.
    """

    _attempt_count: list[int] = PrivateAttr(default_factory=lambda: [0])
    _exception_to_raise: Exception = PrivateAttr()
    _fail_attempts: int = PrivateAttr(default=1)

    def __init__(
        self, exception: Exception, fail_attempts: int = 1, **data: Any
    ) -> None:
        super().__init__(**data)
        self._exception_to_raise = exception
        self._fail_attempts = fail_attempts

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._attempt_count[0] += 1
        if self._attempt_count[0] <= self._fail_attempts:
            raise self._exception_to_raise
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FailThenSucceedModel":  # type: ignore[override]
        return self

    @property
    def attempt_count(self) -> int:
        return self._attempt_count[0]


def _build_retry_test_graph(
    fake_llm: BindableToolsFakeModel,
    *,
    with_retry: bool = True,
) -> Any:
    """Build a minimal GAIA agent graph for retry testing.

    Uses real GAIA production nodes and the real ``create_agent`` override.
    Checkpointer and store are always in-memory (retry behavior is
    independent of persistence backend).
    """
    pre_model_hooks: list[HookType] = [
        cast(HookType, filter_messages_node),
        cast(HookType, manage_system_prompts_node),
    ]
    builder = create_agent(
        llm=fake_llm,
        agent_name="retry_test_agent",
        tool_registry={},
        disable_retrieve_tools=True,
        initial_tool_ids=[],
        middleware=None,
        pre_model_hooks=pre_model_hooks,
        agent_retry_policy=_AGENT_RETRY_POLICY if with_retry else None,
    )
    return builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())


def _make_config() -> dict[str, Any]:
    return {"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestRetryPolicyEndToEnd:
    """End-to-end verification that _AGENT_RETRY_POLICY fires on the compiled graph."""

    async def test_retries_on_resource_exhausted_and_succeeds(self) -> None:
        """When the LLM raises ResourceExhausted once, the node retries and returns the response.

        This is the primary contract: a single transient 429/quota error must
        not surface to the caller. The agent should recover transparently.
        """
        fake_llm = FailThenSucceedModel(
            exception=ResourceExhausted("Simulated quota exceeded"),
            fail_attempts=1,
            responses=[AIMessage(content="Recovered after retry!")],
        )
        graph = _build_retry_test_graph(fake_llm, with_retry=True)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config=_make_config(),
        )

        ai_messages = [
            m for m in result["messages"] if isinstance(m, AIMessage) and m.content
        ]
        assert ai_messages, "Expected at least one non-empty AIMessage in the result"
        assert ai_messages[-1].content == "Recovered after retry!"
        assert fake_llm.attempt_count == 2, (
            f"Expected exactly 2 LLM invocations (1 fail + 1 succeed), "
            f"got {fake_llm.attempt_count}"
        )

    async def test_retries_twice_on_two_consecutive_failures(self) -> None:
        """With two consecutive ResourceExhausted errors, the node retries twice and succeeds.

        max_attempts=3 means the node is tried at most 3 times total.
        """
        fake_llm = FailThenSucceedModel(
            exception=ResourceExhausted("Simulated quota exceeded"),
            fail_attempts=2,
            responses=[AIMessage(content="Recovered on attempt 3!")],
        )
        graph = _build_retry_test_graph(fake_llm, with_retry=True)

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hello")]},
            config=_make_config(),
        )

        ai_messages = [
            m for m in result["messages"] if isinstance(m, AIMessage) and m.content
        ]
        assert ai_messages[-1].content == "Recovered on attempt 3!"
        assert fake_llm.attempt_count == 3, (
            f"Expected 3 LLM invocations (2 fail + 1 succeed), "
            f"got {fake_llm.attempt_count}"
        )

    async def test_non_retryable_exception_propagates_immediately(self) -> None:
        """ValueError is not in _LLM_RETRYABLE_EXCEPTIONS and must propagate on the first attempt.

        This validates the ``retry_on`` predicate: we should not blindly retry
        every exception — only known transient infrastructure errors.
        """
        fake_llm = FailThenSucceedModel(
            exception=ValueError("Bad input — logic error, do not retry"),
            fail_attempts=1,
            responses=[AIMessage(content="should not be returned")],
        )
        graph = _build_retry_test_graph(fake_llm, with_retry=True)

        with pytest.raises(ValueError, match="Bad input"):
            await graph.ainvoke(
                {"messages": [HumanMessage(content="hi")]},
                config=_make_config(),
            )

        assert fake_llm.attempt_count == 1, (
            f"Expected exactly 1 LLM invocation (no retry for ValueError), "
            f"got {fake_llm.attempt_count}"
        )

    async def test_without_retry_policy_exception_propagates_immediately(self) -> None:
        """Without a RetryPolicy, ResourceExhausted propagates on the first attempt.

        This is the control case: proves _AGENT_RETRY_POLICY is what enables
        the retry behaviour, not some other mechanism.
        """
        fake_llm = FailThenSucceedModel(
            exception=ResourceExhausted("Quota exceeded — no retry configured"),
            fail_attempts=1,
            responses=[AIMessage(content="should not be returned")],
        )
        graph = _build_retry_test_graph(fake_llm, with_retry=False)

        with pytest.raises(ResourceExhausted):
            await graph.ainvoke(
                {"messages": [HumanMessage(content="hi")]},
                config=_make_config(),
            )

        assert fake_llm.attempt_count == 1, (
            f"Expected exactly 1 LLM invocation (no retry policy), "
            f"got {fake_llm.attempt_count}"
        )

    async def test_exhausting_all_retries_raises(self) -> None:
        """With max_attempts=3, failing 3 times in a row re-raises the last exception.

        max_attempts=3 means 3 total attempts (1 original + 2 retries).
        After all 3 fail, the exception must bubble up.
        """
        fake_llm = FailThenSucceedModel(
            exception=ResourceExhausted("Persistent outage — no recovery"),
            fail_attempts=99,  # always fail
            responses=[AIMessage(content="unreachable")],
        )
        graph = _build_retry_test_graph(fake_llm, with_retry=True)

        with pytest.raises(ResourceExhausted, match="Persistent outage"):
            await graph.ainvoke(
                {"messages": [HumanMessage(content="hi")]},
                config=_make_config(),
            )

        assert fake_llm.attempt_count == 3, (
            f"Expected exactly 3 LLM invocations (max_attempts=3), "
            f"got {fake_llm.attempt_count}"
        )
