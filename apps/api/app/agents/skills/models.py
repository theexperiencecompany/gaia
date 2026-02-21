"""
Agent Skills Models - Pydantic models for installable skills.

Follows the Agent Skills open standard (agentskills.io) with GAIA-specific
extensions for scoping skills to executor/subagents.

Flat schema: all fields are top-level on the Skill document (no nested
skill_metadata). SkillMetadata is retained only for parsing external
SKILL.md frontmatter during import.
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


# Valid skill name pattern: lowercase alphanumeric + hyphens, no consecutive hyphens
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
CONSECUTIVE_HYPHENS = re.compile(r"--")


class SkillMetadata(BaseModel):
    """Parsed from SKILL.md YAML frontmatter.

    Used only during import to validate external SKILL.md files.
    Once imported, fields are flattened onto the top-level Skill model.

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
        default="executor",
        description=(
            "Target agent: 'executor', or a subagent agent_name "
            "(gmail_agent, github_agent, etc.)"
        ),
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


class Skill(BaseModel):
    """A skill tracked in MongoDB with a flat schema.

    All metadata fields (name, description, target, etc.) live at the
    top level alongside ownership and installation tracking fields.
    System skills use user_id="system"; user skills use the actual user ID.
    """

    id: Optional[str] = Field(default=None, description="MongoDB document ID")

    # Ownership
    user_id: str = Field(
        ..., description="User who installed this skill, or 'system' for system skills"
    )

    # Skill identity (from frontmatter, now top-level)
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
    target: str = Field(
        default="executor",
        description=(
            "Target agent: 'executor', or a subagent agent_name "
            "(gmail_agent, github_agent, etc.)"
        ),
    )

    # Optional metadata (from frontmatter, now top-level)
    license: Optional[str] = Field(
        default=None, description="License name or reference"
    )
    compatibility: Optional[str] = Field(
        default=None, max_length=500, description="Environment requirements"
    )
    metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata from frontmatter",
    )
    allowed_tools: List[str] = Field(
        default_factory=list, description="Pre-approved tools (experimental)"
    )

    # Skill content
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

    @field_serializer("installed_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None


# Backward-compat alias — existing code that imports InstalledSkill still works
# during the transition. Once all callers are updated, this can be removed.
InstalledSkill = Skill


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
        default="executor",
        description="Target agent: 'executor' or a subagent agent_name (e.g., gmail_agent)",
    )


class SkillListResponse(BaseModel):
    """Response for listing installed skills."""

    skills: List[Skill] = Field(default_factory=list)
    total: int = Field(default=0)
