"""Every /sessions route serves only the caller's own conversation; any other id is a 404."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from tests.conftest import FAKE_USER_2

_MODULE = "app.api.v1.endpoints.sessions"

_ROUTES = [
    ("GET", "artifacts", None),
    ("GET", "artifacts/out/report.pdf", None),
    ("GET", "uploads", None),
    ("GET", "uploads/photo.png", None),
    ("POST", "pin", {"path": "out/report.pdf"}),
]


@pytest.mark.parametrize("conv_id", ["conv-of-user-2", "conv-nobody-made"])
@pytest.mark.parametrize(("method", "suffix", "body"), _ROUTES)
async def test_a_conversation_the_user_does_not_own_is_not_found(
    client: AsyncClient,
    owned_conversations: set[tuple[str, str]],
    conv_id: str,
    method: str,
    suffix: str,
    body: dict[str, str] | None,
) -> None:
    """A foreign conversation answers exactly like a missing one, so ids cannot be probed."""
    owned_conversations.add(("conv-of-user-2", FAKE_USER_2.user_id))
    with (
        patch(f"{_MODULE}.list_artifacts", new_callable=AsyncMock) as list_artifacts,
        patch(f"{_MODULE}.list_user_uploaded", new_callable=AsyncMock) as list_uploaded,
        patch(f"{_MODULE}.resolve_session_path", new_callable=AsyncMock) as resolve,
        patch(f"{_MODULE}.pin_session_artifact", new_callable=AsyncMock) as pin,
    ):
        resp = await client.request(method, f"/api/v1/sessions/{conv_id}/{suffix}", json=body)

    assert resp.status_code == 404
    assert resp.json() == {"message": "Conversation not found", "code": "CONVERSATION_NOT_FOUND"}
    for storage_call in (list_artifacts, list_uploaded, resolve, pin):
        storage_call.assert_not_called()
