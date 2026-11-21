"""Every JEV caller names a failed call with the one classification beside the transport."""

import json

import httpx
from pydantic import BaseModel, ValidationError
import pytest

from app.constants.hil import JevFailure
from app.services.hil import jev_client
from app.services.hil.jev_client import JevUnconfiguredError, jev_failure, post_decisions
from app.services.providers.provider_credentials_service import ProviderConfig


class _Shape(BaseModel):
    answers: dict[str, float]


def _validation_error() -> ValidationError:
    try:
        _Shape.model_validate({"answers": "nope"})
    except ValidationError as e:
        return e
    raise AssertionError("unreachable")


def _status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://jev.example/decisions")
    return httpx.HTTPStatusError("502", request=request, response=httpx.Response(502))


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (JevUnconfiguredError("no key"), JevFailure.UNCONFIGURED),
        (TimeoutError(), JevFailure.TIMEOUT),
        (httpx.ReadTimeout("slow"), JevFailure.TIMEOUT),
        (httpx.ConnectTimeout("slow"), JevFailure.TIMEOUT),
        (httpx.PoolTimeout("slow"), JevFailure.TIMEOUT),
        (ValueError("unknown JEV choice"), JevFailure.MALFORMED),
        (json.JSONDecodeError("bad", "x", 0), JevFailure.MALFORMED),
        (_validation_error(), JevFailure.MALFORMED),
        (httpx.ConnectError("refused"), JevFailure.ERROR),
        (_status_error(), JevFailure.ERROR),
        (RuntimeError("boom"), JevFailure.ERROR),
    ],
)
def test_each_exception_names_its_failure(error: Exception, failure: JevFailure) -> None:
    assert jev_failure(error) is failure


def test_the_values_are_the_labels_the_trigger_gate_alert_reads() -> None:
    assert [f.value for f in JevFailure] == [
        "jev_error",
        "jev_timeout",
        "jev_malformed",
        "jev_unconfigured",
    ]


@pytest.mark.parametrize(
    ("base_url", "decisions"),
    [
        (None, "https://openrouter.ai/api/alpha/decisions"),
        ("http://127.0.0.1:9797/api/v1", "http://127.0.0.1:9797/api/alpha/decisions"),
        ("http://127.0.0.1:9797/api/v1/", "http://127.0.0.1:9797/api/alpha/decisions"),
    ],
)
async def test_a_development_openrouter_base_moves_the_decisions_call_with_it(
    monkeypatch: pytest.MonkeyPatch, base_url: str | None, decisions: str
) -> None:
    """Regression: the approval judge posted to openrouter.ai past a test stack's model server, so every call asked."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"answers": {}})

    async def configured(_provider: object) -> ProviderConfig:
        return ProviderConfig(api_key="sk-or-test", base_url=base_url)

    monkeypatch.setattr(jev_client, "resolve", configured)
    monkeypatch.setattr(
        jev_client, "jev_http_client", httpx.AsyncClient(transport=httpx.MockTransport(answer))
    )

    await post_decisions({}, {})

    assert [str(request.url) for request in seen] == [decisions]
