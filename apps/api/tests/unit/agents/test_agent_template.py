"""Unit tests for the experiment variants in agent_template."""

from app.agents.templates.agent_template import (
    COMMS_PROMPT_BY_SOURCE,
    _text_only_addendum,
    get_comms_static_prompt,
    get_executor_prompt,
)
from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource

OPENUI_MARKER = "## Output Format (this app renders rich components)"
PLATFORM_MARKER = "Platform Context"
TELEGRAM_REACTIONS_MARKER = "REACTIONS ON TELEGRAM"


class TestOpenuiVariants:
    def test_renderable_channels_carry_openui(self) -> None:
        for source in ("web", "mobile", "desktop"):
            assert OPENUI_MARKER in get_comms_static_prompt(source)

    def test_renderable_channels_write_math_in_double_dollars(self) -> None:
        for source in ("web", "mobile", "desktop"):
            prompt = get_comms_static_prompt(source)
            assert "$$...$$" in prompt
            assert "a single $ is a literal dollar sign" in prompt

    def test_desktop_keeps_desktop_context_and_openui(self) -> None:
        desktop = get_comms_static_prompt("desktop")
        assert "Desktop Context" in desktop
        assert OPENUI_MARKER in desktop

    def test_text_channels_get_platform_context_not_openui(self) -> None:
        for source in ("whatsapp", "telegram", "discord", "slack", "imessage"):
            prompt = get_comms_static_prompt(source)
            assert PLATFORM_MARKER in prompt
            assert OPENUI_MARKER not in prompt

    def test_only_telegram_lists_its_reaction_set(self) -> None:
        for source in ("whatsapp", "discord", "slack", "imessage"):
            assert TELEGRAM_REACTIONS_MARKER not in get_comms_static_prompt(source)
        assert TELEGRAM_REACTIONS_MARKER in get_comms_static_prompt("telegram")

    def test_reaction_rules_close_the_platform_block(self) -> None:
        assert _text_only_addendum("X", "fmt", "\n\nREACT").endswith("brevity.\n\nREACT")
        assert _text_only_addendum("X", "fmt").endswith("outranks brevity.")

    def test_unknown_source_falls_back_to_web(self) -> None:
        assert get_comms_static_prompt("nope") == get_comms_static_prompt("web")
        assert get_comms_static_prompt(None) == get_comms_static_prompt("web")


class TestExecutorPrompt:
    def test_teaches_activation(self) -> None:
        prompt = get_executor_prompt()
        assert "activate_integration" in prompt
        assert "You activate one, then do" in prompt

    def test_default_matches_env_template(self) -> None:
        from app.agents.templates.agent_template import EXECUTOR_PROMPT_TEMPLATE

        assert get_executor_prompt() == EXECUTOR_PROMPT_TEMPLATE

    def test_prompt_never_points_at_a_card(self) -> None:
        # The executor is channel-blind: it must not describe UI-only approval
        # mechanics that are wrong on a messaging channel.
        assert "approval card" not in get_executor_prompt()


MESSAGING_SOURCES = tuple(sorted(source.value for source in BOT_CONVERSATION_SOURCES))
UI_SOURCES = tuple(
    sorted(
        source.value
        for source in (
            ConversationSource.WEB,
            ConversationSource.MOBILE,
            ConversationSource.DESKTOP,
        )
    )
)


class TestApprovalMessagingWording:
    """GAIA-713: approval asks must be channel-aware.

    Messaging channels have no approval card or button, so the user must be told
    to reply YES/NO in chat. Web/mobile/desktop keep the card-based approval.
    """

    def test_every_channel_is_classified(self) -> None:
        assert set(COMMS_PROMPT_BY_SOURCE) == set(MESSAGING_SOURCES) | set(UI_SOURCES)

    def test_non_ui_channels_instruct_reply_yes_no(self) -> None:
        for source in MESSAGING_SOURCES:
            prompt = get_comms_static_prompt(source)
            assert "reply YES to approve or NO to decline" in prompt, (
                f"{source} did not instruct a YES/NO chat reply"
            )
            assert "no approval card or button here" in prompt
            # The only allowed mention of a card is the one saying there is none.
            assert "approval card" not in prompt.replace("no approval card or button here", "")

    def test_ui_channels_keep_card_based_approval(self) -> None:
        for source in UI_SOURCES:
            prompt = get_comms_static_prompt(source)
            assert "## Approvals in the app" in prompt
            assert "approval card" in prompt
            assert "do not ask them to type a reply in chat" in prompt
            # UI channels must NOT ask the user to reply YES/NO in chat.
            assert "reply YES to approve or NO to decline" not in prompt
            assert "APPROVALS ON THIS PLATFORM" not in prompt

    def test_channel_aware_not_telegram_only(self) -> None:
        # The YES/NO wording is driven by the channel (all messaging sources),
        # not hardcoded to Telegram.
        for source in MESSAGING_SOURCES:
            assert "reply YES to approve or NO to decline" in get_comms_static_prompt(source)
        for source in UI_SOURCES:
            assert "reply YES to approve or NO to decline" not in get_comms_static_prompt(source)
