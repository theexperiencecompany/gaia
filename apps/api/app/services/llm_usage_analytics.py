"""The dimensions PostHog's LLM analytics cannot work out for itself.

``posthog.ai.langchain.CallbackHandler`` already emits ``$ai_generation`` for
every call inside an agent graph, with its own token counts and cost. It does
not know what the spend was *for*, where it came *from*, or which workflow
asked for it, and it never sees the auxiliary one-shots that run outside a
graph. This module fills exactly those two gaps and nothing else:

- :func:`graph_call_properties` — extra properties for that existing handler,
  so the graph route stays ONE event.
- :func:`capture_auxiliary_llm_call` — the only new event, for background spend
  the handler is never attached to.

Deliberately not a second event for graph calls: two events over the same calls
would double-count cost, and PostHog already prices that half.
"""

from app.config.model_pricing import has_rate_card
from app.models.chat_models import SourceCategory
from app.services.analytics_service import AIFeature, AnalyticsEvents, capture_event
from shared.py.wide_events import log

#: The two graph tiers. Any other ``agent_name`` is a per-integration subagent,
#: which is what makes integration spend separable.
TIER_AGENT_NAMES = frozenset({"comms_agent", "executor_agent"})


def llm_feature(agent_name: str, workflow_id: str | None) -> AIFeature:
    """Which capability an agent-graph call served.

    ``workflow_id`` wins over the subagent check on purpose: a Gmail subagent
    running inside a workflow is workflow spend that Gmail happens to execute,
    and ``agent_name`` still carries the second half.
    """
    if workflow_id:
        return AIFeature.WORKFLOW
    if agent_name in TIER_AGENT_NAMES:
        return AIFeature.CHAT
    return AIFeature.INTEGRATION


def graph_call_properties(
    agent_name: str,
    source: str | None,
    workflow_id: str | None,
) -> dict[str, str]:
    """The feature/surface/workflow properties to stamp onto ``$ai_generation``."""
    properties = {
        "feature": str(llm_feature(agent_name, workflow_id)),
        "surface": SourceCategory.from_source(source).value,
    }
    if workflow_id:
        properties["workflow_id"] = workflow_id
    return properties


def capture_auxiliary_llm_call(
    *,
    user_id: str | None,
    feature: AIFeature,
    label: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    reasoning_tokens: int,
    cost_usd: float,
) -> None:
    """Emit ``ai:llm_call_completed`` for one background call.

    Auxiliary one-shots (memory, onboarding, follow-ups, title generation) run
    outside any agent graph, so PostHog's own LLM analytics never sees them and
    their spend is invisible. ``user_id`` is explicit because these run outside
    a request context, where the contextvar identity would attribute the event
    to nobody; a call with no user is skipped rather than left anonymous.
    """
    if user_id is None:
        log.warning("llm_call_unattributed", feature=str(feature), label=label, model=model_name)
        return

    capture_event(
        user_id,
        AnalyticsEvents.AI_LLM_CALL_COMPLETED,
        {
            "feature": str(feature),
            "surface": SourceCategory.BG.value,
            "label": label,
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": cost_usd,
            "charged": False,
            # A model missing from the rate card is priced at DEFAULT_PRICING
            # rather than raising, so the dollar figure is plausible and wrong.
            "cost_estimated": not has_rate_card(model_name),
        },
    )
