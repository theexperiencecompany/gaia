"""The comms style guard: a draft carrying LLM tells is rewritten, once.

The prompt alone cannot do this. A 60-vs-60 A/B of the old and the rewritten
static comms prompt on real production queries moved nothing: forty turns of the
model's own tell-laden replies sit in context and outvote the instruction. So
the draft is scored in code and, when it scores dirty, sent back with its own
offending fragments quoted.

These tests drive the real middleware against a scripted handler, which is the
same seam ``MiddlewareExecutor.wrap_model_invocation`` builds in production —
the model itself is the only thing faked, because a real model cannot be made
to emit a chosen tell on demand.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.middleware.style_guard import StyleGuardMiddleware
from app.constants.agents import AgentTag

#: Every detector at once, in the register the production replies used.
DIRTY_DRAFT = (
    "it's not a feature, it's a switching cost — that's the whole point.\n\nwant me to draft that?"
)
CLEAN_REWRITE = "that's a switching cost, and it's the whole point. i can draft it."
WORSE_REWRITE = (
    "honestly, here's the thing — it's not a feature, it's a switching cost.\n\n"
    "**One**: lock-in.\n**Two**: pricing.\n**Three**: support.\n\nshould i draft that?"
)


def _request(messages: list[Any] | None = None) -> ModelRequest:
    return ModelRequest(
        model=MagicMock(),
        messages=messages if messages is not None else [HumanMessage(content="why?")],
        system_message=None,
        tools=[],
        state={"messages": []},
        runtime=MagicMock(),
    )


class _ScriptedHandler:
    """Returns the next scripted message per call, recording every request."""

    def __init__(self, *messages: AIMessage) -> None:
        self._messages = list(messages)
        self.requests: list[ModelRequest] = []

    async def __call__(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            result=[self._messages[min(len(self.requests) - 1, len(self._messages) - 1)]]
        )


@pytest.fixture
def emitted_frames() -> Any:
    """Captures what the middleware writes to the graph's custom stream."""
    frames: list[dict[str, Any]] = []
    with patch(
        "app.agents.middleware.style_guard.get_stream_writer",
        return_value=frames.append,
    ):
        yield frames


@pytest.fixture
def interactive_run() -> Any:
    """The ambient run config a chat turn has: interactive, with a user."""
    config: RunnableConfig = {"configurable": {"user_id": "u1", "execution_mode": "interactive"}}
    with patch("app.agents.middleware.style_guard.current_run_config", return_value=config):
        yield config


def _draft(text: str, message_id: str) -> AIMessage:
    return AIMessage(content=text, id=message_id)


@pytest.mark.unit
class TestStyleGuardRegeneration:
    async def test_a_dirty_draft_is_regenerated_once_and_the_rewrite_is_returned(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 2
        assert response.result[0].id == "m2"
        assert response.result[0].text == CLEAN_REWRITE

    async def test_the_retry_quotes_the_draft_and_its_offending_fragments(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """Counts alone ("2 banned phrases") leave the model guessing which words
        to drop. The fragment is what makes the instruction actionable."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        retry_messages = handler.requests[1].messages
        assert retry_messages[-2].text == DIRTY_DRAFT
        note = retry_messages[-1]
        assert isinstance(note, HumanMessage), "Gemini drops a trailing SystemMessage"
        assert AgentTag.STYLE_CORRECTION in note.text
        assert "em dashes" in note.text
        assert "a closing offer to do the next thing" in note.text
        assert "want me to draft that?" in note.text
        assert "Keep every fact, id, link and number." in note.text

    async def test_the_draft_is_retracted_on_the_wire_before_the_rewrite_streams(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The draft's tokens are already on the client by the time it is scored,
        so the only way to take them back is the boundary frame the handoff
        preamble already uses — and it has to land before the replacement text."""
        streamed_at: list[int] = []

        async def handler(request: ModelRequest) -> ModelResponse:
            streamed_at.append(len(emitted_frames))
            index = len(streamed_at) - 1
            return ModelResponse(
                result=[_draft(DIRTY_DRAFT if index == 0 else CLEAN_REWRITE, f"m{index + 1}")]
            )

        await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert emitted_frames == [{"message_boundary": {"message_id": "m1", "discarded": True}}]
        # ...and it was written before the rewrite call started streaming.
        assert streamed_at == [0, 1]

    async def test_a_clean_draft_costs_one_call_and_no_retraction(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        handler = _ScriptedHandler(_draft(CLEAN_REWRITE, "m1"))

        response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 1
        assert response.result[0].id == "m1"
        assert emitted_frames == []

    async def test_a_draft_with_tool_calls_is_never_scored(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """A handoff preamble is discarded wholesale by the driver, and its text
        never reaches the user — regenerating it would buy a second model call to
        improve something nobody reads, and would re-issue the tool call."""
        preamble = AIMessage(
            content=DIRTY_DRAFT,
            id="m1",
            tool_calls=[{"name": "call_executor", "args": {"task": "x"}, "id": "c1"}],
        )
        handler = _ScriptedHandler(preamble)

        response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 1
        assert response.result[0].id == "m1"
        assert emitted_frames == []

    async def test_an_empty_draft_is_never_scored(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        handler = _ScriptedHandler(_draft("   ", "m1"))

        await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 1

    async def test_a_background_run_is_skipped_entirely(
        self, emitted_frames: list[dict[str, Any]]
    ) -> None:
        """Nobody is watching a workflow delivery mid-stream, and it has no live
        client to retract from — the extra call would be paid for nothing."""
        config: RunnableConfig = {"configurable": {"user_id": "u1", "execution_mode": "background"}}
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        with patch("app.agents.middleware.style_guard.current_run_config", return_value=config):
            response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert len(handler.requests) == 1
        assert response.result[0].id == "m1"
        assert emitted_frames == []

    async def test_a_rewrite_that_scores_worse_is_still_delivered_and_recorded(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The draft was retracted on the wire before the rewrite was requested,
        so returning it would persist text every client was told to drop. The
        regression is recorded instead, never silently swallowed."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(WORSE_REWRITE, "m2"))

        with patch("app.agents.middleware.style_guard.log") as logger:
            response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert response.result[0].id == "m2"
        namespaces = dict(logger.set_ns.call_args.kwargs)
        assert namespaces["regressed"] is True
        assert namespaces["violations_after"] > namespaces["violations_before"]

    async def test_the_wide_event_names_the_detectors_that_fired(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        with patch("app.agents.middleware.style_guard.log") as logger:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        (namespace,) = logger.set_ns.call_args.args
        fields = logger.set_ns.call_args.kwargs
        assert namespace == "style_guard"
        assert fields["regenerated"] is True
        assert fields["violations_before"] == 3
        assert fields["violations_after"] == 0
        assert sorted(fields["detectors"]) == ["closing_hook", "em_dash", "negation_antithesis"]

    async def test_the_retracted_draft_is_charged_to_the_user_budget(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """Accounting prices the run from the last AI message in state, and the
        draft never reaches state. Unbilled, a regenerated turn costs two model
        calls and charges for one — which on the free tier, where the daily
        budget is about one turn, silently doubles real spend."""
        draft = _draft(DIRTY_DRAFT, "m1")
        draft.usage_metadata = {
            "input_tokens": 900,
            "output_tokens": 40,
            "total_tokens": 940,
            "input_token_details": {"cache_read": 800},
        }
        handler = _ScriptedHandler(draft, _draft(CLEAN_REWRITE, "m2"))

        with patch(
            "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
        ) as record:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        charged = record.call_args.kwargs
        assert charged["user_id"] == "u1"
        assert charged["input_tokens"] == 900
        assert charged["output_tokens"] == 40
        assert charged["cached_tokens"] == 800
        assert charged["charge_to_budget"] is True

    async def test_a_draft_that_is_never_retracted_is_never_double_charged(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """A clean draft IS the delivered message, so accounting already prices
        it off state. Charging here too would bill the turn twice."""
        handler = _ScriptedHandler(_draft(CLEAN_REWRITE, "m1"))

        with patch(
            "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
        ) as record:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        record.assert_not_called()

    async def test_the_regeneration_is_captured_for_the_user_not_an_anonymous_profile(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """A graph node has no request context, so the distinct id has to be
        passed explicitly or the event lands on a fresh anonymous person."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        with patch("app.agents.middleware.style_guard.capture_event") as capture:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        user_id, event, properties = capture.call_args.args
        assert user_id == "u1"
        assert event == "chat:style_guard_regenerated"
        assert properties["violations_before"] == 3
        assert not any(DIRTY_DRAFT[:20] in str(value) for value in properties.values())


@pytest.mark.unit
class TestCorrectionNoteVocabulary:
    def test_every_scored_detector_has_a_rule_description(self) -> None:
        """The note is built by looking each fired detector up by its score
        field. A detector added to the scorer without a description here would
        silently drop out of the note."""
        from app.agents.evals.ai_isms import VIOLATION_FIELDS
        from app.constants.style_guard import STYLE_GUARD_RULES

        assert set(STYLE_GUARD_RULES) == set(VIOLATION_FIELDS)
