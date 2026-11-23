"""A brief's in-app delivery: one Notice in the user's Briefings conversation, its edition as a card."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from tests.unit.services.conversation.runtime_doubles import USER, Runtime
import time_machine

from app.constants.briefing import BriefingKind
from app.constants.chat import ConversationSource
from app.db.repositories.conversations import conversation_repository
from app.models.brief_view_models import BriefCard
from app.models.chat_models import SystemPurpose
from app.models.conversation_log_models import Notice
from app.models.conversation_models import ConversationDocument, SystemConversationCreated
from app.services.briefing import conversation
from app.services.briefing.conversation import post_brief_message
from app.services.conversation.runtime import install_runtime_ports
from shared.py.conversation_wire import ToolDataEntry

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
EXISTING = "conv-briefings"
CREATED = "conv-new"
CARD = BriefCard(
    briefing_id="brief-1",
    date="2026-11-12",
    kind=BriefingKind.DAILY,
    headline="Your morning, sorted",
    edition=None,
    edition_name=None,
    stamp_city_name=None,
    needs_you_count=2,
)


@pytest.fixture
def runtime() -> Iterator[Runtime]:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    with time_machine.travel(NOW, tick=False):
        yield runtime


@pytest.fixture
def find() -> Iterator[AsyncMock]:
    existing = ConversationDocument(
        user_id=USER,
        conversation_id=EXISTING,
        description="Briefings",
        is_system_generated=True,
        system_purpose=SystemPurpose.BRIEFING,
        source=ConversationSource.WORKFLOW_SYSTEM,
    )
    with patch.object(
        conversation_repository,
        "find_system_conversation",
        AsyncMock(return_value=existing),
    ) as find:
        yield find


@pytest.fixture
def create() -> Iterator[AsyncMock]:
    created = SystemConversationCreated(
        conversation_id=CREATED,
        user_id=USER,
        description="Briefings",
        is_system_generated=True,
        system_purpose=SystemPurpose.BRIEFING,
        createdAt=NOW.isoformat(),
        detail="System conversation created successfully",
    )
    with patch.object(
        conversation, "create_system_conversation", AsyncMock(return_value=created)
    ) as create:
        yield create


async def _notices(runtime: Runtime, conversation_id: str) -> list[Notice]:
    entries = [logged.entry for logged in await runtime.log.read_after(conversation_id, USER, 0)]
    assert all(isinstance(entry, Notice) for entry in entries)
    return [entry for entry in entries if isinstance(entry, Notice)]


async def test_an_edition_is_logged_in_the_users_briefings_conversation_with_its_card(
    runtime: Runtime, find: AsyncMock, create: AsyncMock
) -> None:
    await post_brief_message(USER, "brief-1", "Two things wait on you.", CARD)

    find.assert_awaited_once_with(USER, SystemPurpose.BRIEFING)
    create.assert_not_awaited()
    assert await _notices(runtime, EXISTING) == [
        Notice(
            id="brief:brief-1",
            text="Two things wait on you.",
            origin="brief brief-1",
            tool_data=(
                ToolDataEntry(
                    tool_name="briefing_data",
                    data=CARD.model_dump(),
                    timestamp=NOW.isoformat(),
                ),
            ),
        )
    ]


async def test_a_quiet_note_is_its_text_alone(
    runtime: Runtime, find: AsyncMock, create: AsyncMock
) -> None:
    await post_brief_message(USER, "brief-2", "A quiet day.", None)

    assert await _notices(runtime, EXISTING) == [
        Notice(id="brief:brief-2", text="A quiet day.", origin="brief brief-2")
    ]


async def test_a_retried_delivery_logs_the_brief_once(
    runtime: Runtime, find: AsyncMock, create: AsyncMock
) -> None:
    await post_brief_message(USER, "brief-1", "Two things wait on you.", CARD)
    await post_brief_message(USER, "brief-1", "Two things wait on you.", CARD)

    assert [n.id for n in await _notices(runtime, EXISTING)] == ["brief:brief-1"]


async def test_a_user_with_no_briefings_conversation_gets_one_and_the_brief_lands_in_it(
    runtime: Runtime, find: AsyncMock, create: AsyncMock
) -> None:
    find.return_value = None

    await post_brief_message(USER, "brief-1", "Two things wait on you.", None)

    create.assert_awaited_once_with(USER, "Briefings", SystemPurpose.BRIEFING)
    assert [n.id for n in await _notices(runtime, CREATED)] == ["brief:brief-1"]
