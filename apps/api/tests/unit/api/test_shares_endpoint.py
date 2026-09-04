"""Unit tests for the share-download route (token-gated, no session).

The service layer is mocked: routing, status codes, armor headers, and the
uniform-404 contract are what's asserted here. Grant cryptography is covered
in test_share_service.py; fetcher compatibility in test_share_fetcher_compat.py.
"""

from unittest.mock import patch

from httpx import AsyncClient

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
