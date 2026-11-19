"""Owner reads: only the caller's own artifact, and never more than the response carries."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.services.openui_artifacts.read import (
    ArtifactNotFoundError,
    artifact_response,
    get_owned_artifact,
    read_artifact,
)

_READ = "app.services.openui_artifacts.read"
ARTIFACT = OpenUIArtifact(
    id="a1",
    user_id="owner",
    conversation_id="conv-1",
    kind=ArtifactKind.PLAN,
    title="Pilot",
    program='root = Artifact("Pilot", "s", [], [])',
    brief_hash="brief-secret",
    model="gpt-6-luna",
    version=2,
)


async def test_the_owners_artifact_is_looked_up_under_their_id() -> None:
    with patch(f"{_READ}.openui_artifact_repository") as repo:
        repo.get = AsyncMock(return_value=ARTIFACT)
        assert await get_owned_artifact("owner", "a1") == ARTIFACT

    repo.get.assert_awaited_once_with("a1", user_id="owner")


async def test_someone_elses_artifact_is_a_404() -> None:
    with patch(f"{_READ}.openui_artifact_repository") as repo:
        repo.get = AsyncMock(return_value=None)
        with pytest.raises(ArtifactNotFoundError) as refused:
            await get_owned_artifact("intruder", "a1")

    assert (refused.value.status_code, refused.value.message) == (404, "artifact not found")


async def test_the_response_carries_the_program_and_nothing_internal() -> None:
    response = artifact_response(ARTIFACT)

    assert response.model_dump() == {
        "id": "a1",
        "kind": ArtifactKind.PLAN,
        "title": "Pilot",
        "program": ARTIFACT.program,
        "version": 2,
        "conversation_id": "conv-1",
        "created_at": ARTIFACT.created_at,
    }


async def test_a_read_returns_the_response_of_the_owned_artifact() -> None:
    with patch(f"{_READ}.get_owned_artifact", AsyncMock(return_value=ARTIFACT)) as owned:
        response = await read_artifact("owner", "a1")

    owned.assert_awaited_once_with("owner", "a1")
    assert response == artifact_response(ARTIFACT)
