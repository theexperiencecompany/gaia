"""Calls the API makes to GAIA's other servers, declared as OpenAPI webhooks.

Nothing serves these: FastAPI only documents them, which puts each body in
openapi.json so the server that receives it reads the generated type.
"""

from fastapi import APIRouter

from app.constants.public_pages import PUBLIC_PAGES_CHANGED_WEBHOOK
from app.core.openapi import api_operation_id
from app.schemas.public_pages import PublicPagesChanged

webhooks_router = APIRouter(tags=["webhooks"], generate_unique_id_function=api_operation_id)


@webhooks_router.post(PUBLIC_PAGES_CHANGED_WEBHOOK, status_code=204)
def public_pages_changed(body: PublicPagesChanged) -> None:
    """Sent to the web server by app.services.public_pages when public data changes."""
