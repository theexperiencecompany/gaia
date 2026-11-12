"""Every JEV caller names a failed call with the one classification beside the transport."""

import json

import httpx
from pydantic import BaseModel, ValidationError
import pytest

from app.constants.hil import JevFailure
from app.services.hil.jev_client import JevUnconfiguredError, jev_failure


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
