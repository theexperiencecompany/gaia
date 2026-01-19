"""String utilities for the API."""

import re
from collections.abc import Awaitable, Callable


def slugify(text: str, max_length: int = 50) -> str:
    """
    Convert text to URL-safe slug.

    Args:
        text: Text to convert
        max_length: Maximum length of the slug

    Returns:
        URL-safe slug
    """
    # Lowercase
    slug = text.lower()

    # Replace spaces and special chars with hyphens
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)

    # Remove leading/trailing hyphens
    slug = slug.strip("-")

    # Remove consecutive hyphens
    slug = re.sub(r"-+", "-", slug)

    # Truncate to max length (at word boundary if possible)
    if len(slug) > max_length:
        parts = slug[:max_length].rsplit("-", 1)
        slug = parts[0] if parts else slug[:max_length]

    return slug


async def generate_unique_slug(
    name: str,
    user_id: str,
    check_exists_func: Callable[[str], Awaitable[bool]],
    max_length: int = 50,
) -> str:
    """
    Generate URL-safe slug, ensuring uniqueness.

    Args:
        name: Integration name
        user_id: User ID (for uniqueness suffix if needed)
        check_exists_func: Async function that takes slug and returns bool
        max_length: Maximum length of the slug

    Returns:
        Unique URL-safe slug
    """
    base_slug = slugify(name, max_length=max_length)

    # Check if base slug is available
    exists = await check_exists_func(base_slug)
    if not exists:
        return base_slug

    # Add short user ID suffix for uniqueness
    unique_slug = f"{base_slug}-{user_id[:6]}"

    # Truncate if needed
    if len(unique_slug) > max_length:
        # Trim base_slug to make room for suffix
        trimmed_base = base_slug[: max_length - 7]  # 6 chars + hyphen
        unique_slug = f"{trimmed_base}-{user_id[:6]}"

    return unique_slug
