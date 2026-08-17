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
