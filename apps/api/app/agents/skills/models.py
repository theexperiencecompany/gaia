"""
Agent Skills Models - Pydantic models for installable skills.

Follows the Agent Skills open standard (agentskills.io) with GAIA-specific
extensions for scoping skills to executor/subagents.

Flat schema: all fields are top-level on the Skill document (no nested
skill_metadata). SkillMetadata is retained only for parsing external
SKILL.md frontmatter during import.
"""

from datetime import UTC, datetime
from enum import Enum
import re

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


def _validate_skill_name(value: str) -> str:
    if not value:
        raise ValueError("name must not be empty")
    if len(value) > 64:
        raise ValueError("name must be at most 64 characters")
    if not SKILL_NAME_PATTERN.match(value):
        raise ValueError(
            "name must contain only lowercase letters, numbers, and hyphens, "
            "and must not start or end with a hyphen"
        )
    if CONSECUTIVE_HYPHENS.search(value):
        raise ValueError("name must not contain consecutive hyphens")
    return value


def _validate_skill_description(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("description must not be empty")
    return value


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
    license: str | None = Field(default=None, description="License name or reference")
    compatibility: str | None = Field(
        default=None, max_length=500, description="Environment requirements"
    )
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Arbitrary key-value metadata"
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="Pre-approved tools (experimental)"
    )

    # GAIA extensions
    target: str = Field(
        default="executor",
        description=(
            "Target agent: 'executor', or a subagent agent_name (gmail_agent, github_agent, etc.)"
        ),
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_skill_name(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_skill_description(v)


class Skill(BaseModel):
    """A skill tracked in MongoDB with a flat schema.

    All metadata fields (name, description, target, etc.) live at the
    top level alongside ownership and installation tracking fields.
    System skills use user_id="system"; user skills use the actual user ID.
    """

    id: str | None = Field(default=None, description="MongoDB document ID")

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
            "Target agent: 'executor', or a subagent agent_name (gmail_agent, github_agent, etc.)"
        ),
    )

    # Optional metadata (from frontmatter, now top-level)
    license: str | None = Field(default=None, description="License name or reference")
    compatibility: str | None = Field(
        default=None, max_length=500, description="Environment requirements"
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata from frontmatter",
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="Pre-approved tools (experimental)"
    )

    # Skill content
    body_content: str | None = Field(
        default=None,
        description="Markdown body from SKILL.md (cached for discovery)",
    )

    # Logical storage path (JuiceFS: /skills/{user_id}/{name}).
    # Field name kept as vfs_path for MongoDB doc back-compat.
    vfs_path: str = Field(..., description="Logical storage path for this skill")

    # Installation tracking
    enabled: bool = Field(default=True, description="Whether skill is active")
    source: SkillSource = Field(..., description="How the skill was installed")
    source_url: str | None = Field(
        default=None, description="Original source for updates (GitHub URL, etc.)"
    )
    installed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)

    # Files in the skill directory (relative paths)
    files: list[str] = Field(
        default_factory=list,
        description="List of files in the skill folder (e.g., SKILL.md, scripts/run.py)",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_skill_name(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_skill_description(v)

    @field_serializer("installed_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None


# Backward-compat alias — existing code that imports InstalledSkill still works
# during the transition. Once all callers are updated, this can be removed.
InstalledSkill = Skill


class SkillInlineCreateRequest(BaseModel):
    """Request to create a skill from components."""

    name: str = Field(..., max_length=64, description="Skill name (kebab-case)")
    description: str = Field(..., max_length=1024, description="What it does and when to use it")
    instructions: str = Field(..., description="Markdown instructions (body of SKILL.md)")
    target: str = Field(
        default="executor",
        description="Target agent: 'executor' or a subagent agent_name (e.g., gmail_agent)",
    )


class SkillUpdateRequest(BaseModel):
    """Request to edit an existing skill. Only provided fields are changed.

    The skill ``name`` is its identity (and the key of its VFS directory), so it
    is immutable after creation — rename is delete + recreate, not an edit.
    """

    description: str | None = Field(
        default=None, max_length=1024, description="What it does and when to use it"
    )
    instructions: str | None = Field(
        default=None, description="Markdown instructions (body of SKILL.md)"
    )
    target: str | None = Field(
        default=None,
        description="Target agent: 'executor' or a connected subagent agent_name (unchanged if omitted)",
    )


class SkillListResponse(BaseModel):
    """Response for listing installed skills."""

    skills: list[Skill] = Field(default_factory=list)
    total: int = Field(default=0)


class SkillTarget(BaseModel):
    """A place a skill can run: the executor, or a connected integration subagent.

    ``value`` is the subagent ``agent_name`` written to a skill's ``target``;
    ``icon`` is the integration id (``executor`` for the general bucket) so the
    UI can reuse the integration logo set.
    """

    value: str = Field(..., description="Skill target value (agent_name)")
    label: str = Field(..., description="Human-readable display name")
    icon: str = Field(..., description="Icon key (integration id, or 'executor')")
    connected: bool = Field(default=True, description="Whether the target is available")


class SkillTargetsResponse(BaseModel):
    """Available skill targets for the current user."""

    targets: list[SkillTarget] = Field(default_factory=list)


class BuiltinSkillInfo(BaseModel):
    """A read-only built-in skill shipped with GAIA, for display in settings."""

    slug: str = Field(..., description="Skill directory slug")
    name: str = Field(..., description="Skill name")
    description: str = Field(..., description="What the skill does")
    target: str = Field(..., description="Target agent_name (executor or a subagent)")
    group_label: str = Field(..., description="Display name of the owning agent")
    icon: str = Field(..., description="Icon key (owning subagent id, or 'executor')")
    connected: bool = Field(
        default=True,
        description="Whether the owning agent is available to the user (always-on, or a connected integration)",
    )
    body: str = Field(default="", description="SKILL.md markdown body (for read-only preview)")


class BuiltinSkillsResponse(BaseModel):
    """Response for listing built-in skills."""

    skills: list[BuiltinSkillInfo] = Field(default_factory=list)
    total: int = Field(default=0)
