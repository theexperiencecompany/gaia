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

from app.agents.middleware.style_guard import StyleGuardMiddleware, build_correction_note
from app.constants.agents import AgentTag
from app.constants.llm import LANE_FIELD_ID, PROVIDER_NAME_METADATA_KEY, UNKNOWN_MODEL_NAME
from app.constants.log_tags import LogTag

#: Every detector at once, in the register the production replies used. The
#: closing hook is the reflexive shape (offer + justification clause) — a
#: plain offer is a legitimate nudge and does not count as a violation.
DIRTY_DRAFT = (
    "it's not a feature, it's a switching cost — that's the whole point.\n\n"
    "want me to draft that? that's the only move that matters."
)
CLEAN_REWRITE = "that's a switching cost, and it's the whole point. i can draft it."
WORSE_REWRITE = (
    "honestly, here's the thing — it's not a feature, it's a switching cost.\n\n"
    "**One**: lock-in.\n**Two**: pricing.\n**Three**: support.\n\n"
    "should i draft that? that's the piece that actually matters."
)
#: Three em dashes: exactly as many tells as ``DIRTY_DRAFT``, so a rewrite that
#: scores this one ties rather than regresses.
TIED_REWRITE = "a — b — c — d"


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


def _draft(text: str, message_id: str | None) -> AIMessage:
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
        assert "want me to draft that? that's the only" in note.text
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

    async def test_a_clean_draft_still_records_the_whole_style_guard_namespace(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """A turn that was never regenerated writes the same five fields as one
        that was. Without them, "the guard did nothing" and "the guard never ran"
        are the same absence on the wide event."""
        handler = _ScriptedHandler(_draft(CLEAN_REWRITE, "m1"))

        with patch("app.agents.middleware.style_guard.log") as logger:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        (namespace,) = logger.set_ns.call_args.args
        assert namespace == "style_guard"
        assert logger.set_ns.call_args.kwargs == {
            "violations_before": 0,
            "violations_after": 0,
            "regenerated": False,
            "regressed": False,
            "detectors": [],
        }

    async def test_a_draft_the_provider_gave_no_id_still_retracts(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """Bots key nothing by message id — they hold the text streamed since the
        last boundary and drop it — so an id-less draft must still emit a frame,
        with an empty id rather than a placeholder."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, None), _draft(CLEAN_REWRITE, "m2"))

        await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert emitted_frames == [{"message_boundary": {"message_id": "", "discarded": True}}]

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

    async def test_a_rewrite_that_ties_the_draft_is_not_a_regression(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """``regressed`` means strictly worse, not "no better". A tie is the
        model swapping one tell for another, which is a different story from the
        rewrite actively making the reply worse."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(TIED_REWRITE, "m2"))

        with patch("app.agents.middleware.style_guard.log") as logger:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        fields = logger.set_ns.call_args.kwargs
        assert fields["violations_before"] == 3
        assert fields["violations_after"] == 3
        assert fields["regressed"] is False

    async def test_the_retracted_draft_cost_lands_on_the_wide_event(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The spend is deliberately kept out of the event's ``model`` totals, so
        this field is the only place a regenerated turn's second call is visible."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        with (
            patch(
                "app.agents.middleware.style_guard.record_llm_call",
                new_callable=AsyncMock,
                return_value=0.0042,
            ),
            patch("app.agents.middleware.style_guard.log") as logger,
        ):
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert logger.set_ns.call_args.kwargs["retracted_cost_usd"] == 0.0042

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

    async def test_an_empty_rewrite_keeps_the_draft_text_instead_of_ending_in_silence(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The second call can come back with nothing — truncated, refused, or
        dropped by the provider. The draft is already retracted and cannot be
        un-retracted, so returning the empty rewrite would end the turn in
        silence AND persist an empty reply."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft("", "m2"))

        with patch("app.agents.middleware.style_guard.log") as logger:
            response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert response.result[0].text == DIRTY_DRAFT
        # ...under the rewrite's id, so the thread's history stays coherent.
        assert response.result[0].id == "m2"
        (message,) = logger.error.call_args.args
        assert message == (
            f"{LogTag.AGENT} Style guard rewrite came back empty; keeping the draft text"
        )
        assert logger.error.call_args.kwargs == {
            "agent_name": "comms_agent",
            "violations_before": 3,
        }

    async def test_a_rewrite_call_that_returns_nothing_at_all_keeps_the_draft_id(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The provider can hand back a response with no message in it, not just
        an empty one. There is no rewrite id to inherit then, so the draft's own
        id is what the delivered message keeps."""
        responses = [
            ModelResponse(result=[_draft(DIRTY_DRAFT, "m1")]),
            ModelResponse(result=[]),
        ]

        async def handler(request: ModelRequest) -> ModelResponse:
            return responses.pop(0)

        with patch("app.agents.middleware.style_guard.log") as logger:
            response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert response.result[0].text == DIRTY_DRAFT
        assert response.result[0].id == "m1"
        assert logger.error.called, "an empty rewrite is a failure, not a quiet fallback"

    async def test_a_rewrite_that_chose_to_call_a_tool_is_returned_untouched(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """Carrying tool calls means the model decided to act rather than
        answer. Substituting the draft's text would strand the work it asked
        for; the graph's own preamble handling covers the text it rode in on."""
        acting = AIMessage(
            content="",
            id="m2",
            tool_calls=[{"name": "call_executor", "args": {"task": "x"}, "id": "c1"}],
        )
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), acting)

        response = await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert response.result[0].tool_calls[0]["id"] == "c1"
        assert response.result[0].text == ""

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
        assert charged["usage"]["input_tokens"] == 900
        assert charged["usage"]["output_tokens"] == 40
        assert charged["usage"]["cached_tokens"] == 800
        assert charged["context"].charge_to_budget is True

    async def test_the_retracted_draft_lands_in_the_ledger_with_the_turns_own_identity(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The draft the user paid for and never saw is a real call, so its ledger
        row has to name the same conversation and the same model as the reply that
        replaced it — otherwise the turn's cost breakdown is missing a call that
        has no obvious home."""
        draft = _draft(DIRTY_DRAFT, "m1")
        draft.usage_metadata = {"input_tokens": 900, "output_tokens": 40, "total_tokens": 940}
        draft.response_metadata = {
            "model_name": "served/model",
            "id": "gen-abc123",
            "finish_reason": "stop",
            PROVIDER_NAME_METADATA_KEY: "StreamLake",
        }
        interactive_run["configurable"]["conversation_source"] = "web"
        interactive_run["configurable"]["conversation_id"] = "conv-1"
        interactive_run["configurable"]["thread_id"] = "executor_conv-1"
        interactive_run["configurable"]["workflow_id"] = "wf-1"
        handler = _ScriptedHandler(draft, _draft(CLEAN_REWRITE, "m2"))

        with patch(
            "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
        ) as record:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        context = record.call_args.kwargs["context"]
        assert context.agent_name == "comms_agent"
        assert context.background is False
        assert context.conversation_id == "conv-1"
        assert context.thread_id == "executor_conv-1"
        assert context.workflow_id == "wf-1"
        assert context.model_served == "served/model"
        assert context.generation_id == "gen-abc123"
        # The surface the turn came from, and why the draft stopped — the
        # retraction is a real call and its row has to answer both.
        assert context.channel == "web"
        assert context.finish_reason == "stop"
        assert context.provider == "StreamLake"
        # Nothing here timed the draft: it arrives already finished, so an
        # invented latency would be worse than no latency.
        assert context.duration_ms is None

    async def test_a_retracted_draft_is_not_background_system_work(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The user asked for this turn — they just never saw this draft of it.
        Recording it as ``system`` would move real user spend into the bucket
        for work nobody requested."""
        draft = _draft(DIRTY_DRAFT, "m1")
        draft.usage_metadata = {"input_tokens": 900, "output_tokens": 40, "total_tokens": 940}
        handler = _ScriptedHandler(draft, _draft(CLEAN_REWRITE, "m2"))

        with patch(
            "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
        ) as record:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert record.call_args.kwargs["context"].channel is None

    async def test_the_retracted_draft_is_charged_what_the_provider_said_it_cost(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """The pricing table carries ONE rate per model while OpenRouter routes
        the same model to upstreams more than 10x apart, so a table-priced
        retraction charges the user's budget the wrong amount. When the reply
        says what it cost, that figure is what gets booked."""
        draft = _draft(DIRTY_DRAFT, "m1")
        draft.usage_metadata = {
            "input_tokens": 900,
            "output_tokens": 40,
            "total_tokens": 940,
            "input_token_details": {"cache_read": 800},
        }
        draft.response_metadata = {"cost": 0.0041}
        handler = _ScriptedHandler(draft, _draft(CLEAN_REWRITE, "m2"))

        with patch(
            "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
        ) as record:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert record.call_args.kwargs["provider_cost"] == 0.0041

    async def test_a_draft_with_no_reported_price_falls_back_to_the_table(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """Direct Gemini and the sim lane never report one; passing anything but
        ``None`` there would book an invented figure."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        with patch(
            "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
        ) as record:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        assert record.call_args.kwargs["provider_cost"] is None

    async def test_the_charge_carries_the_run_s_lane_model_and_root_request(
        self, emitted_frames: list[dict[str, Any]]
    ) -> None:
        """Priced against the wrong model, or filed outside the request it
        belongs to, the spend is still money the user paid and cannot be traced
        back to the turn that spent it."""
        config: RunnableConfig = {
            "configurable": {
                "user_id": "u1",
                "execution_mode": "interactive",
                LANE_FIELD_ID: {"provider": "gemini", "model": "gemini-2.5-flash"},
                "root_request_id": "req-42",
            }
        }
        draft = _draft(DIRTY_DRAFT, "m1")
        draft.usage_metadata = {
            "input_tokens": 900,
            "output_tokens": 40,
            "total_tokens": 940,
            "output_token_details": {"reasoning": 12},
        }
        handler = _ScriptedHandler(draft, _draft(CLEAN_REWRITE, "m2"))

        with (
            patch("app.agents.middleware.style_guard.current_run_config", return_value=config),
            patch(
                "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
            ) as record,
        ):
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        charged = record.call_args.kwargs
        assert charged["model_name"] == "gemini-2.5-flash"
        assert charged["root_request_id"] == "req-42"
        assert charged["usage"]["reasoning_tokens"] == 12

    async def test_a_run_with_no_lane_is_charged_against_the_unknown_model(
        self, emitted_frames: list[dict[str, Any]], interactive_run: RunnableConfig
    ) -> None:
        """A bag written before lanes existed carries no lane. The draft was
        still paid for, so it is billed under a named placeholder rather than
        dropped or billed under ``None``."""
        handler = _ScriptedHandler(_draft(DIRTY_DRAFT, "m1"), _draft(CLEAN_REWRITE, "m2"))

        with patch(
            "app.agents.middleware.style_guard.record_llm_call", new_callable=AsyncMock
        ) as record:
            await StyleGuardMiddleware().awrap_model_call(_request(), handler)

        charged = record.call_args.kwargs
        assert charged["model_name"] == UNKNOWN_MODEL_NAME
        assert charged["root_request_id"] is None

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
        assert properties == {
            "violations_before": 3,
            "violations_after": 0,
            "detectors": ["closing_hook", "em_dash", "negation_antithesis"],
        }
        assert not any(DIRTY_DRAFT[:20] in str(value) for value in properties.values())


@pytest.mark.unit
class TestCorrectionNoteRendering:
    """The note IS the second prompt, so its exact text is the contract — a
    dropped separator, a re-cased header or a missing count is a different
    instruction reaching the model, and nothing downstream would notice."""

    def test_the_note_is_rendered_verbatim(self) -> None:
        assert build_correction_note(DIRTY_DRAFT) == (
            "<style_correction>\n"
            "Your draft violated the voice rules:\n"
            '- the "not X, it\'s Y" antithesis ×1: "not a feature, it\'s"\n'
            "- em dashes ×1: \"eature, it's a switching cost — that's the whole point.\"\n"
            '- a closing offer to do the next thing ×1: "want me to draft that? that\'s the only"\n'
            "Rewrite the same reply without them. Keep every fact, id, link and number. "
            "Keep the bubble breaks.\n"
            "</style_correction>\n"
        )

    def test_the_count_is_the_real_one_even_though_only_three_snippets_are_quoted(self) -> None:
        """The whole list would just re-send the draft; the count is what tells
        the model the three it can see are not all of them."""
        assert build_correction_note("honestly, here's the thing. real talk. good question.") == (
            "<style_correction>\n"
            "Your draft violated the voice rules:\n"
            '- stock filler phrases ×4: "here\'s the thing"; "honestly"; "real talk"\n'
            "Rewrite the same reply without them. Keep every fact, id, link and number. "
            "Keep the bubble breaks.\n"
            "</style_correction>\n"
        )


@pytest.mark.unit
class TestCorrectionNoteVocabulary:
    def test_every_scored_detector_has_a_rule_description(self) -> None:
        """The note is built by looking each fired detector up by its score
        field. A detector added to the scorer without a description here would
        silently drop out of the note."""
        from app.agents.evals.ai_isms import VIOLATION_FIELDS
        from app.constants.style_guard import STYLE_GUARD_RULES

        assert set(STYLE_GUARD_RULES) == set(VIOLATION_FIELDS)
