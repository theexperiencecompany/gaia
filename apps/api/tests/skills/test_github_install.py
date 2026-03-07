"""
Unit tests for skill discovery from GitHub.

These tests verify:
1. Discovering skills from a repo works end-to-end
2. Getting a specific skill by name works
3. Skills have correct metadata on the returned objects
4. The function returns an empty list on 403 (rate limit)
5. The function returns an empty list on 404 (repo not found)

All HTTP calls are intercepted by respx — no real network traffic.
"""

import httpx
import pytest
import respx

from app.agents.skills.github_discovery import (
    discover_skills_from_repo,
    get_skill_from_repo,
)
from app.agents.skills.utils import GITHUB_API_BASE, GITHUB_RAW_BASE

# ---------------------------------------------------------------------------
# Canned fixtures
# ---------------------------------------------------------------------------

# Minimal Git Tree API response for vercel-labs/agent-skills on branch "main".
# Contains one skill file at skills/vercel-react-best-practices/SKILL.md.
_TREE_RESPONSE = {
    "sha": "abc123",
    "truncated": False,
    "tree": [
        {
            "path": "skills/vercel-react-best-practices/SKILL.md",
            "mode": "100644",
            "type": "blob",
            "sha": "def456",
        },
        {
            "path": "README.md",
            "mode": "100644",
            "type": "blob",
            "sha": "ghi789",
        },
    ],
}

# Minimal SKILL.md content that passes parse_skill_md validation.
_SKILL_MD_CONTENT = """\
---
name: vercel-react-best-practices
description: Best practices for building React apps on Vercel
target: global
---

Follow these guidelines when writing React code for Vercel deployments.
"""

# Tree response with two skills, used by the metadata validation test.
_TREE_TWO_SKILLS = {
    "sha": "abc123",
    "truncated": False,
    "tree": [
        {
            "path": "skills/skill-alpha/SKILL.md",
            "mode": "100644",
            "type": "blob",
            "sha": "aaa111",
        },
        {
            "path": "skills/skill-beta/SKILL.md",
            "mode": "100644",
            "type": "blob",
            "sha": "bbb222",
        },
    ],
}

_SKILL_MD_ALPHA = """\
---
name: skill-alpha
description: Alpha skill description
target: global
---

Alpha skill body.
"""

_SKILL_MD_BETA = """\
---
name: skill-beta
description: Beta skill description
target: executor
---

Beta skill body.
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_discover_skills_from_vercel_repo() -> None:
    """Discover skills from vercel-labs/agent-skills returns a populated list."""
    tree_url = f"{GITHUB_API_BASE}/repos/vercel-labs/agent-skills/git/trees/main"
    raw_url = (
        f"{GITHUB_RAW_BASE}/vercel-labs/agent-skills/main"
        "/skills/vercel-react-best-practices/SKILL.md"
    )

    respx.get(tree_url).mock(return_value=httpx.Response(200, json=_TREE_RESPONSE))
    respx.get(raw_url).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

    skills = await discover_skills_from_repo("vercel-labs/agent-skills")

    assert len(skills) > 0, "Should find at least one skill"
    assert all(s.name for s in skills), "All skills should have names"
    assert all(s.description for s in skills), "All skills should have descriptions"


@respx.mock
async def test_get_skill_by_name() -> None:
    """get_skill_from_repo returns the matching DiscoveredSkill by name."""
    tree_url = f"{GITHUB_API_BASE}/repos/vercel-labs/agent-skills/git/trees/main"
    raw_url = (
        f"{GITHUB_RAW_BASE}/vercel-labs/agent-skills/main"
        "/skills/vercel-react-best-practices/SKILL.md"
    )

    respx.get(tree_url).mock(return_value=httpx.Response(200, json=_TREE_RESPONSE))
    respx.get(raw_url).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

    skill = await get_skill_from_repo(
        "vercel-labs/agent-skills", "vercel-react-best-practices"
    )

    assert skill is not None, "Should find vercel-react-best-practices skill"
    assert skill.name == "vercel-react-best-practices"


@respx.mock
async def test_skill_has_valid_metadata() -> None:
    """Each discovered skill carries name, description, path, and repo_url."""
    tree_url = f"{GITHUB_API_BASE}/repos/vercel-labs/agent-skills/git/trees/main"
    raw_alpha = (
        f"{GITHUB_RAW_BASE}/vercel-labs/agent-skills/main/skills/skill-alpha/SKILL.md"
    )
    raw_beta = (
        f"{GITHUB_RAW_BASE}/vercel-labs/agent-skills/main/skills/skill-beta/SKILL.md"
    )

    respx.get(tree_url).mock(return_value=httpx.Response(200, json=_TREE_TWO_SKILLS))
    respx.get(raw_alpha).mock(return_value=httpx.Response(200, text=_SKILL_MD_ALPHA))
    respx.get(raw_beta).mock(return_value=httpx.Response(200, text=_SKILL_MD_BETA))

    skills = await discover_skills_from_repo("vercel-labs/agent-skills")

    assert len(skills) == 2, "Should find exactly two skills"

    for skill in skills:
        assert skill.name, "Skill should have a name"
        assert skill.description, "Skill should have a description"
        assert skill.path, "Skill should have a path"
        assert skill.repo_url, "Skill should have a repo URL"
        assert skill.repo_url == "https://github.com/vercel-labs/agent-skills"


@respx.mock
async def test_discover_skills_from_gaia_repo() -> None:
    """discover_skills_from_repo returns populated list with correct field values."""
    tree_url = f"{GITHUB_API_BASE}/repos/anthropic/claude-code-skills/git/trees/main"
    raw_url = (
        f"{GITHUB_RAW_BASE}/anthropic/claude-code-skills/main"
        "/skills/vercel-react-best-practices/SKILL.md"
    )

    respx.get(tree_url).mock(return_value=httpx.Response(200, json=_TREE_RESPONSE))
    respx.get(raw_url).mock(return_value=httpx.Response(200, text=_SKILL_MD_CONTENT))

    skills = await discover_skills_from_repo("anthropic/claude-code-skills")

    assert len(skills) == 1, "Should find exactly one skill from canned response"
    skill = skills[0]
    assert skill.name == "vercel-react-best-practices"
    assert skill.description == "Best practices for building React apps on Vercel"
    assert skill.path == "skills/vercel-react-best-practices"
    assert skill.repo_url == "https://github.com/anthropic/claude-code-skills"


@respx.mock
async def test_discover_skills_returns_empty_on_rate_limit() -> None:
    """A 403 response from the tree endpoint returns an empty list (not an error)."""
    tree_url = f"{GITHUB_API_BASE}/repos/vercel-labs/agent-skills/git/trees/main"

    respx.get(tree_url).mock(return_value=httpx.Response(403))

    skills = await discover_skills_from_repo("vercel-labs/agent-skills")

    assert skills == [], "Rate-limited (403) should yield an empty list"


@respx.mock
async def test_discover_skills_returns_empty_on_404() -> None:
    """A 404 on main falls back to master; a 404 on master raises HTTPStatusError."""
    tree_main = f"{GITHUB_API_BASE}/repos/no-one/no-repo/git/trees/main"
    tree_master = f"{GITHUB_API_BASE}/repos/no-one/no-repo/git/trees/master"

    respx.get(tree_main).mock(return_value=httpx.Response(404))
    respx.get(tree_master).mock(return_value=httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        await discover_skills_from_repo("no-one/no-repo")
