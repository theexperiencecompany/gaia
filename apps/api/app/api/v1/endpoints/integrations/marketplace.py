"""Marketplace integration routes."""

from typing import Optional

from shared.py.wide_events import log
from app.schemas.integrations.responses import IntegrationResponse, MarketplaceResponse
from app.services.integrations.marketplace import (
    get_all_integrations,
    get_integration_details,
)
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("", response_model=MarketplaceResponse)
async def list_marketplace_integrations(category: Optional[str] = None):
    try:
        log.set(operation="list_marketplace_integrations", category=category)
        result = await get_all_integrations(category=category)
        log.set(
            result_count=len(result.integrations)
            if hasattr(result, "integrations")
            else 0
        )
        log.set(outcome="success")
        return result
    except Exception as e:
        log.error(f"Error fetching marketplace: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch integrations")


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_marketplace_integration(integration_id: str):
    log.set(operation="get_marketplace_integration", integration_id=integration_id)
    integration = await get_integration_details(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    log.set(integration_name=integration.name if hasattr(integration, "name") else None)
    log.set(outcome="success")
    return integration
