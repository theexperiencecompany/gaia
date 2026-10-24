"""The presence note: what GAIA is told when the user's surface changes, and where it sits in the thread."""

from datetime import UTC, datetime
from unittest.mock import patch

from langchain_core.messages import AnyMessage, HumanMessage
import pytest
from tests._harness.context_chain import AgentTier, ContextSeed, effective_context, text_of
from tests._harness.context_sources import ContextSources

from app.agents.context import presence_note as presence_note_module
from app.agents.context.presence_note import presence_note
from app.agents.context.section_context import ExecutionMode
from app.agents.context.slots import PromptSlot, is_gaia_authored_note, slot_of
from app.models.agent_models import AgentConfigurable
from app.models.chat_models import ConversationSource
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.chat_channel import ChatChannel

pytestmark = pytest.mark.unit


def _epoch(month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(2026, month, day, hour, minute, tzinfo=UTC).timestamp())


WEB_AT = _epoch(10, 24, 16, 55)
WHATSAPP_AT = _epoch(10, 21, 9, 10)
TELEGRAM_AT = _epoch(10, 24, 17, 2)
WEB_EARLIER_AT = _epoch(10, 23, 11, 40)

TELEGRAM_RECENT = ChatChannel(
    source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="recent_activity"
)
WHATSAPP_BY_ORDER = ChatChannel(
    source=ConversationSource.WHATSAPP, platform_user_id="wa-1", basis="priority"
)


def _seen(**last_seen: int) -> PresenceSnapshot:
    return {"captured_at": _epoch(10, 24, 17, 30), "last_seen": last_seen}


#: Before this Telegram turn the user last wrote on the web, and on WhatsApp days ago.
CAME_FROM_WEB = _seen(web=WEB_AT, whatsapp=WHATSAPP_AT)
#: Before this Telegram turn the user last wrote on Telegram itself.
STAYED_ON_TELEGRAM = _seen(telegram=TELEGRAM_AT, web=WEB_EARLIER_AT)


class TestTheNote:
    def test_a_switch_names_where_they_came_from_with_absolute_times(self) -> None:
        note = presence_note(CAME_FROM_WEB, "telegram", "interactive", TELEGRAM_RECENT)

        assert note == (
            "[Surface change: the user is now writing from Telegram. Their previous message "
            "was on Web at 2026-10-24 16:55 UTC. Also last seen: WhatsApp at 2026-10-21 09:10 "
            "UTC. Messages you send on your own (reminders, workflow results, updates) go to "
            "Telegram, the chat app they last wrote on within the past 3 hours.]"
        )

    def test_staying_on_the_same_surface_says_nothing(self) -> None:
        assert presence_note(STAYED_ON_TELEGRAM, "telegram", "interactive", TELEGRAM_RECENT) is None

    @pytest.mark.parametrize(
        "presence", [None, _seen()], ids=["no_snapshot", "never_seen_anywhere"]
    )
    def test_no_history_says_nothing(self, presence: PresenceSnapshot | None) -> None:
        assert presence_note(presence, "telegram", "interactive", TELEGRAM_RECENT) is None
        assert presence_note(presence, None, "background", TELEGRAM_RECENT) is None

    def test_a_background_run_lists_last_seen_and_where_its_message_goes(self) -> None:
        note = presence_note(
            _seen(telegram=TELEGRAM_AT, web=WEB_EARLIER_AT), None, "background", TELEGRAM_RECENT
        )

        assert note == (
            "[User presence: not in a chat with you right now. Last seen: Telegram at "
            "2026-10-24 17:02 UTC, Web at 2026-10-23 11:40 UTC. If this run messages the user, "
            "it goes to Telegram, the chat app they last wrote on within the past 3 hours.]"
        )

    def test_a_chat_source_on_a_background_run_is_still_background(self) -> None:
        note = presence_note(STAYED_ON_TELEGRAM, "telegram", "background", TELEGRAM_RECENT)

        assert note is not None
        assert note.startswith("[User presence: not in a chat with you right now.")

    def test_a_target_picked_by_order_says_so(self) -> None:
        note = presence_note(CAME_FROM_WEB, "telegram", "interactive", WHATSAPP_BY_ORDER)

        assert note is not None
        assert note.endswith(
            "go to WhatsApp, first in their chat order (they have not written on a chat app "
            "in the past 3 hours).]"
        )

    def test_no_chat_app_means_only_the_app(self) -> None:
        switch = presence_note(CAME_FROM_WEB, "telegram", "interactive", None)
        background = presence_note(STAYED_ON_TELEGRAM, None, "background", None)

        assert switch is not None
        assert switch.endswith("only show in the GAIA app (no chat app linked).]")
        assert background is not None
        assert background.endswith(
            "If this run messages the user, it only shows in the GAIA app (no chat app linked).]"
        )

    def test_the_window_comes_from_the_presence_constant(self) -> None:
        with patch.object(presence_note_module, "PRESENCE_ACTIVE_WINDOW_SECONDS", 2 * 60 * 60):
            note = presence_note(CAME_FROM_WEB, "telegram", "interactive", TELEGRAM_RECENT)

        assert note is not None
        assert note.endswith("the chat app they last wrote on within the past 2 hours.]")

    def test_the_note_never_carries_an_em_or_en_dash(self) -> None:
        for note in (
            presence_note(CAME_FROM_WEB, "telegram", "interactive", WHATSAPP_BY_ORDER),
            presence_note(CAME_FROM_WEB, None, "background", None),
        ):
            assert note is not None
            assert "\u2014" not in note
            assert "\u2013" not in note


def _notes(messages: list[AnyMessage]) -> list[AnyMessage]:
    return [message for message in messages if is_gaia_authored_note(message)]


def _seed(
    presence: PresenceSnapshot, source: str | None, mode: ExecutionMode = "interactive"
) -> ContextSeed:
    overrides: AgentConfigurable = {
        "presence": presence,
        "conversation_source": source,
        "execution_mode": mode,
    }
    return ContextSeed(
        query="book the table for friday",
        sources=ContextSources(presence=presence, chat_channel=TELEGRAM_RECENT),
        configurable_overrides=overrides,
    )


class TestWhereTheNoteSits:
    """Through the real seed and pre-model hook chain: what the model is actually sent."""

    @pytest.mark.parametrize("tier", [AgentTier.COMMS, AgentTier.EXECUTOR])
    async def test_a_switch_turn_opens_with_the_note_right_before_the_users_words(
        self, tier: AgentTier
    ) -> None:
        messages = await effective_context(tier, _seed(CAME_FROM_WEB, "telegram"))

        (note,) = _notes(messages)
        index = messages.index(note)
        assert isinstance(note, HumanMessage)
        assert slot_of(note) is PromptSlot.CONVERSATION
        assert text_of(note).startswith("[Surface change: the user is now writing from Telegram.")
        assert text_of(messages[index + 1]) == "book the table for friday"

    @pytest.mark.parametrize("tier", [AgentTier.COMMS, AgentTier.EXECUTOR])
    async def test_a_same_surface_turn_has_no_note(self, tier: AgentTier) -> None:
        messages = await effective_context(tier, _seed(STAYED_ON_TELEGRAM, "telegram"))

        assert _notes(messages) == []

    async def test_a_handoff_subagent_gets_no_note(self) -> None:
        messages = await effective_context(
            AgentTier.PROVIDER_SUBAGENT, _seed(CAME_FROM_WEB, "telegram")
        )

        assert _notes(messages) == []


class TestTheTargetLookup:
    """The delivery target is a user read: only a run that gets a note may pay for it."""

    async def test_a_same_surface_turn_never_reads_the_target(self) -> None:
        with patch.object(presence_note_module, "resolve_chat_channel") as lookup:
            message = await presence_note_module.presence_note_message(
                "user-1", STAYED_ON_TELEGRAM, "telegram", "interactive"
            )

        assert message is None
        lookup.assert_not_called()

    async def test_a_switch_turn_reads_it_once(self) -> None:
        with patch.object(
            presence_note_module, "resolve_chat_channel", return_value=TELEGRAM_RECENT
        ) as lookup:
            message = await presence_note_module.presence_note_message(
                "user-1", CAME_FROM_WEB, "telegram", "interactive"
            )

        assert message is not None
        lookup.assert_awaited_once_with("user-1")
