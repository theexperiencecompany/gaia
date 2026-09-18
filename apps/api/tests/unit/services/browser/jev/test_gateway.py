"""The wire contract with OpenRouter's decisions endpoint."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.browser.jev.gateway import (
    JevChoiceQuestion,
    JevEvaluationRequest,
    JevGatewayClient,
    JevGatewayError,
)

pytestmark = pytest.mark.unit

REQUEST = JevEvaluationRequest(
    state={"page": {"url": "https://x", "title": "X", "text": "hi"}, "elements": []},
    questions={
        "operation": JevChoiceQuestion(
            instructions={"goal": "g", "rules": ["r"]}, criteria={"DONE": "done", "WAIT": "wait"}
        )
    },
)
ANSWER = {
    "answers": {
        "operation": {
            "type": "choice",
            "choice": "DONE",
            "probabilities": {"DONE": 0.9, "WAIT": 0.1},
        }
    },
    "usage": {"inputTokens": 120, "outputTokens": 4},
    "warnings": [],
}


def _client(handler, **kwargs) -> JevGatewayClient:
    return JevGatewayClient(
        api_key="sk-or-test",
        model="~typesafe/jev-latest",
        url="https://openrouter.ai/api/alpha/decisions",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


async def test_the_request_names_the_model_in_the_body_the_endpoint_expects() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ANSWER)

    evaluation = await _client(handler).evaluate(REQUEST)

    (request,) = seen
    assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
    assert request.headers["authorization"] == "Bearer sk-or-test"
    body = json.loads(request.content)
    # The model rides in the body here, not in a header as the old gateway wanted.
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "~typesafe/jev-latest"
    assert body["questions"]["operation"] == {
        "type": "choice",
        "instructions": {"goal": "g", "rules": ["r"]},
        "criteria": {"DONE": "done", "WAIT": "wait"},
    }
    assert evaluation.answers["operation"].choice == "DONE"
    assert evaluation.answers["operation"].probabilities == {"DONE": 0.9, "WAIT": 0.1}
    assert evaluation.usage is not None
    assert (evaluation.usage.input_tokens, evaluation.usage.output_tokens) == (120, 4)
    assert evaluation.latency_ms >= 0


async def test_a_transient_429_is_retried_then_succeeds(monkeypatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.services.browser.jev.gateway.asyncio.sleep", fake_sleep)
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(
            status, json=ANSWER if status == 200 else {"error": {"message": "slow"}}
        )

    evaluation = await _client(handler).evaluate(REQUEST)

    assert evaluation.answers["operation"].choice == "DONE"
    assert sleeps == [0.5, 1.0]


async def test_a_persistent_429_surfaces_after_the_last_attempt(monkeypatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("app.services.browser.jev.gateway.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    with pytest.raises(JevGatewayError, match="HTTP 429: rate limited"):
        await _client(handler).evaluate(REQUEST)


async def test_a_gateway_refusal_names_the_gateways_own_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {"message": "AI Gateway requires a valid credit card on file", "type": "x"}
            },
        )

    with pytest.raises(JevGatewayError) as err:
        await _client(handler).evaluate(REQUEST)

    assert str(err.value) == (
        "Jev decisions returned HTTP 403: AI Gateway requires a valid credit card on file; "
        "no action executed."
    )


async def test_a_non_json_error_body_is_truncated_into_the_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(JevGatewayError, match="HTTP 502: <html>bad gateway</html>"):
        await _client(handler).evaluate(REQUEST)


async def test_a_connection_failure_is_a_gateway_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(JevGatewayError, match="request failed: refused"):
        await _client(handler).evaluate(REQUEST)


async def test_a_malformed_answer_set_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"answers": {"operation": {"type": "boolean", "probability": 1}}}
        )

    with pytest.raises(ValueError):
        await _client(handler).evaluate(REQUEST)
