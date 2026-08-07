"""Regression tests: notes & reminders endpoints must surface 404, not 500.

The endpoint handlers wrap the service call in a generic ``except Exception`` that
raised a 500. A deliberate ``HTTPException(404, ...)`` from the service (or from
the handler's own not-found check) was caught by that generic clause and masked
as ``500 Failed to retrieve/update/delete``. The fix re-raises ``HTTPException``
before the generic catch; these tests pin that a nonexistent id returns 404.
"""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status
import pytest


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    """Bypass the tiered rate limiter's Redis/payment calls (notes writes use it)."""
    with (
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
        ),
    ):
        yield


def _not_found(detail: str):
    return AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    )


@pytest.mark.integration
class TestNotesNotFound:
    """A deliberate 404 from the notes service must reach the client as 404."""

    async def test_get_missing_note_returns_404(self, test_client) -> None:
        with patch("app.api.v1.endpoints.notes.get_note", _not_found("Note not found")):
            response = await test_client.get("/api/v1/notes/does-not-exist")
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Note not found"

    async def test_update_missing_note_returns_404(self, test_client) -> None:
        with patch("app.api.v1.endpoints.notes.update_note", _not_found("Note not found")):
            response = await test_client.put(
                "/api/v1/notes/does-not-exist",
                json={"content": "x", "plaintext": "x"},
            )
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Note not found"

    async def test_delete_missing_note_returns_404(self, test_client) -> None:
        with patch("app.api.v1.endpoints.notes.delete_note", _not_found("Note not found")):
            response = await test_client.delete("/api/v1/notes/does-not-exist")
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Note not found"


@pytest.mark.integration
class TestRemindersNotFound:
    """The reminders GET handler raises 404 for a missing id; it must not be masked."""

    async def test_get_missing_reminder_returns_404(self, test_client) -> None:
        with patch(
            "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
            new=AsyncMock(return_value=None),
        ):
            response = await test_client.get("/api/v1/reminders/does-not-exist")
        assert response.status_code == 404, response.text
        assert "not found" in response.json()["detail"].lower()
