from typing import List
from fastapi import APIRouter, status
from app.models.team_models import TeamMemberCreate, TeamMemberUpdate, TeamMember
from app.decorators.caching import Cacheable
from app.services.team_service import TeamService

router = APIRouter()


@router.get("/team", response_model=List[TeamMember])
@Cacheable(smart_hash=True, ttl=1800, model=List[TeamMember])  # 30 minutes
async def get_team_members():
    """Get all team members with caching."""
    return await TeamService.get_all_team_members()


@router.get("/team/{member_id}", response_model=TeamMember)
@Cacheable(
    key_pattern="team_member:{member_id}", ttl=1800, model=TeamMember
)  # 30 minutes
async def get_team_member(member_id: str):
    """Get a specific team member by ID with caching."""
    return await TeamService.get_team_member_by_id(member_id)


@router.post("/team", response_model=TeamMember, status_code=status.HTTP_201_CREATED)
async def create_team_member(member: TeamMemberCreate):
    """Create a new team member with cache invalidation."""
    return await TeamService.create_team_member(member)


@router.put("/team/{member_id}", response_model=TeamMember)
async def update_team_member(member_id: str, member: TeamMemberUpdate):
    """Update a team member with cache invalidation."""
    return await TeamService.update_team_member(member_id, member)


@router.delete("/team/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_member(member_id: str):
    """Delete a team member with cache invalidation."""
    await TeamService.delete_team_member(member_id)
