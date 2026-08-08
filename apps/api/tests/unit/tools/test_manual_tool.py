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
