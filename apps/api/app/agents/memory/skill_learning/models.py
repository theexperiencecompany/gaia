"""
Skill Learning Models - Pydantic models for skill storage and retrieval.

Two types of skills are supported:
1. Extracted Skills - Procedural knowledge extracted by a cheap LLM
2. Reflections - Self-documented experiences written by the executing LLM
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SkillType(str, Enum):
    """Type of skill/learning stored."""

    EXTRACTED = "extracted"  # Extracted by cheap LLM from conversation
    REFLECTION = "reflection"  # Self-documented by the executing LLM


class Skill(BaseModel):
    """A learned procedural skill or reflection.

    Skills are isolated per agent_id (e.g., twitter_agent, github_agent).
    They capture reusable procedures that can help with similar future tasks.
    """

    id: Optional[str] = Field(default=None, description="MongoDB document ID")

    # Core identification
    agent_id: str = Field(
        ..., description="Agent that learned this skill (e.g., twitter_agent)"
    )
    skill_type: SkillType = Field(..., description="How this skill was created")

    # Content
    trigger: str = Field(..., description="What type of request triggers this skill")
    procedure: str = Field(
        ..., description="Step-by-step procedure or reflection content"
    )
    tools_used: List[str] = Field(
        default_factory=list, description="Tools essential to this skill"
    )

    # Optional metadata
    success_criteria: Optional[str] = Field(
        default=None, description="How to verify success"
    )
    improvements: Optional[str] = Field(
        default=None, description="What could be done better (for reflections)"
    )
    unnecessary_tools: List[str] = Field(
        default_factory=list, description="Tools that were called but weren't needed"
    )
    optimal_approach: Optional[str] = Field(
        default=None, description="Most efficient way to do this task"
    )
    what_worked: Optional[str] = Field(
        default=None, description="What approach worked well and why"
    )
    what_didnt_work: Optional[str] = Field(
        default=None, description="Failed attempts or unnecessary steps taken"
    )
    gotchas: Optional[str] = Field(
        default=None, description="Edge cases, gotchas, or things to watch out for"
    )

    # Tracking
    session_id: Optional[str] = Field(
        default=None, description="Session where this was learned"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    usage_count: int = Field(
        default=0, description="How many times this skill was retrieved"
    )
    last_used_at: Optional[datetime] = Field(default=None)

    # Embedding for semantic search (optional - can be added later)
    embedding: Optional[List[float]] = Field(default=None, exclude=True)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class SkillExtractionResult(BaseModel):
    """Result from skill extraction process."""

    skills: List[Skill] = Field(default_factory=list)
    skipped_reason: Optional[str] = Field(default=None)
    extraction_time_ms: Optional[float] = Field(default=None)


class SkillSearchResult(BaseModel):
    """Result from skill search."""

    skills: List[Skill] = Field(default_factory=list)
    query: str
    agent_id: str
