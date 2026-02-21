"""
Skill Discovery from GitHub - Discover available skills in remote repos.

This module provides functionality to:
- List available skills in a GitHub repository
- Efficiently search for skills using Git Tree API
- Install skills without knowing the exact path

Based on Vercel skills CLI patterns (https://github.com/vercel-labs/skills)
"""

import asyncio
from typing import List, Optional, Tuple

import httpx
from app.agents.skills.parser import parse_skill_md
from app.agents.skills.utils import (
    GITHUB_API_BASE,
    GITHUB_RAW_BASE,
    MAX_SKILLS_PER_REPO,
    check_tree_truncated,
    find_skill_files,
    get_folder_path,
    get_folder_priority,
    get_github_headers,
    parse_github_url,
)
from app.config.loggers import app_logger as logger


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


async def _fetch_git_tree(
    owner: str,
    repo: str,
    branch: str = "main",
) -> Tuple[List[dict], str]:
    """Fetch entire repository tree using Git Tree API.

    Uses recursive=1 to get all files in a single API call.
    Returns (tree_entries, resolved_branch).

    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch to fetch (default: main)

    Returns:
        Tuple of (list of tree entries, resolved branch name)
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}"
    params = {"recursive": "1"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, params=params, headers=get_github_headers())

        # Try master if main branch not found
        if resp.status_code == 404 and branch == "main":
            return await _fetch_git_tree(owner, repo, "master")

        if resp.status_code == 403:
            logger.warning(
                "[skills] GitHub rate limited. Set GITHUB_TOKEN for higher limits"
            )
            return [], branch

        resp.raise_for_status()
        data = resp.json()

        # Handle truncated trees (very large repos)
        check_tree_truncated(data, owner, repo)

        return data.get("tree", []), branch


async def _fetch_single_file_content(
    owner: str,
    repo: str,
    path: str,
    branch: str,
) -> Optional[Tuple[str, str]]:
    """Fetch raw file content from GitHub.

    Args:
        owner: Repository owner
        repo: Repository name
        path: File path
        branch: Branch name

    Returns:
        Tuple of (file_path, content) or None if failed
    """
    url = f"{GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=get_github_headers())

            if resp.status_code == 404:
                logger.debug(f"[skills] File not found: {path}")
                return None

            resp.raise_for_status()
            return path, resp.text

    except Exception as e:
        logger.debug(f"[skills] Failed to fetch {path}: {e}")
        return None


async def _fetch_file_contents_batch(
    owner: str,
    repo: str,
    paths: List[str],
    branch: str,
) -> List[Tuple[str, str]]:
    """Fetch multiple file contents in parallel.

    Args:
        owner: Repository owner
        repo: Repository name
        paths: List of file paths to fetch
        branch: Branch name

    Returns:
        List of (path, content) tuples for successful fetches
    """
    tasks = [_fetch_single_file_content(owner, repo, path, branch) for path in paths]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    contents: List[Tuple[str, str]] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.debug(f"[skills] Exception fetching file: {result}")
            continue
        if result is not None:
            contents.append(result)

    return contents


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


async def discover_skills_from_repo(
    repo_url: str,
    branch: str = "main",
) -> List[DiscoveredSkill]:
    """Discover all available skills in a GitHub repository.

    Uses Git Tree API for efficient discovery in a single API call,
    then batches content fetches using raw URLs.

    Args:
        repo_url: GitHub repo (owner/repo or full URL)
        branch: Branch to search (default: main)

    Returns:
        List of DiscoveredSkill objects
    """
    owner, repo = parse_github_url(repo_url)
    full_repo_url = f"https://github.com/{owner}/{repo}"
    logger.info(f"[skills] Discovering skills in {owner}/{repo}")

    # Step 1: Fetch entire repo tree in one API call
    tree_entries, resolved_branch = await _fetch_git_tree(owner, repo, branch)

    if not tree_entries:
        logger.warning(f"[skills] No tree entries found in {owner}/{repo}")
        return []

    logger.info(
        f"[skills] Fetched tree with {len(tree_entries)} entries from "
        f"{owner}/{repo} ({resolved_branch})"
    )

    # Step 2: Find all SKILL.md files in the tree
    skill_files = find_skill_files(tree_entries)

    if not skill_files:
        logger.info(f"[skills] No SKILL.md files found in {owner}/{repo}")
        return []

    logger.info(f"[skills] Found {len(skill_files)} potential skill files")

    # Step 3: Sort by priority (standard folders first)
    skill_files.sort(key=get_folder_priority)

    # Step 4: Batch fetch all skill file contents
    contents = await _fetch_file_contents_batch(
        owner, repo, skill_files, resolved_branch
    )

    # Step 5: Parse each skill file
    all_skills: List[DiscoveredSkill] = []

    for file_path, content in contents:
        folder_path = get_folder_path(file_path)

        skill = await _parse_skill_from_content(content, folder_path, full_repo_url)
        if skill:
            all_skills.append(skill)
            logger.debug(f"[skills] Parsed skill: {skill.name} from {folder_path}")

        if len(all_skills) >= MAX_SKILLS_PER_REPO:
            logger.warning(f"[skills] Reached max skills limit ({MAX_SKILLS_PER_REPO})")
            break

    logger.info(f"[skills] Found {len(all_skills)} valid skills in {owner}/{repo}")
    return all_skills


async def get_skill_from_repo(
    repo_url: str,
    skill_name: str,
    branch: str = "main",
) -> Optional[DiscoveredSkill]:
    """Get a specific skill by name from a GitHub repository.

    Uses the same efficient tree-based discovery as discover_skills_from_repo.

    Args:
        repo_url: GitHub repo (owner/repo or full URL)
        skill_name: Name of the skill to find
        branch: Branch to search (default: main)

    Returns:
        DiscoveredSkill if found, None otherwise
    """
    owner, repo = parse_github_url(repo_url)
    full_repo_url = f"https://github.com/{owner}/{repo}"
    logger.info(f"[skills] Looking for skill '{skill_name}' in {owner}/{repo}")

    # Fetch tree and find skill files
    tree_entries, resolved_branch = await _fetch_git_tree(owner, repo, branch)

    if not tree_entries:
        return None

    skill_files = find_skill_files(tree_entries)

    # Batch fetch and parse until we find the matching skill
    contents = await _fetch_file_contents_batch(
        owner, repo, skill_files, resolved_branch
    )

    for file_path, content in contents:
        folder_path = get_folder_path(file_path)

        skill = await _parse_skill_from_content(content, folder_path, full_repo_url)
        if skill and skill.name == skill_name:
            logger.info(f"[skills] Found skill '{skill_name}' at {folder_path}")
            return skill

    logger.info(f"[skills] Skill '{skill_name}' not found in {owner}/{repo}")
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
