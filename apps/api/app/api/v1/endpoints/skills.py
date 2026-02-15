"""
FastAPI endpoints for agent skill management.

Provides REST API for installing, creating, listing, and managing
installable agent skills (Agent Skills open standard).
"""

from typing import Optional

from app.agents.skills.installer import (
    install_from_github,
    install_from_inline,
    uninstall_skill_full,
)
from app.agents.skills.models import (
    InstalledSkill,
    SkillInlineCreateRequest,
    SkillInstallRequest,
    SkillListResponse,
)
from app.agents.skills.registry import (
    disable_skill,
    enable_skill,
    get_skill,
    list_skills,
)
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import general_logger as logger
from app.decorators import tiered_rate_limit
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status

router = APIRouter(prefix="/skills", tags=["skills"])


@router.post(
    "/install/github",
    response_model=InstalledSkill,
    status_code=http_status.HTTP_201_CREATED,
)
@tiered_rate_limit("skill_operations")
async def install_from_github_endpoint(
    request: SkillInstallRequest,
    user: dict = Depends(get_current_user),
):
    """Install a skill from a GitHub repository."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    try:
        installed = await install_from_github(
            user_id=user_id,
            repo_url=request.repo_url,
            skill_path=request.skill_path,
            target_override=request.target,
        )
        return installed
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error installing skill from GitHub: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to install skill from GitHub",
        )


@router.post(
    "/install/inline",
    response_model=InstalledSkill,
    status_code=http_status.HTTP_201_CREATED,
)
@tiered_rate_limit("skill_operations")
async def create_inline_skill_endpoint(
    request: SkillInlineCreateRequest,
    user: dict = Depends(get_current_user),
):
    """Create a skill from inline components."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    try:
        installed = await install_from_inline(
            user_id=user_id,
            name=request.name,
            description=request.description,
            instructions=request.instructions,
            target=request.target,
        )
        return installed
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating inline skill: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create skill",
        )


@router.get("", response_model=SkillListResponse)
async def list_skills_endpoint(
    user: dict = Depends(get_current_user),
    target: Optional[str] = Query(
        None, description="Filter by target (global, executor, or subagent ID)"
    ),
    enabled_only: bool = Query(False, description="Only return enabled skills"),
):
    """List all installed skills for the current user."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    try:
        skills = await list_skills(
            user_id=user_id,
            target=target,
            enabled_only=enabled_only,
        )
        return SkillListResponse(skills=skills, total=len(skills))
    except Exception as e:
        logger.error(f"Error listing skills: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list skills",
        )


@router.get("/{skill_id}", response_model=InstalledSkill)
async def get_skill_endpoint(
    skill_id: str,
    user: dict = Depends(get_current_user),
):
    """Get a specific installed skill by ID."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    try:
        skill = await get_skill(user_id, skill_id)
        if not skill:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Skill {skill_id} not found",
            )
        return skill
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting skill {skill_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve skill",
        )


@router.patch("/{skill_id}/enable", response_model=dict)
async def enable_skill_endpoint(
    skill_id: str,
    user: dict = Depends(get_current_user),
):
    """Enable a disabled skill."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    try:
        success = await enable_skill(user_id, skill_id)
        return {"success": success, "skill_id": skill_id, "enabled": True}
    except Exception as e:
        logger.error(f"Error enabling skill {skill_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enable skill",
        )


@router.patch("/{skill_id}/disable", response_model=dict)
async def disable_skill_endpoint(
    skill_id: str,
    user: dict = Depends(get_current_user),
):
    """Disable a skill without uninstalling it."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    try:
        success = await disable_skill(user_id, skill_id)
        return {"success": success, "skill_id": skill_id, "enabled": False}
    except Exception as e:
        logger.error(f"Error disabling skill {skill_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disable skill",
        )


@router.delete("/{skill_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def uninstall_skill_endpoint(
    skill_id: str,
    user: dict = Depends(get_current_user),
):
    """Uninstall a skill and remove its files from VFS."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    try:
        success = await uninstall_skill_full(user_id, skill_id)
        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Skill {skill_id} not found",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uninstalling skill {skill_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to uninstall skill",
        )
