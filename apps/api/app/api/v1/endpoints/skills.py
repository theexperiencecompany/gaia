"""
FastAPI endpoints for agent skill management.

Provides REST API for installing, creating, listing, and managing
installable agent skills (Agent Skills open standard).
"""

from typing import Optional

from app.agents.skills.github_discovery import (
    discover_skills_from_repo,
    get_skill_from_repo,
)
from app.agents.skills.installer import (
    install_from_github,
    install_from_inline,
    uninstall_skill_full,
)
from app.agents.skills.models import (
    Skill,
    SkillInlineCreateRequest,
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


def _get_user_id(user: dict = Depends(get_current_user)) -> str:
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )
    return user_id


@router.get("/discover")
async def discover_skills_from_github(
    repo: str = Query(..., description="GitHub repo (owner/repo or full URL)"),
    branch: str = Query("main", description="Branch to search"),
):
    """Discover available skills in a GitHub repository.

    Lists all skills found in standard locations without installing.
    Use this to preview what skills are available before installing.

    Example: GET /api/v1/skills/discover?repo=vercel-labs/agent-skills
    """
    try:
        skills = await discover_skills_from_repo(repo, branch)
        return {
            "repo": repo,
            "branch": branch,
            "skills": [s.to_dict() for s in skills],
            "count": len(skills),
        }
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error discovering skills from {repo}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to discover skills from repository",
        )


@router.post(
    "/install/github",
    response_model=Skill,
    status_code=http_status.HTTP_201_CREATED,
)
async def install_skill_with_auto_discover(
    repo_url: str = Query(..., description="GitHub repo (owner/repo or full URL)"),
    skill_name: Optional[str] = Query(
        None, description="Skill name to install (auto-discovers if provided)"
    ),
    skill_path: Optional[str] = Query(
        None, description="Explicit path to skill folder"
    ),
    target: Optional[str] = Query(
        None, description="Override target (executor or subagent agent_name)"
    ),
    user_id: str = Depends(_get_user_id),
):
    """Install a skill from a GitHub repository.

    Can work in two modes:
    1. With skill_path: Direct install from known path
    2. With skill_name: Auto-discovers the skill path first, then installs

    Examples:
    - /api/v1/skills/install/github?repo_url=owner/repo&skill_path=skills/my-skill
    - /api/v1/skills/install/github?repo_url=owner/repo&skill_name=my-skill
    """
    try:
        install_path = skill_path

        if skill_name and not install_path:
            skill = await get_skill_from_repo(repo_url, skill_name)
            if not skill:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"Skill '{skill_name}' not found in repository",
                )
            install_path = skill.path

        if not install_path:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Either skill_path or skill_name must be provided",
            )

        installed = await install_from_github(
            user_id=user_id,
            repo_url=repo_url,
            skill_path=install_path,
            target_override=target,
        )
        return installed
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"Error installing skill from GitHub: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to install skill from GitHub",
        ) from e


@router.post(
    "/install/inline",
    response_model=Skill,
    status_code=http_status.HTTP_201_CREATED,
)
@tiered_rate_limit("skill_operations")
async def create_inline_skill_endpoint(
    request: SkillInlineCreateRequest,
    user_id: str = Depends(_get_user_id),
):
    """Create a skill from inline components."""
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
        ) from e
    except Exception as e:
        logger.error(f"Error creating inline skill: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create skill",
        ) from e


@router.get("", response_model=SkillListResponse)
async def list_skills_endpoint(
    user_id: str = Depends(_get_user_id),
    target: Optional[str] = Query(
        None, description="Filter by target (executor or subagent agent_name)"
    ),
    enabled_only: bool = Query(False, description="Only return enabled skills"),
):
    """List all installed skills for the current user."""
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
        ) from e


@router.get("/{skill_id}", response_model=Skill)
async def get_skill_endpoint(
    skill_id: str,
    user_id: str = Depends(_get_user_id),
):
    """Get a specific installed skill by ID."""
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
        ) from e


@router.patch("/{skill_id}/enable", response_model=dict)
async def enable_skill_endpoint(
    skill_id: str,
    user_id: str = Depends(_get_user_id),
):
    """Enable a disabled skill."""
    try:
        success = await enable_skill(user_id, skill_id)
        return {"success": success, "skill_id": skill_id, "enabled": True}
    except Exception as e:
        logger.error(f"Error enabling skill {skill_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enable skill",
        ) from e


@router.patch("/{skill_id}/disable", response_model=dict)
async def disable_skill_endpoint(
    skill_id: str,
    user_id: str = Depends(_get_user_id),
):
    """Disable a skill without uninstalling it."""
    try:
        success = await disable_skill(user_id, skill_id)
        return {"success": success, "skill_id": skill_id, "enabled": False}
    except Exception as e:
        logger.error(f"Error disabling skill {skill_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disable skill",
        ) from e


@router.delete("/{skill_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def uninstall_skill_endpoint(
    skill_id: str,
    user_id: str = Depends(_get_user_id),
):
    """Uninstall a skill and remove its files from VFS."""
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
        ) from e
