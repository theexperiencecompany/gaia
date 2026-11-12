"""Tests for app/api/v1/endpoints/openui_artifacts.py."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact, OpenUIArtifactResponse
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

BASE = "/api/v1/artifacts"
_ENDPOINT = "app.api.v1.endpoints.openui_artifacts"
ARTIFACT = OpenUIArtifact(
    id="a1",
    user_id=FAKE_USER.user_id,
    kind=ArtifactKind.REPORT,
    title="Q3 plan",
    program='root = Artifact("Q3 plan", "s", [], [])',
    brief_hash="h",
    model="gpt-6-luna",
    version=3,
)


async def test_the_owner_reads_their_artifact_and_the_event_names_it(client: AsyncClient) -> None:
    stored = OpenUIArtifactResponse(
        id=ARTIFACT.id,
        kind=ARTIFACT.kind,
        title=ARTIFACT.title,
        program=ARTIFACT.program,
        version=ARTIFACT.version,
        conversation_id=None,
        created_at=ARTIFACT.created_at,
    )
    with patch(f"{_ENDPOINT}.read_artifact", AsyncMock(return_value=stored)) as read:
        async with captured_wide_event() as event:
            response = await client.get(f"{BASE}/a1")

    assert response.status_code == 200
    assert response.json()["program"] == ARTIFACT.program
    read.assert_awaited_once_with(FAKE_USER.user_id, "a1")
    assert event["user"] == {"id": FAKE_USER.user_id}
    assert event["artifact"] == {"operation": "read", "id": "a1", "kind": "report", "version": 3}


async def test_the_owner_downloads_a_pdf_named_after_the_title(client: AsyncClient) -> None:
    with patch(
        f"{_ENDPOINT}.owner_artifact_pdf", AsyncMock(return_value=(ARTIFACT, b"%PDF-1.7"))
    ) as export:
        async with captured_wide_event() as event:
            response = await client.get(f"{BASE}/a1/pdf")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="Q3 plan.pdf"'
    assert response.headers["cache-control"] == "no-store"
    export.assert_awaited_once_with(FAKE_USER.user_id, "a1")
    assert event["user"] == {"id": FAKE_USER.user_id}
    assert event["artifact"] == {"operation": "pdf", "id": "a1", "kind": "report", "pdf_bytes": 8}
