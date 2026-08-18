"""Photon (Spectrum) management API client.

Used for iMessage account linking on Photon's shared-number pool: a recipient
must be registered as a project user before Photon will deliver to them, and
registration assigns them their pool number. Runtime messaging is NOT done
here — the iMessage bot process owns that via the spectrum-ts SDK.
"""

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config.settings import settings
from app.utils.errors import create_error

SPECTRUM_API_BASE = "https://spectrum.photon.codes"
_REQUEST_TIMEOUT_SECONDS = 15.0
_SHARED_USER_TYPE = "shared"
_REGISTER_FAILURE = "Could not register your number for iMessage"
_UNREGISTER_FAILURE = "Could not disconnect your number from iMessage"
_RETRY_FIX = "verify the Photon project credentials and plan user limit, then retry"


class PhotonUser(BaseModel):
    id: str
    phoneNumber: str
    assignedPhoneNumber: str


class _ListedPhotonUser(PhotonUser):
    type: str


_PhotonUserT = TypeVar("_PhotonUserT", bound=PhotonUser)


def _auth() -> tuple[str, str]:
    if not settings.SPECTRUM_PROJECT_ID or not settings.SPECTRUM_PROJECT_SECRET:
        raise create_error(
            message="iMessage is not configured",
            why="SPECTRUM_PROJECT_ID / SPECTRUM_PROJECT_SECRET are not set",
            fix="set the Photon project credentials in the API environment",
            status_code=501,
        )
    return (settings.SPECTRUM_PROJECT_ID, settings.SPECTRUM_PROJECT_SECRET)


async def _photon_request(
    method: str,
    path: str,
    failure_message: str,
    *,
    payload: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Call the project-scoped Photon management API and unwrap its `{succeed, data}` envelope."""
    auth = _auth()
    url = f"{SPECTRUM_API_BASE}/projects/{auth[0]}{path}"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, auth=auth) as client:
            resp = await client.request(method, url, json=payload, params=params)
    except httpx.RequestError as exc:
        raise create_error(
            message=failure_message,
            why=f"Photon could not be reached for {method} {path}: {type(exc).__name__}: {exc}",
            fix="check outbound network access to spectrum.photon.codes, then retry",
            status_code=502,
        ) from exc

    if not resp.is_success:
        raise create_error(
            message=failure_message,
            why=f"Photon returned HTTP {resp.status_code} for {method} {path}",
            fix=_RETRY_FIX,
            status_code=502,
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise create_error(
            message=failure_message,
            why=f"Photon returned a non-JSON body for {method} {path}",
            fix=_RETRY_FIX,
            status_code=502,
        ) from exc

    if not isinstance(body, dict):
        raise create_error(
            message=failure_message,
            why=f"Photon returned a JSON {type(body).__name__}, not an envelope, for {method} {path}",
            fix=_RETRY_FIX,
            status_code=502,
        )

    if body.get("succeed") is not True:
        raise create_error(
            message=failure_message,
            why=(
                f"Photon returned an unsuccessful envelope for {method} {path}: "
                f"code={body.get('code')} message={body.get('message')}"
            ),
            fix=_RETRY_FIX,
            status_code=502,
        )

    data = body.get("data")
    if not isinstance(data, dict):
        raise create_error(
            message=failure_message,
            why=f"Photon envelope for {method} {path} carried no `data` object",
            fix=_RETRY_FIX,
            status_code=502,
        )
    return data


def _parse_user(model: type[_PhotonUserT], data: object, failure_message: str) -> _PhotonUserT:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise create_error(
            message=failure_message,
            why=f"Photon user payload could not be parsed: {exc.errors(include_url=False)}",
            fix=_RETRY_FIX,
            status_code=502,
        ) from exc


async def register_shared_user(phone_number: str) -> PhotonUser:
    """Register the project user for a phone number (idempotent on Photon's side)."""
    data = await _photon_request(
        "POST",
        "/users/",
        _REGISTER_FAILURE,
        payload={"type": _SHARED_USER_TYPE, "phoneNumber": phone_number},
    )
    return _parse_user(PhotonUser, data, _REGISTER_FAILURE)


async def unregister_shared_user(phone_number: str) -> bool:
    """Delete the shared project user for a phone number; False when there is none to delete."""
    listing = await _photon_request(
        "GET",
        "/users/",
        _UNREGISTER_FAILURE,
        params={"type": _SHARED_USER_TYPE, "search": phone_number},
    )
    entries = listing.get("users")
    if not isinstance(entries, list):
        raise create_error(
            message=_UNREGISTER_FAILURE,
            why="Photon user listing carried no `users` array",
            fix=_RETRY_FIX,
            status_code=502,
        )

    users = [_parse_user(_ListedPhotonUser, entry, _UNREGISTER_FAILURE) for entry in entries]
    match = next(
        (u for u in users if u.phoneNumber == phone_number and u.type == _SHARED_USER_TYPE),
        None,
    )
    if match is None:
        return False

    await _photon_request("DELETE", f"/users/{match.id}/", _UNREGISTER_FAILURE)
    return True


def redirect_deep_link(photon_user_id: str) -> str:
    """Public Photon URL that 302s to the sms: deep link for the user's assigned number."""
    return f"{SPECTRUM_API_BASE}/users/{photon_user_id}/redirect"
