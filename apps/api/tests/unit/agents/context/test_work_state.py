"""The work-state block comms reads each turn: the user's wider picture, in labels and never internals."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from tests._harness.judge import notice

from app.agents.context.section_context import ExecutionMode, SectionContext
from app.agents.context.tiers import AgentTier
from app.agents.context.work_state import build_work_state_block
from app.constants.todos import WaitingOn
from app.constants.work_state import (
    WORK_STATE_LIST_MAX,
    WORK_STATE_TOLD_ELSEWHERE_MAX,
    WORK_STATE_TOLD_EXCERPT_CHARS,
)
from app.models.hil_models import ApprovalLedgerDocument, LedgerState
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.todo_models import TodoDocument
from app.services.outbox.models import ComposeMode, ItemState, MessageState, UrgencyClass

pytestmark = pytest.mark.unit

MODULE = "app.agents.context.work_state"
USER = "6812f0b3c9a14e2b7d5a91cc"
CHAT = "chat-1"
RUNNING_LINE = "Background work is running right now (task_id: t1)."
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _ctx(execution_mode: ExecutionMode = "interactive") -> SectionContext:
    return SectionContext(
        tier=AgentTier.COMMS, user_id=USER, conversation_id=CHAT, execution_mode=execution_mode
    )


def _todo(title: str, *, waiting_on: WaitingOn | None = None, question: str | None = None) -> Any:
    return TodoDocument(
        user_id=USER, title=title, labels=["gaia"], waiting_on=waiting_on, question=question
    )


def _approval(summary: str, state: LedgerState = LedgerState.PENDING) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id="appr-secret-id",
        conversation_id=CHAT,
        user_id=USER,
        fingerprint="fp",
        tool_name="GMAIL_SEND_EMAIL",
        summary=summary,
        state=state,
    )


def _untold(label: str, state: ItemState) -> OutboxItemDocument:
    return OutboxItemDocument(
        user_id=USER,
        report_id=f"r-{label}",
        report=notice(
            report_id=f"r-{label}",
            subject={"kind": "todo_run", "id": "run-secret-id", "label": label},
        ),
        state=state,
        expires_at=NOW,
    )


def _told(text: str, *, recorded_in: list[str]) -> OutboxMessageDocument:
    return OutboxMessageDocument(
        user_id=USER,
        compose_attempt_id="a",
        report_ids=[],
        state=MessageState.SENT,
        mode=ComposeMode.ANSWER,
        max_class=UrgencyClass.ROUTINE,
        parts=[text],
        destination="chat_app",
        destination_basis="owner_chat",
        conversation_id="whatsapp-dm",
        recorded_in=recorded_in,
        sent_at=NOW,
        expires_at=NOW,
    )


@contextmanager
def _world(
    *,
    todos: list[TodoDocument] | None = None,
    approvals: list[ApprovalLedgerDocument] | None = None,
    untold: list[OutboxItemDocument] | None = None,
    told: list[OutboxMessageDocument] | None = None,
) -> Iterator[SimpleNamespace]:
    reads = SimpleNamespace(
        todos=AsyncMock(return_value=todos or []),
        approvals=AsyncMock(return_value=approvals or []),
        untold=AsyncMock(return_value=untold or []),
        told=AsyncMock(return_value=told or []),
    )
    with ExitStack() as stack:
        stack.enter_context(
            patch(f"{MODULE}.build_executor_status_block", AsyncMock(return_value=RUNNING_LINE))
        )
        stack.enter_context(
            patch(f"{MODULE}.todo_repository.find_running_tracked_for_user", reads.todos)
        )
        stack.enter_context(
            patch(f"{MODULE}.approval_ledger_repository.list_open", reads.approvals)
        )
        stack.enter_context(patch(f"{MODULE}.outbox_items_repository.list_unsettled", reads.untold))
        stack.enter_context(patch(f"{MODULE}.outbox_messages_repository.sent_since", reads.told))
        yield reads


async def test_a_user_with_nothing_beside_the_chat_gets_only_the_running_state() -> None:
    with _world():
        assert await build_work_state_block(_ctx()) == RUNNING_LINE


async def test_the_wider_picture_is_labels_in_the_users_words_never_ids_or_tools() -> None:
    with _world(
        todos=[
            _todo("Morning briefing"),
            _todo("Pick the venue", waiting_on=WaitingOn.USER, question="Which of the two?"),
        ],
        approvals=[_approval("Send the intro email to Priya")],
        untold=[_untold("Inbox desk", ItemState.QUEUED)],
        told=[_told("Your flight dropped to 210", recorded_in=["whatsapp-dm"])],
    ):
        block = await build_work_state_block(_ctx())

    assert block == (
        f"{RUNNING_LINE}\n\n"
        "Ongoing follow-ups you keep for them:\n- Morning briefing\n\n"
        "Waiting on the user:\n- Send the intro email to Priya\n- Pick the venue: Which of the two?\n\n"
        "Results the user has not been told yet:\n"
        "- Inbox desk (info): finished, waiting for a good moment to tell\n\n"
        "Told on another surface recently:\n1. Your flight dropped to 210"
    )
    for internal in ("appr-secret-id", "run-secret-id", "gmail_send_email", "todo"):
        assert internal not in block.lower()


async def test_an_approval_already_decided_is_not_waiting_on_the_user() -> None:
    with _world(approvals=[_approval("Send it", state=LedgerState.APPROVED)]):
        assert await build_work_state_block(_ctx()) == RUNNING_LINE


async def test_a_background_turn_has_nobody_to_answer_so_it_reads_only_what_is_running() -> None:
    with _world(todos=[_todo("Morning briefing")]) as reads:
        block = await build_work_state_block(_ctx("background"))

    assert block == RUNNING_LINE
    reads.todos.assert_not_awaited()


async def test_a_message_recorded_in_this_chat_is_not_told_elsewhere() -> None:
    with _world(
        told=[
            _told("already in this thread", recorded_in=[CHAT, "whatsapp-dm"]),
            _told("only on whatsapp", recorded_in=["whatsapp-dm"]),
        ]
    ):
        block = await build_work_state_block(_ctx())

    assert "only on whatsapp" in block
    assert "already in this thread" not in block


async def test_every_list_is_bounded() -> None:
    long_text = "x" * (WORK_STATE_TOLD_EXCERPT_CHARS + 50)
    with _world(
        todos=[_todo(f"follow-up {i}") for i in range(WORK_STATE_LIST_MAX + 3)],
        told=[
            _told(long_text, recorded_in=["whatsapp-dm"])
            for _ in range(WORK_STATE_TOLD_ELSEWHERE_MAX + 2)
        ],
    ):
        block = await build_work_state_block(_ctx())

    assert block.count("- follow-up") == WORK_STATE_LIST_MAX
    told_lines = [line for line in block.splitlines() if line[:1].isdigit()]
    assert len(told_lines) == WORK_STATE_TOLD_ELSEWHERE_MAX
    assert all(len(line) <= WORK_STATE_TOLD_EXCERPT_CHARS + 3 for line in told_lines)


async def test_a_source_that_cannot_be_read_leaves_the_running_state_and_says_so_loudly() -> None:
    with _world() as reads, patch(f"{MODULE}.log") as log:
        reads.untold.side_effect = ConnectionError("mongo down")

        block = await build_work_state_block(_ctx())

    assert block == RUNNING_LINE
    log.error.assert_called_once()
    assert log.error.call_args.kwargs["error_type"] == "ConnectionError"
