"""Unit tests for the experiment variants in agent_template."""

from app.agents.templates.agent_template import (
    get_comms_static_prompt,
    get_executor_prompt,
)

OPENUI_MARKER = "## Output Format (this app renders rich components)"
PLATFORM_MARKER = "Platform Context"


class TestOpenuiVariants:
    def test_renderable_channels_carry_openui(self) -> None:
        for source in ("web", "mobile", "desktop"):
            assert OPENUI_MARKER in get_comms_static_prompt(source)

    def test_desktop_keeps_desktop_context_and_openui(self) -> None:
        desktop = get_comms_static_prompt("desktop")
        assert "Desktop Context" in desktop
        assert OPENUI_MARKER in desktop

    def test_text_channels_get_platform_context_not_openui(self) -> None:
        for source in ("whatsapp", "telegram", "discord", "slack", "imessage"):
            prompt = get_comms_static_prompt(source)
            assert PLATFORM_MARKER in prompt
            assert OPENUI_MARKER not in prompt

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
