"""Unit tests for the image generation endpoints.

Covers generation, image-to-text, and the SSE streaming route. Service layer
is mocked; status codes, response shapes, validation, and the relayed error
status are verified.
"""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from httpx import AsyncClient

from app.models.chat_models import ImageData
from app.models.image_models import ImageToTextResponse
from tests.conftest import FAKE_USER

API = "/api/v1"

# The `client` fixture's dependency override (`get_current_user` -> FAKE_USER)
# is FastAPI DI, not the WorkOSAuthMiddleware-set request context that
# require_subscription's resolve_caller reads first — the test app strips
# that middleware entirely. So a gate test has to set the context directly to
# exercise the real resolution path, the same way production requests do.
_GET_AUTHENTICATED_USER = "app.core.request_context.get_authenticated_user"


def _image_data(**overrides) -> ImageData:
    base = {
        "url": "https://res.cloudinary.com/test/image.jpg",
        "prompt": "a cat",
        "improved_prompt": "a cat, studio lighting",
    }
    base.update(overrides)
    return ImageData(**base)


# ---------------------------------------------------------------------------
# POST /image/generate
# ---------------------------------------------------------------------------


class TestImageGenerate:
    """POST /api/v1/image/generate"""

    @patch("app.api.v1.endpoints.image.api_generate_image", new_callable=AsyncMock)
    async def test_generate_success(self, mock_generate: AsyncMock, client: AsyncClient):
        mock_generate.return_value = _image_data()
        resp = await client.post(f"{API}/image/generate", json={"message": "a cat"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["url"] == "https://res.cloudinary.com/test/image.jpg"
        assert body["prompt"] == "a cat"
        assert body["improved_prompt"] == "a cat, studio lighting"
        mock_generate.assert_awaited_once_with("a cat")

    async def test_missing_message_is_rejected(self, client: AsyncClient):
        resp = await client.post(f"{API}/image/generate", json={})
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.image.api_generate_image", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_generate: AsyncMock, client: AsyncClient):
        mock_generate.side_effect = HTTPException(status_code=500, detail="Internal Server Error")
        resp = await client.post(f"{API}/image/generate", json={"message": "a cat"})
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(f"{API}/image/generate", json={"message": "a cat"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /image/text
# ---------------------------------------------------------------------------


class TestImageToText:
    """POST /api/v1/image/text"""

    @patch("app.api.v1.endpoints.image.image_to_text_endpoint", new_callable=AsyncMock)
    async def test_image_to_text_success(self, mock_convert: AsyncMock, client: AsyncClient):
        mock_convert.return_value = ImageToTextResponse(response="A cat on a sofa")
        resp = await client.post(
            f"{API}/image/text",
            data={"message": "what is this"},
            files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json() == {"response": "A cat on a sofa"}
        assert mock_convert.await_args.args[0] == "what is this"
        assert mock_convert.await_args.args[1].filename == "photo.png"

    async def test_missing_file_is_rejected(self, client: AsyncClient):
        resp = await client.post(f"{API}/image/text", data={"message": "what is this"})
        assert resp.status_code == 422

    async def test_missing_message_is_rejected(self, client: AsyncClient):
        resp = await client.post(
            f"{API}/image/text",
            files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        )
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.image.image_to_text_endpoint", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_convert: AsyncMock, client: AsyncClient):
        mock_convert.side_effect = HTTPException(status_code=500, detail="Internal Server Error")
        resp = await client.post(
            f"{API}/image/text",
            data={"message": "what is this"},
            files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        )
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            f"{API}/image/text",
            data={"message": "what is this"},
            files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /image/generate/stream
# ---------------------------------------------------------------------------


class TestImageStream:
    """POST /api/v1/image/generate/stream"""

    async def test_stream_emits_status_image_and_done_frames(self, client: AsyncClient):
        async def fake_stream(query_text: str):
            assert query_text == "a cat"
            yield 'data: {"status": "generating_image"}\n\n'
            yield 'data: {"image_data": {"url": "https://cdn/x", "prompt": "a cat", "improved_prompt": null}}\n\n'
            yield "data: [DONE]\n\n"

        with patch("app.api.v1.endpoints.image.generate_image_stream", new=fake_stream):
            resp = await client.post(f"{API}/image/generate/stream", json={"message": "a cat"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert '"status": "generating_image"' in resp.text
        assert '"image_data"' in resp.text
        assert "data: [DONE]" in resp.text

    async def test_stream_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(f"{API}/image/generate/stream", json={"message": "a cat"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Paid-only gate — /image/generate and /image/generate/stream burn real LLM
# spend and must 402 a FREE-plan user before generation ever runs.
# ---------------------------------------------------------------------------


class TestImagePaidOnlyGate:
    @patch("app.api.v1.endpoints.image.api_generate_image", new_callable=AsyncMock)
    async def test_generate_free_user_gets_402(self, mock_generate: AsyncMock, client: AsyncClient):
        with patch(_GET_AUTHENTICATED_USER, return_value=FAKE_USER):
            resp = await client.post(f"{API}/image/generate", json={"message": "a cat"})

        assert resp.status_code == 402
        assert resp.json()["detail"]["code"] == "subscription_required"
        mock_generate.assert_not_called()

    async def test_generate_stream_free_user_gets_402(self, client: AsyncClient):
        with patch(_GET_AUTHENTICATED_USER, return_value=FAKE_USER):
            resp = await client.post(f"{API}/image/generate/stream", json={"message": "a cat"})

        assert resp.status_code == 402
        assert resp.json()["detail"]["code"] == "subscription_required"
