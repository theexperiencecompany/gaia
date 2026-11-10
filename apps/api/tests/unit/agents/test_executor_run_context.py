"""A run started with no live turn still knows the user's surface and timezone.

Carry runs and approval-ticket runs are built from the user's id alone; what makes them
the user's run is the context the conversation's latest turn left on the conversation.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.agent import AgentRunOptions, _core_agent_logic
from app.agents.core.background import executor_runner as er
from app.constants.chat import SourceCategory
from app.constants.executor import EXECUTOR_CARRY_TASK
from app.db.repositories.conversations import conversation_repository
from app.models.conversation_models import ConversationRunContext
from app.models.hil_models import ApprovalLedgerDocument
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.hil import ledger_decide

pytestmark = pytest.mark.unit

CONVERSATION = "conv-ctx-1"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
WHATSAPP_CONTEXT = ConversationRunContext(
    conversation_source="whatsapp", user_timezone="Asia/Kolkata"
)


def _item_prepared(prepare: AsyncMock) -> dict[str, Any]:
    """Return the configurable of the run item the conversation's run was prepared from."""
    prepare.assert_awaited_once()
    return prepare.await_args.args[1]["configurable"]


@pytest.fixture
def stored_context() -> Any:
    with patch.object(
        conversation_repository,
        "get_run_context",
        AsyncMock(return_value=WHATSAPP_CONTEXT),
    ) as read:
        yield read


@pytest.fixture
def prepare() -> Any:
    with (
        patch.object(er, "prepare_run_from_item", AsyncMock(return_value=MagicMock())) as prepare,
        patch.object(er, "_spawn_detached_run"),
        patch.object(er, "reclaim_dead_lock", AsyncMock(return_value=True)),
    ):
        yield prepare


class TestACarryRunKnowsWhereTheUserIs:
    async def test_it_carries_the_stored_source_and_timezone(
        self, stored_context: AsyncMock, prepare: AsyncMock
    ) -> None:
        user = AuthenticatedUser(user_id=USER_ID, timezone="UTC")

        await er._start_executor_run(CONVERSATION, user, EXECUTOR_CARRY_TASK)

        configurable = _item_prepared(prepare)
        assert configurable["conversation_source"] == "whatsapp"
        assert configurable["source_category"] == SourceCategory.BOT.value
        assert configurable["user_timezone"] == "Asia/Kolkata"
        stored_context.assert_awaited_once_with(CONVERSATION, user_id=USER_ID)

    async def test_a_conversation_with_no_stored_context_keeps_what_the_caller_knew(
        self, prepare: AsyncMock
    ) -> None:
        user = AuthenticatedUser(user_id=USER_ID, timezone="Europe/Paris")
        with patch.object(
            conversation_repository,
            "get_run_context",
            AsyncMock(return_value=ConversationRunContext()),
        ):
            await er._start_executor_run(CONVERSATION, user, EXECUTOR_CARRY_TASK)

        configurable = _item_prepared(prepare)
        assert configurable["user_timezone"] == "Europe/Paris"
        assert "conversation_source" not in configurable
        assert "source_category" not in configurable


class TestAnApprovalTicketRunKnowsWhereTheUserIs:
    async def test_the_ticket_run_carries_the_stored_source_and_timezone(
        self, stored_context: AsyncMock, prepare: AsyncMock
    ) -> None:
        row = ApprovalLedgerDocument(
            approval_id="ap_1",
            conversation_id=CONVERSATION,
            user_id=USER_ID,
            fingerprint="fp",
            tool_name="GMAIL_SEND_EMAIL",
            args={"to": "b@x"},
            summary="Send it",
            owner_agent="gmail_conv-1",
            proposing_run_id="stream-1",
            v=3,
        )

        await ledger_decide._deliver_ticket(row)

        configurable = _item_prepared(prepare)
        assert configurable["conversation_source"] == "whatsapp"
        assert configurable["user_timezone"] == "Asia/Kolkata"
        assert configurable["user_id"] == USER_ID


class TestATurnLeavesItsContextOnTheConversation:
    @pytest.fixture
    def turn(self) -> Any:
        with (
            patch("app.agents.core.agent.construct_langchain_messages", AsyncMock(return_value=[])),
            patch("app.agents.core.agent.GraphManager.get_graph", AsyncMock()),
            patch("app.agents.core.agent.build_initial_state", return_value={}),
            patch("app.agents.core.agent.read_presence", AsyncMock(return_value=None)),
            patch(
                "app.agents.core.agent.conversation_repository.set_run_context",
                AsyncMock(return_value=True),
            ) as record,
        ):
            yield record

    async def _run_turn(self, user: AuthenticatedUser, source: str | None) -> None:
        request = MessageRequestWithHistory.model_validate(
            {"message": "hi", "messages": [{"role": "user", "content": "hi"}]}
        )
        await _core_agent_logic(request, CONVERSATION, user, AgentRunOptions(source=source))

    async def test_it_records_the_turns_surface_and_timezone(self, turn: AsyncMock) -> None:
        await self._run_turn(
            AuthenticatedUser(user_id=USER_ID, timezone="Asia/Kolkata"), "whatsapp"
        )

        turn.assert_awaited_once_with(
            CONVERSATION,
            user_id=USER_ID,
            conversation_source="whatsapp",
            user_timezone="Asia/Kolkata",
        )

    async def test_a_user_with_no_known_timezone_records_none_rather_than_utc(
        self, turn: AsyncMock
    ) -> None:
        await self._run_turn(AuthenticatedUser(user_id=USER_ID), "web")

        assert turn.await_args.kwargs["user_timezone"] is None
