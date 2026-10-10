"""Behavior tests for app.agents.tools.manual_tool.

The tool is a thin read over the in-memory manual: a known topic returns that
topic's body, an unknown topic returns the error line plus the topic index.
"""

from app.agents.tools.manual_tool import read_manual
from app.agents.workspace.operational_docs import get_manual, manual_index_text


class TestReadManual:
    async def test_known_topic_returns_its_body(self) -> None:
        doc = get_manual("integrations")
        assert doc is not None

        result = await read_manual.coroutine(topic="integrations")

        assert result == doc.body
        assert len(result) > 0

    async def test_unknown_topic_returns_the_index(self) -> None:
        result = await read_manual.coroutine(topic="bogus-topic")

        assert "Unknown manual topic: 'bogus-topic'" in result
        assert manual_index_text() in result

    async def test_topic_lookup_is_case_insensitive(self) -> None:
        doc = get_manual("workflows")
        assert doc is not None

        result = await read_manual.coroutine(topic="Workflows")

        assert result == doc.body


class TestAccountTopic:
    """The account topic is the discovery surface for the account tools."""

    async def test_account_topic_serves_its_manual_body(self) -> None:
        result = await read_manual.coroutine(topic="account")

        assert result.startswith("# Account")
        # The body must name every mutation tool — this IS the doors-open doc.
        for tool in (
            "update_notification_settings",
            "update_preferences",
            "update_custom_instructions",
            "set_selected_voice",
            "manage_linked_account",
        ):
            assert tool in result, tool

    async def test_account_states_the_billing_limit(self) -> None:
        body = get_manual("account").body

        assert "cannot modify or cancel subscriptions" in body
        assert "read-only" in body

    def test_account_appears_in_the_topic_index(self) -> None:
        index = manual_index_text()

        assert "- account:" in index
