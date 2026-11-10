"""The prompt a catalog-enabled Composio toolkit's subagent runs under."""

from app.agents.prompts.subagent_prompts import composio_toolkit_system_prompt


def test_the_prompt_names_the_toolkit_and_carries_its_description() -> None:
    prompt = composio_toolkit_system_prompt("Attio", "CRM for fast-moving teams")

    assert (
        "You are a specialized Attio agent with deep expertise in using Attio through its Composio tools."
        in prompt
    )
    assert "## DOMAIN OVERVIEW\nCRM for fast-moving teams\n" in prompt
    assert "read each tool's schema before the first call" in prompt


def test_a_toolkit_with_no_description_says_how_it_is_connected() -> None:
    prompt = composio_toolkit_system_prompt("Attio", "")

    assert "## DOMAIN OVERVIEW\nAttio, connected through Composio.\n" in prompt


def test_the_prompt_leaves_no_placeholder_unfilled() -> None:
    prompt = composio_toolkit_system_prompt("Attio", "CRM")

    assert "{" not in prompt.replace("{{", "").replace("}}", "")
