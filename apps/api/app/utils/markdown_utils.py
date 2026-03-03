"""Utilities for markdown detection and conversion."""

import re
from typing import Optional

import markdown2

from app.config.loggers import app_logger as logger


def is_markdown_content(text: str) -> bool:
    """
    Detect if text contains markdown syntax.

    Args:
        text: The text to check

    Returns:
        bool: True if markdown syntax is detected
    """
    if not text or not isinstance(text, str):
        return False

    markdown_patterns = [
        r"^#{1,6}\s",  # Headers
        r"\*\*[^*]+\*\*",  # Bold with **
        r"__[^_]+__",  # Bold with __
        r"\*[^*]+\*",  # Italic with *
        r"_[^_]+_",  # Italic with _
        r"\[.+?\]\(.+?\)",  # Links [text](url)
        r"^[-*+]\s",  # Unordered lists
        r"^\d+\.\s",  # Ordered lists
        r"`[^`]+`",  # Inline code
        r"```[\s\S]*?```",  # Code blocks
        r"^>\s",  # Blockquotes
    ]

    for pattern in markdown_patterns:
        if re.search(pattern, text, re.MULTILINE):
            return True

    return False


def convert_markdown_to_html(markdown_text: str) -> str:
    """
    Convert markdown text to HTML.

    Args:
        markdown_text: The markdown text to convert

    Returns:
        str: HTML string
    """
    try:
        html = markdown2.markdown(
            markdown_text,
            extras=[
                "fenced-code-blocks",
                "tables",
                "break-on-newline",
                "cuddled-lists",
                "strike",
                "task_list",
            ],
        )
        return html
    except Exception as e:
        logger.error(f"Error converting markdown to HTML: {e}")
        return markdown_text


def convert_markdown_to_plain_text(markdown_text: str) -> str:
    """
    Convert markdown text to plain text by stripping markdown syntax.

    Args:
        markdown_text: The markdown text to convert

    Returns:
        str: Plain text string
    """
    try:
        text = markdown_text

        # Remove code blocks
        text = re.sub(r"```[\s\S]*?```", "", text)

        # Remove inline code
        text = re.sub(r"`([^`]+)`", r"\1", text)

        # Remove bold/italic
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)

        # Convert links to just text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

        # Remove headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

        # Remove blockquotes
        text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)

        # Remove list markers
        text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)

        # Clean up extra whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()
    except Exception as e:
        logger.error(f"Error converting markdown to plain text: {e}")
        return markdown_text


def split_yaml_frontmatter(content: str) -> Optional[tuple[str, str]]:
    """Split YAML frontmatter from markdown body.

    Expected format:
    ---
    <yaml>
    ---
    <body>

    Returns:
        (frontmatter_yaml, body) if frontmatter exists, else None.
    """
    if not content:
        return None

    lines = content.splitlines(keepends=True)
    if not lines:
        return None

    if lines[0].strip() != "---":
        return None

    frontmatter_lines: list[str] = []
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            frontmatter_raw = "".join(frontmatter_lines).rstrip("\r\n")
            body = "".join(lines[idx + 1 :])
            return frontmatter_raw, body
        frontmatter_lines.append(lines[idx])

    return None
