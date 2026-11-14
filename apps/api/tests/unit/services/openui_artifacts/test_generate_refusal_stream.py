"""Regression: a prompt flagged mid-stream arrives as a plain APIError, not a BadRequestError.

The live bench's second dashboard run hit exactly this ("Invalid prompt: your prompt was
flagged ..."), and generate_reply let it escape as a crash instead of a refusal.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from openai import APIError
import pytest

from app.models.openui_artifact_models import ArtifactKind
from app.services.openui_artifacts.generate import (
    ArtifactRefusedError,
    ArtifactRequest,
    generate_reply,
)

REQUEST = ArtifactRequest(
    kind=ArtifactKind.DASHBOARD, brief="b", user_id="6ad86cdfb9e7ae0b43a0efea", conversation_id=None
)


def _stream_failing_with(code: str) -> AsyncIterator[object]:
    async def events() -> AsyncIterator[object]:
        raise APIError(
            "Invalid prompt: your prompt was flagged",
            httpx.Request("POST", "https://api.openai.com/v1/responses"),
            body={"code": code, "message": "flagged"},
        )
        yield  # pragma: no cover -- makes this an async generator

    return events()


def _client(stream: AsyncIterator[object]) -> MagicMock:
    client = MagicMock()
    client.responses.create = AsyncMock(return_value=stream)
    return client


async def test_a_prompt_flagged_mid_stream_is_a_refusal() -> None:
    client = _client(_stream_failing_with("invalid_prompt"))
    with (
        patch("app.services.openui_artifacts.generate._client", AsyncMock(return_value=client)),
        pytest.raises(ArtifactRefusedError) as refused,
    ):
        await generate_reply(REQUEST, "input")

    assert refused.value.message == "the provider refused the artifact request"


async def test_any_other_stream_error_still_raises_as_itself() -> None:
    client = _client(_stream_failing_with("server_error"))
    with (
        patch("app.services.openui_artifacts.generate._client", AsyncMock(return_value=client)),
        pytest.raises(APIError) as raised,
    ):
        await generate_reply(REQUEST, "input")
    assert not isinstance(raised.value, ArtifactRefusedError)
