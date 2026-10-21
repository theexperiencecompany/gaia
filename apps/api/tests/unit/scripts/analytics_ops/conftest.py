"""Fakes for the two I/O boundaries analytics_ops crosses: PostHog's query API and the SDK's network send."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from posthog import Posthog
import pytest
from scripts.analytics_ops.posthog_api import Sender

Rows = list[list[object]]


@dataclass
class FakeReader:
    """Answers each HogQL query constant with fixed rows, or with rows computed from its values."""

    answers: Mapping[str, Rows | Callable[[Mapping[str, object]], Rows]] = field(
        default_factory=dict
    )
    api_token: str = "phc_test"
    queries: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    def hogql(self, query: str, values: Mapping[str, object] | None = None) -> Rows:
        """Record the query and return its scripted rows; an unscripted query is a test bug."""
        bound = dict(values or {})
        self.queries.append((query, bound))
        answer = self.answers[query]
        return answer(bound) if callable(answer) else answer

    def project(self) -> dict[str, object]:
        """Return the project's token, as the API does."""
        return {"api_token": self.api_token}


@pytest.fixture
def sent() -> list[dict[str, object]]:
    """Collect every message the real SDK built for the recording sender, in order."""
    return []


@pytest.fixture
def recording_sender(sent: list[dict[str, object]]) -> Sender:
    """Return a Sender on a real PostHog client whose before_send records each message and drops it."""

    def record(message: dict[str, object]) -> None:
        sent.append(message)

    return Sender(
        Posthog("phc_test", host="http://127.0.0.1:9", before_send=record, sync_mode=True)
    )
