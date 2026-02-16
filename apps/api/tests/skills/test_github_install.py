"""
Integration tests for skill discovery from GitHub.

These tests verify:
1. Discovering skills from a real GitHub repo works
2. Getting specific skill by name works
3. Skills have correct metadata

Requires GITHUB_TOKEN for GitHub API access.
Set EVAL_USER_ID if you want to run full integration tests (requires MongoDB/VFS).
"""

import os
from typing import cast

import pytest
from app.agents.skills.github_discovery import (
    discover_skills_from_repo,
    get_skill_from_repo,
)

pytestmark = pytest.mark.asyncio


EVAL_USER_ID = os.environ.get("EVAL_USER_ID")


@pytest.fixture
def user_id() -> str:
    """Get user ID from environment or skip test."""
    if not EVAL_USER_ID:
        pytest.skip("EVAL_USER_ID not set in environment")
    return cast(str, EVAL_USER_ID)


@pytest.mark.asyncio
async def test_discover_skills_from_vercel_repo():
    """Test discovering skills from Vercel agent-skills repo."""
    skills = await discover_skills_from_repo("vercel-labs/agent-skills")

    if not skills:
        pytest.skip("GitHub API rate limited (60 requests/hour without token)")

    assert len(skills) > 0, "Should find at least one skill"

    skill_names = [s.name for s in skills]
    print(f"Found {len(skills)} skills: {skill_names[:5]}...")

    assert all(s.name for s in skills), "All skills should have names"
    assert all(s.description for s in skills), "All skills should have descriptions"


@pytest.mark.asyncio
async def test_get_skill_by_name():
    """Test getting a specific skill by name."""
    skill = await get_skill_from_repo(
        "vercel-labs/agent-skills", "vercel-react-best-practices"
    )

    if not skill:
        pytest.skip("GitHub API rate limited")

    assert skill is not None, "Should find vercel-react-best-practices skill"
    assert skill.name == "vercel-react-best-practices"


@pytest.mark.asyncio
async def test_skill_has_valid_metadata():
    """Test that discovered skills have valid metadata."""
    skills = await discover_skills_from_repo("vercel-labs/agent-skills")

    if not skills:
        pytest.skip("GitHub API rate limited")

    assert len(skills) > 0, "Should find skills"

    for skill in skills:
        assert skill.name, "Skill should have a name"
        assert skill.description, "Skill should have a description"
        assert skill.path, "Skill should have a path"
        assert skill.repo_url, "Skill should have a repo URL"


@pytest.mark.asyncio
async def test_discover_skills_from_gaia_repo():
    """Test discovering skills from a different repo."""
    skills = await discover_skills_from_repo("anthropic/claude-code-skills")

    print(f"Found {len(skills)} skills in anthropic/claude-code-skills")
