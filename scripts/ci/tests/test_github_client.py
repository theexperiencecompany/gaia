"""lib/github.py retries: a rate limit waits as long as GitHub asks, a refusal is not retried."""

from __future__ import annotations

import time

from github_fake import FakeGitHub, Reply
from lib import github
from lib.github import GitHub, GitHubError
import pytest

PATH = "/repos/o/r/statuses/abc"
SECONDARY = {"message": "You have exceeded a secondary rate limit."}


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


def _post(api: FakeGitHub) -> None:
    GitHub.from_env().post(PATH.lstrip("/"), {"state": "success"})


def test_a_secondary_rate_limit_without_retry_after_waits_the_cooldown(
    api: FakeGitHub, waits: list[float]
) -> None:
    api.on("POST", PATH, Reply(403, SECONDARY), Reply(201, {}))

    _post(api)
    assert waits == [github.RATE_LIMIT_COOLDOWN_SECS]


def test_a_rate_limit_with_no_requests_left_waits_until_the_reset(
    api: FakeGitHub, waits: list[float]
) -> None:
    reset = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 30)}
    api.on("POST", PATH, Reply(403, SECONDARY, headers=reset), Reply(201, {}))

    _post(api)
    assert 25 <= waits[0] <= 31


def test_a_primary_rate_limit_403_is_retried_after_the_reset(
    api: FakeGitHub, waits: list[float]
) -> None:
    reset = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 10)}
    limited = Reply(403, {"message": "API rate limit exceeded"}, headers=reset)
    api.on("POST", PATH, limited, Reply(201, {}))

    _post(api)
    assert 5 <= waits[0] <= 11


def test_retry_after_is_honoured(api: FakeGitHub, waits: list[float]) -> None:
    api.on("POST", PATH, Reply(429, {}, headers={"Retry-After": "7"}), Reply(201, {}))

    _post(api)
    assert waits == [7.0]


def test_a_plain_403_is_a_refusal_and_not_retried(api: FakeGitHub, waits: list[float]) -> None:
    api.on("POST", PATH, Reply(403, {"message": "Resource not accessible by integration"}))

    with pytest.raises(GitHubError, match="after 1 attempt"):
        _post(api)
    assert waits == []


def test_a_download_redirect_does_not_carry_the_token(api: FakeGitHub) -> None:
    """Blob storage answers a forwarded GitHub token with 401 (artifact 13967725027, 2026-11-12)."""
    blob = api.url.replace("127.0.0.1", "localhost") + "/blob/zip"
    api.on("GET", "/artifacts/9/zip$", Reply(302, None, headers={"Location": blob}))
    api.on("GET", "/blob/zip$", Reply(200, b"PK\x03\x04"))

    assert GitHub.from_env().get_bytes("repos/o/r/actions/artifacts/9/zip") == b"PK\x03\x04"
    first, followed = api.requests
    assert first.headers.get("Authorization") == "Bearer stub-token"
    assert "Authorization" not in followed.headers


def test_a_failure_says_whether_it_was_transient(api: FakeGitHub, waits: list[float]) -> None:
    api.on("GET", "/outage$", Reply(503, {}))
    api.on("GET", "/gone$", Reply(404, {}))

    with pytest.raises(GitHubError) as outage:
        GitHub.from_env().get("repos/o/r/outage")
    with pytest.raises(GitHubError) as gone:
        GitHub.from_env().get("repos/o/r/gone")
    assert (outage.value.transient, outage.value.status) == (True, 503)
    assert (gone.value.transient, gone.value.status) == (False, 404)
