"""Tests for app/services/photon/photon_client.py"""

from unittest.mock import patch

import httpx
import pytest

from app.services.photon import photon_client
from app.services.photon.photon_client import (
    PhotonUser,
    redirect_deep_link,
    register_shared_user,
)
from app.utils.errors import AppError

PHOTON_USER_PAYLOAD = {
    "succeed": True,
    "data": {
        "id": "63506fde-32a7-4da9-bfe1-a88f6c25d52a",
        "projectId": "d5b07b02-0000-4000-8000-000000000000",
        "type": "shared",
        "phoneNumber": "+9779743679108",
        "assignedPhoneNumber": "+14155955082",
        "createdAt": "2026-08-14T19:19:47.168Z",
    },
}


_RealAsyncClient = httpx.AsyncClient


def _client_with(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return _RealAsyncClient(transport=handler, base_url="https://spectrum.photon.codes")


@pytest.mark.unit
class TestRegisterSharedUser:
    async def test_parses_user_from_data_envelope(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path.endswith("/users/")
            return httpx.Response(200, json=PHOTON_USER_PAYLOAD)

        transport = httpx.MockTransport(handler)
        with (
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_ID", "pid"),
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_SECRET", "sec"),
            patch.object(httpx, "AsyncClient", lambda **kw: _client_with(transport)),
        ):
            user = await register_shared_user("+9779743679108")

        assert user == PhotonUser(
            id="63506fde-32a7-4da9-bfe1-a88f6c25d52a",
            phoneNumber="+9779743679108",
        )

    async def test_non_2xx_raises_app_error(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(402, json={"succeed": False})
        )
        with (
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_ID", "pid"),
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_SECRET", "sec"),
            patch.object(httpx, "AsyncClient", lambda **kw: _client_with(transport)),
            pytest.raises(AppError),
        ):
            await register_shared_user("+15551234567")

    async def test_unconfigured_credentials_raise(self) -> None:
        with (
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_ID", None),
            pytest.raises(AppError),
        ):
            await register_shared_user("+15551234567")


@pytest.mark.unit
class TestRedirectDeepLink:
    def test_builds_public_redirect_url(self) -> None:
        assert redirect_deep_link("pu-1") == "https://spectrum.photon.codes/users/pu-1/redirect"
