"""Tests for reading a model's thinking off a streamed chunk."""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestExtractReasoningDelta:
    """Shared by comms and the subagent runner, so one extractor serves both — comms thinking used to be dropped entirely because only the runner had it."""

    def test_reads_standard_reasoning_content_blocks(self) -> None:
        from langchain_core.messages import AIMessageChunk

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = AIMessageChunk(
            content=[
                {"type": "reasoning", "reasoning": "we"},
                {"type": "text", "text": "ignored"},
            ]
        )
        assert extract_reasoning_delta(chunk) == "we"

    def test_a_reasoning_key_on_a_non_reasoning_block_is_not_thinking(self) -> None:
        from langchain_core.messages import AIMessageChunk

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = AIMessageChunk(content=[{"type": "text", "text": "answer", "reasoning": "stray"}])
        assert extract_reasoning_delta(chunk) == ""

    def test_deepseek_style_reasoning_content_is_extracted(self) -> None:
        """DeepSeek-style providers put thinking in additional_kwargs — LangChain normalises that into a reasoning content block, so it arrives via the block path rather than the explicit fallback below."""
        from langchain_core.messages import AIMessageChunk

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "thinking"})
        assert extract_reasoning_delta(chunk) == "thinking"

    def test_the_additional_kwargs_fallback_still_works(self) -> None:
        """Fall back to additional_kwargs for a chunk-like object exposing no reasoning block."""
        from types import SimpleNamespace

        from app.agents.llm.reasoning import extract_reasoning_delta

        raw = SimpleNamespace(content_blocks=[], additional_kwargs={"reasoning_content": "raw"})
        assert extract_reasoning_delta(raw) == "raw"  # type: ignore[arg-type]  # passes a SimpleNamespace stub in place of the real AIMessageChunk

    def test_object_style_reasoning_blocks_are_read_by_attribute(self) -> None:
        """Read a reasoning block exposed as an object, not a dict, by attribute rather than key."""
        from types import SimpleNamespace

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = SimpleNamespace(
            content_blocks=[
                SimpleNamespace(type="text", text="ignored"),
                SimpleNamespace(type="reasoning", reasoning="thought"),
            ],
            additional_kwargs={},
        )
        assert extract_reasoning_delta(chunk) == "thought"  # type: ignore[arg-type]  # SimpleNamespace stub stands in for the real AIMessageChunk

    def test_an_object_block_carrying_no_type_at_all_is_skipped(self) -> None:
        """Skip a block object missing type entirely instead of failing the whole turn's thinking."""
        from types import SimpleNamespace

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = SimpleNamespace(
            content_blocks=[
                SimpleNamespace(text="untyped"),
                SimpleNamespace(type="reasoning", reasoning="kept"),
            ],
            additional_kwargs={},
        )
        assert extract_reasoning_delta(chunk) == "kept"  # type: ignore[arg-type]  # SimpleNamespace stub stands in for the real AIMessageChunk

    def test_an_object_block_with_no_reasoning_text_contributes_nothing(self) -> None:
        """The "" default is what makes a reasoning-typed block with no text a no-op; any other default would inject junk into the persisted thinking."""
        from types import SimpleNamespace

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = SimpleNamespace(
            content_blocks=[SimpleNamespace(type="reasoning")], additional_kwargs={}
        )
        assert extract_reasoning_delta(chunk) == ""  # type: ignore[arg-type]  # SimpleNamespace stub stands in for the real AIMessageChunk

    def test_reasoning_across_several_blocks_is_concatenated_unseparated(self) -> None:
        """One chunk can carry the thinking split across blocks; anything joined between them would show up as literal characters in the think block."""
        from langchain_core.messages import AIMessageChunk

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = AIMessageChunk(
            content=[
                {"type": "reasoning", "reasoning": "first "},
                {"type": "reasoning", "reasoning": "second"},
            ]
        )
        assert extract_reasoning_delta(chunk) == "first second"

    def test_a_non_string_reasoning_content_is_stringified(self) -> None:
        """Stringify a non-string reasoning_content value instead of dropping it."""
        from types import SimpleNamespace

        from app.agents.llm.reasoning import extract_reasoning_delta

        chunk = SimpleNamespace(
            content_blocks=[], additional_kwargs={"reasoning_content": ["a", "b"]}
        )
        assert extract_reasoning_delta(chunk) == "['a', 'b']"  # type: ignore[arg-type]  # SimpleNamespace stub stands in for the real AIMessageChunk

    def test_a_non_reasoning_chunk_yields_nothing(self) -> None:
        """Returns "" rather than None so the caller emits no frame at all for a plain model — an empty reasoning frame would render an empty think block."""
        from langchain_core.messages import AIMessageChunk

        from app.agents.llm.reasoning import extract_reasoning_delta

        assert extract_reasoning_delta(AIMessageChunk(content="hello")) == ""
