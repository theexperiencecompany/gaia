"""Tests for app/services/photon/photon_client.py"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.services.photon import photon_client
from app.services.photon.photon_client import (
    PhotonUser,
    redirect_deep_link,
    register_shared_user,
    unregister_shared_user,
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


def _listed_user(user_id: str, phone_number: str, user_type: str = "shared") -> dict[str, object]:
    return {
        "id": user_id,
        "projectId": "d5b07b02-0000-4000-8000-000000000000",
        "type": user_type,
        "phoneNumber": phone_number,
        "assignedPhoneNumber": "+14155955082",
        "createdAt": "2026-08-14T19:19:47.168Z",
    }


_RealAsyncClient = httpx.AsyncClient


@contextmanager
def _photon(handler: httpx.MockTransport) -> Iterator[None]:
    def build(**_kwargs: object) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=handler, base_url="https://spectrum.photon.codes")

    with (
        patch.object(photon_client.settings, "SPECTRUM_PROJECT_ID", "pid"),
        patch.object(photon_client.settings, "SPECTRUM_PROJECT_SECRET", "sec"),
        patch.object(httpx, "AsyncClient", build),
    ):
        yield


@pytest.mark.unit
class TestRegisterSharedUser:
    async def test_parses_user_from_data_envelope(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path.endswith("/users/")
            return httpx.Response(200, json=PHOTON_USER_PAYLOAD)

        with _photon(httpx.MockTransport(handler)):
            user = await register_shared_user("+9779743679108")

        assert user == PhotonUser(
            id="63506fde-32a7-4da9-bfe1-a88f6c25d52a",
            phoneNumber="+9779743679108",
        )

    async def test_transport_failure_raises_bad_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        with _photon(httpx.MockTransport(handler)), pytest.raises(AppError) as exc_info:
            await register_shared_user("+15551234567")

        assert exc_info.value.status_code == 502
        assert "could not be reached" in exc_info.value.why
        assert "ConnectTimeout" in exc_info.value.why

    async def test_redirect_response_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "/elsewhere"})
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user("+15551234567")

        assert exc_info.value.status_code == 502
        assert "HTTP 302" in exc_info.value.why

    async def test_non_2xx_raises_app_error(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(402, json={"succeed": False})
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user("+15551234567")

        assert exc_info.value.status_code == 502
        assert "HTTP 402" in exc_info.value.why

    async def test_malformed_json_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"not json"))
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user("+15551234567")

        assert exc_info.value.status_code == 502
        assert "non-JSON" in exc_info.value.why

    async def test_unsuccessful_envelope_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "succeed": False,
                    "data": None,
                    "code": "max_shared_users",
                    "message": "plan limit reached",
                },
            )
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user("+15551234567")

        assert exc_info.value.status_code == 502
        assert "unsuccessful envelope" in exc_info.value.why
        assert "max_shared_users" in exc_info.value.why

    async def test_invalid_user_payload_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"succeed": True, "data": {"id": 17, "phoneNumber": None}}
            )
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user("+15551234567")

        assert exc_info.value.status_code == 502
        assert "could not be parsed" in exc_info.value.why

    async def test_unconfigured_credentials_raise(self) -> None:
        with (
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_ID", None),
            pytest.raises(AppError) as exc_info,
        ):
            await register_shared_user("+15551234567")

        assert exc_info.value.status_code == 501


@pytest.mark.unit
class TestUnregisterSharedUser:
    async def test_deletes_matching_shared_user(self) -> None:
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            if request.method == "GET":
                assert request.url.params["search"] == "+9779743679108"
                assert request.url.params["type"] == "shared"
                return httpx.Response(
                    200,
                    json={
                        "succeed": True,
                        "data": {
                            "users": [_listed_user("pu-1", "+9779743679108")],
                            "total": 1,
                        },
                    },
                )
            return httpx.Response(200, json={"succeed": True, "data": {"userId": "pu-1"}})

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user("+9779743679108")

        assert deleted is True
        assert seen == [
            ("GET", "/projects/pid/users/"),
            ("DELETE", "/projects/pid/users/pu-1/"),
        ]

    async def test_no_match_returns_false_without_deleting(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(200, json={"succeed": True, "data": {"users": [], "total": 0}})

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user("+9779743679108")

        assert deleted is False
        assert seen == ["GET"]

    async def test_fuzzy_only_match_returns_false_without_deleting(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(
                200,
                json={
                    "succeed": True,
                    "data": {
                        "users": [_listed_user("pu-9", "+97797436791081")],
                        "total": 1,
                    },
                },
            )

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user("+9779743679108")

        assert deleted is False
        assert seen == ["GET"]

    async def test_dedicated_user_is_not_deleted(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(
                200,
                json={
                    "succeed": True,
                    "data": {
                        "users": [_listed_user("pu-2", "+9779743679108", user_type="dedicated")],
                        "total": 1,
                    },
                },
            )

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user("+9779743679108")

        assert deleted is False
        assert seen == ["GET"]

    async def test_delete_failure_raises_bad_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "succeed": True,
                        "data": {
                            "users": [_listed_user("pu-1", "+9779743679108")],
                            "total": 1,
                        },
                    },
                )
            return httpx.Response(500, json={"succeed": False, "code": "internal"})

        with _photon(httpx.MockTransport(handler)), pytest.raises(AppError) as exc_info:
            await unregister_shared_user("+9779743679108")

        assert exc_info.value.status_code == 502
        assert "HTTP 500" in exc_info.value.why

    async def test_listing_transport_failure_raises_bad_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with _photon(httpx.MockTransport(handler)), pytest.raises(AppError) as exc_info:
            await unregister_shared_user("+9779743679108")

        assert exc_info.value.status_code == 502
        assert "could not be reached" in exc_info.value.why


@pytest.mark.unit
class TestRedirectDeepLink:
    def test_builds_public_redirect_url(self) -> None:
        assert redirect_deep_link("pu-1") == "https://spectrum.photon.codes/users/pu-1/redirect"
