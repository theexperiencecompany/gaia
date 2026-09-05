"""Unit tests for the share-download route (token-gated, no session).

The service layer is mocked: routing, status codes, armor headers, and the
uniform-404 contract are what's asserted here. Grant cryptography is covered
in test_share_service.py; fetcher compatibility in test_share_fetcher_compat.py.
"""

from unittest.mock import patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.shares import download_shared_file
from tests.helpers import captured_wide_event

ENDPOINT = "app.api.v1.endpoints.shares"


async def test_valid_grant_serves_bytes_with_armor_headers(
    client: AsyncClient,
) -> None:
    with patch(
        f"{ENDPOINT}.redeem_share_grant",
        return_value=(b"%PDF-1.4 x", "report.pdf", "application/pdf"),
    ):
        response = await client.get("/api/v1/files/s/report.pdf?token=some-token")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 x"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="report.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store, max-age=0"


async def test_unknown_token_is_404_without_detail(client: AsyncClient) -> None:
    with patch(f"{ENDPOINT}.redeem_share_grant", return_value=None):
        response = await client.get("/api/v1/files/s/nothing.pdf?token=nope")
    assert response.status_code == 404
    assert "token" not in response.text.lower()


async def test_missing_token_is_404_not_422(client: AsyncClient) -> None:
    response = await client.get("/api/v1/files/s/report.pdf")
    assert response.status_code == 404


async def test_swapped_filename_segment_still_serves_grant_file(
    client: AsyncClient,
) -> None:
    # The filename segment is cosmetic: resolution uses only the token.
    with patch(
        f"{ENDPOINT}.redeem_share_grant",
        return_value=(b"data", "real.pdf", "application/pdf"),
    ) as redeem:
        response = await client.get("/api/v1/files/s/attacker.pdf?token=some-token")
    assert response.status_code == 200
    assert response.content == b"data"
    assert redeem.call_args.args == ("some-token",)


async def test_trailing_slash_does_not_redirect(client: AsyncClient) -> None:
    # No Starlette slash-redirect (which would echo the bearer into Location).
    with patch(f"{ENDPOINT}.redeem_share_grant", return_value=None):
        response = await client.get("/api/v1/files/s/report.pdf/?token=some-token")
    assert response.status_code == 404
    assert "location" not in response.headers


async def test_quotes_and_newlines_are_stripped_from_the_filename(
    client: AsyncClient,
) -> None:
    # Header injection: a grant filename carrying a quote + CRLF would close the
    # filename parameter and start a header of the attacker's choosing.
    with patch(
        f"{ENDPOINT}.redeem_share_grant",
        return_value=(b"x", 'ev"il\r\nSet-Cookie: a=b.pdf', "application/pdf"),
    ):
        response = await client.get("/api/v1/files/s/x.pdf?token=t")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="evilSet-Cookie: a=b.pdf"'
    )
    assert "set-cookie" not in response.headers


async def test_non_latin1_filename_still_produces_a_sendable_header(
    client: AsyncClient,
) -> None:
    # HTTP headers are latin-1; an un-encodable byte would raise inside the
    # server rather than downloading, so the name is narrowed, not the response.
    with patch(
        f"{ENDPOINT}.redeem_share_grant",
        return_value=(b"x", "\u043e\u0442\u0447\u0451\u0442-report.pdf", "application/pdf"),
    ):
        response = await client.get("/api/v1/files/s/x.pdf?token=t")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="-report.pdf"'


async def test_a_filename_that_strips_to_nothing_falls_back_to_download(
    client: AsyncClient,
) -> None:
    with patch(
        f"{ENDPOINT}.redeem_share_grant",
        return_value=(b"x", '"""', "application/pdf"),
    ):
        response = await client.get("/api/v1/files/s/x.pdf?token=t")
    assert response.headers["content-disposition"] == 'attachment; filename="download"'


async def test_a_served_download_is_recorded_on_the_wide_event() -> None:
    # The route answers 404 for every failure and never explains itself, so the
    # event is the only place an operator can tell a redeemed grant from a
    # rejected one, or see what was served.
    with patch(
        f"{ENDPOINT}.redeem_share_grant",
        return_value=(b"%PDF-1.4 xx", "report.pdf", "application/pdf"),
    ):
        async with captured_wide_event() as event:
            await download_shared_file(token="t")

    assert event["share"] == {"operation": "redeem", "redeemed": True, "byte_count": 11}


async def test_a_rejected_grant_is_recorded_as_not_redeemed() -> None:
    with patch(f"{ENDPOINT}.redeem_share_grant", return_value=None):
        async with captured_wide_event() as event:
            with pytest.raises(HTTPException) as exc:
                await download_shared_file(token="t")

    assert exc.value.status_code == 404
    assert event["share"] == {"operation": "redeem", "redeemed": False}


async def test_every_failure_answers_the_same_uniform_body(client: AsyncClient) -> None:
    # Tampered, expired, missing, oversize and unknown tokens all come back from
    # the service as None; the body must not vary with them, or it becomes an
    # oracle a prober can measure.
    with patch(f"{ENDPOINT}.redeem_share_grant", return_value=None):
        response = await client.get("/api/v1/files/s/report.pdf?token=t")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
