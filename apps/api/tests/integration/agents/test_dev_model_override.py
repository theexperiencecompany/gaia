"""DEV_DEFAULT_MODEL=custom sends every consumer to the DEV_LLM_* endpoint, and nowhere else.

One consumer per category, each through its real entry point: the comms and
executor lanes, a structured one-shot, the HIL judge, the browser writer and
text model, memory extraction and the vision describer. The endpoint is faked
at the HTTP seam (respx, Responses API); respx fails any request it has no
route for, so a call that leaked to OpenRouter or Gemini fails the test.
"""

from collections.abc import Iterator
import json
from typing import Any

from browser_use import ChatOpenAI as BrowserUseChatOpenAI
import httpx
from pydantic import BaseModel
import pytest
import respx

from app.agents.llm import dev_lane
from app.agents.llm.client import (
    StructuredCallOptions,
    _build_default_llm,
    ainvoke_structured,
    ainvoke_structured_gemini,
)
from app.agents.llm.lane import AgentRole, resolve_lane
from app.agents.llm.vision.describe import describe_image
from app.config.settings import settings
from app.constants.llm import (
    DEV_CUSTOM_MODEL_OPTION,
    DevLLMApi,
    LLMProviderName,
    ModelUse,
)
from app.services.browser.ledger import RunLedger
from app.services.browser.llm import build_agent_llm, build_text_model

pytestmark = pytest.mark.integration

_BASE_URL = "https://dev-llm.test/v1"
_MODEL = "gpt-6-luna"


class _Answer(BaseModel):
    text: str


@pytest.fixture(autouse=True)
def forced_custom_lane(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Throw the one switch, with every other provider configured so a leak has somewhere to go."""
    for name, value in {
        "ENV": "development",
        "GAIA_SIM_MODE": False,
        "DEV_DEFAULT_MODEL": DEV_CUSTOM_MODEL_OPTION,
        "DEV_LLM_BASE_URL": _BASE_URL,
        "DEV_LLM_API_KEY": "dev-key",
        "DEV_LLM_MODEL": _MODEL,
        "DEV_LLM_API": DevLLMApi.RESPONSES,
        "OPENROUTER_API_KEY": "or-key",
        "GOOGLE_API_KEY": "g-key",
    }.items():
        monkeypatch.setattr(settings, name, value)
    dev_lane.build_custom_chat_model.cache_clear()
    _build_default_llm.cache_clear()
    yield
    dev_lane.build_custom_chat_model.cache_clear()
    _build_default_llm.cache_clear()


def _function_call_reply(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": _MODEL,
        "output": [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": name,
                "arguments": json.dumps(arguments),
                "status": "completed",
            }
        ],
        "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
    }


def _answer_every_tool(request: httpx.Request) -> httpx.Response:
    """Answer whichever schema the request offers, the way a model filling it would."""
    tool = json.loads(request.content)["tools"][0]
    return httpx.Response(200, json=_function_call_reply(tool["name"], {"text": "done"}))


@pytest.fixture
def endpoint() -> Iterator[respx.Route]:
    with respx.mock() as router:
        yield router.post(f"{_BASE_URL}/responses").mock(side_effect=_answer_every_tool)


def _sent(route: respx.Route) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(route.calls.last.request.content)
    return body


@pytest.mark.parametrize("role", [AgentRole.COMMS, AgentRole.EXECUTOR])
async def test_a_top_level_run_of_any_role_starts_on_the_custom_lane(role: AgentRole) -> None:
    """No request picked a model: a background narration or a workflow run gets the switch too."""
    lane, plan = await resolve_lane(None, role)

    assert lane.provider == LLMProviderName.CUSTOM
    assert lane.reasoning is None
    assert plan is None


async def test_a_structured_one_shot_runs_on_the_endpoint(endpoint: respx.Route) -> None:
    result = await ainvoke_structured(_Answer, "say done", label="override_test")

    assert result == _Answer(text="done")
    assert _sent(endpoint)["model"] == _MODEL


async def test_the_hil_judge_runs_on_the_endpoint_not_its_pinned_model(
    endpoint: respx.Route,
) -> None:
    await ainvoke_structured(
        _Answer,
        "judge this",
        label="override_test",
        options=StructuredCallOptions(use=ModelUse.JUDGE),
    )

    sent = _sent(endpoint)
    assert sent["model"] == _MODEL
    assert "models" not in sent


def test_the_browser_text_model_runs_on_the_endpoint() -> None:
    text_model = build_text_model(RunLedger())._inner

    assert isinstance(text_model, BrowserUseChatOpenAI)
    assert text_model.model == _MODEL
    assert str(text_model.base_url) == _BASE_URL
    # Browser-Use's client speaks chat completions, where gpt-6-luna rejects "minimal".
    assert text_model.reasoning_effort == "low"


async def test_the_browser_agent_runs_on_the_endpoint_at_low_effort() -> None:
    agent_model = (await build_agent_llm(None, RunLedger()))._inner

    assert isinstance(agent_model, BrowserUseChatOpenAI)
    assert (agent_model.model, str(agent_model.base_url)) == (_MODEL, _BASE_URL)
    assert agent_model.reasoning_effort == "low"


async def test_memory_extraction_runs_on_the_endpoint(endpoint: respx.Route) -> None:
    result = await ainvoke_structured_gemini(_Answer, "a transcript", label="memory:extract")

    assert result == _Answer(text="done")
    assert endpoint.call_count == 1


async def test_a_failed_memory_call_does_not_fall_back_to_gemini() -> None:
    """Respx has no Gemini route, so a fallback attempt would surface as its error instead."""
    with respx.mock() as router:
        router.post(f"{_BASE_URL}/responses").mock(side_effect=httpx.ConnectError("down"))

        with pytest.raises(Exception, match="Connection error") as raised:
            await ainvoke_structured_gemini(_Answer, "a transcript", label="memory:extract")

    assert "respx" not in type(raised.value).__module__


def _streamed_text_reply(text: str) -> bytes:
    """Build the Responses API event stream for one assistant message carrying text."""
    started: dict[str, Any] = {"id": "resp_1", "object": "response", "created_at": 0}
    part: dict[str, Any] = {"type": "output_text", "text": text, "annotations": []}
    message: dict[str, Any] = {"type": "message", "id": "msg_1", "role": "assistant"}
    events: list[dict[str, Any]] = [
        {
            "type": "response.created",
            "response": {**started, "status": "in_progress", "output": []},
        },
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**message, "content": []},
        },
        {
            "type": "response.content_part.added",
            "output_index": 0,
            "item_id": "msg_1",
            "content_index": 0,
            "part": {**part, "text": ""},
        },
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "item_id": "msg_1",
            "content_index": 0,
            "delta": text,
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {**message, "content": [part]},
        },
        {
            "type": "response.completed",
            "response": {
                **started,
                "status": "completed",
                "output": [{**message, "content": [part]}],
            },
        },
    ]
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': index})}\n\n"
        for index, event in enumerate(events)
    ).encode()


async def test_the_vision_describer_runs_on_the_endpoint() -> None:
    """The describer streams, like every client the endpoint builds."""
    with respx.mock() as router:
        route = router.post(f"{_BASE_URL}/responses").mock(
            return_value=httpx.Response(
                200,
                content=_streamed_text_reply("a red barn"),
                headers={"content-type": "text/event-stream"},
            )
        )

        description = await describe_image("QkFTRTY0", "image/png", prompt="what is this?")

    assert description == "a red barn"
    sent = _sent(route)
    assert sent["model"] == _MODEL
    assert [part["type"] for part in sent["input"][0]["content"]] == ["input_text", "input_image"]
