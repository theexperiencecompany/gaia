"""PDF export: the owner's export never depends on the artifact being shared."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.services.openui_artifacts.export import (
    owner_artifact_pdf,
    pdf_download_headers,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.artifacts import ArtifactPdfExported
from tests.helpers import captured_wide_event

# Exports are cached per artifact version; a real Redis would carry one test's print into the next.
pytestmark = pytest.mark.usefixtures("fake_redis")

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


async def test_an_export_reads_the_callers_artifact_prints_it_and_counts_it() -> None:
    with (
        patch(f"{_SVC}.get_owned_artifact", AsyncMock(return_value=ARTIFACT)) as read,
        patch(f"{_SVC}.render_program_to_pdf", AsyncMock(return_value=(b"%PDF-1.7", 2))),
        patch(f"{_SVC}.capture") as capture,
    ):
        async with captured_wide_event() as event:
            await owner_artifact_pdf(OWNER, "a1")

    read.assert_awaited_once_with(OWNER, "a1")
    capture.assert_called_once_with(UserId(OWNER), ArtifactPdfExported(kind="report", pages=2))
    assert event["artifact"] == {"pdf_rendered": True, "pages": 2, "pdf_bytes": 8}


def test_the_download_is_named_after_the_title_and_never_cached() -> None:
    titled = ARTIFACT.model_copy(update={"title": 'Q3: "plan"/2026!'})

    assert pdf_download_headers(titled) == {
        "Content-Disposition": 'attachment; filename="Q3 plan2026.pdf"',
        "Cache-Control": "no-store",
    }


def test_a_title_with_nothing_printable_falls_back_to_the_kind() -> None:
    untitled = ARTIFACT.model_copy(update={"title": "!!!"})

    assert pdf_download_headers(untitled)["Content-Disposition"] == (
        'attachment; filename="report.pdf"'
    )


async def test_a_print_is_reused_until_the_artifact_or_its_version_changes() -> None:
    other = ARTIFACT.model_copy(update={"id": "a2"})
    revised = ARTIFACT.model_copy(update={"version": 2})
    with (
        patch(f"{_SVC}.render_program_to_pdf", AsyncMock(return_value=(b"%PDF-1.7", 1))) as render,
        patch(f"{_SVC}.capture"),
    ):
        for artifact in (ARTIFACT, ARTIFACT, other, revised):
            with patch(f"{_SVC}.get_owned_artifact", AsyncMock(return_value=artifact)):
                await owner_artifact_pdf(OWNER, artifact.id)

    assert render.await_count == 3
