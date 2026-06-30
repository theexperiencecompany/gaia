"""Smoke tests for the real agent-graph composition.

Every other graph/agent test mocks the middleware factory and create_agent away
(``create_comms_middleware`` -> ``[]``, ``create_agent`` -> a MagicMock builder), so
the real fraction-of-window middleware stack — summarization + compaction — is never
constructed under test. That blind spot let a regression ship green: the default
model lost the LangChain token profile those fractional triggers need, so
``build_comms_graph`` raised at runtime, ``GraphManager`` returned ``None``, and every
chat died with ``'NoneType' object has no attribute 'astream'``.

These tests build the REAL composition (real middleware + real ``create_agent``),
mocking only the external providers (LLM, tool store, tool registry, checkpointer),
so that class of failure is caught here instead of in production.
"""

from contextlib import ExitStack
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings

_BUILD = "app.agents.core.graph_builder.build_graph"


@pytest.fixture
def google_configured():
    """Enable the Gemini code paths. ChatGoogleGenerativeAI needs a key at
    construction (never used — no network here); ``GOOGLE_API_KEY`` gates
    ``get_default_llm`` / ``get_summarization_llm``."""
    import app.agents.middleware.factory as factory_mod

    prev = os.environ.get("GOOGLE_API_KEY")
    os.environ["GOOGLE_API_KEY"] = "test-key"  # pragma: allowlist secret
    factory_mod._summarization_llm = None  # drop any cached summarization model
    with patch.object(settings, "GOOGLE_API_KEY", "test-key"):  # pragma: allowlist secret
        yield
    factory_mod._summarization_llm = None
    if prev is None:
        os.environ.pop("GOOGLE_API_KEY", None)
    else:
        os.environ["GOOGLE_API_KEY"] = prev


def _mock_external_providers(stack: ExitStack) -> None:
    """Mock the graph's external dependencies (LLM, tool store/registry, checkpointer)
    while leaving ``create_agent`` and the middleware factory REAL — exercising the
    real composition is the whole point of these tests."""
    mock_llm = MagicMock()
    mock_llm.model_name = "test-model"
    targets = {
        f"{_BUILD}.init_llm": MagicMock(return_value=mock_llm),
        f"{_BUILD}.get_tools_store": AsyncMock(return_value=MagicMock()),
        f"{_BUILD}.get_tool_registry": AsyncMock(
            return_value=MagicMock(get_tool_dict=MagicMock(return_value={"tool_a": MagicMock()}))
        ),
        f"{_BUILD}.create_todo_tools": MagicMock(return_value=[]),
        f"{_BUILD}.create_todo_pre_model_hook": MagicMock(return_value=MagicMock()),
        f"{_BUILD}.build_executor_child_tool_runtime_config": MagicMock(return_value={}),
        f"{_BUILD}.get_retrieve_tools_function": MagicMock(return_value=AsyncMock()),
        f"{_BUILD}.get_checkpointer_manager": AsyncMock(return_value=None),
    }
    for target, mock in targets.items():
        stack.enter_context(patch(target, mock))


@pytest.mark.unit
def test_default_llm_carries_context_window_profile(google_configured):
    """Directly guards the fix: the default model must expose ``max_input_tokens`` so
    the fractional-token middleware can resolve the window without relying on
    LangChain's profile registry (which lags new model releases)."""
    from app.agents.llm.client import get_default_llm

    profile = getattr(get_default_llm(), "profile", None) or {}
    assert profile.get("max_input_tokens"), (
        "default model must carry max_input_tokens; without it the summarization/"
        "compaction middleware fail to build and the agent graph cannot be built"
    )


@pytest.mark.unit
async def test_comms_graph_builds_with_real_middleware(google_configured):
    """Build the REAL comms graph end-to-end (real middleware + real ``create_agent``
    + compile). This is the only test that exercises the full composition; it fails
    on the profile regression."""
    with ExitStack() as stack:
        _mock_external_providers(stack)
        from app.agents.core.graph_builder.build_graph import build_comms_graph

        async with build_comms_graph(in_memory_checkpointer=True) as graph:
            assert graph is not None


@pytest.mark.unit
def test_executor_middleware_stack_builds(google_configured):
    """The executor middleware stack must construct. Covers the executor-only
    ``SubagentMiddleware`` plus the summarization/compaction consumers that broke
    (the full executor graph build needs heavier provider mocking; the middleware
    stack is where the fraction-of-window risk lives)."""
    from app.agents.middleware.factory import create_executor_middleware

    names = {type(m).__name__ for m in create_executor_middleware()}
    assert "SubagentMiddleware" in names
    assert "WorkspaceArchivingSummarizationMiddleware" in names
    assert "WorkspaceCompactionMiddleware" in names
