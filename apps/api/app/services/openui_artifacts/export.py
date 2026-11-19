"""PDF export of an artifact: its heygaia.link page in print mode, cached per version."""

import base64
import json
import re

from pydantic import BaseModel

from app.config.settings import settings
from app.constants.openui_artifacts import (
    ARTIFACT_PDF_CACHE_KEY,
    ARTIFACT_PDF_CACHE_TTL_SECONDS,
    ARTIFACT_PRINT_PROGRAM_GLOBAL,
    ARTIFACT_PRINT_URL,
    ARTIFACT_READY_SELECTOR,
)
from app.decorators.caching import Cacheable
from app.models.openui_artifact_models import OpenUIArtifact
from app.models.short_link_models import ShortLinkTargetType
from app.services.analytics_service import capture
from app.services.openui_artifacts.read import get_owned_artifact
from app.services.render.pdf import render_url_to_pdf
from app.services.short_link_service import live_link_for_slug
from shared.py.analytics import UserId
from shared.py.analytics.catalog.artifacts import ArtifactPdfExported
from shared.py.wide_events import log


class PrintedPdf(BaseModel):
    pdf_b64: str
    pages: int


async def render_program_to_pdf(program: str) -> tuple[bytes, int]:
    """Print a program on the web app's print page; no link or session needed."""
    url = ARTIFACT_PRINT_URL.format(frontend=settings.FRONTEND_URL)
    init_script = f"window.{ARTIFACT_PRINT_PROGRAM_GLOBAL} = {json.dumps(program)};"
    return await render_url_to_pdf(url, ARTIFACT_READY_SELECTOR, init_script)


@Cacheable(key_pattern=ARTIFACT_PDF_CACHE_KEY, ttl=ARTIFACT_PDF_CACHE_TTL_SECONDS, model=PrintedPdf)
async def _print_artifact(artifact_id: str, version: int, program: str) -> PrintedPdf:  # noqa: ARG001 -- id and version key the cache
    pdf, pages = await render_program_to_pdf(program)
    log.set_ns("artifact", pdf_rendered=True, pages=pages, pdf_bytes=len(pdf))
    return PrintedPdf(pdf_b64=base64.b64encode(pdf).decode(), pages=pages)


async def _pdf_for(artifact: OpenUIArtifact) -> bytes:
    printed = await _print_artifact(artifact.id, artifact.version, artifact.program)
    capture(
        UserId(artifact.user_id), ArtifactPdfExported(kind=artifact.kind.value, pages=printed.pages)
    )
    return base64.b64decode(printed.pdf_b64)


async def owner_artifact_pdf(user_id: str, artifact_id: str) -> tuple[OpenUIArtifact, bytes]:
    """Print the owner's artifact; sharing it or not makes no difference."""
    artifact = await get_owned_artifact(user_id, artifact_id)
    return artifact, await _pdf_for(artifact)


async def public_artifact_pdf(slug: str) -> tuple[OpenUIArtifact, bytes] | None:
    """Print the artifact behind a live link; None for any other slug."""
    link = await live_link_for_slug(slug, ShortLinkTargetType.OPENUI_ARTIFACT)
    if link is None:
        return None
    artifact = await get_owned_artifact(link.user_id, link.target_id)
    return artifact, await _pdf_for(artifact)


def pdf_download_headers(artifact: OpenUIArtifact) -> dict[str, str]:
    """Headers that save the PDF under the artifact's title."""
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", artifact.title).strip() or artifact.kind.value
    return {
        "Content-Disposition": f'attachment; filename="{stem}.pdf"',
        "Cache-Control": "no-store",
    }
