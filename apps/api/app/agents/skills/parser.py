"""
SKILL.md Parser - Parse and validate Agent Skills format files.

Handles YAML frontmatter extraction and validation following the
Agent Skills spec (agentskills.io/specification).
"""

import re
from typing import List, Tuple

import yaml  # type: ignore[import-untyped]
from app.agents.skills.models import SkillMetadata

# Frontmatter delimiter pattern
FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)",
    re.DOTALL,
)


def parse_skill_md(content: str) -> Tuple[SkillMetadata, str]:
    """Parse a SKILL.md file into metadata and body content.

    Args:
        content: Raw SKILL.md file content

    Returns:
        Tuple of (SkillMetadata, body_markdown)

    Raises:
        ValueError: If frontmatter is missing or invalid
    """
    if not content or not content.strip():
        raise ValueError("SKILL.md content is empty")

    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise ValueError(
            "SKILL.md must start with YAML frontmatter delimited by --- lines"
        )

    frontmatter_raw = match.group(1)
    body = match.group(2).strip()

    try:
        frontmatter = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter: {e}") from e

    if not isinstance(frontmatter, dict):
        raise ValueError("YAML frontmatter must be a mapping (key-value pairs)")

    # Map allowed-tools (YAML key with hyphen) to allowed_tools (Python field)
    if "allowed-tools" in frontmatter:
        tools_raw = frontmatter.pop("allowed-tools")
        if isinstance(tools_raw, str):
            frontmatter["allowed_tools"] = tools_raw.split()
        elif isinstance(tools_raw, list):
            frontmatter["allowed_tools"] = tools_raw

    # Map subagent_id to target (GAIA-specific extension)
    if "subagent_id" in frontmatter:
        frontmatter["target"] = frontmatter.pop("subagent_id")

    # Ensure metadata field is dict[str, str]
    if "metadata" in frontmatter and isinstance(frontmatter["metadata"], dict):
        frontmatter["metadata"] = {
            str(k): str(v) for k, v in frontmatter["metadata"].items()
        }

    metadata = SkillMetadata(**frontmatter)

    return metadata, body


def strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from SKILL.md content, returning only the body.

    Used when writing to VFS — we store body-only in VFS since metadata
    lives in MongoDB.

    Args:
        content: Raw SKILL.md file content (with or without frontmatter)

    Returns:
        Body content without frontmatter delimiters
    """
    if not content:
        return ""

    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return content.strip()

    return match.group(2).strip()


def validate_skill_content(content: str) -> List[str]:
    """Validate a SKILL.md file and return a list of errors.

    Args:
        content: Raw SKILL.md file content

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: List[str] = []

    if not content or not content.strip():
        errors.append("SKILL.md content is empty")
        return errors

    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        errors.append("Missing YAML frontmatter (must start with --- delimiters)")
        return errors

    frontmatter_raw = match.group(1)
    body = match.group(2).strip()

    try:
        frontmatter = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML: {e}")
        return errors

    if not isinstance(frontmatter, dict):
        errors.append("Frontmatter must be a YAML mapping")
        return errors

    # Check required fields
    if "name" not in frontmatter:
        errors.append("Missing required field: name")
    if "description" not in frontmatter:
        errors.append("Missing required field: description")

    # Validate name format
    name = frontmatter.get("name", "")
    if name:
        if len(name) > 64:
            errors.append(f"name too long ({len(name)} chars, max 64)")
        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", name):
            errors.append("name must be lowercase alphanumeric with hyphens only")
        if "--" in name:
            errors.append("name must not contain consecutive hyphens")

    # Validate description
    description = frontmatter.get("description", "")
    if isinstance(description, str):
        if not description.strip():
            errors.append("description must not be empty")
        if len(description) > 1024:
            errors.append(f"description too long ({len(description)} chars, max 1024)")

    # Validate optional fields
    compatibility = frontmatter.get("compatibility")
    if compatibility and len(str(compatibility)) > 500:
        errors.append("compatibility too long (max 500 chars)")

    # Warn if body is very long
    if body:
        line_count = body.count("\n") + 1
        if line_count > 500:
            errors.append(
                f"Body has {line_count} lines (recommended max 500). "
                "Consider splitting into reference files."
            )

    return errors


def generate_skill_md(
    name: str,
    description: str,
    instructions: str,
    target: str = "executor",
    metadata: dict[str, str] | None = None,
) -> str:
    """Generate a SKILL.md file from components.

    Args:
        name: Skill name (kebab-case)
        description: What the skill does
        instructions: Markdown body instructions
        target: Target agent (default: executor)
        metadata: Optional additional metadata

    Returns:
        Complete SKILL.md content
    """
    frontmatter: dict = {
        "name": name,
        "description": description,
        "target": target,
    }

    if metadata:
        frontmatter["metadata"] = metadata

    yaml_str = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()

    return f"---\n{yaml_str}\n---\n\n{instructions}\n"
