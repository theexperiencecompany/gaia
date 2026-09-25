"""The forced dev lane: DEV_DEFAULT_MODEL=custom sends every one-shot to the DEV_LLM_* endpoint.

The wire tests fake the endpoint at the HTTP seam (respx), so the OpenAI SDK,
LangChain's Responses parsing and the app's structured-reply parse all run for
real; only the server is simulated.
"""

import asyncio
from collections.abc import Iterator
import json
from typing import Any

import httpx
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.configurable import RunnableConfigurableFields
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
import openai
from pydantic import BaseModel
import pytest
import respx

from app.agents.llm import client as client_module, dev_lane
from app.agents.llm.client import (
    LLMInvokeOptions,
    StructuredCallOptions,
    _build_default_llm,
    ainvoke_llm,
    ainvoke_structured,
    resolve_model,
)
from app.agents.llm.exceptions import LLMNotConfiguredError, MalformedStructuredOutputError
from app.config.settings import settings
from app.constants.llm import (
    AUX_MODEL_NAME,
    DEV_CUSTOM_MODEL_OPTION,
    DEV_LLM_BROWSER_HEADERS,
    DEV_LLM_MAX_OUTPUT_TOKENS,
    HELPER_MAX_OUTPUT_TOKENS,
    LLM_INVOKE_TIMEOUT_SECONDS,
    LLM_RETRY_MAX_ATTEMPTS,
    DevLLMApi,
    ModelUse,
    ReasoningLevel,
)

pytestmark = pytest.mark.unit

_BASE_URL = "https://dev-llm.test/v1"
_MODEL = "gpt-6-luna"
_BROWSER_USER_AGENT = DEV_LLM_BROWSER_HEADERS["User-Agent"]
_CLOUDFLARE_BLOCK = httpx.Response(403, json={"error": {"message": "blocked"}})


class _Answer(BaseModel):
    text: str


@pytest.fixture(autouse=True)
def _fresh_models() -> Iterator[None]:
    dev_lane.build_custom_chat_model.cache_clear()
    _build_default_llm.cache_clear()
    yield
    dev_lane.build_custom_chat_model.cache_clear()
    _build_default_llm.cache_clear()


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the endpoint over the Responses API without forcing any lane onto it."""
    monkeypatch.setattr(settings, "ENV", "development")
    monkeypatch.setattr(settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(settings, "DEV_DEFAULT_MODEL", None)
    monkeypatch.setattr(settings, "DEV_LLM_BASE_URL", _BASE_URL)
    monkeypatch.setattr(settings, "DEV_LLM_API_KEY", "dev-key")
    monkeypatch.setattr(settings, "DEV_LLM_MODEL", _MODEL)
    monkeypatch.setattr(settings, "DEV_LLM_API", DevLLMApi.RESPONSES)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "g-key")


@pytest.fixture
def forced(endpoint: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEV_DEFAULT_MODEL", DEV_CUSTOM_MODEL_OPTION)


def _responses_reply(arguments: str, *, incomplete_reason: str | None = None) -> dict[str, Any]:
    """One Responses API reply carrying a single function call with these raw arguments."""
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "status": "incomplete" if incomplete_reason else "completed",
        "incomplete_details": {"reason": incomplete_reason} if incomplete_reason else None,
        "model": _MODEL,
        "output": [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": _Answer.__name__,
                "arguments": arguments,
                "status": "completed",
            }
        ],
        "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
    }


def _sent(route: respx.Route) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(route.calls.last.request.content)
    return body


class TestTheSwitch:
    @pytest.mark.usefixtures("endpoint")
    def test_the_custom_menu_entry_forces_the_lane(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "DEV_DEFAULT_MODEL", DEV_CUSTOM_MODEL_OPTION)

        assert dev_lane.custom_lane_forced() is True

    @pytest.mark.parametrize("dev_default", [None, "minimax-m3", "not-a-real-id"])
    @pytest.mark.usefixtures("endpoint")
    def test_any_other_default_leaves_every_lane_where_it_was(
        self, monkeypatch: pytest.MonkeyPatch, dev_default: str | None
    ) -> None:
        monkeypatch.setattr(settings, "DEV_DEFAULT_MODEL", dev_default)

        assert dev_lane.custom_lane_forced() is False

    @pytest.mark.usefixtures("forced")
    def test_production_never_forces_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENV", "production")

        assert dev_lane.custom_lane_forced() is False

    @pytest.mark.parametrize("unset", ["DEV_LLM_BASE_URL", "DEV_LLM_API_KEY", "DEV_LLM_MODEL"])
    @pytest.mark.usefixtures("forced")
    def test_a_forced_lane_missing_a_setting_fails_loud_naming_the_settings(
        self, monkeypatch: pytest.MonkeyPatch, unset: str
    ) -> None:
        """Quietly serving OpenRouter instead is the very thing the switch exists to prevent."""
        monkeypatch.setattr(settings, unset, None)

        with pytest.raises(LLMNotConfiguredError, match=unset):
            resolve_model()


class TestEveryOneShotResolvesToTheEndpoint:
    @pytest.mark.parametrize("use", list(ModelUse))
    @pytest.mark.usefixtures("forced")
    def test_every_use_runs_the_endpoints_model_capped_like_a_helper(self, use: ModelUse) -> None:
        llm = resolve_model(use)

        assert isinstance(llm, ChatOpenAI)
        assert llm.model_name == _MODEL
        assert str(llm.openai_api_base) == _BASE_URL
        assert llm.max_tokens == HELPER_MAX_OUTPUT_TOKENS

    @pytest.mark.usefixtures("endpoint")
    def test_a_configured_endpoint_alone_moves_nothing(self) -> None:
        """Production resolution is untouched until the switch is thrown."""
        llm = resolve_model()

        assert isinstance(llm, ChatOpenRouter)
        assert llm.model_name == AUX_MODEL_NAME

    @pytest.mark.usefixtures("forced")
    def test_one_client_serves_every_call_of_one_shape(self) -> None:
        """Each build opens its own httpx pools; per-call builds leak them."""
        assert resolve_model() is resolve_model()


class TestTheApiMode:
    @pytest.mark.usefixtures("forced")
    def test_responses_mode_sends_the_effort_as_a_reasoning_object_and_no_temperature(self) -> None:
        """OpenAI's reasoning models reject any temperature but the default."""
        llm = resolve_model(reasoning=ReasoningLevel.LIGHT, temperature=0.4)

        assert isinstance(llm, ChatOpenAI)
        assert llm.use_responses_api is True
        assert llm.reasoning == {"effort": "low"}
        assert llm.reasoning_effort is None
        assert llm.temperature is None

    @pytest.mark.usefixtures("forced")
    def test_chat_completions_mode_sends_reasoning_effort_and_keeps_the_temperature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "DEV_LLM_API", DevLLMApi.CHAT_COMPLETIONS)

        llm = resolve_model(reasoning=ReasoningLevel.OFF, temperature=0.4)

        assert isinstance(llm, ChatOpenAI)
        assert llm.use_responses_api is False
        assert llm.reasoning_effort == "none"
        assert llm.reasoning is None
        assert llm.temperature == 0.4

    @pytest.mark.usefixtures("forced")
    def test_no_reasoning_level_runs_at_light_effort_not_the_models_medium(self) -> None:
        llm = resolve_model()

        assert isinstance(llm, ChatOpenAI)
        assert llm.reasoning == {"effort": "low"}
        assert llm.reasoning_effort is None

    @pytest.mark.usefixtures("endpoint")
    def test_the_graph_client_keeps_the_endpoints_output_budget(self) -> None:
        llm = client_module.init_custom_llm().loader_func()

        assert isinstance(llm, RunnableConfigurableFields)
        bound = llm.default
        assert isinstance(bound, ChatOpenAI)
        assert bound.use_responses_api is True
        assert bound.max_tokens == DEV_LLM_MAX_OUTPUT_TOKENS


@pytest.mark.usefixtures("forced")
class TestAStructuredCallOverTheResponsesApi:
    async def test_the_tool_call_is_parsed_into_the_schema(self) -> None:
        with respx.mock() as router:
            route = router.post(f"{_BASE_URL}/responses").mock(
                return_value=httpx.Response(200, json=_responses_reply('{"text": "hi"}'))
            )

            result = await ainvoke_structured(
                _Answer,
                "say hi",
                label="dev_lane_test",
                options=StructuredCallOptions(reasoning=ReasoningLevel.OFF),
            )

        assert result == _Answer(text="hi")
        sent = _sent(route)
        assert sent["model"] == _MODEL
        assert sent["reasoning"] == {"effort": "none"}
        # Offered, gpt-6-luna answered in prose; forcing is safe on OpenAI's own API.
        assert sent["tool_choice"] == "required"
        assert sent["stream"] is False
        assert sent["max_output_tokens"] == HELPER_MAX_OUTPUT_TOKENS
        assert "temperature" not in sent

    async def test_arguments_that_are_not_json_raise_malformed_output(self) -> None:
        with respx.mock() as router:
            router.post(f"{_BASE_URL}/responses").mock(
                return_value=httpx.Response(200, json=_responses_reply('{"text": "hi'))
            )

            with pytest.raises(MalformedStructuredOutputError, match="not valid JSON"):
                await ainvoke_structured(
                    _Answer,
                    "say hi",
                    label="dev_lane_test",
                    options=StructuredCallOptions(max_attempts=1),
                )

    async def test_a_reply_cut_at_the_output_cap_raises_malformed_output(self) -> None:
        """The Responses API says so in incomplete_details, not finish_reason; valid-looking JSON is still not the whole answer."""
        reply = _responses_reply(
            '{"text": "The page title is"}', incomplete_reason="max_output_tokens"
        )
        with respx.mock() as router:
            router.post(f"{_BASE_URL}/responses").mock(return_value=httpx.Response(200, json=reply))

            with pytest.raises(MalformedStructuredOutputError, match="output cap"):
                await ainvoke_structured(
                    _Answer,
                    "say hi",
                    label="dev_lane_test",
                    options=StructuredCallOptions(max_attempts=1),
                )


@pytest.mark.usefixtures("forced")
async def test_a_chat_completions_endpoint_is_offered_the_tool_with_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nous-style endpoints keep the offered tool: some reject a forced one in thinking mode."""
    monkeypatch.setattr(settings, "DEV_LLM_API", DevLLMApi.CHAT_COMPLETIONS)
    reply = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": _MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "_Answer", "arguments": '{"text": "hi"}'},
                        }
                    ],
                },
            }
        ],
    }
    with respx.mock() as router:
        route = router.post(f"{_BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=reply)
        )

        result = await ainvoke_structured(
            _Answer,
            "say hi",
            label="dev_lane_test",
            options=StructuredCallOptions(reasoning=ReasoningLevel.OFF, temperature=0.3),
        )

    assert result == _Answer(text="hi")
    sent = _sent(route)
    assert sent["tool_choice"] == "auto"
    assert sent["reasoning_effort"] == "none"
    assert sent["temperature"] == 0.3


def _sse(events: list[dict[str, Any]]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class _Lookup(BaseModel):
    query: str


@pytest.mark.usefixtures("endpoint")
async def test_the_graph_client_streams_a_tool_call_over_the_responses_api() -> None:
    """The agent graph streams: arguments arrive as deltas and must reassemble into one tool call."""
    started = {"id": "resp_1", "object": "response", "created_at": 0, "status": "in_progress"}
    item = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "_Lookup"}
    done = {**item, "arguments": '{"query": "weather"}', "status": "completed"}
    usage = {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}
    events = [
        {"type": "response.created", "sequence_number": 0, "response": {**started, "output": []}},
        {
            "type": "response.output_item.added",
            "sequence_number": 1,
            "output_index": 0,
            "item": {**item, "arguments": "", "status": "in_progress"},
        },
        *(
            {
                "type": "response.function_call_arguments.delta",
                "sequence_number": 2 + index,
                "output_index": 0,
                "item_id": "fc_1",
                "delta": delta,
            }
            for index, delta in enumerate(('{"query": "wea', 'ther"}'))
        ),
        {
            "type": "response.output_item.done",
            "sequence_number": 4,
            "output_index": 0,
            "item": done,
        },
        {
            "type": "response.completed",
            "sequence_number": 5,
            "response": {**started, "status": "completed", "output": [done], "usage": usage},
        },
    ]
    graph_client = client_module.init_custom_llm().loader_func()
    assert isinstance(graph_client, RunnableConfigurableFields)
    chat_model = graph_client.default
    assert isinstance(chat_model, ChatOpenAI)

    with respx.mock() as router:
        route = router.post(f"{_BASE_URL}/responses").mock(
            return_value=httpx.Response(
                200, content=_sse(events), headers={"content-type": "text/event-stream"}
            )
        )
        chunks = [
            chunk
            async for chunk in chat_model.bind_tools([_Lookup]).astream("what is the weather?")
        ]

    pieces = [chunk for chunk in chunks if isinstance(chunk, AIMessageChunk)]
    assert len(pieces) == len(chunks) > 1
    message = pieces[0]
    for piece in pieces[1:]:
        message = message + piece
    assert message.tool_calls == [
        {"name": "_Lookup", "args": {"query": "weather"}, "id": "call_1", "type": "tool_call"}
    ]
    assert message.usage_metadata is not None
    assert message.usage_metadata["total_tokens"] == 10
    assert _sent(route)["stream"] is True


class TestNoCallLeavesTheForcedLane:
    @pytest.mark.usefixtures("forced")
    async def test_a_failed_call_raises_instead_of_falling_back(self) -> None:
        """A fallback is another provider's model: the one thing the switch rules out."""
        primary = RunnableLambda(_refuse)
        fallback = RunnableLambda(_answer)

        with pytest.raises(ConnectionError, match="endpoint down"):
            await ainvoke_llm(
                primary,
                "hi",
                fallback=fallback,
                options=LLMInvokeOptions(max_attempts=1, meter_auxiliary=False),
            )

    @pytest.mark.usefixtures("endpoint")
    async def test_without_the_switch_the_same_failure_still_falls_back(self) -> None:
        result = await ainvoke_llm(
            RunnableLambda(_refuse),
            "hi",
            fallback=RunnableLambda(_answer),
            options=LLMInvokeOptions(max_attempts=1, meter_auxiliary=False),
        )

        assert result.content == "fallback answered"


def _refuse(_: LanguageModelInput) -> AIMessage:
    raise ConnectionError("endpoint down")


def _answer(_: LanguageModelInput) -> AIMessage:
    return AIMessage(content="fallback answered")


@pytest.fixture
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip with_llm_retry's real backoff sleeps; the attempts themselves still run."""
    real_sleep = asyncio.sleep

    async def _no_wait(_seconds: float, result: object = None) -> object:
        return await real_sleep(0, result)

    monkeypatch.setattr(asyncio, "sleep", _no_wait)


@pytest.mark.usefixtures("forced", "no_backoff")
class TestAFailedAttemptOnTheEndpoint:
    """gpt-6-luna stalls now and then (measured: 4 of 48 raw-SDK calls hung past 40 s).

    The attempt must end and be retried, not sit until the 300 s call budget runs out.
    """

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ReadTimeout("stalled"),
            httpx.ConnectError("refused"),
            httpx.Response(429, json={"error": {"message": "slow down"}}),
            httpx.Response(503, json={"error": {"message": "overloaded"}}),
        ],
        ids=["stalled", "refused", "rate-limited", "overloaded"],
    )
    async def test_is_retried_and_the_next_attempt_answers(
        self, failure: httpx.Response | Exception
    ) -> None:
        with respx.mock() as router:
            route = router.post(f"{_BASE_URL}/responses").mock(
                side_effect=[failure, httpx.Response(200, json=_responses_reply('{"text": "hi"}'))]
            )

            result = await ainvoke_structured(_Answer, "say hi", label="dev_lane_test")

        assert result == _Answer(text="hi")
        assert route.call_count == 2

    async def test_a_request_the_endpoint_rejects_is_not_retried(self) -> None:
        """A 400 fails the same way every time; retrying it only burns the budget."""
        with respx.mock() as router:
            route = router.post(f"{_BASE_URL}/responses").mock(
                return_value=httpx.Response(400, json={"error": {"message": "bad param"}})
            )

            with pytest.raises(Exception, match="bad param"):
                await ainvoke_structured(_Answer, "say hi", label="dev_lane_test")

        assert route.call_count == 1

    def test_every_attempt_can_time_out_inside_the_call_budget(self) -> None:
        """With no read timeout the SDK waits 600 s, so one stalled attempt ate the whole 300 s budget."""
        llm = resolve_model()

        assert isinstance(llm, ChatOpenAI)
        assert isinstance(llm.request_timeout, httpx.Timeout)
        read = llm.request_timeout.read
        assert read is not None
        assert read * LLM_RETRY_MAX_ATTEMPTS < LLM_INVOKE_TIMEOUT_SECONDS

    def test_an_unreachable_endpoint_gives_up_before_a_slow_reply_would(self) -> None:
        """A dead host never answers the handshake; waiting the read budget on it wastes the attempt."""
        llm = resolve_model()

        assert isinstance(llm, ChatOpenAI)
        assert isinstance(llm.request_timeout, httpx.Timeout)
        connect, read = llm.request_timeout.connect, llm.request_timeout.read
        assert connect is not None
        assert read is not None
        assert connect < read


@pytest.mark.usefixtures("forced")
class TestTheEndpointsHttpClients:
    async def test_a_failed_request_is_left_to_the_callers_retry_policy(self) -> None:
        """An SDK retry under with_llm_retry multiplies every attempt and its backoff."""
        llm = resolve_model()
        with respx.mock() as router:
            route = router.post(f"{_BASE_URL}/responses").mock(
                return_value=httpx.Response(500, json={"error": {"message": "down"}})
            )

            with pytest.raises(openai.InternalServerError):
                await llm.ainvoke("hi")

        assert route.call_count == 1

    def test_a_sync_request_carries_a_browser_user_agent(self) -> None:
        """Discounted lanes sit behind Cloudflare, which 403s a programmatic user agent."""
        llm = resolve_model()
        with respx.mock() as router:
            route = router.post(f"{_BASE_URL}/responses").mock(return_value=_CLOUDFLARE_BLOCK)

            with pytest.raises(openai.PermissionDeniedError):
                llm.invoke("hi")

        assert route.calls.last.request.headers["user-agent"] == _BROWSER_USER_AGENT

    async def test_an_async_request_carries_a_browser_user_agent(self) -> None:
        llm = resolve_model()
        with respx.mock() as router:
            route = router.post(f"{_BASE_URL}/responses").mock(return_value=_CLOUDFLARE_BLOCK)

            with pytest.raises(openai.PermissionDeniedError):
                await llm.ainvoke("hi")

        assert route.calls.last.request.headers["user-agent"] == _BROWSER_USER_AGENT
