"""Image generation: GAIA's hosted generator in production, the operator's OpenAI key elsewhere."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.providers.provider_credentials_service import ProviderConfig
from app.utils import image_utils
from app.utils.image_utils import (
    IMAGE_GENERATION_NOT_CONFIGURED_MESSAGE,
    ImageGenerationNotConfiguredError,
    generate_image,
)

_MOD = "app.utils.image_utils"


def _openai(api_key: str | None) -> ProviderConfig:
    return ProviderConfig(api_key=api_key, base_url=None, model=None, preset=None)


class TestProduction:
    async def test_posts_to_the_hosted_generator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_utils.settings, "ENV", "production")
        request = httpx.Request("POST", "https://generateimage.aryanranderiya1478.workers.dev/")
        post = AsyncMock(return_value=httpx.Response(200, content=b"png", request=request))

        with (
            patch.object(image_utils.http_async_client, "post", post),
            patch(f"{_MOD}.AsyncOpenAI") as openai_client,
        ):
            assert await generate_image("a cat") == b"png"

        post.assert_awaited_once_with(
            "https://generateimage.aryanranderiya1478.workers.dev/",
            json={"imageprompt": "a cat"},
        )
        openai_client.assert_not_called()

    async def test_a_generator_failure_raises_instead_of_returning_an_error_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(image_utils.settings, "ENV", "production")
        request = httpx.Request("POST", "https://generateimage.aryanranderiya1478.workers.dev/")
        post = AsyncMock(return_value=httpx.Response(502, request=request))

        with (
            patch.object(image_utils.http_async_client, "post", post),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await generate_image("a cat")


class TestSelfHost:
    @pytest.fixture(autouse=True)
    def _selfhost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(image_utils.settings, "ENV", "selfhost")

    async def test_never_calls_the_hosted_generator(self) -> None:
        post = AsyncMock()
        with (
            patch.object(image_utils.http_async_client, "post", post),
            patch(f"{_MOD}.resolve", AsyncMock(return_value=None)),
            pytest.raises(ImageGenerationNotConfiguredError) as raised,
        ):
            await generate_image("a cat")

        assert str(raised.value) == IMAGE_GENERATION_NOT_CONFIGURED_MESSAGE
        post.assert_not_called()

    async def test_an_openai_key_generates_with_gpt_image_1(self) -> None:
        images = SimpleNamespace(
            generate=AsyncMock(
                return_value=SimpleNamespace(
                    data=[SimpleNamespace(b64_json=base64.b64encode(b"png").decode())]
                )
            )
        )
        client = MagicMock(return_value=SimpleNamespace(images=images))

        resolver = AsyncMock(return_value=_openai("sk-store"))
        with (
            patch(f"{_MOD}.resolve", resolver),
            patch(f"{_MOD}.AsyncOpenAI", client),
        ):
            assert await generate_image("a cat") == b"png"

        resolver.assert_awaited_once_with("openai")
        client.assert_called_once_with(api_key="sk-store")
        images.generate.assert_awaited_once_with(
            model="gpt-image-1", prompt="a cat", size="1024x1024"
        )

    async def test_an_empty_openai_reply_raises(self) -> None:
        images = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(data=[])))

        with (
            patch(f"{_MOD}.resolve", AsyncMock(return_value=_openai("sk-store"))),
            patch(f"{_MOD}.AsyncOpenAI", MagicMock(return_value=SimpleNamespace(images=images))),
            pytest.raises(ValueError, match="^OpenAI image generation returned no image data$"),
        ):
            await generate_image("a cat")
