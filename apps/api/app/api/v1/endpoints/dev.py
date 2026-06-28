from fastapi import APIRouter, HTTPException

from app.config.settings import settings
from app.schemas.dev import FaviconAuditResponse
from app.services.integrations.favicon_audit import get_favicon_audit
from shared.py.wide_events import log

router = APIRouter()


@router.get("/favicon-audit", response_model=FaviconAuditResponse)
async def favicon_audit() -> FaviconAuditResponse:
    """Dev-only: legacy vs patched favicon resolution for every MCP server."""
    if settings.ENV != "development":
        raise HTTPException(status_code=404, detail="Not found")

    log.set(operation="favicon_audit")
    items = await get_favicon_audit()
    changed = sum(1 for item in items if item.changed)
    log.set(favicon_audit={"total": len(items), "changed": changed})
    return FaviconAuditResponse(
        environment=settings.ENV, total=len(items), changed=changed, items=items
    )
