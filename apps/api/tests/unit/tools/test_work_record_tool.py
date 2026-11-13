"""read_work_record: comms reads what its work did, scoped to this conversation and bounded."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.work_record_tool import (
    NO_CONVERSATION,
    NO_WORK_RECORDED,
    read_work_record,
)
from app.constants.run_trace import WORK_RECORD_DETAIL_CHARS
from app.models.run_trace_models import (
    CallEffect,
    CallStatus,
    RunCallDocument,
    RunDocument,
    RunState,
)
from app.services.executor_trace.reader import CallDetail

pytestmark = pytest.mark.unit

MODULE = "app.agents.tools.work_record_tool"
USER = "6812f0b3c9a14e2b7d5a91cc"
CONVERSATION = "conv-1"
AT = datetime(2026, 11, 13, 9, 30, tzinfo=UTC)
CONFIG = {"configurable": {"thread_id": CONVERSATION, "user_id": USER}}


def _run(run_id: str = "r1") -> RunDocument:
    return RunDocument(
        user_id=USER,
        run_id=run_id,
        conversation_id=CONVERSATION,
        state=RunState.FINISHED,
        started_at=AT,
        last_activity_at=AT,
    )


def _call(call_id: str = "c1") -> RunCallDocument:
    return RunCallDocument(
        user_id=USER,
        run_id="r1",
        call_id=call_id,
        tool_name="GMAIL_SEND_EMAIL",
        effect=CallEffect.WRITE,
        status=CallStatus.OK,
        started_at=AT,
        finished_at=AT,
        summary="to=priya@example.com",
        payload_ref="p1",
    )


async def _read(call_id: str | None = None) -> str:
    return await read_work_record.ainvoke({"call_id": call_id}, config=CONFIG)


async def test_without_a_call_id_it_lists_the_conversations_runs_and_their_calls() -> None:
    with (
        patch(f"{MODULE}.list_conversation_runs", AsyncMock(return_value=[_run()])) as runs,
        patch(f"{MODULE}.list_run_calls", AsyncMock(return_value=[_call()])),
    ):
        text = await _read()

    assert text == (
        "Run finished, started 2026-11-13T09:30+00:00:\n"
        "[c1] write GMAIL_SEND_EMAIL ok: to=priya@example.com"
    )
    assert runs.await_args.args == (USER, CONVERSATION)


async def test_a_conversation_with_no_runs_says_so() -> None:
    with patch(f"{MODULE}.list_conversation_runs", AsyncMock(return_value=[])):
        assert await _read() == NO_WORK_RECORDED


async def test_a_call_id_returns_that_calls_input_and_output_found_in_a_later_run() -> None:
    detail = CallDetail(
        call=_call(), input_json='{"body": "see you at 5"}', output_text="sent", truncated=False
    )
    with (
        patch(f"{MODULE}.list_conversation_runs", AsyncMock(return_value=[_run("r2"), _run("r1")])),
        patch(
            f"{MODULE}.get_call_detail",
            AsyncMock(side_effect=lambda user, run, call: detail if run == "r1" else None),
        ),
    ):
        text = await _read("c1")

    assert '"body": "see you at 5"' in text and "Output:\nsent" in text
    assert "cut" not in text


async def test_a_call_that_is_not_recorded_here_is_not_invented() -> None:
    with (
        patch(f"{MODULE}.list_conversation_runs", AsyncMock(return_value=[_run()])),
        patch(f"{MODULE}.get_call_detail", AsyncMock(return_value=None)),
    ):
        assert await _read("nope") == "No call nope is recorded here."


async def test_a_long_call_is_cut_and_says_so() -> None:
    detail = CallDetail(
        call=_call(),
        input_json="{}",
        output_text="x" * (WORK_RECORD_DETAIL_CHARS + 10),
        truncated=False,
    )
    with (
        patch(f"{MODULE}.list_conversation_runs", AsyncMock(return_value=[_run()])),
        patch(f"{MODULE}.get_call_detail", AsyncMock(return_value=detail)),
    ):
        text = await _read("c1")

    assert text.endswith("(cut: the stored call was longer)")
    assert len(text.split("Output:\n")[1].split("\n(cut")[0]) == WORK_RECORD_DETAIL_CHARS


async def test_a_run_with_no_conversation_reads_nothing() -> None:
    assert (
        await read_work_record.ainvoke(
            {"call_id": None}, config={"configurable": {"user_id": USER}}
        )
        == NO_CONVERSATION
    )
