"""Mirroring a user's upload into the session workspace."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.files.sandbox import mirror_upload

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
CONVERSATION_ID = "conv-1"


@pytest.mark.asyncio
async def test_a_mirrored_upload_is_not_announced_as_a_gaia_artifact(tmp_path: Path) -> None:
    """Regression: the upload was published as an artifact event, so chat drew the user's file as a GAIA card."""
    host_path = tmp_path / "user-uploaded" / "notes.md"
    redis = MagicMock()
    redis.publish = AsyncMock()
    with (
        patch("app.services.files.sandbox.session_root", return_value=tmp_path),
        patch(
            "app.services.files.sandbox.write_session_file",
            AsyncMock(
                return_value=(host_path, "/workspace/sessions/conv-1/user-uploaded/notes.md")
            ),
        ),
        patch("app.services.files.sandbox.chmod_path", AsyncMock()),
        patch("app.services.artifact_events.redis_cache", MagicMock(redis=redis)),
    ):
        sandbox_path = await mirror_upload(USER_ID, CONVERSATION_ID, "notes.md", b"# notes")

    assert sandbox_path == "/workspace/sessions/conv-1/user-uploaded/notes.md"
    redis.publish.assert_not_awaited()
