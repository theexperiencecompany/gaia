from typing import List

from fastapi import APIRouter, HTTPException, status

from app.decorators.caching import Cacheable
from app.models.team_models import TeamMember
from app.services.team_service import TeamService
from shared.py.wide_events import log

router = APIRouter()

_DEPRECATED_DETAIL = "Endpoint not used anymore. Team members are managed out-of-band."


@router.get("/team", response_model=List[TeamMember])
@Cacheable(smart_hash=True, ttl=1800, model=List[TeamMember])  # 30 minutes
async def get_team_members():
    """Get all team members with caching."""
    log.set(operation="get_team_members")
    result = await TeamService.get_all_team_members()
    log.set(outcome="success")
    return result


@router.get("/team/{member_id}", response_model=TeamMember)
@Cacheable(
    key_pattern="team_member:{member_id}", ttl=1800, model=TeamMember
)  # 30 minutes
async def get_team_member(member_id: str):
    """Get a specific team member by ID with caching."""
    log.set(operation="get_team_member", member_id=member_id)
    result = await TeamService.get_team_member_by_id(member_id)
    log.set(outcome="success")
    return result


@router.post("/team", status_code=status.HTTP_410_GONE, include_in_schema=False)
async def create_team_member_deprecated() -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_DEPRECATED_DETAIL)


@router.put(
    "/team/{member_id}", status_code=status.HTTP_410_GONE, include_in_schema=False
)
async def update_team_member_deprecated(member_id: str) -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_DEPRECATED_DETAIL)


@router.delete(
    "/team/{member_id}", status_code=status.HTTP_410_GONE, include_in_schema=False
)
async def delete_team_member_deprecated(member_id: str) -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_DEPRECATED_DETAIL)
