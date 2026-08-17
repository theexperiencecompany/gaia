"""Unit tests for the artifact event wire contract (artifact_events).

Locks the exact Redis channel name + payload shapes shared by the sandbox
watcher, the upload pipeline, and the chat stream forwarder — a shape drift
here silently breaks artifact streaming in the UI.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

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


class TestUpsertEvent:
    def test_exact_shape_without_body(self):
        info = _artifact_info()

        event = upsert_event(SESSION_ID, info)

        assert event == {
            "event": "upsert",
            "session_id": SESSION_ID,
            "path": "artifacts/notes.md",
            "size_bytes": 12,
            "mtime": 1234.5,
            "content_type": "text/markdown",
        }

    def test_body_inlined_when_provided(self):
        event = upsert_event(SESSION_ID, _artifact_info(), body="hello")

        assert event["body"] == "hello"

    def test_no_body_key_when_omitted(self):
        event = upsert_event(SESSION_ID, _artifact_info())

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
            await publish_artifact_event(USER_ID, upsert_event(SESSION_ID, _artifact_info()))

    async def test_publishes_enriched_json_to_user_channel(self):
        fake_redis = AsyncMock()
        with patch(f"{_MOD}.redis_cache", SimpleNamespace(redis=fake_redis)):
            await publish_artifact_event(USER_ID, upsert_event(SESSION_ID, _artifact_info()))

        fake_redis.publish.assert_awaited_once()
        channel, raw = fake_redis.publish.await_args.args
        assert channel == f"artifacts:{USER_ID}"
        payload = json.loads(raw)
        assert payload["event"] == "upsert"
        assert payload["session_id"] == SESSION_ID
        assert payload["path"] == "artifacts/notes.md"
        assert payload["user_id"] == USER_ID
        assert isinstance(payload["ts"], float)

    async def test_publish_failure_is_swallowed(self):
        """Delivery is a latency optimization — a Redis error must never raise."""
        fake_redis = AsyncMock()
        fake_redis.publish.side_effect = RuntimeError("redis down")
        with patch(f"{_MOD}.redis_cache", SimpleNamespace(redis=fake_redis)):
            await publish_artifact_event(USER_ID, remove_event(SESSION_ID, "x.txt"))
