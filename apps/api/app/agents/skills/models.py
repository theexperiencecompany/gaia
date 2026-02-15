"""
Agent Skills Models - Pydantic models for installable skills.

Follows the Agent Skills open standard (agentskills.io) with GAIA-specific
extensions for scoping skills to executor/subagents.
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator


class SkillSource(str, Enum):
    """How the skill was installed."""

    GITHUB = "github"
    URL = "url"
    UPLOAD = "upload"
    INLINE = "inline"


class SkillTarget(str, Enum):
    """Where the skill is available."""

    GLOBAL = "global"
    EXECUTOR = "executor"
    # Subagent targets are free-form strings (gmail, github, slack, etc.)
    # validated separately, not part of this enum


# Valid skill name pattern: lowercase alphanumeric + hyphens, no consecutive hyphens
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
CONSECUTIVE_HYPHENS = re.compile(r"--")


class SkillMetadata(BaseModel):
    """Parsed from SKILL.md YAML frontmatter.

    Required fields follow the Agent Skills spec (agentskills.io/specification).
    Optional fields extend the spec for GAIA's multi-agent architecture.
    """

    # Required (Agent Skills spec)
    name: str = Field(
        ...,
        max_length=64,
        description="Skill identifier. Lowercase, hyphens, no consecutive hyphens.",
    )
    description: str = Field(
        ...,
        max_length=1024,
        description="What the skill does and when to use it.",
    )

    # Optional (Agent Skills spec)
    license: Optional[str] = Field(
        default=None, description="License name or reference"
    )
    compatibility: Optional[str] = Field(
        default=None, max_length=500, description="Environment requirements"
    )
    metadata: Dict[str, str] = Field(
        default_factory=dict, description="Arbitrary key-value metadata"
    )
    allowed_tools: List[str] = Field(
        default_factory=list, description="Pre-approved tools (experimental)"
    )

    # GAIA extensions
    target: str = Field(
        default="global",
        description=(
            "Where this skill is available: 'global' (all agents), "
            "'executor', or a subagent ID (gmail, github, slack, etc.)"
        ),
    )
    auto_invoke: bool = Field(
        default=True,
        description="Whether the agent can auto-activate this skill",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 64:
            raise ValueError("name must be at most 64 characters")
        if not SKILL_NAME_PATTERN.match(v):
            raise ValueError(
                "name must contain only lowercase letters, numbers, and hyphens, "
                "and must not start or end with a hyphen"
            )
        if CONSECUTIVE_HYPHENS.search(v):
            raise ValueError("name must not contain consecutive hyphens")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("description must not be empty")
        return v


class InstalledSkill(BaseModel):
    """A skill installed in a user's VFS, tracked in MongoDB."""

    id: Optional[str] = Field(default=None, description="MongoDB document ID")

    # Ownership
    user_id: str = Field(..., description="User who installed this skill")

    # Skill content
    skill_metadata: SkillMetadata = Field(
        ..., description="Parsed from SKILL.md frontmatter"
    )
    body_content: Optional[str] = Field(
        default=None,
        description="Markdown body from SKILL.md (cached for discovery)",
    )

    # VFS location
    vfs_path: str = Field(..., description="VFS directory path for this skill")

    # Installation tracking
    enabled: bool = Field(default=True, description="Whether skill is active")
    source: SkillSource = Field(..., description="How the skill was installed")
    source_url: Optional[str] = Field(
        default=None, description="Original source for updates (GitHub URL, etc.)"
    )
    installed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)

    # Files in the skill directory (relative paths)
    files: List[str] = Field(
        default_factory=list,
        description="List of files in the skill folder (e.g., SKILL.md, scripts/run.py)",
    )

    @field_serializer("installed_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None


class SkillInstallRequest(BaseModel):
    """Request to install a skill from GitHub."""

    repo_url: str = Field(..., description="GitHub repo (owner/repo or full URL)")
    skill_path: Optional[str] = Field(
        default=None,
        description="Path within repo to the skill folder (e.g., skills/pdf-processing)",
    )
    target: Optional[str] = Field(
        default=None,
        description="Override target from SKILL.md (global, executor, or subagent ID)",
    )


class SkillInlineCreateRequest(BaseModel):
    """Request to create a skill from components."""

    name: str = Field(..., max_length=64, description="Skill name (kebab-case)")
    description: str = Field(
        ..., max_length=1024, description="What it does and when to use it"
    )
    instructions: str = Field(
        ..., description="Markdown instructions (body of SKILL.md)"
    )
    target: str = Field(
        default="global",
        description="Where to make it available (global, executor, or subagent ID)",
    )


class SkillListResponse(BaseModel):
    """Response for listing installed skills."""

    skills: List[InstalledSkill] = Field(default_factory=list)
    total: int = Field(default=0)
