"""Unit tests for app/services/llm_usage_analytics.py.

Two seams, two jobs: the properties stamped onto PostHog's existing
``$ai_generation`` for agent-graph calls, and the one new event for background
calls PostHog never sees. The PostHog *client* is mocked, never
``capture_event`` itself — attributing an event to the wrong ``distinct_id`` is
the failure mode that matters, and mocking the helper would hide it.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.constants.llm import DEFAULT_MODEL_NAME
from app.services.analytics_service import AIFeature, AnalyticsEvents
from app.services.llm_usage_analytics import (
    capture_auxiliary_llm_call,
    graph_call_properties,
    llm_feature,
)


@pytest.fixture
def posthog() -> Any:
    client = MagicMock()
    with patch(
        "app.services.analytics_service._get_posthog_client",
        return_value=client,
    ):
        yield client


def _captured(posthog: Any) -> dict[str, Any]:
    return dict(posthog.capture.call_args.kwargs)


# --- llm_feature -------------------------------------------------------------- #


def test_a_workflow_run_is_workflow_spend() -> None:
    assert llm_feature("executor_agent", "wf-1") is AIFeature.WORKFLOW


def test_a_graph_tier_without_a_workflow_is_chat() -> None:
    assert llm_feature("comms_agent", None) is AIFeature.CHAT
    assert llm_feature("executor_agent", None) is AIFeature.CHAT


def test_a_subagent_is_integration_spend() -> None:
    assert llm_feature("gmail_agent", None) is AIFeature.INTEGRATION


def test_a_subagent_inside_a_workflow_is_still_workflow_spend() -> None:
    """The workflow asked for it; Gmail merely executed it. ``agent_name``
    carries the second half, so nothing is lost."""
    assert llm_feature("gmail_agent", "wf-9") is AIFeature.WORKFLOW


# --- graph_call_properties ---------------------------------------------------- #


def test_graph_properties_carry_feature_and_surface() -> None:
    props = graph_call_properties("comms_agent", "web", None)
    assert props == {"feature": "chat", "surface": "ui"}


def test_graph_properties_carry_the_workflow_when_there_is_one() -> None:
    props = graph_call_properties("executor_agent", None, "wf-7")
    assert props["feature"] == "workflow"
    assert props["workflow_id"] == "wf-7"


def test_a_bot_turn_reports_the_bot_surface() -> None:
    assert graph_call_properties("comms_agent", "discord", None)["surface"] == "bot"


def test_an_unset_source_reports_background() -> None:
    """The only callers that leave the source blank are the silent background
    paths, so 'unknown' would be a worse answer than 'bg'."""
    assert graph_call_properties("executor_agent", None, None)["surface"] == "bg"


# --- capture_auxiliary_llm_call ----------------------------------------------- #


def _capture(user_id: str | None = "user-1", **overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "feature": AIFeature.MEMORY,
        "label": "memory:extract",
        "model_name": DEFAULT_MODEL_NAME,
        "input_tokens": 3000,
        "output_tokens": 150,
        "cached_tokens": 400,
        "reasoning_tokens": 20,
        "cost_usd": 0.00036,
    }
    capture_auxiliary_llm_call(**{**kwargs, **overrides})


def test_the_event_is_attributed_to_the_gaia_user_id(posthog: Any) -> None:
    _capture(user_id="mongo-user-42")
    call = _captured(posthog)
    assert call["distinct_id"] == "mongo-user-42"
    assert call["event"] == AnalyticsEvents.AI_LLM_CALL_COMPLETED


def test_the_event_carries_the_tokens_cost_and_attribution(posthog: Any) -> None:
    _capture()
    props = _captured(posthog)["properties"]
    assert props["feature"] == "memory"
    assert props["label"] == "memory:extract"
    assert props["input_tokens"] == 3000
    assert props["output_tokens"] == 150
    assert props["cached_tokens"] == 400
    assert props["reasoning_tokens"] == 20
    assert props["total_tokens"] == 3150
    assert props["cost_usd"] == 0.00036


def test_background_spend_is_never_marked_charged(posthog: Any) -> None:
    """Auxiliary work is deliberately not billed to the user's budget, so an
    event claiming otherwise would overstate what they consumed."""
    _capture()
    props = _captured(posthog)["properties"]
    assert props["charged"] is False
    assert props["surface"] == "bg"


def test_a_call_with_no_user_is_skipped_not_left_anonymous(posthog: Any) -> None:
    _capture(user_id=None)
    posthog.capture.assert_not_called()


def test_a_priced_model_is_not_flagged_as_estimated(posthog: Any) -> None:
    _capture(model_name=DEFAULT_MODEL_NAME)
    assert _captured(posthog)["properties"]["cost_estimated"] is False


def test_a_model_missing_from_the_rate_card_is_flagged(posthog: Any) -> None:
    """An unpriced model does not raise — it is silently charged
    DEFAULT_PRICING, so the dollar figure looks plausible and is wrong."""
    _capture(model_name="some/model-nobody-priced")
    assert _captured(posthog)["properties"]["cost_estimated"] is True


def test_the_event_is_not_deduped(posthog: Any) -> None:
    """A retried task re-invokes the provider, so a second event is a second
    real charge. Collapsing them would under-report spend."""
    _capture()
    assert "uuid" not in _captured(posthog)


def test_the_event_carries_no_message_content(posthog: Any) -> None:
    _capture()
    assert set(_captured(posthog)["properties"]) == {
        "feature",
        "surface",
        "label",
        "model",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "total_tokens",
        "cost_usd",
        "charged",
        "cost_estimated",
        "timestamp",
    }
