"""The "Where the user is" section: where the user is now, where they came from, and where GAIA's output lands."""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AnyMessage
import pytest
from tests._harness.context_chain import (
    FIXED_NOW,
    AgentTier,
    ContextSeed,
    effective_context,
    message_in_slot,
    text_of,
)
from tests._harness.context_snapshot import assert_snapshot
from tests._harness.context_sources import ContextSources, fake_context_sources
import time_machine

from app.agents.context import fetchers
from app.agents.context.section_context import ExecutionMode, SectionContext
from app.agents.context.sections import SECTIONS
from app.agents.context.slots import PromptSlot
from app.agents.core import agent as agent_module
from app.models.chat_models import ConversationSource
from app.models.message_models import MessageRequestWithHistory
from app.models.presence_models import PresenceSnapshot
from app.models.user_models import AuthenticatedUser
from app.services.delivery.chat_channel import ChatChannel

NOW = int(FIXED_NOW.timestamp())
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
MINUTE, HOUR, DAY = 60, 60 * 60, 24 * 60 * 60

TELEGRAM_RECENT = ChatChannel(
    source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="recent_activity"
)
WHATSAPP_BY_ORDER = ChatChannel(
    source=ConversationSource.WHATSAPP, platform_user_id="wa-1", basis="priority"
)
LATER = (
    'Anything you send later on your own (reminders, workflow results, "keep me posted" updates)'
)


def _seen(**ages: int) -> PresenceSnapshot:
    return {"captured_at": NOW, "last_seen": {surface: NOW - age for surface, age in ages.items()}}


async def _render(
    *,
    source: str | None,
    presence: PresenceSnapshot | None,
    channel: ChatChannel | None = TELEGRAM_RECENT,
    execution_mode: ExecutionMode = "interactive",
    tier: AgentTier = AgentTier.COMMS,
) -> str:
    ctx = SectionContext(
        tier=tier,
        user_id="user-1",
        source=source,
        presence=presence,
        execution_mode=execution_mode,
    )
    resolve = AsyncMock(return_value=channel)
    with (
        time_machine.travel(FIXED_NOW, tick=False),
        patch.object(fetchers, "resolve_chat_channel", resolve),
    ):
        return await fetchers.build_presence_block(ctx)


@pytest.mark.unit
class TestInteractiveTurnOnABotPlatform:
    async def test_a_switch_names_where_they_came_from(self) -> None:
        rendered = await _render(
            source="telegram", presence=_seen(web=25 * MINUTE, whatsapp=3 * DAY)
        )

        assert rendered == (
            "Where the user is:\n"
            "- Now: Telegram (this message). Your reply lands in this Telegram chat.\n"
            "- They switched here from Web, where they last wrote 25 min ago.\n"
            "- Also seen: WhatsApp 3 days ago.\n"
            f"- {LATER} goes to Telegram (their most recent chat app)."
        )

    async def test_staying_on_the_same_platform_names_no_switch(self) -> None:
        rendered = await _render(source="telegram", presence=_seen(telegram=MINUTE, web=2 * DAY))

        assert rendered == (
            "Where the user is:\n"
            "- Now: Telegram (this message). Your reply lands in this Telegram chat.\n"
            "- Also seen: Web 2 days ago.\n"
            f"- {LATER} goes to Telegram (their most recent chat app)."
        )

    async def test_the_executor_is_told_comms_delivers_its_result(self) -> None:
        """The executor never writes into the chat itself; its result reaches it through comms."""
        rendered = await _render(
            source="telegram", presence=_seen(web=25 * MINUTE), tier=AgentTier.EXECUTOR
        )

        assert rendered.splitlines()[1] == (
            "- The user is chatting with you on Telegram; comms delivers your result there."
        )

    async def test_a_surface_left_outside_the_active_window_is_not_a_switch(self) -> None:
        rendered = await _render(source="telegram", presence=_seen(web=3 * HOUR + 1))

        assert rendered == (
            "Where the user is:\n"
            "- Now: Telegram (this message). Your reply lands in this Telegram chat.\n"
            "- Also seen: Web 3 h ago.\n"
            f"- {LATER} goes to Telegram (their most recent chat app)."
        )

    async def test_a_surface_left_at_the_edge_of_the_window_is_a_switch(self) -> None:
        rendered = await _render(source="telegram", presence=_seen(web=3 * HOUR))

        assert rendered.splitlines()[2] == (
            "- They switched here from Web, where they last wrote 3 h ago."
        )


@pytest.mark.unit
class TestInteractiveTurnInTheApp:
    async def test_a_web_turn_names_the_app_and_the_chat_app_target(self) -> None:
        rendered = await _render(source="web", presence=_seen(telegram=12 * MINUTE))

        assert rendered == (
            "Where the user is:\n"
            "- Now: Web (this message). Your reply shows in the GAIA app.\n"
            "- They switched here from Telegram, where they last wrote 12 min ago.\n"
            f"- {LATER} goes to Telegram (their most recent chat app)."
        )

    async def test_a_target_picked_by_order_says_so(self) -> None:
        rendered = await _render(
            source="desktop", presence=_seen(desktop=30), channel=WHATSAPP_BY_ORDER
        )

        assert rendered == (
            "Where the user is:\n"
            "- Now: Desktop (this message). Your reply shows in the GAIA app.\n"
            f"- {LATER} goes to WhatsApp (first in their chat order)."
        )

    async def test_no_usable_chat_app_means_only_the_app(self) -> None:
        rendered = await _render(source="web", presence=None, channel=None)

        assert rendered == (
            "Where the user is:\n"
            "- Now: Web (this message). Your reply shows in the GAIA app.\n"
            f"- {LATER} only shows in the GAIA app."
        )


@pytest.mark.unit
class TestBackgroundRun:
    async def test_lists_last_seen_and_where_the_result_goes(self) -> None:
        rendered = await _render(
            source=None,
            presence=_seen(telegram=12 * MINUTE, web=2 * DAY),
            execution_mode="background",
        )

        assert rendered == (
            "Where the user is:\n"
            "- They are not in a chat with you right now.\n"
            "- Last seen: Telegram 12 min ago, Web 2 days ago.\n"
            "- If this run messages the user, it goes to Telegram (their most recent chat app)."
        )

    async def test_no_usable_chat_app_means_it_only_shows_in_the_app(self) -> None:
        rendered = await _render(
            source=None, presence=_seen(web=HOUR), channel=None, execution_mode="background"
        )

        assert rendered.splitlines()[3] == (
            "- If this run messages the user, it only shows in the GAIA app."
        )

    async def test_a_chat_source_on_a_background_run_is_still_background(self) -> None:
        rendered = await _render(
            source="telegram", presence=_seen(telegram=3 * HOUR), execution_mode="background"
        )

        assert rendered.splitlines()[1] == "- They are not in a chat with you right now."
        assert rendered.splitlines()[2] == "- Last seen: Telegram 3 h ago."

    async def test_nothing_seen_and_no_chat_renders_nothing(self) -> None:
        resolve = AsyncMock(return_value=TELEGRAM_RECENT)
        with patch.object(fetchers, "resolve_chat_channel", resolve):
            rendered = await fetchers.build_presence_block(
                SectionContext(tier=AgentTier.EXECUTOR, user_id="user-1", presence=None)
            )

        assert rendered == ""
        resolve.assert_not_awaited()


@pytest.mark.unit
class TestAges:
    @pytest.mark.parametrize(
        ("age", "expected"),
        [
            (0, "just now"),
            (2 * MINUTE - 1, "just now"),
            (2 * MINUTE, "2 min ago"),
            (HOUR - 1, "59 min ago"),
            (HOUR, "1 h ago"),
            (DAY - 1, "23 h ago"),
            (DAY, "1 day ago"),
            (6 * DAY, "6 days ago"),
        ],
    )
    async def test_ages_are_rendered_from_the_stored_stamp(self, age: int, expected: str) -> None:
        rendered = await _render(source=None, presence=_seen(web=age), execution_mode="background")

        assert rendered.splitlines()[2] == f"- Last seen: Web {expected}."


@pytest.mark.unit
class TestTheSectionIsVolatileAndWorkerFacing:
    def test_it_lives_in_the_volatile_slot_for_comms_and_the_executor(self) -> None:
        """Ages tick every minute: in the stable prefix they would break the prompt cache on every call."""
        (entry,) = [s for s in SECTIONS if s.id == "presence"]

        assert entry.slot is PromptSlot.MEMORY_RECALL
        assert entry.applies_to == frozenset({AgentTier.COMMS, AgentTier.EXECUTOR})


#: A Telegram turn by a user who was on the web 25 minutes earlier.
SWITCHED_TO_TELEGRAM = ContextSources(
    presence=_seen(web=25 * MINUTE, whatsapp=3 * DAY), chat_channel=TELEGRAM_RECENT
)


@pytest.mark.unit
class TestTheRunSeesIt:
    @pytest.mark.parametrize(
        ("tier", "first_line"),
        [
            (
                AgentTier.COMMS,
                "- Now: Telegram (this message). Your reply lands in this Telegram chat.\n",
            ),
            (
                AgentTier.EXECUTOR,
                "- The user is chatting with you on Telegram; comms delivers your result there.\n",
            ),
        ],
    )
    async def test_a_bot_turn_shows_where_the_user_is(
        self, tier: AgentTier, first_line: str
    ) -> None:
        """Through the real seed and hook chain: presence reaches comms and the executor from the run's configurable."""
        messages = await effective_context(
            tier,
            ContextSeed(
                sources=SWITCHED_TO_TELEGRAM,
                configurable_overrides={"conversation_source": "telegram"},
            ),
        )

        volatile = text_of(message_in_slot(messages, PromptSlot.MEMORY_RECALL))
        assert volatile.startswith(
            "Where the user is:\n"
            f"{first_line}"
            "- They switched here from Web, where they last wrote 25 min ago.\n"
        )
        assert_snapshot(f"presence_bot_switch_{tier.value}", messages)

    async def test_a_resumed_run_ages_the_same_stamps(self) -> None:
        """Ages come from the stored epochs at render time, so a run resumed an hour later reads an hour older."""
        messages = await effective_context(
            AgentTier.EXECUTOR,
            ContextSeed(
                sources=SWITCHED_TO_TELEGRAM,
                configurable_overrides={"conversation_source": "telegram"},
                now=FIXED_NOW.replace(hour=FIXED_NOW.hour + 1),
            ),
        )

        volatile = text_of(message_in_slot(messages, PromptSlot.MEMORY_RECALL))
        assert "where they last wrote 1 h ago." in volatile


@pytest.mark.unit
class TestAWorkflowFireSeesIt:
    async def test_a_silent_run_with_no_presence_reads_it_into_the_comms_context(self) -> None:
        """A workflow fire carries no presence; comms must still render the section from one read."""
        seeded: dict[str, list[AnyMessage]] = {}

        async def _run_graph(
            graph: object, initial_state: dict[str, list[AnyMessage]], config: object
        ) -> tuple[str, list[object]]:
            seeded["messages"] = initial_state["messages"]
            return "done", []

        with (
            fake_context_sources(
                ContextSources(presence=_seen(telegram=12 * MINUTE), chat_channel=TELEGRAM_RECENT)
            ),
            time_machine.travel(FIXED_NOW, tick=False),
            patch.object(agent_module.GraphManager, "get_graph", AsyncMock()),
            patch.object(agent_module, "execute_graph_silent", _run_graph),
            patch("app.services.analytics_service.capture"),
        ):
            await agent_module.call_agent_silent(
                request=MessageRequestWithHistory(message="Execute workflow: Brief", messages=[]),
                conversation_id="conv-1",
                user=AuthenticatedUser(user_id=USER_ID, email="user@example.com", name="User"),
                options=agent_module.AgentRunOptions(
                    trigger_context={
                        "workflow_id": "wf-1",
                        "workflow_title": "Brief",
                        "execution_mode": "background",
                    }
                ),
            )

        volatile = text_of(message_in_slot(seeded["messages"], PromptSlot.MEMORY_RECALL))
        assert volatile.startswith(
            "Where the user is:\n"
            "- They are not in a chat with you right now.\n"
            "- Last seen: Telegram 12 min ago.\n"
            "- If this run messages the user, it goes to Telegram (their most recent chat app).\n"
        )
