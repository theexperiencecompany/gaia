"""The attribution dimensions PostHog's LLM analytics cannot derive itself.

PostHog's LangChain callback handler already emits $ai_generation with tokens
and cost for every agent-graph call, but not what the spend was for, and it
never sees the one-shots that run outside a graph. This module adds properties
to that existing event and emits a separate one for those one-shots. Graph
calls deliberately get no second event, which would double-count cost.
"""

from app.config.model_pricing import has_rate_card
from app.models.chat_models import SourceCategory
from app.services.analytics_service import AIFeature, AnalyticsEvents, capture_event
from app.services.llm_metering import TokenUsage
from shared.py.wide_events import log

#: The two graph tiers; any other ``agent_name`` is a per-integration subagent.
TIER_AGENT_NAMES = frozenset({"comms_agent", "executor_agent"})

#: Built at runtime as ``f"memory:{operation}"``, so it cannot be an exact key.
_MEMORY_LABEL_PREFIX = "memory:"


def llm_feature(agent_name: str, workflow_id: str | None) -> AIFeature:
    """Return which capability an agent-graph call served.

    workflow_id outranks the subagent check: a subagent running inside a
    workflow is workflow spend, and agent_name still carries which one.
    """
    if workflow_id:
        return AIFeature.WORKFLOW
    if agent_name in TIER_AGENT_NAMES:
        return AIFeature.CHAT
    return AIFeature.INTEGRATION


def feature_for_label(label: str) -> AIFeature:
    """Return which capability an auxiliary call served, from the label it carries."""
    if label.startswith(_MEMORY_LABEL_PREFIX):
        return AIFeature.MEMORY
    return AIFeature.for_label(label)


def graph_call_properties(
    agent_name: str,
    source: str | None,
    workflow_id: str | None,
) -> dict[str, str]:
    """Build the feature/surface/workflow properties stamped onto $ai_generation."""
    properties = {
        "feature": str(llm_feature(agent_name, workflow_id)),
        "surface": SourceCategory.from_source(source).value,
    }
    if workflow_id:
        properties["workflow_id"] = workflow_id
    return properties


def capture_auxiliary_llm_call(
    user_id: str | None,
    label: str,
    model_name: str,
    usage: TokenUsage,
    cost_usd: float,
) -> None:
    """Emit ai:llm_call_completed for one call made outside an agent graph.

    user_id is passed explicitly because these run with no request context for
    the contextvar identity to read; a call without one is skipped.
    """
    if user_id is None:
        log.warning("llm_call_unattributed", label=label, model=model_name)
        return

    feature = feature_for_label(label)
    if feature is AIFeature.UNATTRIBUTED:
        log.error("llm_call_unmapped_label", label=label, model=model_name)

    capture_event(
        user_id,
        AnalyticsEvents.AI_LLM_CALL_COMPLETED,
        {
            "feature": str(feature),
            "surface": SourceCategory.BG.value,
            "label": label,
            "model": model_name,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cached_tokens": usage["cached_tokens"],
            "reasoning_tokens": usage["reasoning_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
            "cost_usd": cost_usd,
            "charged": False,
            # Unpriced models fall back to DEFAULT_PRICING rather than raising,
            # so the figure is plausible and wrong.
            "cost_estimated": not has_rate_card(model_name),
        },
    )
