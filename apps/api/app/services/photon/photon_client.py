"""Photon (Spectrum) management API client.

Used for iMessage account linking on Photon's shared-number pool: a recipient
must be registered as a project user before Photon will deliver to them, and
registration assigns them their pool number. Runtime messaging is NOT done
here — the iMessage bot process owns that via the spectrum-ts SDK.
"""

import httpx
from pydantic import BaseModel

from app.config.settings import settings
from app.utils.errors import create_error

SPECTRUM_API_BASE = "https://spectrum.photon.codes"
_REQUEST_TIMEOUT_SECONDS = 15.0


class PhotonUser(BaseModel):
    id: str
    phoneNumber: str


def _auth() -> tuple[str, str]:
    if not settings.SPECTRUM_PROJECT_ID or not settings.SPECTRUM_PROJECT_SECRET:
        raise create_error(
            message="iMessage is not configured",
            why="SPECTRUM_PROJECT_ID / SPECTRUM_PROJECT_SECRET are not set",
            fix="set the Photon project credentials in the API environment",
            status_code=501,
        )
    return (settings.SPECTRUM_PROJECT_ID, settings.SPECTRUM_PROJECT_SECRET)


async def register_shared_user(phone_number: str) -> PhotonUser:
    """Register (or return the existing) project user for a phone number."""
    auth = _auth()
    users_url = f"{SPECTRUM_API_BASE}/projects/{auth[0]}/users/"
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, auth=auth) as client:
        resp = await client.post(users_url, json={"type": "shared", "phoneNumber": phone_number})
        if resp.status_code < 400:
            return PhotonUser.model_validate(resp.json()["data"])

        # Registration is not idempotent on Photon's side — an already-registered
        # phone fails, so fall back to finding the existing user record.
        listing = await client.get(users_url)
        listing.raise_for_status()
        for raw in listing.json()["data"]:
            user = PhotonUser.model_validate(raw)
            if user.phoneNumber == phone_number:
                return user

    raise create_error(
        message="Could not register your number for iMessage",
        why=f"Photon user registration failed with HTTP {resp.status_code}",
        fix="verify the Photon project credentials and plan user limit, then retry",
        status_code=502,
    )


def redirect_deep_link(photon_user_id: str) -> str:
    """Public Photon URL that 302s to the sms: deep link for the user's assigned number."""
    return f"{SPECTRUM_API_BASE}/users/{photon_user_id}/redirect"
