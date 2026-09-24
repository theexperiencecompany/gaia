"""The wire contract with OpenRouter's decisions endpoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from app.constants.browser import JEV_GATEWAY_MAX_ATTEMPTS, JEV_GATEWAY_TIMEOUT_SECONDS
from app.constants.log_tags import LogTag
from app.services.browser.jev import gateway
from app.services.browser.jev.gateway import (
    JevChoiceQuestion,
    JevEvaluationRequest,
    JevFailoverClient,
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


def _client(handler, provider: str = "openrouter", **kwargs) -> JevGatewayClient:
    return JevGatewayClient(
        api_key="sk-or-test",
        model="~typesafe/jev-latest",
        url="https://openrouter.ai/api/alpha/decisions",
        provider=provider,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def _one_second_per_read(monkeypatch) -> None:
    """Advance the gateway's clock a whole second on every read, so each latency is exact."""
    ticks = iter(range(1000))
    monkeypatch.setattr(gateway, "perf_counter", lambda: float(next(ticks)))


_REQUEST_BYTES = len(
    json.dumps({"model": "~typesafe/jev-latest", **REQUEST.model_dump(mode="json")})
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


async def test_gateway_reported_cost_is_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                **ANSWER,
                "providerMetadata": {"gateway": {"cost": "0", "marketCost": "0.00001302"}},
            },
        )

    evaluation = await _client(handler).evaluate(REQUEST)

    assert evaluation.gateway_cost_usd == 0.0


async def test_missing_cost_metadata_reports_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ANSWER)

    evaluation = await _client(handler).evaluate(REQUEST)

    assert evaluation.gateway_cost_usd is None


async def test_an_answer_is_attributed_to_the_gateway_that_served_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ANSWER)

    evaluation = await _client(handler, provider="vercel").evaluate(REQUEST)

    assert evaluation.provider == "vercel"


def _no_sleep(monkeypatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("app.services.browser.jev.gateway.asyncio.sleep", fake_sleep)


async def test_a_primary_that_exhausts_its_retries_hands_the_same_request_to_the_fallback(
    monkeypatch,
) -> None:
    _no_sleep(monkeypatch)
    primary_bodies: list[dict] = []
    fallback_bodies: list[dict] = []

    def primary(request: httpx.Request) -> httpx.Response:
        primary_bodies.append(json.loads(request.content))
        return httpx.Response(503, json={"error": {"message": "Service temporarily unavailable"}})

    def fallback(request: httpx.Request) -> httpx.Response:
        fallback_bodies.append(json.loads(request.content))
        return httpx.Response(200, json=ANSWER)

    client = JevFailoverClient(
        primary=_client(primary, provider="vercel"),
        fallback=_client(fallback, provider="openrouter"),
    )

    evaluation = await client.evaluate(REQUEST)

    assert evaluation.answers["operation"].choice == "DONE"
    assert evaluation.provider == "openrouter"
    assert len(primary_bodies) == 3, "the primary gets every retry before the fallback is asked"
    assert len(fallback_bodies) == 1
    assert primary_bodies[0]["state"] == fallback_bodies[0]["state"]
    assert primary_bodies[0]["questions"] == fallback_bodies[0]["questions"]


async def test_the_fallback_is_never_asked_when_the_primary_answers() -> None:
    fallback_calls = 0

    def primary(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ANSWER)

    def fallback(request: httpx.Request) -> httpx.Response:
        nonlocal fallback_calls
        fallback_calls += 1
        return httpx.Response(200, json=ANSWER)

    client = JevFailoverClient(
        primary=_client(primary, provider="vercel"),
        fallback=_client(fallback, provider="openrouter"),
    )

    evaluation = await client.evaluate(REQUEST)

    assert evaluation.provider == "vercel"
    assert fallback_calls == 0


async def test_a_transport_failure_on_the_primary_also_fails_over() -> None:
    def primary(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    def fallback(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ANSWER)

    client = JevFailoverClient(
        primary=_client(primary, provider="vercel"),
        fallback=_client(fallback, provider="openrouter"),
    )

    assert (await client.evaluate(REQUEST)).provider == "openrouter"


async def test_both_gateways_failing_surfaces_the_fallbacks_error(monkeypatch) -> None:
    _no_sleep(monkeypatch)

    def primary(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "primary down"}})

    def fallback(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "fallback limited"}})

    client = JevFailoverClient(
        primary=_client(primary, provider="vercel"),
        fallback=_client(fallback, provider="openrouter"),
    )

    with pytest.raises(JevGatewayError, match="returned HTTP 429: fallback limited"):
        await client.evaluate(REQUEST)


async def test_an_evaluation_reports_the_whole_round_trip_it_took(monkeypatch) -> None:
    _one_second_per_read(monkeypatch)

    evaluation = await _client(lambda _r: httpx.Response(200, json=ANSWER)).evaluate(REQUEST)

    assert evaluation.latency_ms == 2000


async def test_a_refusal_is_traced_with_what_was_sent_and_how_long_it_took(monkeypatch) -> None:
    """The wide-event warning is all an operator has to tell a slow gateway from a bad request."""
    _one_second_per_read(monkeypatch)
    logger = MagicMock()
    monkeypatch.setattr(gateway, "log", logger)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "unknown model"}})

    with pytest.raises(JevGatewayError):
        await _client(handler, provider="vercel").evaluate(REQUEST)

    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev gateway refused",
        provider="vercel",
        status_code=400,
        error="unknown model",
        attempt=1,
        max_attempts=JEV_GATEWAY_MAX_ATTEMPTS,
        request_bytes=_REQUEST_BYTES,
        latency_ms=1000,
    )


async def test_a_transport_failure_is_traced_the_same_way(monkeypatch) -> None:
    _one_second_per_read(monkeypatch)
    logger = MagicMock()
    monkeypatch.setattr(gateway, "log", logger)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(JevGatewayError):
        await _client(handler, provider="vercel").evaluate(REQUEST)

    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev gateway request failed",
        provider="vercel",
        attempt=1,
        max_attempts=JEV_GATEWAY_MAX_ATTEMPTS,
        request_bytes=_REQUEST_BYTES,
        latency_ms=1000,
        error_type="ConnectError",
    )


async def test_a_failover_is_traced_naming_both_gateways_and_why(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(gateway, "log", logger)

    def primary(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = JevFailoverClient(
        primary=_client(primary, provider="vercel"),
        fallback=_client(lambda _r: httpx.Response(200, json=ANSWER), provider="openrouter"),
    )

    await client.evaluate(REQUEST)

    failed_over = logger.warning.call_args_list[-1]
    assert failed_over.args == (f"{LogTag.BROWSER} Jev decision failed over",)
    assert failed_over.kwargs == {
        "provider": "vercel",
        "fallback_provider": "openrouter",
        "error_type": "JevGatewayError",
        "error": "Jev decisions request failed: refused (vercel); no action executed.",
    }


def test_a_failover_client_decides_with_the_primarys_model() -> None:
    """Jev meters and labels every decision by this model."""
    primary = _client(lambda _r: httpx.Response(200, json=ANSWER), provider="vercel")
    primary.model = "typesafe/jev-latest"

    client = JevFailoverClient(primary=primary, fallback=_client(lambda _r: None))

    assert client.model == "typesafe/jev-latest"


def test_a_gateway_that_never_answers_cannot_hold_a_step_forever() -> None:
    client = JevGatewayClient(api_key="k", model="m", url="https://x.test", provider="vercel")

    assert client._client.timeout == httpx.Timeout(JEV_GATEWAY_TIMEOUT_SECONDS)


@pytest.mark.parametrize(
    "body",
    [
        "x" * 300,
        json.dumps({"detail": "x" * 300}),
        json.dumps({"error": {"code": 500}, "detail": "x" * 300}),
    ],
    ids=["not-json", "no-error-object", "error-without-message-or-type"],
)
async def test_an_unreadable_refusal_quotes_the_first_200_characters_of_the_body(
    body: str,
) -> None:
    """Enough to recognise the page a proxy answered with, not the whole of it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=body)

    with pytest.raises(JevGatewayError) as err:
        await _client(handler).evaluate(REQUEST)

    assert f": {body[:200]}; no action executed." in str(err.value)


async def test_a_refusal_prefers_the_gateways_message_over_its_error_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"message": "Model not found", "type": "invalid_request"}}
        )

    with pytest.raises(JevGatewayError, match="HTTP 404: Model not found;"):
        await _client(handler).evaluate(REQUEST)
