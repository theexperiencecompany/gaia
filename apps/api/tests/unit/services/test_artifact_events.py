"""Unit tests for the artifact event wire contract (artifact_events).

Locks the exact Redis channel name + payload shapes shared by the sandbox
watcher, the upload pipeline, and the chat stream forwarder — a shape drift
here silently breaks artifact streaming in the UI.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.short_link_models import ShortLinkTargetType
from app.services.artifact_events import (
    artifact_channel,
    publish_artifact_event,
    remove_event,
    upload_event,
    upsert_event,
)
from app.services.storage import ArtifactInfo

_MOD = "app.services.artifact_events"

USER_ID = "507f1f77bcf86cd799439011"
SESSION_ID = "sess-1"


def _artifact_info(**overrides: object) -> ArtifactInfo:
    data: dict[str, object] = {
        "path": "artifacts/notes.md",
        "size_bytes": 12,
        "mtime": 1234.5,
        "content_type": "text/markdown",
    }
    data.update(overrides)
    return ArtifactInfo(**data)


class TestArtifactChannel:
    def test_channel_is_prefixed_with_user_id(self):
        assert artifact_channel(USER_ID) == f"artifacts:{USER_ID}"

    def test_rejects_unsafe_user_id(self):
        for bad in ["a:b", "a*b", "a?b", "", "x" * 65, "has space"]:
            with pytest.raises(ValueError, match="unsafe user_id"):
                artifact_channel(bad)


SHORT_URL = "https://heygaia.link/abcdefghijk"


@pytest.fixture
def mint():
    with patch(f"{_MOD}.get_or_create_short_link", AsyncMock(return_value=SHORT_URL)) as mint:
        yield mint


class TestUpsertEvent:
    async def test_exact_shape_without_body(self, mint):
        info = _artifact_info()

        event = await upsert_event(USER_ID, SESSION_ID, info)

        assert event == {
            "event": "upsert",
            "session_id": SESSION_ID,
            "path": "artifacts/notes.md",
            "size_bytes": 12,
            "mtime": 1234.5,
            "content_type": "text/markdown",
            "short_url": SHORT_URL,
        }

    async def test_the_artifact_link_is_minted_for_this_session_file(self, mint):
        """Every surface (chat card, bot message, the agent's tool result) reads
        the link off this event, so the event is where it is minted."""
        await upsert_event(USER_ID, SESSION_ID, _artifact_info())

        mint.assert_awaited_once_with(
            USER_ID, ShortLinkTargetType.SESSION_ARTIFACT, f"{SESSION_ID}/artifacts/notes.md"
        )

    async def test_body_inlined_when_provided(self, mint):
        event = await upsert_event(USER_ID, SESSION_ID, _artifact_info(), body="hello")

        assert event["body"] == "hello"

    async def test_no_body_key_when_omitted(self, mint):
        event = await upsert_event(USER_ID, SESSION_ID, _artifact_info())

        assert "body" not in event


class TestRemoveEvent:
    def test_exact_shape(self):
        assert remove_event(SESSION_ID, "artifacts/gone.txt") == {
            "event": "remove",
            "session_id": SESSION_ID,
            "path": "artifacts/gone.txt",
        }


class TestUploadEvent:
    def test_exact_shape_with_explicit_mtime(self):
        assert upload_event(
            SESSION_ID, "user-uploaded/pic.png", size_bytes=99, content_type="image/png", mtime=5.0
        ) == {
            "event": "upload",
            "session_id": SESSION_ID,
            "path": "user-uploaded/pic.png",
            "size_bytes": 99,
            "mtime": 5.0,
            "content_type": "image/png",
        }

    def test_mtime_defaults_to_now(self):
        event = upload_event(
            SESSION_ID, "user-uploaded/pic.png", size_bytes=99, content_type="image/png"
        )

        assert isinstance(event["mtime"], float)
        assert event["mtime"] > 0


class TestPublishArtifactEvent:
    async def test_noop_when_redis_unavailable(self):
        with patch(f"{_MOD}.redis_cache", SimpleNamespace(redis=None)):
            await publish_artifact_event(USER_ID, remove_event(SESSION_ID, "artifacts/gone.txt"))

    async def test_publishes_enriched_json_to_user_channel(self):
        fake_redis = AsyncMock()
        with patch(f"{_MOD}.redis_cache", SimpleNamespace(redis=fake_redis)):
            await publish_artifact_event(USER_ID, remove_event(SESSION_ID, "artifacts/gone.txt"))

        fake_redis.publish.assert_awaited_once()
        channel, raw = fake_redis.publish.await_args.args
        assert channel == f"artifacts:{USER_ID}"
        payload = json.loads(raw)
        assert payload["event"] == "remove"
        assert payload["session_id"] == SESSION_ID
        assert payload["path"] == "artifacts/gone.txt"
        assert payload["user_id"] == USER_ID
        assert isinstance(payload["ts"], float)

    async def test_publish_failure_is_swallowed(self):
        """Delivery is a latency optimization — a Redis error must never raise."""
        fake_redis = AsyncMock()
        fake_redis.publish.side_effect = RuntimeError("redis down")
        with patch(f"{_MOD}.redis_cache", SimpleNamespace(redis=fake_redis)):
            await publish_artifact_event(USER_ID, remove_event(SESSION_ID, "x.txt"))
