"""Unit tests for the experiment variants in agent_template."""

from app.agents.templates.agent_template import (
    _text_only_addendum,
    get_comms_static_prompt,
    get_executor_prompt,
)

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
