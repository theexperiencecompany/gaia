"""Verify a Cloudflare Turnstile token against siteverify before a public form is accepted."""

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config.settings import settings
from app.constants.email import SUPPORT_EMAIL
from app.constants.error_codes import TURNSTILE_UNAVAILABLE, TURNSTILE_VERIFICATION_FAILED
from app.constants.turnstile import (
    TURNSTILE_SITEVERIFY_TIMEOUT_SECONDS,
    TURNSTILE_SITEVERIFY_URL,
)
from app.utils.errors import AppError
from shared.py.wide_events import log


class TurnstileSiteverifyResponse(BaseModel):
    """The fields of Cloudflare's siteverify answer this check reads."""

    success: bool
    error_codes: list[str] = Field(default_factory=list, alias="error-codes")


def _unavailable(cause: str) -> AppError:
    return AppError(
        message="We could not check that you are human right now",
        why="The verification service is unavailable",
        fix=f"Try again in a minute, or email {SUPPORT_EMAIL}",
        status_code=503,
        code=TURNSTILE_UNAVAILABLE,
        meta={"cause": cause},
    )


async def _siteverify(
    secret: str, token: str, remote_ip: str | None
) -> TurnstileSiteverifyResponse:
    form = {"secret": secret, "response": token}
    if remote_ip:
        form["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=TURNSTILE_SITEVERIFY_TIMEOUT_SECONDS) as client:
            response = await client.post(TURNSTILE_SITEVERIFY_URL, data=form)
            response.raise_for_status()
        return TurnstileSiteverifyResponse.model_validate(response.json())
    except (httpx.HTTPError, ValueError, ValidationError) as e:
        log.error("Turnstile siteverify call failed", error=str(e), error_type=type(e).__name__)
        raise _unavailable(f"siteverify failed: {type(e).__name__}") from e


async def verify_turnstile_token(token: str, remote_ip: str | None) -> None:
    """Raise unless Cloudflare confirms the token; a missing secret or siteverify failure is a 503."""
    secret = settings.TURNSTILE_SECRET_KEY
    if not secret:
        log.error("Turnstile secret is not configured", error_type="TurnstileSecretMissing")
        raise _unavailable("TURNSTILE_SECRET_KEY is unset")

    result = await _siteverify(secret, token, remote_ip)
    log.set_ns("turnstile", success=result.success, error_codes=result.error_codes)
    if not result.success:
        log.warning("Turnstile rejected the token", error_codes=result.error_codes)
        raise AppError(
            message="We could not verify that you are human",
            why="The bot check did not pass or has expired",
            fix="Reload the page and submit the form again",
            status_code=400,
            code=TURNSTILE_VERIFICATION_FAILED,
            meta={"error_codes": result.error_codes},
        )
