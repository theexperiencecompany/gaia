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
