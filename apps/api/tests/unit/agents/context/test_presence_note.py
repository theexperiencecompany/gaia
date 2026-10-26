"""The presence note: what GAIA is told when the user's surface changes, and where it sits in the thread."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
import pytest
from tests._harness.context_chain import AgentTier, ContextSeed, effective_context, text_of
from tests._harness.context_sources import ContextSources

from app.agents.context import presence_note as presence_note_module
from app.agents.context.assemble import AssembledContext
from app.agents.context.presence_note import presence_note
from app.agents.context.section_context import ExecutionMode
from app.agents.context.slots import PromptSlot, is_gaia_authored_note, slot_of
from app.agents.core import messages as messages_module
from app.models.agent_models import AgentConfigurable
from app.models.chat_models import ConversationSource
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.chat_channel import ChatChannel, InApp
from app.utils import presence_utils

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
ACTIVE_IN_APP = InApp(reason="active_in_app")
NO_CHAT_APP = InApp(reason="no_chat_app")
TELEGRAM_UNREACHABLE_TO_WHATSAPP = ChatChannel(
    source=ConversationSource.WHATSAPP,
    platform_user_id="wa-1",
    basis="priority",
    unreachable_active=ConversationSource.TELEGRAM,
)
TELEGRAM_UNREACHABLE_ONLY = InApp(
    reason="no_chat_app", unreachable_active=ConversationSource.TELEGRAM
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
            "UTC. Messages you send on your own (reminders, tracked todo updates, workflow "
            "results) go to Telegram, where they are active (they wrote there within the past "
            "3 hours).]"
        )

    def test_a_conversations_first_turn_says_where_they_are_without_a_switch(self) -> None:
        """A new chat is a fresh thread: it has never been told where its messages land."""
        note = presence_note(STAYED_ON_TELEGRAM, "telegram", "interactive", TELEGRAM_RECENT)

        assert note == (
            "[User presence: the user is writing from Telegram. Also last seen: Web at "
            "2026-10-23 11:40 UTC. Messages you send on your own (reminders, tracked todo "
            "updates, workflow results) go to Telegram, where they are active (they wrote there "
            "within the past 3 hours).]"
        )

    def test_a_live_turn_on_a_chat_app_that_cannot_be_messaged_says_where_messages_go(self) -> None:
        note = presence_note(
            CAME_FROM_WEB, "telegram", "interactive", TELEGRAM_UNREACHABLE_TO_WHATSAPP
        )
        only_app = presence_note(
            CAME_FROM_WEB, "telegram", "interactive", TELEGRAM_UNREACHABLE_ONLY
        )

        assert note is not None
        assert note.endswith(
            "They are on Telegram right now, which you cannot message on your own: reminders "
            "land back in the chat they were set in and on WhatsApp too when that chat is not "
            "WhatsApp; tracked todo updates and workflow results go to WhatsApp, first in "
            "their chat order.]"
        )
        assert only_app is not None
        assert only_app.endswith(
            "They are on Telegram right now, which you cannot message on your own: reminders "
            "land back in the chat they were set in; tracked todo updates and workflow results "
            "only show in the GAIA app.]"
        )

    def test_a_background_run_for_a_user_on_a_chat_app_that_cannot_be_messaged(self) -> None:
        note = presence_note(
            STAYED_ON_TELEGRAM, None, "background", TELEGRAM_UNREACHABLE_TO_WHATSAPP
        )
        only_app = presence_note(STAYED_ON_TELEGRAM, None, "background", TELEGRAM_UNREACHABLE_ONLY)

        assert note is not None
        assert note.endswith(
            "If this run messages the user, it goes to WhatsApp: they are on Telegram right "
            "now, which you cannot message on your own.]"
        )
        assert only_app is not None
        assert only_app.endswith(
            "If this run messages the user, it goes to the GAIA app only: they are on Telegram "
            "right now, which you cannot message on your own.]"
        )

    def test_a_background_run_lists_last_seen_and_where_its_message_goes(self) -> None:
        note = presence_note(
            _seen(telegram=TELEGRAM_AT, web=WEB_EARLIER_AT), None, "background", TELEGRAM_RECENT
        )

        assert note == (
            "[User presence: not in a chat with you right now. Last seen: Telegram at "
            "2026-10-24 17:02 UTC, Web at 2026-10-23 11:40 UTC. If this run messages the user, "
            "it goes to Telegram, where they are active (they wrote there within the past 3 "
            "hours).]"
        )

    def test_a_chat_source_on_a_background_run_is_still_background(self) -> None:
        note = presence_note(STAYED_ON_TELEGRAM, "telegram", "background", TELEGRAM_RECENT)

        assert note is not None
        assert note.startswith("[User presence: not in a chat with you right now.")

    def test_a_target_picked_by_order_says_so(self) -> None:
        note = presence_note(CAME_FROM_WEB, "telegram", "interactive", WHATSAPP_BY_ORDER)

        assert note is not None
        assert note.endswith(
            "They are not active anywhere right now: reminders land back in the chat they were "
            "set in and on WhatsApp too when that chat is not WhatsApp; tracked todo updates and "
            "workflow results go to WhatsApp, first in their chat order.]"
        )

    def test_a_background_run_with_nobody_active_names_the_first_chat_app(self) -> None:
        note = presence_note(STAYED_ON_TELEGRAM, None, "background", WHATSAPP_BY_ORDER)

        assert note is not None
        assert note.endswith(
            "If this run messages the user, it goes to WhatsApp, first in their chat order "
            "(not active anywhere in the past 3 hours).]"
        )

    def test_a_user_active_in_the_app_hears_from_gaia_only_in_the_app(self) -> None:
        live = presence_note(_seen(telegram=TELEGRAM_AT), "web", "interactive", ACTIVE_IN_APP)
        background = presence_note(_seen(web=WEB_AT), None, "background", ACTIVE_IN_APP)

        assert live == (
            "[Surface change: the user is now writing from Web. Their previous message was on "
            "Telegram at 2026-10-24 17:02 UTC. Messages you send on your own (reminders, "
            "tracked todo updates, workflow results) stay in the GAIA app, where they are "
            "active; nothing goes to a chat app.]"
        )
        assert background is not None
        assert background.endswith(
            "If this run messages the user, it stays in the GAIA app, where they are active.]"
        )

    def test_no_chat_app_means_only_the_app(self) -> None:
        switch = presence_note(CAME_FROM_WEB, "telegram", "interactive", NO_CHAT_APP)
        background = presence_note(STAYED_ON_TELEGRAM, None, "background", NO_CHAT_APP)

        assert switch is not None
        assert switch.endswith(
            "Reminders land back in the chat they were set in; tracked todo updates and "
            "workflow results only show in the GAIA app (no chat app linked).]"
        )
        assert background is not None
        assert background.endswith(
            "If this run messages the user, it only shows in the GAIA app (no chat app linked).]"
        )

    def test_the_window_comes_from_the_presence_constant(self) -> None:
        with patch.object(presence_utils, "PRESENCE_ACTIVE_WINDOW_SECONDS", 2 * 60 * 60):
            note = presence_note(CAME_FROM_WEB, "telegram", "interactive", TELEGRAM_RECENT)

        assert note is not None
        assert note.endswith("(they wrote there within the past 2 hours).]")

    def test_the_note_never_carries_an_em_or_en_dash(self) -> None:
        targets = (
            TELEGRAM_RECENT,
            WHATSAPP_BY_ORDER,
            ACTIVE_IN_APP,
            NO_CHAT_APP,
            TELEGRAM_UNREACHABLE_TO_WHATSAPP,
            TELEGRAM_UNREACHABLE_ONLY,
        )
        for note in [
            presence_note(CAME_FROM_WEB, source, mode, target)
            for target in targets
            for source, mode in (("telegram", "interactive"), (None, "background"))
        ]:
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
        sources=ContextSources(presence=presence, proactive_target=TELEGRAM_RECENT),
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
        with patch.object(presence_note_module, "resolve_proactive_target") as lookup:
            message = await presence_note_module.presence_note_message(
                "user-1", STAYED_ON_TELEGRAM, "telegram", "interactive", opens_thread=False
            )

        assert message is None
        lookup.assert_not_called()

    @pytest.mark.parametrize("presence", [None, _seen()], ids=["no_snapshot", "never_seen"])
    async def test_no_history_never_reads_the_target(
        self, presence: PresenceSnapshot | None
    ) -> None:
        with patch.object(presence_note_module, "resolve_proactive_target") as lookup:
            live = await presence_note_module.presence_note_message(
                "user-1", presence, "telegram", "interactive", opens_thread=True
            )
            background = await presence_note_module.presence_note_message(
                "user-1", presence, None, "background", opens_thread=False
            )

        assert live is None
        assert background is None
        lookup.assert_not_called()

    async def test_no_user_never_reads_the_target(self) -> None:
        with patch.object(presence_note_module, "resolve_proactive_target") as lookup:
            message = await presence_note_module.presence_note_message(
                "", CAME_FROM_WEB, "telegram", "interactive", opens_thread=False
            )

        assert message is None
        lookup.assert_not_called()

    async def test_a_known_user_without_a_snapshot_never_reads_the_target(self) -> None:
        with patch.object(presence_note_module, "resolve_proactive_target") as lookup:
            message = await presence_note_module.presence_note_message(
                "user-1", None, "telegram", "interactive", opens_thread=False
            )

        assert message is None
        lookup.assert_not_called()

    async def test_a_background_run_is_noted_and_worded_as_background(self) -> None:
        """Same surface, same snapshot: only the run's mode makes it due and picks the wording."""
        with patch.object(
            presence_note_module, "resolve_proactive_target", return_value=TELEGRAM_RECENT
        ):
            background = await presence_note_module.presence_note_message(
                "user-1", STAYED_ON_TELEGRAM, "telegram", "background", opens_thread=False
            )
            interactive = await presence_note_module.presence_note_message(
                "user-1", STAYED_ON_TELEGRAM, "telegram", "interactive", opens_thread=False
            )

        assert interactive is None
        assert background is not None
        assert text_of(background).startswith("[User presence: not in a chat with you right now.")

    async def test_a_switch_turn_reads_it_once(self) -> None:
        with patch.object(
            presence_note_module, "resolve_proactive_target", return_value=TELEGRAM_RECENT
        ) as lookup:
            message = await presence_note_module.presence_note_message(
                "user-1", CAME_FROM_WEB, "telegram", "interactive", opens_thread=False
            )

        assert message is not None
        lookup.assert_awaited_once_with("user-1")


class TestComms:
    async def test_the_scopes_execution_mode_reaches_the_note(self) -> None:
        with (
            patch.object(
                messages_module,
                "assemble_context",
                AsyncMock(
                    return_value=AssembledContext(
                        stable=SystemMessage(content="ctx"), volatile=None
                    )
                ),
            ),
            patch.object(
                messages_module, "presence_note_message", AsyncMock(return_value=None)
            ) as note,
        ):
            await messages_module.construct_langchain_messages(
                query="hi",
                scope=messages_module.MessageScope(
                    user_id="user-1",
                    source="telegram",
                    presence=STAYED_ON_TELEGRAM,
                    opens_thread=False,
                    execution_mode="background",
                ),
            )

        note.assert_awaited_once_with(
            "user-1", STAYED_ON_TELEGRAM, "telegram", "background", opens_thread=False
        )


class TestAConversationsFirstTurn:
    """Through comms' real message builder: a new chat on the same surface still gets the note."""

    async def _comms_messages(self, *, opens_thread: bool) -> list[AnyMessage]:
        with (
            patch.object(
                messages_module,
                "assemble_context",
                AsyncMock(
                    return_value=AssembledContext(
                        stable=SystemMessage(content="ctx"), volatile=None
                    )
                ),
            ),
            patch.object(
                presence_note_module,
                "resolve_proactive_target",
                AsyncMock(return_value=TELEGRAM_RECENT),
            ),
        ):
            return await messages_module.construct_langchain_messages(
                query="remind me in 2 minutes to drink water",
                scope=messages_module.MessageScope(
                    user_id="user-1",
                    source="telegram",
                    presence=STAYED_ON_TELEGRAM,
                    opens_thread=opens_thread,
                ),
            )

    async def test_a_new_conversation_opens_with_the_note(self) -> None:
        messages = await self._comms_messages(opens_thread=True)

        (note,) = _notes(messages)
        assert text_of(note).startswith("[User presence: the user is writing from Telegram.")
        assert (
            text_of(messages[messages.index(note) + 1]) == "remind me in 2 minutes to drink water"
        )

    async def test_a_later_turn_on_the_same_surface_does_not(self) -> None:
        assert _notes(await self._comms_messages(opens_thread=False)) == []
