"""
GitHub Skills Utilities - Helper functions for GitHub skill discovery.

This module provides utility functions for:
- GitHub API authentication
- URL parsing
- Tree API operations
- Skill file filtering and sorting
"""

import os
from typing import TypedDict
from urllib.parse import quote, urlparse

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

MAX_SKILLS_PER_REPO = 100
SKILL_FILENAMES = ["SKILL.md", "skill.md"]


class GitHubTreeEntry(TypedDict):
    """One entry of a Git Trees API response, limited to the keys discovery reads."""

    path: str
    type: str


class GitHubTree(TypedDict):
    """A Git Trees API response."""

    tree: list[GitHubTreeEntry]
    truncated: bool


class GitHubContentEntry(TypedDict):
    """One entry of a Contents API response; download_url is null for directories."""

    name: str
    path: str
    type: str
    download_url: str | None


def get_github_token() -> str | None:
    """Get GitHub token from environment for API rate limit relief."""
    return os.environ.get("GITHUB_TOKEN")


def get_github_headers() -> dict[str, str]:
    """Get headers for GitHub API requests."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def parse_github_url(url: str) -> tuple[str, str]:
    """Parse GitHub URL into owner and repo.

    Raises:
        ValueError: If URL is invalid.
    """
    url = url.strip()
    if not url:
        raise ValueError("Invalid GitHub URL")

    url = url.rstrip("/")

    if url.startswith(("http://", "https://")):
        parsed = urlparse(url)
        if parsed.netloc not in {"github.com", "www.github.com"}:
            raise ValueError(f"Invalid GitHub URL: {url}")
        parts = [p for p in parsed.path.strip("/").split("/") if p]
    else:
        parts = [p for p in url.strip("/").split("/") if p]
        if parts and parts[0] in {"github.com", "www.github.com"}:
            parts = parts[1:]

    if len(parts) >= 2:
        owner, repo = parts[0], parts[1]
        repo = repo.removesuffix(".git")
        return owner, repo

    raise ValueError(f"Invalid GitHub URL: {url}")


def github_url(base: str, *parts: str) -> str:
    """Join caller-supplied parts onto a GitHub base URL, percent-encoding every path segment."""
    segments = [segment for part in parts for segment in part.split("/")]
    # httpx collapses dot segments, so one would steer the server's token to any GitHub endpoint
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"Invalid GitHub path segment in {'/'.join(parts)!r}")
    return "/".join([base, *(quote(segment) for segment in segments)])


def find_skill_files(tree_entries: list[GitHubTreeEntry]) -> list[str]:
    """Find all SKILL.md and skill.md files in the tree entries from Git Tree API."""
    skill_files = []

    for entry in tree_entries:
        if entry["type"] != "blob":
            continue

        path = entry["path"]
        filename = path.split("/")[-1] if "/" in path else path

        if filename in SKILL_FILENAMES:
            skill_files.append(path)

    return skill_files


def get_folder_path(file_path: str) -> str:
    """Get the folder path from a file path (empty string if in root)."""
    if "/" not in file_path:
        return ""
    return file_path.rsplit("/", 1)[0]


def get_folder_priority(file_path: str) -> int:
    """Get priority for folder sorting (lower = higher priority).

    Order: root, skills/, .claude(cursor)/skills/, .claude/, other folders.
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


def check_tree_truncated(tree_data: GitHubTree, owner: str, repo: str) -> None:
    """Log a warning if the tree is truncated.

    Args:
        tree_data: Response from Git Tree API
        owner: Repository owner
        repo: Repository name
    """
    if tree_data["truncated"]:
        log.warning(
            f"{LogTag.SKILLS} Repository tree is truncated; some skills may not be discovered",
            owner=owner,
            repo=repo,
        )
