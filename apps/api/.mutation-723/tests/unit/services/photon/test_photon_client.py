"""Tests for app/services/photon/photon_client.py"""

from base64 import b64encode
from collections.abc import Iterator
from contextlib import contextmanager
import json
from unittest.mock import patch

import httpx
import pytest

from app.services.photon import photon_client
from app.services.photon.photon_client import (
    _REQUEST_TIMEOUT_SECONDS,
    PhotonUser,
    redirect_deep_link,
    register_shared_user,
    unregister_shared_user,
)
from app.utils.errors import AppError

# Spelled out rather than imported: importing the module's own constants would
# compare a mutated value against itself, so a wrong string would still pass.
REGISTER_FAILURE_MESSAGE = "Could not register your number for iMessage"
UNREGISTER_FAILURE_MESSAGE = "Could not disconnect your number from iMessage"
RETRY_FIX = "verify the Photon project credentials and plan user limit, then retry"
NETWORK_FIX = "check outbound network access to spectrum.photon.codes, then retry"
PARSE_WHY_PREFIX = "Photon user payload could not be parsed: "
PYDANTIC_DOC_URL = "https://errors.pydantic.dev"

PHONE = "+9779743679108"
USERS_URL = "https://spectrum.photon.codes/projects/pid/users/"

PHOTON_USER_PAYLOAD = {
    "succeed": True,
    "data": {
        "id": "63506fde-32a7-4da9-bfe1-a88f6c25d52a",
        "projectId": "d5b07b02-0000-4000-8000-000000000000",
        "type": "shared",
        "phoneNumber": PHONE,
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


def _listing(*users: dict[str, object]) -> dict[str, object]:
    return {"succeed": True, "data": {"users": list(users), "total": len(users)}}


def _assert_photon_error(exc: AppError, *, message: str, why: str, fix: str) -> None:
    """Every Photon failure carries the same four-field 502 contract."""
    assert exc.message == message
    assert exc.why == why
    assert exc.fix == fix
    assert exc.status_code == 502


_RealAsyncClient = httpx.AsyncClient


@contextmanager
def _photon(handler: httpx.MockTransport) -> Iterator[list[dict[str, object]]]:
    """Patch settings + AsyncClient, yielding the kwargs each client was built with."""
    client_kwargs: list[dict[str, object]] = []

    def build(**kwargs: object) -> httpx.AsyncClient:
        client_kwargs.append(kwargs)
        return _RealAsyncClient(
            transport=handler, base_url="https://spectrum.photon.codes", auth=kwargs.get("auth")
        )

    with (
        patch.object(photon_client.settings, "SPECTRUM_PROJECT_ID", "pid"),
        patch.object(photon_client.settings, "SPECTRUM_PROJECT_SECRET", "sec"),
        patch.object(httpx, "AsyncClient", build),
    ):
        yield client_kwargs


@pytest.mark.unit
class TestRegisterSharedUser:
    async def test_parses_user_from_data_envelope(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=PHOTON_USER_PAYLOAD)

        with _photon(httpx.MockTransport(handler)):
            user = await register_shared_user(PHONE)

        assert user == PhotonUser(
            id="63506fde-32a7-4da9-bfe1-a88f6c25d52a",
            phoneNumber=PHONE,
        )
        assert [(r.method, str(r.url)) for r in seen] == [("POST", USERS_URL)]
        assert json.loads(seen[0].content) == {"type": "shared", "phoneNumber": PHONE}

    async def test_client_carries_the_request_timeout(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=PHOTON_USER_PAYLOAD)
        )
        with _photon(transport) as client_kwargs:
            await register_shared_user(PHONE)

        assert client_kwargs == [{"timeout": _REQUEST_TIMEOUT_SECONDS, "auth": ("pid", "sec")}]

    async def test_transport_failure_raises_bad_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        with _photon(httpx.MockTransport(handler)), pytest.raises(AppError) as exc_info:
            await register_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=REGISTER_FAILURE_MESSAGE,
            why="Photon could not be reached for POST /users/: ConnectTimeout: timed out",
            fix=NETWORK_FIX,
        )

    async def test_redirect_response_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "/elsewhere"})
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=REGISTER_FAILURE_MESSAGE,
            why="Photon returned HTTP 302 for POST /users/",
            fix=RETRY_FIX,
        )

    async def test_non_2xx_raises_app_error(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(402, json={"succeed": False})
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=REGISTER_FAILURE_MESSAGE,
            why="Photon returned HTTP 402 for POST /users/",
            fix=RETRY_FIX,
        )

    async def test_malformed_json_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"not json"))
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=REGISTER_FAILURE_MESSAGE,
            why="Photon returned a non-JSON body for POST /users/",
            fix=RETRY_FIX,
        )

    async def test_json_array_body_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[{"id": "pu-1"}]))
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=REGISTER_FAILURE_MESSAGE,
            why="Photon returned a JSON list, not an envelope, for POST /users/",
            fix=RETRY_FIX,
        )

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
            await register_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=REGISTER_FAILURE_MESSAGE,
            why=(
                "Photon returned an unsuccessful envelope for POST /users/: "
                "code=max_shared_users message=plan limit reached"
            ),
            fix=RETRY_FIX,
        )

    async def test_envelope_without_data_object_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"succeed": True, "data": None})
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=REGISTER_FAILURE_MESSAGE,
            why="Photon envelope for POST /users/ carried no `data` object",
            fix=RETRY_FIX,
        )

    async def test_invalid_user_payload_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"succeed": True, "data": {"id": 17, "phoneNumber": None}}
            )
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await register_shared_user(PHONE)

        error = exc_info.value
        assert error.message == REGISTER_FAILURE_MESSAGE
        assert error.fix == RETRY_FIX
        assert error.status_code == 502
        assert error.why.startswith(PARSE_WHY_PREFIX)
        assert "phoneNumber" in error.why
        # include_url=False keeps pydantic's doc links out of our operator-facing why.
        assert PYDANTIC_DOC_URL not in error.why

    @pytest.mark.parametrize("missing", ["SPECTRUM_PROJECT_ID", "SPECTRUM_PROJECT_SECRET"])
    async def test_unconfigured_credentials_raise(self, missing: str) -> None:
        with (
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_ID", "pid"),
            patch.object(photon_client.settings, "SPECTRUM_PROJECT_SECRET", "sec"),
            patch.object(photon_client.settings, missing, None),
            pytest.raises(AppError) as exc_info,
        ):
            await register_shared_user(PHONE)

        assert exc_info.value.status_code == 501
        assert exc_info.value.message == "iMessage is not configured"
        assert exc_info.value.why == "SPECTRUM_PROJECT_ID / SPECTRUM_PROJECT_SECRET are not set"
        assert exc_info.value.fix == "set the Photon project credentials in the API environment"

    async def test_requests_authenticate_with_project_basic_auth(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["Authorization"])
            return httpx.Response(200, json=PHOTON_USER_PAYLOAD)

        with _photon(httpx.MockTransport(handler)):
            await register_shared_user(PHONE)

        assert seen == [f"Basic {b64encode(b'pid:sec').decode()}"]


@pytest.mark.unit
class TestUnregisterSharedUser:
    async def test_deletes_matching_shared_user(self) -> None:
        seen: list[tuple[str, str]] = []
        params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            if request.method == "GET":
                params.append(dict(request.url.params))
                return httpx.Response(200, json=_listing(_listed_user("pu-1", PHONE)))
            return httpx.Response(200, json={"succeed": True, "data": {"userId": "pu-1"}})

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user(PHONE)

        assert deleted is True
        assert seen == [
            ("GET", "/projects/pid/users/"),
            ("DELETE", "/projects/pid/users/pu-1/"),
        ]
        assert params == [{"type": "shared", "search": PHONE}]

    async def test_no_match_returns_false_without_deleting(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(200, json=_listing())

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user(PHONE)

        assert deleted is False
        assert seen == ["GET"]

    async def test_fuzzy_only_match_returns_false_without_deleting(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(200, json=_listing(_listed_user("pu-9", PHONE + "1")))

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user(PHONE)

        assert deleted is False
        assert seen == ["GET"]

    async def test_dedicated_user_is_not_deleted(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(
                200, json=_listing(_listed_user("pu-2", PHONE, user_type="dedicated"))
            )

        with _photon(httpx.MockTransport(handler)):
            deleted = await unregister_shared_user(PHONE)

        assert deleted is False
        assert seen == ["GET"]

    async def test_delete_failure_raises_bad_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json=_listing(_listed_user("pu-1", PHONE)))
            return httpx.Response(500, json={"succeed": False, "code": "internal"})

        with _photon(httpx.MockTransport(handler)), pytest.raises(AppError) as exc_info:
            await unregister_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=UNREGISTER_FAILURE_MESSAGE,
            why="Photon returned HTTP 500 for DELETE /users/pu-1/",
            fix=RETRY_FIX,
        )

    async def test_listing_transport_failure_raises_bad_gateway(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with _photon(httpx.MockTransport(handler)), pytest.raises(AppError) as exc_info:
            await unregister_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=UNREGISTER_FAILURE_MESSAGE,
            why="Photon could not be reached for GET /users/: ReadTimeout: timed out",
            fix=NETWORK_FIX,
        )

    async def test_listing_without_users_array_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"succeed": True, "data": {"total": 0}})
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await unregister_shared_user(PHONE)

        _assert_photon_error(
            exc_info.value,
            message=UNREGISTER_FAILURE_MESSAGE,
            why="Photon user listing carried no `users` array",
            fix=RETRY_FIX,
        )

    async def test_unparsable_listed_user_raises_bad_gateway(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"succeed": True, "data": {"users": [{"id": "pu-1"}], "total": 1}}
            )
        )
        with _photon(transport), pytest.raises(AppError) as exc_info:
            await unregister_shared_user(PHONE)

        error = exc_info.value
        assert error.message == UNREGISTER_FAILURE_MESSAGE
        assert error.fix == RETRY_FIX
        assert error.status_code == 502
        assert error.why.startswith(PARSE_WHY_PREFIX)
        assert "phoneNumber" in error.why
        assert PYDANTIC_DOC_URL not in error.why


@pytest.mark.unit
class TestRedirectDeepLink:
    def test_builds_public_redirect_url(self) -> None:
        assert redirect_deep_link("pu-1") == "https://spectrum.photon.codes/users/pu-1/redirect"
