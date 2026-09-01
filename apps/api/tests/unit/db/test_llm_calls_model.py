"""Unit tests for the ``llm_calls`` ledger document and its thread-id split.

The ledger is the permanent, queryable record of every model call — it replaces
log-scraping, so it outlives any retention window. Two things must hold: it
never carries message text, and a wrapped executor thread resolves to the SAME
conversation id a comms call would, or the per-conversation cost query silently
splits one turn across two ids.
"""

from datetime import UTC, datetime

import pytest

from app.db.repositories.llm_calls import (
    LLMCallDocument,
    LLMCallUpdate,
    split_lane_thread,
)

CONVERSATION = "8f2a1c4e-0b3d-4a71-9c62-5d8e1f0a7b34"


def _doc(**overrides: object) -> LLMCallDocument:
    fields: dict[str, object] = {
        "created_at": datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        "agent_name": "comms_agent",
        "background": False,
        "charge_to_budget": True,
        "model_requested": "deepseek/deepseek-v4-flash",
        "cost_source": "table",
    }
    fields.update(overrides)
    return LLMCallDocument.model_validate(fields)


# --- split_lane_thread --------------------------------------------------------- #


def test_a_plain_conversation_thread_has_no_lane_wrapper() -> None:
    assert split_lane_thread(CONVERSATION) == (CONVERSATION, None)


def test_an_executor_thread_yields_the_bare_conversation_and_keeps_the_wrapper() -> None:
    """Both halves stay queryable: the bare id joins the executor's calls to the
    comms calls of the same turn, the wrapper answers "executor lane only"."""
    thread = f"executor_{CONVERSATION}"

    assert split_lane_thread(thread) == (CONVERSATION, thread)


def test_an_integration_executor_thread_strips_its_whole_prefix() -> None:
    thread = f"slack_executor_{CONVERSATION}"

    assert split_lane_thread(thread) == (CONVERSATION, thread)


# The thread-id shapes that actually occur, measured over 24h of production
# traffic. Every one is minted by a named constructor:
#   executor_<conv>                  subagent_runner.py:773  (EXECUTOR_THREAD_PREFIX)
#   <integration>_executor_<conv>    handoff_tools.py:507    (wraps the above)
#   spawn_<conv>_<tool_call_id>      subagent.py:334         (SPAWN_THREAD_PREFIX)
#   <conv>                           the conversation itself
_SPAWNED = f"spawn_{CONVERSATION}_call_08eb2a516389452cab3e68d9"


def test_a_spawned_subagent_thread_resolves_to_its_conversation() -> None:
    """Real prod value, verbatim. A spawn thread carries no ``executor_``, so it
    used to fall through as a plain conversation id — the ledger then recorded
    ``conversation_id = "spawn_<uuid>_call_<hex>"``, which joins to nothing and
    fragments that conversation's cost, with the lane invisible."""
    assert split_lane_thread(_SPAWNED) == (CONVERSATION, _SPAWNED)


def test_two_spawns_in_one_conversation_share_its_conversation_id() -> None:
    """The point of the fix: each spawn has its own thread (one per tool call)
    but they are all spend on the SAME turn, so a per-conversation cost query
    has to gather them."""
    first = f"spawn_{CONVERSATION}_call_08eb2a516389452cab3e68d9"
    second = f"spawn_{CONVERSATION}_call_f4e93cb7f6674ddba76a3de2"

    assert split_lane_thread(first).conversation_id == CONVERSATION
    assert split_lane_thread(second).conversation_id == CONVERSATION
    # ...and remain distinguishable as lanes.
    assert split_lane_thread(first).lane_thread != split_lane_thread(second).lane_thread


@pytest.mark.parametrize("integration", ["gmail", "todos", "googlecalendar", "todoist"])
def test_every_integration_executor_shape_seen_in_production(integration: str) -> None:
    """Regression guard on 99% of traffic: these are the wrapped shapes actually
    measured, and they must keep resolving exactly as before."""
    thread = f"{integration}_executor_{CONVERSATION}"

    assert split_lane_thread(thread) == (CONVERSATION, thread)


def test_a_thread_that_merely_starts_with_spawn_is_not_treated_as_wrapped() -> None:
    """The prefix alone is not the shape. A spawn thread always appends a tool
    call id, so a bare ``spawn_x`` is some other thread and splitting it would
    invent a conversation that does not exist."""
    assert split_lane_thread("spawn_abc") == ("spawn_abc", None)


def test_an_executor_thread_with_an_underscored_tail_is_left_whole() -> None:
    """The shape a reviewer proposed — ``<integration>_executor_<conv>_<hex>``
    — is not minted anywhere: the executor constructors append nothing after the
    conversation. Pinned so that if such a thread ever DOES appear it shows up
    as an unsplit id rather than a silently wrong one."""
    assert split_lane_thread(f"gmail_executor_{CONVERSATION}_deadbeef").lane_thread is None


def test_a_missing_thread_invents_no_conversation() -> None:
    assert split_lane_thread(None) == (None, None)
    assert split_lane_thread("") == (None, None)


def test_a_thread_that_merely_mentions_executor_is_not_treated_as_wrapped() -> None:
    """``executor_`` has to be the prefix of the id, not a substring of it —
    otherwise an unrelated thread name gets shredded into a fake conversation."""
    assert split_lane_thread("my_executor_notes_thread") == ("my_executor_notes_thread", None)


# --- the document ------------------------------------------------------------- #


def test_the_document_round_trips_every_field_it_was_given() -> None:
    doc = _doc(
        user_id="u1",
        model_served="deepseek/deepseek-v4",
        provider="fireworks",
        input_tokens=1200,
        cached_tokens=800,
        output_tokens=90,
        reasoning_tokens=40,
        cost_usd=0.0037,
        cost_source="provider",
        generation_id="gen-abc123",
        conversation_id=CONVERSATION,
        lane_thread=f"executor_{CONVERSATION}",
        root_request_id="req-1",
        workflow_id="wf-1",
        workflow_execution_id="exec_wf-1_ab12cd34",
        job_id="job-9",
        task_name="run_workflow",
        duration_ms=1843.5,
    )

    assert LLMCallDocument.model_validate(doc.model_dump()) == doc


def test_every_optional_identifier_defaults_to_none_rather_than_a_placeholder() -> None:
    """A system-lane call genuinely has no user and no conversation. Storing ""
    would make ``{"user_id": {"$ne": null}}`` count calls nobody made."""
    doc = _doc()

    assert doc.user_id is None
    assert doc.conversation_id is None
    assert doc.lane_thread is None
    assert doc.provider is None
    assert doc.model_served is None
    assert doc.generation_id is None
    assert doc.workflow_id is None
    assert doc.workflow_execution_id is None
    assert doc.job_id is None
    assert doc.task_name is None
    assert doc.duration_ms is None


def test_token_counts_and_cost_default_to_zero_not_none() -> None:
    """A call that reported no tokens spent no tokens — summing the ledger must
    not have to coalesce nulls."""
    doc = _doc()

    assert (doc.input_tokens, doc.cached_tokens, doc.output_tokens, doc.reasoning_tokens) == (
        0,
        0,
        0,
        0,
    )
    assert doc.cost_usd == 0.0


def test_the_document_declares_no_field_that_could_hold_message_text() -> None:
    """The ledger's one hard invariant. It is asserted on the field inventory
    rather than on an instance because the risk is a FUTURE field being added,
    not this test's own data."""
    banned = {
        "content",
        "text",
        "prompt",
        "prompt_preview",
        "completion",
        "completion_preview",
        "messages",
        "response",
        "output",
        "input",
        "query",
        "user_request",
    }

    assert banned & set(LLMCallDocument.model_fields) == set()


def test_the_ledger_is_append_only() -> None:
    """A recorded call is a historical fact; nothing edits one in place."""
    assert LLMCallUpdate.model_fields == {}

    with pytest.raises(ValueError):
        LLMCallUpdate.model_validate({"cost_usd": 1.0})


def test_an_unknown_cost_source_is_rejected() -> None:
    """``cost_source`` decides whether a row counts as provider-priced coverage;
    a third value would quietly be counted as neither."""
    with pytest.raises(ValueError):
        _doc(cost_source="guessed")
