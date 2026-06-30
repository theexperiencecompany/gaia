"""Smoke tests for the real agent-graph composition.

Every other graph/agent test mocks the middleware factory
(``create_comms_middleware`` / ``create_executor_middleware`` -> ``[]``), so the
real middleware stack — summarization + compaction, which trigger on a FRACTION of
the model's context window — is never constructed under test. That blind spot let a
regression ship: the default model lost the LangChain token profile the fractional
triggers need, so the whole comms/executor graph failed to build at runtime (the
graph provider returned ``None`` and every chat died with
``'NoneType' object has no attribute 'astream'``).

These tests build the real stack so that class of failure is caught here instead of
in production.
"""

import os
from unittest.mock import patch

import pytest

from app.config.settings import settings


@pytest.fixture
def _google_configured():
    """Enable the Gemini code paths. ChatGoogleGenerativeAI requires a key at
    construction (never used — no network here), and ``GOOGLE_API_KEY`` gates
    ``get_default_llm`` / ``get_summarization_llm``."""
    import app.agents.middleware.factory as factory_mod

    prev_env = os.environ.get("GOOGLE_API_KEY")
    os.environ["GOOGLE_API_KEY"] = "test-key"  # pragma: allowlist secret
    factory_mod._summarization_llm = None  # drop any cached summarization model
    with patch.object(settings, "GOOGLE_API_KEY", "test-key"):  # pragma: allowlist secret
        yield
    factory_mod._summarization_llm = None
    if prev_env is None:
        os.environ.pop("GOOGLE_API_KEY", None)
    else:
        os.environ["GOOGLE_API_KEY"] = prev_env


@pytest.mark.unit
def test_default_llm_carries_context_window_profile(_google_configured):
    """The default model must expose ``max_input_tokens`` so fractional-token
    middleware can resolve the window without LangChain's profile registry."""
    from app.agents.llm.client import get_default_llm

    profile = getattr(get_default_llm(), "profile", None) or {}
    assert profile.get("max_input_tokens"), (
        "default model must carry max_input_tokens; without it the summarization/"
        "compaction middleware (fractional-token triggers) fail and the agent graph "
        "cannot be built"
    )


@pytest.mark.unit
def test_real_comms_and_executor_middleware_build(_google_configured):
    """Build the real middleware stacks (mocked everywhere else). A model
    profile/window regression fails here instead of at production graph build."""
    from app.agents.middleware.factory import (
        create_comms_middleware,
        create_executor_middleware,
    )

    comms = {type(m).__name__ for m in create_comms_middleware()}
    executor = {type(m).__name__ for m in create_executor_middleware()}

    # The two fraction-of-window consumers that broke must construct successfully.
    assert "WorkspaceArchivingSummarizationMiddleware" in comms
    assert "WorkspaceCompactionMiddleware" in comms
    assert "WorkspaceArchivingSummarizationMiddleware" in executor
    assert "WorkspaceCompactionMiddleware" in executor
