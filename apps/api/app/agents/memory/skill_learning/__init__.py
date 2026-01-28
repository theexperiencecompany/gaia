"""
Skill Learning System - Custom skill extraction to replace mem0 for skills.

Two extraction strategies:
1. LLM Extraction - Uses a cheap LLM (gpt-4o-mini) to extract skills
2. Self-Reflection - Has the executing LLM document its experience

Skills are stored in MongoDB (agent_skills collection), isolated per agent_id.
User memory still uses mem0 via the separate user memory path.
"""

from app.agents.memory.skill_learning.models import (
    Skill,
    SkillExtractionResult,
    SkillSearchResult,
    SkillType,
)
from app.agents.memory.skill_learning.service import (
    SkillLearningService,
    get_skill_learning_service,
    learn_skills,
)
from app.agents.memory.skill_learning.storage import (
    delete_skill,
    delete_skills_by_agent,
    get_skills_by_agent,
    increment_usage,
    search_skills,
    store_skill,
    store_skills_batch,
)

__all__ = [
    # Models
    "Skill",
    "SkillType",
    "SkillExtractionResult",
    "SkillSearchResult",
    # Service
    "SkillLearningService",
    "get_skill_learning_service",
    "learn_skills",
    # Storage operations
    "store_skill",
    "store_skills_batch",
    "search_skills",
    "get_skills_by_agent",
    "increment_usage",
    "delete_skill",
    "delete_skills_by_agent",
]
