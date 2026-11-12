"""PDF export: the owner's export never depends on the artifact being shared."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.services.openui_artifacts.export import owner_artifact_pdf

_SVC = "app.services.openui_artifacts.export"
OWNER = "6ad86cdfb9e7ae0b43a0efea"
ARTIFACT = OpenUIArtifact(
    id="a1",
    user_id=OWNER,
    kind=ArtifactKind.REPORT,
    title="Pilot",
    program='root = Artifact("Pilot", "s", [], [])',
    brief_hash="h",
    model="gpt-6-luna",
)


@pytest.fixture
def printer() -> Iterator[MagicMock]:
    with (
        patch(f"{_SVC}.get_owned_artifact", AsyncMock(return_value=ARTIFACT)),
        patch(f"{_SVC}.render_program_to_pdf", AsyncMock(return_value=(b"%PDF-1.7", 2))) as render,
        patch(f"{_SVC}.capture"),
    ):
        yield render


async def test_an_unshared_artifact_still_exports_for_its_owner(printer: MagicMock) -> None:
    artifact, pdf = await owner_artifact_pdf(OWNER, "a1")

    assert (artifact, pdf) == (ARTIFACT, b"%PDF-1.7")
    assert printer.await_args.args[0] == ARTIFACT.program
