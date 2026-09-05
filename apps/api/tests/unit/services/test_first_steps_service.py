"""Unit tests for the activation checklist.

``mark_step`` is the only writer of ``first_steps.<step>`` and the only emitter
of the ``first_steps_step_done`` event, so both the repository write and the
analytics payload are pinned exactly — including the distinct id, which must
always be GAIA's own user id. ``get_steps`` is the read side: it pre-checks the
steps a long-time user already satisfied before the widget existed, which is
the part that must never over- or under-count. Every repository is faked with
its real signature so a call that drops or reorders an argument fails here
exactly as it would in production; the service itself runs for real.
"""

from typing import Any

import pytest

from app.models.user_models import UserDocument
from app.services import first_steps_service
from app.services.first_steps_service import (
    ALL_STEPS,
    STEP_DISMISSED_ALL,
    STEP_FIRST_APPROVE,
    STEP_LINK_PLATFORM,
    mark_step,
)

USER_ID = "user-abc"
PROPOSAL_STATUSES = ["proposed", "dismissed", "expired"]


def _user(**fields: Any) -> UserDocument:
    return UserDocument.model_validate({"email": "test@example.com", "id": USER_ID, **fields})


class FakeUserRepo:
    """``user_repository`` narrowed to the first-steps accessors, real
    signatures kept so a dropped or reordered argument raises here."""

    def __init__(self) -> None:
        self.user: UserDocument | None = _user()
        self.first_time = True
        self.calls: list[tuple[str, str]] = []
        self.hidden_calls: list[tuple[str, str]] = []
        self.get_calls: list[str] = []

    async def get(self, user_id: str) -> UserDocument | None:
        self.get_calls.append(user_id)
        return self.user if user_id == USER_ID else None

    async def set_first_step(self, user_id: str, step: str) -> bool:
        self.calls.append((user_id, step))
        return self.first_time

    async def add_hidden_first_step(self, user_id: str, step: str) -> None:
        self.hidden_calls.append((user_id, step))


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> FakeUserRepo:
    fake = FakeUserRepo()
    monkeypatch.setattr(first_steps_service, "user_repository", fake)
    return fake


@pytest.fixture
def tracked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any] | None]]:
    events: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_track(user_id: str, event: str, properties: dict[str, Any] | None = None) -> None:
        events.append((user_id, event, properties))

    monkeypatch.setattr(first_steps_service, "track", fake_track)
    return events


@pytest.mark.unit
class TestMarkStep:
    @pytest.mark.parametrize("step", [*ALL_STEPS, STEP_DISMISSED_ALL])
    async def test_every_valid_step_is_recorded_for_that_user(
        self, repo: FakeUserRepo, tracked: list[Any], step: str
    ) -> None:
        await mark_step(USER_ID, step)

        assert repo.calls == [(USER_ID, step)]

    async def test_an_unknown_step_writes_nothing(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        await mark_step(USER_ID, "not_a_step")

        assert repo.calls == []
        assert tracked == []

    async def test_the_first_completion_emits_the_activation_event(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        await mark_step(USER_ID, STEP_FIRST_APPROVE)

        # distinct_id is GAIA's own user id, never a platform handle — a wrong
        # id here strands the event on a second, anonymous profile.
        assert tracked == [(USER_ID, "first_steps_step_done", {"step": STEP_FIRST_APPROVE})]

    async def test_a_repeat_completion_is_idempotent_and_silent(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        repo.first_time = False

        await mark_step(USER_ID, STEP_LINK_PLATFORM)

        assert repo.calls == [(USER_ID, STEP_LINK_PLATFORM)]
        assert tracked == []
