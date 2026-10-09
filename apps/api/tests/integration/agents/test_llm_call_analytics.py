"""What PostHog sees for one model call made through the real comms graph.

The ledger row record_llm_call writes is the cost of record (it matches
OpenRouter's own totals within 0.5%). PostHog used to see graph calls only
through its LangChain callback ($ai_generation): a copy per nested run, priced
by PostHog's own table. Here the run is built the production way
(build_agent_config, build_comms_graph, the real middleware and metering), and
only the seams are fake: the model, Mongo, Redis and the PostHog client.
"""

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId
from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.core.graph_builder.build_graph import build_comms_graph
from app.agents.middleware import accounting
from app.constants.analytics import POSTHOG_PROVIDER_KEY
from app.core.lazy_loader import providers
from app.db.repositories.llm_calls import LLMCallDocument
from app.helpers.agent_helpers import AgentIdentity, build_agent_config
from app.services import llm_metering
from app.services.analytics_service import AnalyticsEvents
from app.services.cost_budget import BudgetCheck
from tests.helpers import BindableToolsFakeModel
from tests.integration.agents.test_comms_agent_flow import (
    _common_patches,
    _make_chroma_store_mock,
)

_PROVIDER_COST = 0.0123
_LEDGER_ROW_ID = "6a40d2f0c1b2a3d4e5f60718"


def _reply() -> AIMessage:
    """Build a provider reply carrying usage and OpenRouter's reported cost."""
    return AIMessage(
        content="Hello there.",
        usage_metadata={"input_tokens": 1200, "output_tokens": 40, "total_tokens": 1240},
        response_metadata={"cost": _PROVIDER_COST, "model_name": "served-model", "id": "gen-1"},
    )


async def _store(doc: LLMCallDocument) -> LLMCallDocument:
    return doc.model_copy(update={"id": _LEDGER_ROW_ID})


def _posthog_or(real: Callable[[str], Any], posthog_answer: object) -> Callable[[str], Any]:
    """Answer the PostHog key with posthog_answer and every other provider for real."""
    return lambda key: posthog_answer if key == POSTHOG_PROVIDER_KEY else real(key)


async def _run_one_turn(posthog: MagicMock, ledger: AsyncMock) -> None:
    """Run one comms turn whose single model call is answered by _reply."""
    user_id = str(ObjectId())
    patches = _common_patches(_make_chroma_store_mock())
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patch.object(providers, "get", side_effect=_posthog_or(providers.get, posthog)),
        patch.object(
            providers,
            "is_available",
            side_effect=_posthog_or(providers.is_available, True),
        ),
        patch.object(
            accounting,
            "get_budget_stop_reason",
            AsyncMock(return_value=BudgetCheck(None, None, None)),
        ),
        patch.object(llm_metering, "record_model_call_usage", AsyncMock()),
        patch.object(llm_metering.llm_calls_repository, "create", ledger),
    ):
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=str(uuid4()),
                user={"user_id": user_id, "email": "t@example.com", "name": "T"},
                agent_name="comms_agent",
            ),
        )
        fake_llm = BindableToolsFakeModel(responses=[_reply()])
        async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
            await graph.ainvoke({"messages": [HumanMessage(content="hi")]}, config)
        await asyncio.gather(
            *(t for t in asyncio.all_tasks() if t.get_name() == "llm_calls_ledger_insert")
        )


def _captured(posthog: MagicMock) -> list[dict[str, Any]]:
    return [dict(call.kwargs) for call in posthog.capture.call_args_list]


@pytest.mark.integration
@pytest.mark.regression
async def test_a_graph_call_emits_exactly_one_completed_event_carrying_the_ledger_cost() -> None:
    posthog = MagicMock()
    ledger = AsyncMock(side_effect=_store)

    await _run_one_turn(posthog, ledger)

    ledger.assert_awaited_once()
    row: LLMCallDocument = ledger.await_args.args[0]
    completed = [
        c for c in _captured(posthog) if c["event"] == AnalyticsEvents.AI_LLM_CALL_COMPLETED
    ]
    assert len(completed) == 1
    assert completed[0]["properties"]["cost_usd"] == row.cost_usd == _PROVIDER_COST
    assert completed[0]["distinct_id"] == row.user_id


@pytest.mark.integration
@pytest.mark.regression
async def test_a_graph_call_reaches_posthog_through_no_second_emitter() -> None:
    """The LangChain callback's $ai_generation was a second copy per nested run, at PostHog's price."""
    posthog = MagicMock()

    await _run_one_turn(posthog, AsyncMock(side_effect=_store))

    assert [c["event"] for c in _captured(posthog)] == [AnalyticsEvents.AI_LLM_CALL_COMPLETED]
