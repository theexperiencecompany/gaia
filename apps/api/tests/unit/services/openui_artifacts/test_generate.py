"""generate.py: what the artifact model is asked, how its stream is read and what the call is billed as."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
import os
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseRefusalDeltaEvent,
    ResponseTextDeltaEvent,
)
import pytest
import time_machine

from app.constants.llm import ARTIFACT_MODEL_NAME, ARTIFACT_REASONING_EFFORT
from app.constants.openui_artifacts import (
    ARTIFACT_MAX_OUTPUT_TOKENS,
    ARTIFACT_PROMPTS_DIR,
    ARTIFACT_REPAIR_INSTRUCTION,
)
from app.constants.providers import CredentialProviderName
from app.models.openui_artifact_models import ArtifactKind
from app.services.openui_artifacts import generate
from app.services.openui_artifacts.generate import (
    ARTIFACT_PROMPTS,
    ArtifactModelNotConfiguredError,
    ArtifactRefusedError,
    ArtifactRequest,
    generate_reply,
    repair_input,
    repair_program,
    write_program,
)

_GEN = "app.services.openui_artifacts.generate"
USER_ID = "6ad86cdfb9e7ae0b43a0efea"
REQUEST = ArtifactRequest(
    kind=ArtifactKind.REPORT, brief="Sign-ups 1,840", user_id=USER_ID, conversation_id="conv-1"
)


def _delta(text: str) -> ResponseTextDeltaEvent:
    return ResponseTextDeltaEvent.model_construct(delta=text)


def _completed(
    input_tokens: int = 100, output_tokens: int = 40, cached: int = 30, reasoning: int = 5
) -> ResponseCompletedEvent:
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached),
        output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
    )
    return ResponseCompletedEvent.model_construct(response=SimpleNamespace(usage=usage))


def _stream(*events: object) -> AsyncIterator[object]:
    async def run() -> AsyncIterator[object]:
        for event in events:
            yield event

    return run()


class Calls:
    def __init__(self) -> None:
        self.create = AsyncMock()
        self.meter = MagicMock()
        self.spawn = MagicMock()


@pytest.fixture
def model() -> Iterator[Calls]:
    calls = Calls()
    client = MagicMock()
    client.responses.create = calls.create
    with (
        patch(f"{_GEN}._client", AsyncMock(return_value=client)),
        patch(f"{_GEN}.record_llm_call", calls.meter),
        patch(f"{_GEN}.spawn_background_task", calls.spawn),
    ):
        yield calls


async def test_the_request_names_the_artifact_model_its_kind_prompt_and_a_cache_key(
    model: Calls,
) -> None:
    model.create.return_value = _stream(_completed())

    await generate_reply(REQUEST, "the input")

    model.create.assert_awaited_once_with(
        model=ARTIFACT_MODEL_NAME,
        instructions=ARTIFACT_PROMPTS[ArtifactKind.REPORT],
        input="the input",
        reasoning={"effort": ARTIFACT_REASONING_EFFORT},
        max_output_tokens=ARTIFACT_MAX_OUTPUT_TOKENS,
        prompt_cache_key="artifact-openui-report",
        stream=True,
    )


def test_every_kind_has_its_own_prompt_read_from_its_file() -> None:
    assert set(ARTIFACT_PROMPTS) == set(ArtifactKind)
    for kind, prompt in ARTIFACT_PROMPTS.items():
        assert prompt == (ARTIFACT_PROMPTS_DIR / f"{kind.value}.txt").read_text(encoding="utf-8")
        assert prompt.strip()
    assert len(set(ARTIFACT_PROMPTS.values())) == len(ArtifactKind)


async def test_deltas_reach_the_sink_in_order_and_make_the_reply_text(model: Calls) -> None:
    model.create.return_value = _stream(_delta("root = "), _delta("A()\n"), _completed())
    sink = AsyncMock()

    reply = await generate_reply(REQUEST, "in", sink)

    assert [c.args[0] for c in sink.await_args_list] == ["root = ", "A()\n"]
    assert reply.text == "root = A()\n"


async def test_a_reply_needs_no_sink(model: Calls) -> None:
    model.create.return_value = _stream(_delta("x"), _completed())

    assert (await generate_reply(REQUEST, "in")).text == "x"


async def test_the_reply_carries_what_the_call_cost(model: Calls) -> None:
    model.create.return_value = _stream(_delta("x"), _completed(100, 40, 30))

    reply = await generate_reply(REQUEST, "in")

    assert (reply.input_tokens, reply.output_tokens, reply.cached_tokens) == (100, 40, 30)


async def test_a_reply_that_never_completed_costs_nothing_and_is_not_metered(
    model: Calls,
) -> None:
    model.create.return_value = _stream(_delta("x"))

    reply = await generate_reply(REQUEST, "in")

    assert (reply.input_tokens, reply.output_tokens, reply.cached_tokens) == (0, 0, 0)
    model.spawn.assert_not_called()


async def test_the_first_component_is_timed_when_the_second_line_completes(
    model: Calls,
) -> None:
    model.create.return_value = _stream(_delta("root = A\n"), _delta("b = B\n"), _completed())
    with patch(f"{_GEN}.time.perf_counter", side_effect=[1.0, 1.25, 1.5, 1.75]):
        reply = await generate_reply(REQUEST, "in")

    assert reply.first_component_ms == 250.0


async def test_a_reply_that_stops_after_one_line_has_no_first_component_time(
    model: Calls,
) -> None:
    model.create.return_value = _stream(_delta("root = A\n"), _completed())

    assert (await generate_reply(REQUEST, "in")).first_component_ms is None


async def test_the_call_is_billed_to_the_user_under_the_artifact_tool(model: Calls) -> None:
    model.create.return_value = _stream(_delta("x"), _completed(100, 40, 30, 5))
    with patch(f"{_GEN}.time.perf_counter", side_effect=[2.0, 2.5]):
        await generate_reply(REQUEST, "in")

    kwargs = model.meter.call_args.kwargs
    assert kwargs["user_id"] == USER_ID
    assert kwargs["model_name"] == ARTIFACT_MODEL_NAME
    assert kwargs["usage"] == {
        "input_tokens": 100,
        "output_tokens": 40,
        "cached_tokens": 30,
        "reasoning_tokens": 5,
    }
    context = kwargs["context"]
    assert (context.agent_name, context.background, context.charge_to_budget) == (
        "create_artifact",
        False,
        True,
    )
    assert (context.conversation_id, context.duration_ms) == ("conv-1", 500.0)
    assert model.spawn.call_args.kwargs == {"name": "artifact_meter_call"}
    assert model.spawn.call_args.args[0] is model.meter.return_value


async def test_a_call_with_no_cache_detail_bills_zero_cached_and_reasoning_tokens(
    model: Calls,
) -> None:
    bare = ResponseCompletedEvent.model_construct(
        response=SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=7,
                output_tokens=3,
                input_tokens_details=None,
                output_tokens_details=None,
            )
        )
    )
    model.create.return_value = _stream(_delta("x"), bare)

    reply = await generate_reply(REQUEST, "in")

    assert model.meter.call_args.kwargs["usage"] == {
        "input_tokens": 7,
        "output_tokens": 3,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
    }
    assert reply.cached_tokens == 0


async def test_a_refusal_in_the_stream_fails_loud_and_the_call_is_still_closed(
    model: Calls,
) -> None:
    model.create.return_value = _stream(_delta("x"), ResponseRefusalDeltaEvent.model_construct())

    with pytest.raises(ArtifactRefusedError) as refused:
        await generate_reply(REQUEST, "in")

    assert refused.value.message == "the artifact model refused the request"


@pytest.mark.parametrize("key", [None, ""])
async def test_without_an_openai_key_the_error_says_where_to_set_one(key: str | None) -> None:
    config = None if key is None else SimpleNamespace(api_key=key)
    with patch(f"{_GEN}.resolve", AsyncMock(return_value=config)) as resolver:
        with pytest.raises(ArtifactModelNotConfiguredError) as refused:
            await generate._client()

    resolver.assert_awaited_once_with(CredentialProviderName.OPENAI)
    assert refused.value.message == "artifacts need an OpenAI key"
    assert refused.value.fix == (
        "set OPENAI_API_KEY or add an OpenAI credential in Settings > Providers"
    )


async def test_a_configured_key_builds_the_client() -> None:
    with (
        patch(f"{_GEN}.resolve", AsyncMock(return_value=SimpleNamespace(api_key="sk-test"))),
        patch(f"{_GEN}.AsyncOpenAI") as client,
    ):
        built = await generate._client()

    client.assert_called_once_with(api_key="sk-test")
    assert built is client.return_value


@time_machine.travel(datetime(2026, 11, 3, 9, 0, tzinfo=UTC), tick=False)
async def test_a_first_draft_is_asked_for_with_the_date_above_the_brief(model: Calls) -> None:
    model.create.return_value = _stream(_delta("root = A"), _completed())
    sink = AsyncMock()

    await write_program(REQUEST, sink)

    assert model.create.await_args.kwargs["input"] == "Today is 03 November 2026.\n\nSign-ups 1,840"
    sink.assert_awaited_once_with("root = A")


@time_machine.travel(datetime(2026, 11, 3, 20, 0, tzinfo=UTC), tick=False)
async def test_the_date_is_todays_in_utc_whatever_zone_the_server_runs_in(model: Calls) -> None:
    model.create.return_value = _stream(_completed())
    with patch.dict(os.environ, {"TZ": "Pacific/Auckland"}):
        time.tzset()
        try:
            await write_program(REQUEST, AsyncMock())
        finally:
            os.environ.pop("TZ", None)
    time.tzset()

    assert model.create.await_args.kwargs["input"].startswith("Today is 03 November 2026.")


@time_machine.travel(datetime(2026, 11, 3, 9, 0, tzinfo=UTC), tick=False)
async def test_a_repair_is_asked_for_with_the_program_and_each_problem(model: Calls) -> None:
    model.create.return_value = _stream(_completed())

    await repair_program(REQUEST, "root = A", ["p1", "p2"])

    assert model.create.await_args.kwargs["input"] == (
        "Today is 03 November 2026.\n\nSign-ups 1,840\n\nYour program:\nroot = A\n\n"
        f"Problems:\n- p1\n- p2\n{ARTIFACT_REPAIR_INSTRUCTION}."
    )


def test_the_repair_input_lists_one_problem_per_line() -> None:
    text: Any = repair_input("brief", "prog", ["a", "b"])

    assert (
        text
        == f"brief\n\nYour program:\nprog\n\nProblems:\n- a\n- b\n{ARTIFACT_REPAIR_INSTRUCTION}."
    )
