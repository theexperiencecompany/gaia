"""PostHog's copy of the llm_calls ledger: one ai:llm_call_completed per stored row.

The ledger row is the cost of record (provider-reported where the provider
reports it, the rate card only where it does not), so the event is built from
the row and nothing else. No second emitter exists for any lane: graph,
auxiliary one-shot, browser, success or error all reach PostHog only here.
"""

from app.db.repositories.llm_calls import LLMCallDocument
from app.db.repositories.users import user_repository
from app.services.analytics_service import AIFeature, capture
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.agents import AiLlmCallCompleted
from shared.py.wide_events import log

#: The two graph tiers; any other ``agent_name`` is a per-integration subagent.
TIER_AGENT_NAMES = frozenset({"comms_agent", "executor_agent"})

#: Built at runtime as ``f"memory:{operation}"``, so it cannot be an exact key.
_MEMORY_LABEL_PREFIX = "memory:"


def feature_for_label(label: str) -> AIFeature:
    """Return which capability an auxiliary call served, from the label it carries."""
    if label.startswith(_MEMORY_LABEL_PREFIX):
        return AIFeature.MEMORY
    return AIFeature.for_label(label)


def llm_feature(agent_name: str, workflow_id: str | None, *, background: bool) -> AIFeature:
    """Return which capability a metered call served.

    Background calls are labelled one-shots. For the rest, workflow_id outranks
    the agent: a subagent running inside a workflow is workflow spend.
    """
    if background:
        return feature_for_label(agent_name)
    if workflow_id:
        return AIFeature.WORKFLOW
    if agent_name in TIER_AGENT_NAMES:
        return AIFeature.CHAT
    labelled = AIFeature.for_label(agent_name)
    return AIFeature.INTEGRATION if labelled is AIFeature.UNATTRIBUTED else labelled


def capture_llm_call(row: LLMCallDocument) -> None:
    """Emit ai:llm_call_completed for one stored ledger row, keyed by the row's id.

    A row with no real user (None, or a non-ObjectId such as "system") is logged
    instead: it would land on a person no human owns.
    """
    if row.user_id is None or not user_repository.is_valid_id(row.user_id):
        log.warning(
            "llm_call_unattributed",
            user_id=row.user_id,
            agent_name=row.agent_name,
            model=row.model_requested,
        )
        return

    feature = llm_feature(row.agent_name, row.workflow_id, background=row.background)
    if feature is AIFeature.UNATTRIBUTED:
        log.error("llm_call_unmapped_label", label=row.agent_name, model=row.model_requested)

    capture(
        UserId(row.user_id),
        AiLlmCallCompleted(
            feature=str(feature),
            agent_name=row.agent_name,
            background=row.background,
            charge_to_budget=row.charge_to_budget,
            model=row.model_requested,
            model_served=row.model_served,
            provider=row.provider,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cached_tokens=row.cached_tokens,
            reasoning_tokens=row.reasoning_tokens,
            total_tokens=row.input_tokens + row.output_tokens,
            cost_usd=row.cost_usd,
            cost_source=row.cost_source,
            status=row.status,
            error_family=row.error_family,
            finish_reason=row.finish_reason,
            duration_ms=row.duration_ms,
            channel=row.channel,
            generation_id=row.generation_id,
            conversation_id=row.conversation_id,
            workflow_id=row.workflow_id,
            llm_call_id=row.id,
        ),
        dedupe=Dedupe(key=row.id, occurred_at=row.created_at),
    )
