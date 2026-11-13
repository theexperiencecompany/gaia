"""A reply is matched to the ask it answers: the quoted message, else the latest message that asked in its chat."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.hil_models import ApprovalLedgerDocument, LedgerState
from app.services.hil.pending_ask import latest_approvals_in_chat, quoted_approvals

MODULE = "app.services.hil.pending_ask"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
CHAT = "tg-dm"


def _row(
    approval_id: str, state: LedgerState = LedgerState.PENDING, user_id: str = USER_ID
) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id="conv-1",
        user_id=user_id,
        fingerprint=f"fp-{approval_id}",
        tool_name="send_email",
        summary=approval_id,
        state=state,
    )


def _message(*report_ids: str, conversation_id: str = CHAT) -> SimpleNamespace:
    return SimpleNamespace(report_ids=list(report_ids), conversation_id=conversation_id)


@pytest.fixture
def stores():
    rows: dict[str, ApprovalLedgerDocument] = {}
    messages: dict[str, SimpleNamespace] = {}
    receipts: dict[str, list[str]] = {}
    latest: list[SimpleNamespace] = []

    async def get_row(approval_id: str) -> ApprovalLedgerDocument | None:
        return rows.get(approval_id)

    async def get_message(user_id: str, attempt_id: str) -> SimpleNamespace | None:
        return messages.get(attempt_id)

    async def outbox_ids(platform_message_id: str) -> list[str]:
        return receipts.get(platform_message_id, [])

    async def recent_in(user_id: str, conversation_id: str, *, limit: int) -> list[SimpleNamespace]:
        return [message for message in latest if message.conversation_id == conversation_id]

    with (
        patch(f"{MODULE}.approval_ledger_repository.get_by_approval_id", new=get_row),
        patch(f"{MODULE}.outbox_messages_repository.get_by_attempt", new=get_message),
        patch(f"{MODULE}.outbox_messages_repository.recent_sent_in", new=recent_in),
        patch(f"{MODULE}.outbound_receipts_repository.outbox_message_ids_of", new=outbox_ids),
    ):
        yield {"rows": rows, "messages": messages, "receipts": receipts, "latest": latest}


class TestQuotedApprovals:
    async def test_the_quoted_message_names_its_open_approvals(self, stores) -> None:
        stores["rows"].update({"ap_old": _row("ap_old"), "ap_new": _row("ap_new")})
        stores["messages"]["att-old"] = _message("hil:ap_old:pending")
        stores["receipts"]["wamid-old"] = ["att-old"]

        rows = await quoted_approvals(USER_ID, "wamid-old")

        assert [row.approval_id for row in rows] == ["ap_old"]

    async def test_a_reply_that_quotes_nothing_names_nothing(self, stores) -> None:
        assert await quoted_approvals(USER_ID, None) == []

    async def test_a_quote_of_something_that_asked_nothing_names_nothing(self, stores) -> None:
        stores["messages"]["att-chat"] = _message("ask:t1:s1")
        stores["receipts"]["wamid-chat"] = ["att-chat"]

        assert await quoted_approvals(USER_ID, "wamid-chat") == []


class TestLatestApprovalsInChat:
    async def test_the_latest_message_that_asked_in_the_chat_is_the_target(self, stores) -> None:
        stores["rows"].update({"ap_old": _row("ap_old"), "ap_new": _row("ap_new")})
        stores["latest"].extend([_message("hil:ap_new:pending"), _message("hil:ap_old:pending")])

        rows = await latest_approvals_in_chat(USER_ID, CHAT)

        assert [row.approval_id for row in rows] == ["ap_new"]

    async def test_an_ask_sent_to_another_chat_is_never_the_target(self, stores) -> None:
        stores["rows"]["ap_web"] = _row("ap_web")
        stores["latest"].append(_message("hil:ap_web:pending", conversation_id="web-1"))

        assert await latest_approvals_in_chat(USER_ID, CHAT) == []

    async def test_a_latest_message_whose_asks_were_answered_is_skipped_for_an_older_open_one(
        self, stores
    ) -> None:
        stores["rows"].update(
            {"ap_done": _row("ap_done", LedgerState.APPROVED), "ap_open": _row("ap_open")}
        )
        stores["latest"].extend([_message("hil:ap_done:pending"), _message("hil:ap_open:pending")])

        rows = await latest_approvals_in_chat(USER_ID, CHAT)

        assert [row.approval_id for row in rows] == ["ap_open"]

    async def test_a_message_that_asked_several_returns_them_in_the_order_told(
        self, stores
    ) -> None:
        stores["rows"].update({"ap_1": _row("ap_1"), "ap_2": _row("ap_2")})
        stores["latest"].append(_message("hil:ap_1:pending", "hil:ap_2:pending"))

        rows = await latest_approvals_in_chat(USER_ID, CHAT)

        assert [row.approval_id for row in rows] == ["ap_1", "ap_2"]

    async def test_another_users_approval_is_never_a_target(self, stores) -> None:
        stores["rows"]["ap_x"] = _row("ap_x", user_id="someone-else")
        stores["latest"].append(_message("hil:ap_x:pending"))

        assert await latest_approvals_in_chat(USER_ID, CHAT) == []

    async def test_nothing_asked_means_no_target(self, stores) -> None:
        assert await latest_approvals_in_chat(USER_ID, CHAT) == []
