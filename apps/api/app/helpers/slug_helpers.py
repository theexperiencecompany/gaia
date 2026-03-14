"""Shared slug generation utilities for workflows and integrations."""

import re


def slugify(text: str, max_length: int = 50) -> str:
    """Convert text to URL-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-+", "-", slug)

    if len(slug) > max_length:
        parts = slug[:max_length].rsplit("-", 1)
        slug = parts[0] if parts else slug[:max_length]

    return slug


def generate_workflow_slug(title: str, workflow_id: str, max_length: int = 80) -> str:
    """Generate human-readable workflow slug: {title}-{shortid}.

    Examples:
        "Email Triaging", "wf_a1b2c3d4e5f6" -> "email-triaging-a1b2c3d4"
        "Monday Standup Notes", "wf_ff0011223344" -> "monday-standup-notes-ff001122"
    """
    title_slug = slugify(
        title, max_length=max_length - 9
    )  # Reserve 9 chars for -{shortid}
    raw_id = (
        workflow_id.replace("wf_", "") if workflow_id.startswith("wf_") else workflow_id
    )
    shortid = raw_id[:8].lower()

    slug = f"{title_slug}-{shortid}" if title_slug else shortid
    return slug.rstrip("-")


def parse_workflow_slug(slug: str) -> str | None:
    """Extract the 8-char workflow ID prefix from a workflow slug.

    Returns None if the slug doesn't end with a valid 8-char hex segment.
    """
    parts = slug.rsplit("-", 1)
    if (
        len(parts) == 2
        and len(parts[1]) == 8
        and all(c in "0123456789abcdef" for c in parts[1])
    ):
        return parts[1]
    return None
