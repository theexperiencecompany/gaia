"""The ``llm_calls`` ledger write, at the one seam every priced call passes through.

``record_llm_call`` is the single place a model call is priced and recorded, so
it is the single place the ledger row is built. These tests hold the three
things that make the ledger trustworthy: exactly one row per call, carrying the
call's real identity, and never carrying message text — plus the one thing that
makes it safe, which is that a Mongo failure costs a row and never the user's
turn.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from openrouter.errors import (
    BadRequestResponseError,
    RequestTimeoutResponseError,
    ServiceUnavailableResponseError,
    TooManyRequestsResponseError,
)
import pytest

from app.constants.llm import PROVIDER_NAME_METADATA_KEY
from app.constants.log_tags import LogTag
from app.db.repositories.llm_calls import LLMCallDocument
from app.services import llm_metering
from app.services.llm_metering import (
    LLMCallContext,
    TokenUsage,
    classify_error_family,
    extract_finish_reason,
    extract_message_provider,
    record_llm_call,
    resolve_channel,
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
    finish_reason="stop",
    channel="web",
)


@pytest.fixture(autouse=True)
def _fresh_wide_event() -> None:
    """Start every test from a clean wide-event boundary.

    The ledger reads its worker/workflow attribution from that ContextVar, so a
    stamp left behind by any earlier test in this process would be attributed to
    a call that never ran inside it — which is exactly the mis-attribution these
    tests exist to catch.
    """
    log.reset()


def _served_by(upstream: str) -> AIMessage:
    """A reply carrying the upstream name the provider-name patch restores."""
    return AIMessage(content="hi", response_metadata={PROVIDER_NAME_METADATA_KEY: upstream})


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
        "channel": "web",
        "duration_ms": 1843.5,
        "finish_reason": "stop",
        "status": "ok",
        "error_family": None,
        # A live row is written once, so it carries no backfill identity.
        "backfilled": False,
        "backfill_key": None,
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
    message = AIMessage(content="hi", response_metadata={PROVIDER_NAME_METADATA_KEY: reported})

    assert extract_message_provider(message) is None


@pytest.mark.parametrize("upstream", ["Baidu", "StreamLake", "Fireworks"])
def test_the_upstream_the_patch_restored_is_recorded_verbatim(upstream: str) -> None:
    """``openrouter_provider_name_patch`` puts the real serving upstream on the
    reply under ``PROVIDER_NAME_METADATA_KEY``; ChatOpenRouter itself drops it.
    Reading that key is what turns ``provider`` from a column that was always
    null into the one that makes the >10x per-upstream rate spread queryable."""
    message = AIMessage(content="hi", response_metadata={PROVIDER_NAME_METADATA_KEY: upstream})

    assert extract_message_provider(message) == upstream


def test_a_reply_the_patch_never_stamped_records_no_upstream() -> None:
    """Non-OpenRouter lanes (direct Gemini, the sim lane) never carry the key.
    Absent is recorded as absent, never guessed from the model id."""
    assert extract_message_provider(AIMessage(content="hi")) is None
    assert extract_message_provider(AIMessage(content="hi", response_metadata={})) is None


async def test_the_ledger_row_records_the_upstream_that_served_the_call() -> None:
    """End to end through the metering seam: the name the patch stamped is what
    lands in the row, so ``group by provider`` over the ledger answers which
    upstream the money actually went to."""
    doc = await _record(
        context=replace(CONTEXT, provider=extract_message_provider(_served_by("StreamLake")))
    )

    assert doc.provider == "StreamLake"


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


# --- which surface the call came from ------------------------------------------ #


@pytest.mark.parametrize(
    "source", ["web", "desktop", "mobile", "discord", "slack", "telegram", "whatsapp", "imessage"]
)
def test_the_surface_the_turn_came_from_is_recorded_verbatim(source: str) -> None:
    """``conversation_source`` is set by the entry point — the chat endpoint's
    ``X-Client-Type`` header or the bot endpoint's platform — and inherited by
    every child agent, so an executor call reports its root turn's surface."""
    assert resolve_channel({"conversation_source": source}) == source


def test_a_workflow_run_is_its_own_channel() -> None:
    """Background runs have nobody to attribute a surface to, so they are told
    apart by what they do carry. A workflow is the one background lane whose
    cost anyone asks about by name."""
    assert resolve_channel({"source_category": "bg", "workflow_id": "wf-1"}) == "workflow"


def test_other_background_work_is_system() -> None:
    assert resolve_channel({"source_category": "bg"}) == "system"


def test_background_work_with_no_surface_is_system() -> None:
    """The documented rule. Live, 11 background rows (memory:*, chatbot) came
    out ``null`` instead — their configurable carries neither a source nor a
    source_category, so the rule never applied and COGS-by-channel could not
    account for them at all."""
    assert resolve_channel({}, background=True) == "system"
    assert resolve_channel({"user_id": "u1"}, background=True) == "system"


def test_a_call_inside_an_executor_run_keeps_the_turns_surface() -> None:
    """Live defect: a comms/follow-up call made INSIDE an executor run was
    labelled ``system`` though the turn came from web. The executor opens its
    own wide-event boundary, and an auxiliary call there gets a bare config —
    so the surface has to come from the boundary the run stamped, or
    COGS-by-channel under-counts web on exactly the expensive turns."""
    log.reset()
    log.set(conversation_source="web")
    try:
        assert resolve_channel({}, background=False) == "web"
    finally:
        log.reset()


def test_the_runs_own_configurable_still_wins_over_the_boundary() -> None:
    """The boundary is a fallback, not an override: a nested call that DOES know
    its own surface must not be relabelled with the enclosing run's."""
    log.reset()
    log.set(conversation_source="web")
    try:
        assert resolve_channel({"conversation_source": "discord"}) == "discord"
    finally:
        log.reset()


def test_a_bag_with_no_surface_at_all_records_none() -> None:
    """Auxiliary one-shots built from a bare ``{"user_id": ...}`` config have no
    originating surface. None is the honest answer, not a default."""
    assert resolve_channel({}) is None
    assert resolve_channel({"user_id": "u1"}) is None


def test_an_explicit_surface_wins_over_the_background_derivation() -> None:
    """A workflow that was kicked off from a real surface keeps that surface —
    the derivation is a fallback for runs nobody started interactively."""
    assert resolve_channel({"conversation_source": "discord", "workflow_id": "wf-1"}) == "discord"


# --- why the provider stopped -------------------------------------------------- #


def test_the_finish_reason_is_read_from_the_streamed_reply() -> None:
    """ChatOpenRouter merges generation_info into response_metadata on the
    streaming path, which is every graph call."""
    message = AIMessage(content="hi", response_metadata={"finish_reason": "length"})

    assert extract_finish_reason(message) == "length"


def test_the_native_finish_reason_is_the_fallback() -> None:
    """The non-streaming path leaves ``finish_reason`` in generation_info, which
    never reaches an AIMessage — only the upstream's own value is copied on."""
    message = AIMessage(content="hi", response_metadata={"native_finish_reason": "STOP"})

    assert extract_finish_reason(message) == "STOP"


def test_a_reply_that_says_nothing_about_stopping_records_none() -> None:
    assert extract_finish_reason(AIMessage(content="hi")) is None
    assert extract_finish_reason(AIMessage(content="hi", response_metadata={})) is None


# --- how a failed call is classified ------------------------------------------- #
#
# By exception TYPE, never message text: provider messages embed model ids,
# request ids and prompt fragments, they change without notice, and grouping a
# dashboard on them yields a long tail instead of the buckets an operator acts on.


@pytest.mark.parametrize(
    ("error", "family"),
    [
        (TimeoutError("deadline"), "timeout"),
        (ConnectionError("refused"), "provider_unavailable"),
        (ValueError("a bug in our own code"), "other"),
    ],
)
def test_a_failure_is_bucketed_by_its_type(error: BaseException, family: str) -> None:
    assert classify_error_family(error) == family


def test_two_failures_of_one_family_with_different_messages_group_together() -> None:
    """The property that makes the field usable: message text varies per call,
    the bucket must not."""
    assert classify_error_family(TimeoutError("model X timed out after 30s")) == (
        classify_error_family(TimeoutError("request 9f2a exceeded deadline"))
    )


async def test_a_failed_call_books_no_money_and_no_tokens() -> None:
    """The attempts did burn tokens upstream, but nothing reported them. A
    guessed number would sit in the same column real spend is summed from."""
    with (
        patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock) as paid,
        patch.object(llm_metering.llm_calls_repository, "create", new_callable=AsyncMock) as create,
    ):
        await llm_metering.record_failed_llm_call(
            user_id="u1",
            model_name="deepseek/deepseek-v4-flash",
            error=TimeoutError("no answer"),
            context=replace(CONTEXT, duration_ms=1200.0),
        )
        await _drain()

    doc = create.await_args.args[0]
    assert doc.status == "error"
    assert doc.error_family == "timeout"
    assert (doc.cost_usd, doc.input_tokens, doc.output_tokens) == (0.0, 0, 0)
    # All four counts, not just the two that are usually non-zero: a cached or
    # reasoning number invented here would be summed as real usage.
    assert (doc.cached_tokens, doc.reasoning_tokens) == (0, 0)
    # Latency to the failure is the whole point — a slow failure and a fast one
    # are different incidents.
    assert doc.duration_ms == 1200.0
    # The budget and the durable rollup are untouched: nothing was spent.
    paid.assert_not_awaited()


# Provider exception types, instantiated without their constructors: the real
# ones need an httpx response and a parsed body, and the classifier reads only
# the TYPE — which is the whole point of classifying on it rather than on text.
_RATE_LIMITED = TooManyRequestsResponseError.__new__(TooManyRequestsResponseError)
_BAD_REQUEST = BadRequestResponseError.__new__(BadRequestResponseError)
_UPSTREAM_DOWN = ServiceUnavailableResponseError.__new__(ServiceUnavailableResponseError)
_UPSTREAM_TIMEOUT = RequestTimeoutResponseError.__new__(RequestTimeoutResponseError)


def test_a_provider_throttling_us_is_its_own_family() -> None:
    """The one failure that is our fault to fix (back off, spread load) rather
    than the upstream's — it must not be lumped in with the outages."""
    assert classify_error_family(_RATE_LIMITED) == "rate_limit"


def test_a_rejected_request_is_not_an_outage() -> None:
    """A 400 means we sent something wrong; nothing upstream is down. Counting
    it as unavailability sends an incident response after a bug."""
    assert classify_error_family(_BAD_REQUEST) == "invalid_request"


def test_an_upstream_outage_is_provider_unavailable() -> None:
    assert classify_error_family(_UPSTREAM_DOWN) == "provider_unavailable"


def test_an_upstream_timeout_is_a_timeout_not_an_outage() -> None:
    """Both are unavailability in the broad sense, and the specific answer is
    the useful one — which is why the checks are ordered."""
    assert classify_error_family(_UPSTREAM_TIMEOUT) == "timeout"


async def test_the_error_row_carries_the_calls_identity_like_any_other() -> None:
    """An error row that could not be filtered by conversation, lane or surface
    would be a count with nothing to drill into."""
    with (
        patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock),
        patch.object(llm_metering.llm_calls_repository, "create", new_callable=AsyncMock) as create,
    ):
        await llm_metering.record_failed_llm_call(
            user_id="u1",
            model_name="deepseek/deepseek-v4-flash",
            error=_RATE_LIMITED,
            context=CONTEXT,
        )
        await _drain()

    doc = create.await_args.args[0]
    assert doc.error_family == "rate_limit"
    assert doc.agent_name == "executor_agent"
    assert doc.conversation_id == CONVERSATION
    assert doc.channel == "web"
    assert doc.model_requested == "deepseek/deepseek-v4-flash"
    # No provider answered, so nothing can claim a provider price.
    assert doc.cost_source == "table"


async def test_a_failed_call_is_never_charged_to_the_user() -> None:
    """Whatever the context said, a call that produced nothing cannot count
    against an allowance."""
    with (
        patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock),
        patch.object(llm_metering.llm_calls_repository, "create", new_callable=AsyncMock) as create,
    ):
        await llm_metering.record_failed_llm_call(
            user_id="u1",
            model_name="m",
            error=TimeoutError("x"),
            context=replace(CONTEXT, charge_to_budget=True),
        )
        await _drain()

    assert create.await_args.args[0].root_request_id is None


async def test_a_ledger_failure_on_an_error_row_still_does_not_raise() -> None:
    """The degrade rule applies to error rows too — an outage must not be made
    worse by the code that records it."""
    with (
        patch.object(
            llm_metering.llm_calls_repository,
            "create",
            new_callable=AsyncMock,
            side_effect=RuntimeError("mongo is down"),
        ),
        patch.object(llm_metering.log, "warning") as warned,
    ):
        await llm_metering.record_failed_llm_call(
            user_id="u1", model_name="m", error=TimeoutError("x"), context=CONTEXT
        )
        await _drain()

    warned.assert_called_once()


async def test_the_error_rows_insert_is_named_for_what_it_is() -> None:
    """Named distinctly from the success insert so a stuck or failing error-row
    task is identifiable in a task dump rather than anonymous."""
    with patch("app.services.llm_metering.spawn_background_task") as spawn:
        await llm_metering.record_failed_llm_call(
            user_id="u1", model_name="m", error=TimeoutError("x"), context=CONTEXT
        )
        spawn.call_args.args[0].close()

    assert spawn.call_args.kwargs["name"] == "llm_calls_ledger_error_insert"


async def test_the_error_row_is_booked_against_the_user_whose_call_failed() -> None:
    """A failure with no user attached cannot answer "who is this failing for"."""
    with (
        patch.object(llm_metering.llm_calls_repository, "create", new_callable=AsyncMock) as create,
    ):
        await llm_metering.record_failed_llm_call(
            user_id="u-42", model_name="m", error=TimeoutError("x"), context=CONTEXT
        )
        await _drain()

    assert create.await_args.args[0].user_id == "u-42"


# --- a failure is an event too --------------------------------------------------- #
#
# DECIDED: failed calls emit an ``llm_call`` wide event, same as successful ones.
# Live evidence made the case: 4 failed POSTs produced 0 log lines and 2 ledger
# rows, so the failures existed in exactly one place. That breaks two things —
# the ledger stops being reconstructable from Loki (the backfill reads log
# lines, so failures could never be recovered), and an operator grepping
# ``llm_event=llm_call`` during an incident sees the traffic drop rather than
# the errors. Parity is cheaper than two sources of truth that disagree.


async def test_a_failed_call_emits_a_wide_event_like_any_other_call() -> None:
    with (
        patch.object(llm_metering.llm_calls_repository, "create", new_callable=AsyncMock),
        patch.object(llm_metering.log, "info") as emitted,
    ):
        await llm_metering.record_failed_llm_call(
            user_id="u1",
            model_name="deepseek/deepseek-v4-flash",
            error=TimeoutError("no answer"),
            context=replace(CONTEXT, duration_ms=1200.0),
        )
        await _drain()

    emitted.assert_called_once()
    fields = emitted.call_args.kwargs
    assert fields["llm_event"] == "llm_call"
    assert fields["status"] == "error"
    assert fields["error_family"] == "timeout"
    assert fields["agent_name"] == "executor_agent"
    assert fields["model"] == "deepseek/deepseek-v4-flash"
    assert fields["user_id"] == "u1"
    assert fields["duration_ms"] == 1200.0


async def test_the_failure_event_books_no_spend() -> None:
    """It has to be summable alongside the success events without inflating
    anything — a failed call cost us nothing we can account for."""
    with (
        patch.object(llm_metering.llm_calls_repository, "create", new_callable=AsyncMock),
        patch.object(llm_metering.log, "info") as emitted,
    ):
        await llm_metering.record_failed_llm_call(
            user_id="u1", model_name="m", error=TimeoutError("x"), context=CONTEXT
        )
        await _drain()

    fields = emitted.call_args.kwargs
    assert fields["cost_usd"] == 0.0
    assert (fields["input_tokens"], fields["output_tokens"]) == (0, 0)
