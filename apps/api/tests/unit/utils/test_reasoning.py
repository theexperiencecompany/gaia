"""Tests for reading a model's thinking off a streamed chunk."""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestExtractReasoningDelta:
    """Shared by comms and the subagent runner, so one extractor serves both —
    comms thinking used to be dropped entirely because only the runner had it."""

    def test_reads_standard_reasoning_content_blocks(self) -> None:
        from langchain_core.messages import AIMessageChunk

        from app.utils.reasoning import extract_reasoning_delta

        chunk = AIMessageChunk(
            content=[
                {"type": "reasoning", "reasoning": "we"},
                {"type": "text", "text": "ignored"},
            ]
        )
        assert extract_reasoning_delta(chunk) == "we"

    def test_deepseek_style_reasoning_content_is_extracted(self) -> None:
        """DeepSeek-style providers put thinking in additional_kwargs — LangChain
        normalises that into a reasoning content block, so it arrives via the
        block path rather than the explicit fallback below."""
        from langchain_core.messages import AIMessageChunk

        from app.utils.reasoning import extract_reasoning_delta

        chunk = AIMessageChunk(
            content="", additional_kwargs={"reasoning_content": "thinking"}
        )
        assert extract_reasoning_delta(chunk) == "thinking"

    def test_the_additional_kwargs_fallback_still_works(self) -> None:
        """Covers the branch a normalised AIMessageChunk can no longer reach: a
        chunk-like object exposing no reasoning block but carrying the raw kwarg.
        Kept for provider/version drift, so it must stay exercised."""
        from types import SimpleNamespace

        from app.utils.reasoning import extract_reasoning_delta

        raw = SimpleNamespace(
            content_blocks=[], additional_kwargs={"reasoning_content": "raw"}
        )
        assert extract_reasoning_delta(raw) == "raw"  # type: ignore[arg-type]

    def test_a_non_reasoning_chunk_yields_nothing(self) -> None:
        """Returns "" rather than None so the caller emits no frame at all for a
        plain model — an empty reasoning frame would render an empty think block."""
        from langchain_core.messages import AIMessageChunk

        from app.utils.reasoning import extract_reasoning_delta

        assert extract_reasoning_delta(AIMessageChunk(content="hello")) == ""
