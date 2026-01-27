"""Marketplace integration routes."""

from typing import Optional

from app.config.loggers import auth_logger as logger
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
        return await get_all_integrations(category=category)
    except Exception as e:
        logger.error(f"Error fetching marketplace: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch integrations")


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_marketplace_integration(integration_id: str):
    integration = await get_integration_details(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration
