"""
Skill Installer - Install skills from GitHub repos or create them inline.

Handles fetching skill content from external sources, parsing SKILL.md,
writing files to VFS, and registering in the MongoDB skill registry.
"""

import os
import re
from typing import List, Optional, Tuple

import httpx

from app.agents.skills.models import InstalledSkill, SkillSource
from app.agents.skills.parser import (
    generate_skill_md,
    parse_skill_md,
    validate_skill_content,
)
from app.agents.skills.registry import install_skill
from app.config.loggers import app_logger as logger
from app.services.vfs.path_resolver import get_custom_skill_path

GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"


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


def _parse_github_url(url: str) -> Tuple[str, str, Optional[str]]:
    """Parse a GitHub URL or shorthand into owner, repo, and optional path.

    Accepts:
        - "owner/repo"
        - "owner/repo/path/to/skill"
        - "https://github.com/owner/repo"
        - "https://github.com/owner/repo/tree/main/path/to/skill"
        - "https://github.com/owner/repo/blob/main/path/to/skill"

    Returns:
        Tuple of (owner, repo, path_within_repo)
    """
    # Strip whitespace and trailing slashes
    url = url.strip().rstrip("/")

    # Full GitHub URL
    github_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)(?:/(?:tree|blob)/[^/]+/(.+))?",
        url,
    )
    if github_match:
        return github_match.group(1), github_match.group(2), github_match.group(3)

    # Shorthand: owner/repo or owner/repo/path/to/skill
    parts = url.split("/")
    if len(parts) >= 2:
        owner = parts[0]
        repo = parts[1]
        path = "/".join(parts[2:]) if len(parts) > 2 else None
        return owner, repo, path

    raise ValueError(
        f"Invalid GitHub reference: {url}. "
        "Use 'owner/repo', 'owner/repo/path', or a full GitHub URL."
    )


async def _fetch_github_contents(
    owner: str,
    repo: str,
    path: str,
    branch: str = "main",
) -> List[dict]:
    """Fetch directory contents from GitHub API.

    Returns list of file info dicts with 'name', 'path', 'type', 'download_url'.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": branch}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params, headers=_get_headers())

        if resp.status_code == 404:
            if branch == "main":
                return await _fetch_github_contents(owner, repo, path, "master")
            raise ValueError(f"Path not found: {owner}/{repo}/{path}")

        if resp.status_code == 403:
            logger.warning("GitHub API rate limit exceeded. Try again later.")
            raise ValueError(
                "GitHub API rate limit exceeded. Please try again later, or set GITHUB_TOKEN for higher limits (5000/hr vs 60/hr)."
            )

        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict):
            return [data]
        return data


async def _fetch_file_content(download_url: str) -> str:
    """Download raw file content from a URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(download_url, headers=_get_headers())
        resp.raise_for_status()
        return resp.text


async def _get_vfs():
    """Get VFS instance lazily."""
    from app.services.vfs import get_vfs

    return await get_vfs()


async def install_from_github(
    user_id: str,
    repo_url: str,
    skill_path: Optional[str] = None,
    target_override: Optional[str] = None,
) -> InstalledSkill:
    """Install a skill from a GitHub repository.

    Args:
        user_id: Owner user ID
        repo_url: GitHub repo reference (owner/repo, full URL, etc.)
        skill_path: Optional path within repo to skill folder
        target_override: Override target from SKILL.md frontmatter

    Returns:
        The installed skill

    Raises:
        ValueError: If skill is invalid or already installed
    """
    owner, repo, url_path = _parse_github_url(repo_url)

    # Combine URL path with explicit skill_path
    base_path = url_path or ""
    if skill_path:
        base_path = f"{base_path}/{skill_path}".strip("/")

    if not base_path:
        raise ValueError(
            "Provide a path to the skill folder within the repo. "
            "Example: 'owner/repo/skills/my-skill' or use skill_path parameter."
        )

    source_url = f"https://github.com/{owner}/{repo}/tree/main/{base_path}"

    logger.info(f"[skills] Fetching from GitHub: {owner}/{repo}/{base_path}")

    # Fetch the directory contents
    contents = await _fetch_github_contents(owner, repo, base_path)

    # Find SKILL.md
    skill_md_entry = None
    for entry in contents:
        if entry["name"] == "SKILL.md":
            skill_md_entry = entry
            break

    if not skill_md_entry:
        raise ValueError(
            f"No SKILL.md found in {owner}/{repo}/{base_path}. "
            "A valid skill must contain a SKILL.md file."
        )

    # Download SKILL.md
    skill_md_content = await _fetch_file_content(skill_md_entry["download_url"])

    # Validate
    errors = validate_skill_content(skill_md_content)
    if errors:
        raise ValueError(f"Invalid SKILL.md: {'; '.join(errors)}")

    # Parse
    metadata, body = parse_skill_md(skill_md_content)

    # Apply target override
    if target_override:
        metadata.target = target_override

    # Determine VFS path
    vfs_dir = get_custom_skill_path(user_id, metadata.target, metadata.name)

    # Download all files in the skill directory
    vfs = await _get_vfs()
    file_list: List[str] = []

    # Write SKILL.md
    await vfs.write(
        f"{vfs_dir}/SKILL.md",
        skill_md_content,
        user_id,
        metadata={"source": "github", "source_url": source_url},
    )
    file_list.append("SKILL.md")

    # Download subdirectories and files recursively
    await _download_github_dir(
        vfs=vfs,
        user_id=user_id,
        vfs_base=vfs_dir,
        owner=owner,
        repo=repo,
        remote_path=base_path,
        contents=contents,
        file_list=file_list,
        source_url=source_url,
    )

    # Register in MongoDB
    installed = await install_skill(
        user_id=user_id,
        skill_metadata=metadata,
        vfs_path=vfs_dir,
        source=SkillSource.GITHUB,
        source_url=source_url,
        body_content=body,
        files=file_list,
    )

    logger.info(
        f"[skills] Installed '{metadata.name}' from GitHub "
        f"({len(file_list)} files, target={metadata.target})"
    )
    return installed


async def _download_github_dir(
    vfs,
    user_id: str,
    vfs_base: str,
    owner: str,
    repo: str,
    remote_path: str,
    contents: List[dict],
    file_list: List[str],
    source_url: str,
) -> None:
    """Recursively download GitHub directory contents to VFS."""
    for entry in contents:
        name = entry["name"]
        entry_type = entry["type"]

        if name == "SKILL.md":
            continue  # Already handled

        if entry_type == "file":
            # Download file
            content = await _fetch_file_content(entry["download_url"])
            relative_path = entry["path"].removeprefix(f"{remote_path}/")
            vfs_path = f"{vfs_base}/{relative_path}"
            await vfs.write(
                vfs_path,
                content,
                user_id,
                metadata={"source": "github", "source_url": source_url},
            )
            file_list.append(relative_path)

        elif entry_type == "dir":
            # Recurse into subdirectory
            sub_contents = await _fetch_github_contents(owner, repo, entry["path"])
            await _download_github_dir(
                vfs=vfs,
                user_id=user_id,
                vfs_base=vfs_base,
                owner=owner,
                repo=repo,
                remote_path=remote_path,
                contents=sub_contents,
                file_list=file_list,
                source_url=source_url,
            )


async def install_from_inline(
    user_id: str,
    name: str,
    description: str,
    instructions: str,
    target: str = "global",
    extra_metadata: Optional[dict[str, str]] = None,
) -> InstalledSkill:
    """Create and install a skill from inline components.

    Generates a SKILL.md from the provided components, writes it to VFS,
    and registers in the skill registry.

    Args:
        user_id: Owner user ID
        name: Skill name (kebab-case)
        description: What the skill does
        instructions: Markdown body instructions
        target: Where to make it available
        extra_metadata: Optional additional metadata key-values

    Returns:
        The installed skill
    """
    # Generate SKILL.md content
    skill_md_content = generate_skill_md(
        name=name,
        description=description,
        instructions=instructions,
        target=target,
        metadata=extra_metadata,
    )

    # Validate
    errors = validate_skill_content(skill_md_content)
    if errors:
        raise ValueError(f"Invalid skill: {'; '.join(errors)}")

    # Parse back to get validated metadata
    metadata, body = parse_skill_md(skill_md_content)

    # Write to VFS
    vfs_dir = get_custom_skill_path(user_id, metadata.target, metadata.name)
    vfs = await _get_vfs()
    await vfs.write(
        f"{vfs_dir}/SKILL.md",
        skill_md_content,
        user_id,
        metadata={"source": "inline"},
    )

    # Register
    installed = await install_skill(
        user_id=user_id,
        skill_metadata=metadata,
        vfs_path=vfs_dir,
        source=SkillSource.INLINE,
        body_content=body,
        files=["SKILL.md"],
    )

    logger.info(f"[skills] Created inline skill '{name}' (target={target})")
    return installed


async def uninstall_skill_full(user_id: str, skill_id: str) -> bool:
    """Uninstall a skill: remove from registry AND delete VFS files.

    Args:
        user_id: Owner user ID
        skill_id: Skill document ID

    Returns:
        True if uninstalled, False if not found
    """
    from app.agents.skills.registry import get_skill, uninstall_skill

    skill = await get_skill(user_id, skill_id)
    if not skill:
        return False

    # Delete VFS directory
    try:
        vfs = await _get_vfs()
        await vfs.delete(skill.vfs_path, user_id=user_id, recursive=True)
    except Exception as e:
        logger.warning(f"[skills] VFS cleanup failed for {skill_id}: {e}")

    # Remove from registry
    return await uninstall_skill(user_id, skill_id)
