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


_SLUG_STRIP_CHARS = "-"


def generate_integration_slug(
    name: str,
    category: str,
    max_length: int = 80,  # pragma: no mutate — segments cap the slug at 65 chars, so 80 and 81 never truncate
) -> str:
    """Generate canonical slug: {name}-mcp-{category}.

    No longer appends a hash suffix — the slug is human-readable and
    stored/indexed in MongoDB for direct lookup.
    """
    # Named constant, not an inline literal: the strip charset is part of the
    # slug format contract, and a mutated inline "-" would be untestable.
    slug = f"{slugify(name, max_length=40)}-mcp-{slugify(category, max_length=20)}"

    if len(slug) > max_length:
        truncated = slug[:max_length]
        last_hyphen = truncated.rfind(_SLUG_STRIP_CHARS)
        slug = truncated[:last_hyphen] if last_hyphen > 0 else truncated

    return slug.rstrip(_SLUG_STRIP_CHARS)
