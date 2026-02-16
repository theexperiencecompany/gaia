"""
Skill Discovery from GitHub - Discover available skills in remote repos.

This module provides functionality to:
- List available skills in a GitHub repository
- Recursively search for skills (following Vercel skills CLI pattern)
- Install skills without knowing the exact path

Based on Vercel skills CLI patterns (https://github.com/vercel-labs/skills)
"""

import os
import re
from typing import List, Optional, Set, Tuple

import httpx

from app.agents.skills.parser import parse_skill_md
from app.config.loggers import app_logger as logger

GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

MAX_RECURSION_DEPTH = 5
MAX_SKILLS_PER_REPO = 100


def _get_github_token() -> Optional[str]:
    """Get GitHub token from environment for API rate limit relief."""
    return os.environ.get("GITHUB_TOKEN")


def _get_headers() -> dict:
    """Get headers for GitHub API requests."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


class DiscoveredSkill:
    """A skill found in a remote repository."""

    def __init__(
        self,
        name: str,
        description: str,
        path: str,
        repo_url: str,
        subagent_id: str = "global",
    ):
        self.name = name
        self.description = description
        self.path = path
        self.repo_url = repo_url
        self.subagent_id = subagent_id

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "repo_url": self.repo_url,
            "subagent_id": self.subagent_id,
        }


def _parse_github_url(url: str) -> Tuple[str, str]:
    """Parse GitHub URL into owner and repo."""
    url = url.strip().rstrip("/")

    github_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        url,
    )
    if github_match:
        return github_match.group(1), github_match.group(2)

    parts = url.split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]

    raise ValueError(f"Invalid GitHub URL: {url}")


async def _fetch_github_contents(
    owner: str,
    repo: str,
    path: str,
    branch: str = "main",
) -> List[dict]:
    """Fetch directory contents from GitHub API."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": branch}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params, headers=_get_headers())

        if resp.status_code == 404:
            if branch == "main":
                return await _fetch_github_contents(owner, repo, path, "master")
            return []

        if resp.status_code == 403:
            logger.warning(
                "[skills] GitHub rate limited. Set GITHUB_TOKEN for higher limits"
            )
            return []

        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict):
            return [data]
        return data


async def _fetch_file_content(
    owner: str, repo: str, path: str, branch: str = "main"
) -> Optional[str]:
    """Fetch raw file content from GitHub."""
    url = f"{GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=_get_headers())

        if resp.status_code == 404:
            return None

        resp.raise_for_status()
        return resp.text


async def _parse_skill_from_content(
    content: str,
    folder_path: str,
    repo_url: str,
) -> Optional[DiscoveredSkill]:
    """Parse SKILL.md content and return DiscoveredSkill."""
    try:
        metadata, _ = parse_skill_md(content)
        return DiscoveredSkill(
            name=metadata.name,
            description=metadata.description,
            path=folder_path,
            repo_url=repo_url,
            subagent_id=metadata.target,
        )
    except Exception as e:
        logger.debug(f"[skills] Failed to parse SKILL.md in {folder_path}: {e}")
        return None


async def _find_skill_in_folder(
    owner: str,
    repo: str,
    folder_path: str,
    repo_url: str,
) -> Optional[DiscoveredSkill]:
    """Check if a folder contains a SKILL.md and parse it."""
    skill_md_path = f"{folder_path}/SKILL.md"

    try:
        content = await _fetch_file_content(owner, repo, skill_md_path)
    except Exception:
        return None

    if not content:
        return None

    return await _parse_skill_from_content(content, folder_path, repo_url)


async def _recursive_search_skills(
    owner: str,
    repo: str,
    current_path: str,
    repo_url: str,
    depth: int,
    visited: Set[str],
    found_skills: List[DiscoveredSkill],
) -> None:
    """Recursively search for skills in a repository."""
    if depth > MAX_RECURSION_DEPTH:
        return

    if len(found_skills) >= MAX_SKILLS_PER_REPO:
        return

    if current_path in visited:
        return
    visited.add(current_path)

    try:
        contents = await _fetch_github_contents(owner, repo, current_path)
    except Exception:
        return

    if not contents:
        return

    for entry in contents:
        if entry.get("type") != "dir":
            continue

        folder_path = entry.get("path", "")

        skill = await _find_skill_in_folder(owner, repo, folder_path, repo_url)
        if skill:
            found_skills.append(skill)
            logger.debug(f"[skills] Found skill: {skill.name} in {folder_path}")
            continue

        await _recursive_search_skills(
            owner,
            repo,
            folder_path,
            repo_url,
            depth + 1,
            visited,
            found_skills,
        )


async def discover_skills_from_repo(
    repo_url: str,
    branch: str = "main",
) -> List[DiscoveredSkill]:
    """Discover all available skills in a GitHub repository.

    Algorithm (following Vercel skills CLI):
    1. First check if root has SKILL.md
    2. Then search common standard folders
    3. Finally do recursive search if no skills found

    Args:
        repo_url: GitHub repo (owner/repo or full URL)
        branch: Branch to search (default: main)

    Returns:
        List of DiscoveredSkill objects
    """
    owner, repo = _parse_github_url(repo_url)
    full_repo_url = f"https://github.com/{owner}/{repo}"
    logger.info(f"[skills] Discovering skills in {owner}/{repo}")

    all_skills: List[DiscoveredSkill] = []
    visited: Set[str] = set()

    root_skill = await _find_skill_in_folder(owner, repo, "", full_repo_url)
    if root_skill:
        all_skills.append(root_skill)
        logger.info(f"[skills] Found skill in root: {root_skill.name}")

    standard_folders = [
        "skills",
        ".claude/skills",
        ".cursor/skills",
        ".windsurf/skills",
        ".agents/skills",
        ".claude",
    ]

    for folder in standard_folders:
        if len(all_skills) >= MAX_SKILLS_PER_REPO:
            break

        skill = await _find_skill_in_folder(owner, repo, folder, full_repo_url)
        if skill:
            all_skills.append(skill)
            logger.debug(f"[skills] Found skill in {folder}: {skill.name}")

    if not all_skills:
        logger.debug("[skills] No skills in standard folders, doing recursive search")
        await _recursive_search_skills(
            owner,
            repo,
            "",
            full_repo_url,
            0,
            visited,
            all_skills,
        )

    logger.info(f"[skills] Found {len(all_skills)} skills in {owner}/{repo}")
    return all_skills


async def get_skill_from_repo(
    repo_url: str,
    skill_name: str,
    branch: str = "main",
) -> Optional[DiscoveredSkill]:
    """Get a specific skill by name from a GitHub repository.

    Args:
        repo_url: GitHub repo (owner/repo or full URL)
        skill_name: Name of the skill to find
        branch: Branch to search (default: main)

    Returns:
        DiscoveredSkill if found, None otherwise
    """
    skills = await discover_skills_from_repo(repo_url, branch)

    for skill in skills:
        if skill.name == skill_name:
            return skill

    return None


async def list_recommended_skills() -> List[dict]:
    """List recommended skill repositories from the ecosystem."""
    recommended = [
        {
            "name": "Vercel Agent Skills",
            "repo": "vercel-labs/agent-skills",
            "description": "Official Vercel skill templates for common tasks",
            "skill_count_estimate": 50,
            "url": "https://github.com/vercel-labs/agent-skills",
        },
    ]

    return recommended
