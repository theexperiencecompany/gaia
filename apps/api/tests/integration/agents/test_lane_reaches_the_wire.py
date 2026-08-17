"""What the provider actually receives.

Every other lane test asserts on the configurable — a dict GAIA controls. This one
asserts on the HTTP request body the real ``ChatOpenRouter`` builds from it, which
is the only place the first-party provider pin either exists or does not.

The gap this closes: the pin is the whole reason a paid run stays off throttled
reseller pools, and nothing proved it survived the trip from ``ModelLane`` through
LangChain's ConfigurableField layer onto the wire. It is also where the
provider-failover bug lived — two individually-correct pieces composing wrong —
so a test one layer above the request could not have caught it.

No network: a loopback sink stands in for OpenRouter and records the body. The
sink's canned response deliberately does not satisfy the SDK's response schema —
the request is captured before the response is parsed, and the request is the
subject.
"""

from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
from typing import Any

from langchain_openrouter import ChatOpenRouter
from pydantic import SecretStr
import pytest

from app.agents.llm.client import _openrouter_wire_configurables, without_sdk_retry
from app.agents.llm.lane import ModelLane
from app.agents.llm.types import LLMProviderName
from app.constants.llm import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    PAID_MODEL_MODEL_KWARGS,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER_SLUG,
)

_CAPTURED: list[dict[str, Any]] = []


class _Sink(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        _CAPTURED.append(json.loads(self.rfile.read(length) or b"{}"))
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log."""


@pytest.fixture(scope="module")
def sink_url() -> Any:
    server = HTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/api/v1"
    server.shutdown()


def _lane(*, pin: dict[str, Any] | None, model: str) -> ModelLane:
    return ModelLane(
        provider=LLMProviderName.OPENROUTER,
        model=model,
        reasoning={"effort": "low"},
        provider_pin=pin,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


async def _request_body(configurable: dict[str, Any], sink_url: str) -> dict[str, Any]:
    """Fire one call through the real client and return what it put on the wire.

    The sink's canned response does not satisfy the SDK's schema, so the parse
    raises — after the request has been sent, which is the subject here.
    """
    client = _openrouter_wire_configurables(
        without_sdk_retry(
            ChatOpenRouter(model="unset", api_key=SecretStr("test-key"), base_url=sink_url)
        )
    )
    _CAPTURED.clear()
    with suppress(Exception):
        await client.ainvoke("hi", config={"configurable": configurable})
    assert _CAPTURED, "the client never sent a request"
    return _CAPTURED[0]


async def _request_body_for(lane: ModelLane, sink_url: str) -> dict[str, Any]:
    return await _request_body(dict(lane.binding_keys()), sink_url)


@pytest.mark.integration
class TestLaneReachesTheWire:
    async def test_a_paid_lane_pins_the_first_party_provider_on_the_request(
        self, sink_url: str
    ) -> None:
        body = await _request_body_for(
            _lane(pin=PAID_MODEL_MODEL_KWARGS, model=PAID_MODEL_NAME), sink_url
        )

        assert body["model"] == PAID_MODEL_NAME
        assert body["provider"] == {"only": [PAID_MODEL_PROVIDER_SLUG]}

    async def test_a_free_lane_sends_no_provider_pin_at_all(self, sink_url: str) -> None:
        """Absent, not empty: OpenRouter is then free to route it anywhere, which is
        the documented free-tier behaviour."""
        body = await _request_body_for(_lane(pin=None, model=DEFAULT_MODEL_NAME), sink_url)

        assert body["model"] == DEFAULT_MODEL_NAME
        assert "provider" not in body or body["provider"] is None

    async def test_the_reasoning_budget_reaches_the_request(self, sink_url: str) -> None:
        body = await _request_body_for(_lane(pin=None, model=DEFAULT_MODEL_NAME), sink_url)

        assert body["reasoning"] == {"effort": "low"}

    async def test_a_fallback_lane_carries_neither_the_pin_nor_the_reasoning(
        self, sink_url: str
    ) -> None:
        """Both are OpenRouter-wire concepts. Carrying either onto the provider we
        just failed away from is how a fallback turns one failure into two."""
        paid = _lane(pin=PAID_MODEL_MODEL_KWARGS, model=PAID_MODEL_NAME)
        crossed = ModelLane(
            provider=LLMProviderName.OPENROUTER,  # kept on the wire lane so it is observable
            model="vendor/fallback-model",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )
        rebound = crossed.rebind(dict(paid.binding_keys()))

        body = await _request_body(rebound, sink_url)

        assert body["model"] == "vendor/fallback-model"
        assert "provider" not in body or body["provider"] is None
        assert body.get("reasoning") != {"effort": "low"}
