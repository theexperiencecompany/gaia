"""Unit tests for the experiment variants in agent_template."""

from typing import cast

import pytest

from app.agents.prompts.openui_prompts import OPENUI_INSTRUCTIONS
from app.agents.prompts.task_prompts import TASK_SYSTEM_PROMPT
from app.agents.templates.agent_template import (
    COMMS_PROMPT_BY_SOURCE,
    EXECUTOR_PROMPT_TEMPLATE,
    _text_only_addendum,
    get_comms_static_prompt,
    get_executor_prompt,
)
from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource
from app.constants.reactions import REACTION_PALETTE_BY_SURFACE

OPENUI_MARKER = "## Output Format (this app renders rich components)"
PLATFORM_MARKER = "Platform Context"
TELEGRAM_REACTIONS_MARKER = "REACTIONS ON TELEGRAM"


class TestOpenuiVariants:
    def test_renderable_channels_carry_openui(self) -> None:
        for source in (
            ConversationSource.WEB,
            ConversationSource.MOBILE,
            ConversationSource.DESKTOP,
        ):
            assert OPENUI_MARKER in get_comms_static_prompt(source)

    def test_renderable_channels_write_math_in_double_dollars(self) -> None:
        for source in (
            ConversationSource.WEB,
            ConversationSource.MOBILE,
            ConversationSource.DESKTOP,
        ):
            prompt = get_comms_static_prompt(source)
            assert "$$...$$" in prompt
            assert "a single $ is a literal dollar sign" in prompt

    def test_desktop_keeps_desktop_context_and_openui(self) -> None:
        desktop = get_comms_static_prompt(ConversationSource.DESKTOP)
        assert "Desktop Context" in desktop
        assert OPENUI_MARKER in desktop

    def test_text_channels_get_platform_context_not_openui(self) -> None:
        for source in (
            ConversationSource.WHATSAPP,
            ConversationSource.TELEGRAM,
            ConversationSource.DISCORD,
            ConversationSource.SLACK,
            ConversationSource.IMESSAGE,
        ):
            prompt = get_comms_static_prompt(source)
            assert PLATFORM_MARKER in prompt
            assert OPENUI_MARKER not in prompt

    def test_only_telegram_lists_its_reaction_set(self) -> None:
        for source in (
            ConversationSource.WHATSAPP,
            ConversationSource.DISCORD,
            ConversationSource.SLACK,
            ConversationSource.IMESSAGE,
        ):
            assert TELEGRAM_REACTIONS_MARKER not in get_comms_static_prompt(source)
        assert TELEGRAM_REACTIONS_MARKER in get_comms_static_prompt(ConversationSource.TELEGRAM)

    def test_the_telegram_prompt_lists_exactly_the_palette_the_reaction_check_reads(self) -> None:
        prompt = get_comms_static_prompt(ConversationSource.TELEGRAM)
        listed = prompt.split(TELEGRAM_REACTIONS_MARKER)[1].split("one of ")[1].split(". Pick")[0]
        palette = REACTION_PALETTE_BY_SURFACE[ConversationSource.TELEGRAM]
        assert listed.split() == list(palette)

    def test_reaction_rules_close_the_platform_block(self) -> None:
        assert _text_only_addendum("X", "fmt", "\n\nREACT").endswith("brevity.\n\nREACT")
        assert _text_only_addendum("X", "fmt").endswith("outranks brevity.")

    def test_every_surface_a_reply_is_read_on_has_its_own_prompt(self) -> None:
        assert set(COMMS_PROMPT_BY_SOURCE) == set(ConversationSource) - {
            ConversationSource.BACKGROUND,
            ConversationSource.WORKFLOW_SYSTEM,
        }

    @pytest.mark.parametrize(
        "source", [ConversationSource.BACKGROUND, ConversationSource.WORKFLOW_SYSTEM]
    )
    def test_a_background_source_is_no_surface_and_raises_instead_of_reading_as_web(
        self, source: ConversationSource
    ) -> None:
        with pytest.raises(KeyError):
            get_comms_static_prompt(source)

    def test_an_unknown_surface_raises_instead_of_reading_as_web(self) -> None:
        with pytest.raises(KeyError):
            get_comms_static_prompt(cast(ConversationSource, "nope"))

    def test_a_voice_turn_is_spoken_so_it_gets_no_openui(self) -> None:
        prompt = get_comms_static_prompt(ConversationSource.VOICE)
        assert OPENUI_INSTRUCTIONS not in prompt
        assert "read aloud" in prompt
        # A call runs inside the app, so an approval is still decided on its card.
        assert "## Approvals in the app" in prompt


class TestExecutorPrompt:
    def test_teaches_activation(self) -> None:
        prompt = get_executor_prompt()
        assert "activate_integration" in prompt
        assert "You activate one, then do" in prompt

    def test_default_matches_env_template(self) -> None:
        assert get_executor_prompt() == EXECUTOR_PROMPT_TEMPLATE

    def test_planning_rules_ride_the_static_prompt(self) -> None:
        # The task rules used to be re-sent before every model call; they are static, so they cache.
        assert TASK_SYSTEM_PROMPT in EXECUTOR_PROMPT_TEMPLATE

    def test_prompt_never_points_at_a_card(self) -> None:
        # The executor is channel-blind: it must not describe UI-only approval
        # mechanics that are wrong on a messaging channel.
        assert "approval card" not in get_executor_prompt()


MESSAGING_SOURCES = tuple(sorted(BOT_CONVERSATION_SOURCES))
# Everything read in the app, a call included, decides approvals on a card.
UI_SOURCES = tuple(sorted(set(COMMS_PROMPT_BY_SOURCE) - BOT_CONVERSATION_SOURCES))


class TestApprovalMessagingWording:
    """GAIA-713: approval asks must be channel-aware.

    Messaging channels have no approval card or button, and GAIA asks there itself
    (the bot's prompt, or a link to the app for an approval asked in a todo's or a
    workflow's chat), so a reply never tells the user what to answer.
    Web/mobile/desktop keep the card-based approval.
    """

    def test_every_channel_is_classified(self) -> None:
        assert set(COMMS_PROMPT_BY_SOURCE) == set(MESSAGING_SOURCES) | set(UI_SOURCES)

    def test_messaging_channels_leave_the_asking_to_gaia(self) -> None:
        for source in MESSAGING_SOURCES:
            prompt = get_comms_static_prompt(source)
            assert "never tell them how to approve or what to reply" in prompt, (
                f"{source} lets a reply explain how to approve"
            )
            assert "no approval card or button here" in prompt
            # The only allowed mention of a card is the one saying there is none.
            assert "approval card" not in prompt.replace("no approval card or button here", "")

    @pytest.mark.regression
    def test_ui_channels_keep_card_based_approval(self) -> None:
        for source in UI_SOURCES:
            prompt = get_comms_static_prompt(source)
            assert "## Approvals in the app" in prompt
            assert "approval card" in prompt
            assert "do not ask them to type a reply in chat" in prompt
            assert "APPROVALS ON THIS PLATFORM" not in prompt

    def test_no_channel_tells_the_user_to_reply_yes(self) -> None:
        # Bug 30: a todo's parked write-up said "Reply YES", which answers nothing anywhere.
        for source in COMMS_PROMPT_BY_SOURCE:
            assert "reply YES" not in get_comms_static_prompt(source)

    @pytest.mark.regression
    def test_approval_is_permission_not_execution(self) -> None:
        # Ledger HIL: an approval lets the action run, it does not mean the action
        # is already running or that anything is waiting on a separate executor.
        for source in MESSAGING_SOURCES:
            prompt = get_comms_static_prompt(source)
            assert "it does not run until they decide" in prompt
            assert "carries the action out or leaves it undone" in prompt
        for source in UI_SOURCES:
            prompt = get_comms_static_prompt(source)
            assert "While one is pending" in prompt
            assert "an approval needs their decision" in prompt
