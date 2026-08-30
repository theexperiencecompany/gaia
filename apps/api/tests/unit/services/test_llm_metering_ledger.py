"""The ``llm_calls`` ledger write, at the one seam every priced call passes through.

``record_llm_call`` is the single place a model call is priced and recorded, so
it is the single place the ledger row is built. These tests hold the three
things that make the ledger trustworthy: exactly one row per call, carrying the
call's real identity, and never carrying message text — plus the one thing that
makes it safe, which is that a Mongo failure costs a row and never the user's
turn.
"""

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.constants.log_tags import LogTag
from app.db.repositories.llm_calls import LLMCallDocument
from app.services import llm_metering
from app.services.llm_metering import (
    LLMCallContext,
    TokenUsage,
    extract_message_provider,
    record_llm_call,
)
from shared.py.wide_events import WorkflowContext, log

CONVERSATION = "8f2a1c4e-0b3d-4a71-9c62-5d8e1f0a7b34"

USAGE = TokenUsage(input_tokens=1200, output_tokens=90, cached_tokens=800, reasoning_tokens=40)

CONTEXT = LLMCallContext(
    agent_name="executor_agent",
    background=False,
    charge_to_budget=True,
    model_served="deepseek/deepseek-v4",
    provider="fireworks",
    generation_id="gen-abc123",
    conversation_id=CONVERSATION,
    thread_id=f"executor_{CONVERSATION}",
    workflow_id="wf-1",
    duration_ms=1843.5,
)


async def _drain() -> None:
    """Let the spawned fire-and-forget insert run to completion."""
    for _ in range(3):
        await asyncio.sleep(0)


async def _record(**overrides: Any) -> LLMCallDocument:
    """Run one metered call and return the ledger row it wrote."""
    kwargs: dict[str, Any] = {
        "user_id": "u1",
        "model_name": "deepseek/deepseek-v4-flash",
        "usage": USAGE,
        "root_request_id": "req-1",
        "provider_cost": 0.0037,
        "context": CONTEXT,
    }
    kwargs.update(overrides)
    with (
        patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock),
        patch.object(llm_metering.llm_calls_repository, "create", new_callable=AsyncMock) as create,
    ):
        await record_llm_call(**kwargs)
        await _drain()

    create.assert_awaited_once()
    doc = create.await_args.args[0]
    assert isinstance(doc, LLMCallDocument)
    return doc


async def test_one_metered_call_writes_exactly_one_ledger_row() -> None:
    doc = await _record()

    assert doc.user_id == "u1"
    assert doc.agent_name == "executor_agent"


async def test_the_row_carries_the_calls_whole_identity() -> None:
    doc = await _record()

    assert doc.model_dump(exclude={"id", "created_at"}) == {
        "user_id": "u1",
        "agent_name": "executor_agent",
        "background": False,
        "charge_to_budget": True,
        "model_requested": "deepseek/deepseek-v4-flash",
        "model_served": "deepseek/deepseek-v4",
        "provider": "fireworks",
        "input_tokens": 1200,
        "cached_tokens": 800,
        "output_tokens": 90,
        "reasoning_tokens": 40,
        "cost_usd": 0.0037,
        "cost_source": "provider",
        "generation_id": "gen-abc123",
        "conversation_id": CONVERSATION,
        "lane_thread": f"executor_{CONVERSATION}",
        "root_request_id": "req-1",
        "workflow_id": "wf-1",
        "workflow_execution_id": None,
        "job_id": None,
        "task_name": None,
        "duration_ms": 1843.5,
    }


async def test_the_row_holds_no_prompt_or_completion_text() -> None:
    """Asserted on the row that actually gets written, not just on the model:
    the ledger must never become a copy of the conversation."""
    doc = await _record()

    stored = doc.model_dump()
    assert not any(isinstance(value, str) and " " in value for value in stored.values())


async def test_a_table_priced_call_says_so() -> None:
    """``cost_source`` is what makes provider-price coverage measurable; a table
    guess recorded as a provider price would overstate coverage."""
    with patch("app.services.llm_metering.calculate_token_cost", return_value={"total_cost": 0.25}):
        doc = await _record(provider_cost=None)

    assert doc.cost_source == "table"
    assert doc.cost_usd == 0.25


async def test_a_call_with_no_user_or_conversation_records_nulls_not_placeholders() -> None:
    doc = await _record(
        user_id=None,
        root_request_id=None,
        context=LLMCallContext(
            agent_name="memory_extraction", background=True, charge_to_budget=False
        ),
    )

    assert doc.user_id is None
    assert doc.conversation_id is None
    assert doc.lane_thread is None
    assert doc.root_request_id is None
    assert doc.duration_ms is None
    assert doc.background is True
    assert doc.charge_to_budget is False


async def test_a_ledger_failure_never_fails_the_metered_call() -> None:
    """The one sanctioned silent degrade in this path. The money is already
    booked in Redis + usage_daily and the call is already on the wide event, so
    a Mongo blip must cost a row of analytics, not the user's reply."""
    with (
        patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock),
        patch.object(
            llm_metering.llm_calls_repository,
            "create",
            new_callable=AsyncMock,
            side_effect=RuntimeError("mongo is down"),
        ),
        patch.object(llm_metering.log, "warning") as warned,
    ):
        cost = await record_llm_call(
            user_id="u1",
            model_name="deepseek/deepseek-v4-flash",
            usage=USAGE,
            provider_cost=0.0037,
            context=CONTEXT,
        )
        await _drain()

    assert cost == 0.0037
    # The warning IS the record of the dropped row, so it has to name the call
    # that lost one and the failure that lost it — a bare "insert failed" cannot
    # be attributed to a lane, a model, or a cause.
    warned.assert_called_once()
    message, kwargs = warned.call_args.args[0], warned.call_args.kwargs
    # The whole line, not a substring: the second half is what tells the reader
    # the money was still booked, which is the difference between "we lost a row"
    # and "we lost a charge".
    assert message == (
        f"{LogTag.MONGO} llm_calls ledger insert failed — the call is still "
        "priced, budgeted and on the wide event; only its ledger row is missing"
    )
    assert kwargs == {
        "agent_name": "executor_agent",
        "model": "deepseek/deepseek-v4-flash",
        "error": "mongo is down",
        "error_type": "RuntimeError",
    }


# --- provider attribution ------------------------------------------------------ #


@pytest.mark.parametrize("reported", ["openrouter", "OpenRouter", "", None])
def test_the_aggregators_own_name_is_not_recorded_as_the_upstream(reported: str | None) -> None:
    """OpenRouter routes one model id across upstreams whose rates differ by more
    than 10x, so ``provider`` exists to tell them apart. Recording the aggregator
    would make every row claim the same provider and answer the question wrong."""
    message = AIMessage(content="hi", response_metadata={"provider": reported})

    assert extract_message_provider(message) is None


def test_a_real_upstream_name_is_recorded_verbatim() -> None:
    message = AIMessage(content="hi", response_metadata={"provider": "Fireworks"})

    assert extract_message_provider(message) == "Fireworks"


# --- worker / workflow attribution --------------------------------------------- #
#
# ``workflow_execution_id``, ``job_id`` and the task name exist only on the wide
# event's boundary — ARQ stamps the job identity in ``arq_task`` and the workflow
# task stamps its execution id — so they reach the ledger through that ContextVar
# rather than through ``config.configurable``. If that read breaks, "what did this
# workflow run cost" silently returns nothing and looks like an empty answer
# rather than a bug.


async def test_a_call_made_inside_a_worker_task_is_attributed_to_its_job_and_workflow_run() -> None:
    log.reset()
    log.set(
        task="run_workflow",
        job_id="job-9",
        workflow=WorkflowContext(id="wf-1", execution_id="exec_wf-1_ab12cd34"),
    )
    try:
        doc = await _record()
    finally:
        log.reset()

    assert doc.workflow_execution_id == "exec_wf-1_ab12cd34"
    assert doc.job_id == "job-9"
    assert doc.task_name == "run_workflow"


async def test_a_workflow_boundary_with_no_execution_id_yet_records_none() -> None:
    """A workflow event is stamped in stages; a call metered before the execution
    id lands must record its absence, not an empty-string id."""
    log.reset()
    log.set(task="run_workflow", workflow=WorkflowContext(id="wf-1"))
    try:
        doc = await _record()
    finally:
        log.reset()

    assert doc.workflow_execution_id is None
    assert doc.task_name == "run_workflow"
    assert doc.job_id is None


async def test_a_call_outside_any_boundary_invents_no_worker_identity() -> None:
    """An HTTP request path has no ARQ job and no workflow run. The fields are
    absent, never a fabricated id."""
    log.reset()
    try:
        doc = await _record()
    finally:
        log.reset()

    assert doc.workflow_execution_id is None
    assert doc.job_id is None
    assert doc.task_name is None


async def test_a_non_mapping_workflow_field_does_not_crash_the_metered_call() -> None:
    """``log.set`` takes arbitrary values, and some call sites stamp
    ``workflow=<id string>``. Reaching into that for ``execution_id`` would raise
    inside the metering path of a call that already succeeded."""
    log.reset()
    log.set(workflow="wf-1")
    try:
        doc = await _record()
    finally:
        log.reset()

    assert doc.workflow_execution_id is None


async def test_the_ledger_write_is_detached_from_the_users_turn() -> None:
    """The insert is spawned, not awaited: nothing downstream depends on it, and
    holding a turn open for a Mongo round-trip to write an analytics row would be
    paying user-visible latency for observability. The task is named so a stuck
    one is identifiable in a task dump rather than anonymous."""
    with (
        patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock),
        patch("app.services.llm_metering.spawn_background_task") as spawn,
    ):
        await record_llm_call(
            user_id="u1",
            model_name="deepseek/deepseek-v4-flash",
            usage=USAGE,
            provider_cost=0.0037,
            context=CONTEXT,
        )
        spawn.call_args.args[0].close()

    assert spawn.call_args.kwargs["name"] == "llm_calls_ledger_insert"


async def test_the_rows_timestamp_is_timezone_aware_utc() -> None:
    """``created_at`` is the TTL key. A naive datetime is interpreted as UTC by
    Mongo but compares wrong against every tz-aware value in the codebase, so a
    ledger query by time would silently skew by the server's offset."""
    doc = await _record()

    assert doc.created_at.tzinfo is not None
    assert doc.created_at.utcoffset() == timedelta(0)


async def test_a_child_lane_with_no_conversation_id_recovers_it_from_the_thread() -> None:
    """An executor run whose config carries only the wrapped thread still has to
    join its parent turn in the ledger. Without the fallback its calls land with
    no conversation and the turn's cost breakdown loses them."""
    doc = await _record(
        context=LLMCallContext(
            agent_name="executor_agent",
            background=False,
            charge_to_budget=True,
            thread_id=f"executor_{CONVERSATION}",
        )
    )

    assert doc.conversation_id == CONVERSATION
    assert doc.lane_thread == f"executor_{CONVERSATION}"
