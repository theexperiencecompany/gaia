"""
GitHub Skills Utilities - Helper functions for GitHub skill discovery.

This module provides utility functions for:
- GitHub API authentication
- URL parsing
- Tree API operations
- Skill file filtering and sorting
"""

import os
import re
from typing import List, Optional, Tuple

from app.config.loggers import app_logger as logger

GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

MAX_SKILLS_PER_REPO = 100
SKILL_FILENAMES = ["SKILL.md", "skill.md"]


def get_github_token() -> Optional[str]:
    """Get GitHub token from environment for API rate limit relief."""
    return os.environ.get("GITHUB_TOKEN")


def get_github_headers() -> dict:
    """Get headers for GitHub API requests."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def parse_github_url(url: str) -> Tuple[str, str]:
    """Parse GitHub URL into owner and repo.

    Args:
        url: GitHub URL or owner/repo string

    Returns:
        Tuple of (owner, repo)

    Raises:
        ValueError: If URL is invalid
    """
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


def find_skill_files(tree_entries: List[dict]) -> List[str]:
    """Find all SKILL.md and skill.md files in the tree.

    Args:
        tree_entries: List of tree entries from Git Tree API

    Returns:
        List of paths to skill files
    """
    skill_files = []

    for entry in tree_entries:
        if entry.get("type") != "blob":
            continue

        path = entry.get("path", "")
        filename = path.split("/")[-1] if "/" in path else path

        if filename in SKILL_FILENAMES:
            skill_files.append(path)

    return skill_files


def get_folder_path(file_path: str) -> str:
    """Get the folder path from a file path.

    Args:
        file_path: Path to the file

    Returns:
        Folder path (empty string if in root)
    """
    if "/" not in file_path:
        return ""
    return file_path.rsplit("/", 1)[0]


def get_folder_priority(file_path: str) -> int:
    """Get priority for folder sorting (lower = higher priority).

    Priority order:
    1. Root (empty path)
    2. skills/
    3. .claude/skills/, .cursor/skills/, etc.
    4. .claude/
    5. Other folders

    Args:
        file_path: Path to the skill file

    Returns:
        Priority value (lower = higher priority)
    """
    folder = get_folder_path(file_path)

    if folder == "":
        return 0
    if folder == "skills":
        return 1
    if folder in [
        ".claude/skills",
        ".cursor/skills",
        ".windsurf/skills",
        ".agents/skills",
    ]:
        return 2
    if folder == ".claude":
        return 3

    return 10


def check_tree_truncated(tree_data: dict, owner: str, repo: str) -> None:
    """Log a warning if the tree is truncated.

    Args:
        tree_data: Response from Git Tree API
        owner: Repository owner
        repo: Repository name
    """
    if tree_data.get("truncated"):
        logger.warning(
            f"[skills] Repository {owner}/{repo} tree is truncated. "
            "Some skills may not be discovered."
        )
