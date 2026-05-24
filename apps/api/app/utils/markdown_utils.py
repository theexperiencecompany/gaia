"""Utilities for markdown detection and conversion."""

import re

import markdown2

from shared.py.wide_events import log


def convert_markdown_to_html(markdown_text: str) -> str:
    """
    Convert markdown text to HTML.

    Args:
        markdown_text: The markdown text to convert

    Returns:
        str: HTML string
    """
    log.set(operation="convert_markdown_to_html", input_length=len(markdown_text))
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
        log.error(f"Error converting markdown to HTML: {e}")
        return markdown_text


_HTML_TAG_RE = re.compile(
    r"<\s*(p|div|html|body|br|h[1-6]|ul|ol|li|table|span|a|strong|em)\b",
    re.IGNORECASE,
)


def looks_like_html(text: str) -> bool:
    """Return True if ``text`` appears to already be HTML.

    Used at the email boundary to decide whether to run the body through the
    markdown→HTML converter. We look for common block/inline HTML tags rather
    than any ``<…>`` so strings like ``"x < 5"`` don't false-positive.
    """
    if not text:
        return False
    return bool(_HTML_TAG_RE.search(text))


def normalize_email_body_to_html(body: str) -> str:
    """Always return HTML for an email body.

    The agent produces Markdown, users/forms sometimes paste Markdown, and the
    REST layer historically had an ``is_html`` flag that was unreliable.
    Normalising at the send boundary means Gmail always receives HTML and
    renders consistently — ``**bold**`` never leaks into the recipient's
    inbox as literal asterisks. markdown2 wraps plain-text bodies in ``<p>``
    tags, so this is safe for both Markdown and plain-text inputs.
    """
    if not body:
        return body
    if looks_like_html(body):
        return body
    return convert_markdown_to_html(body)


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
        log.error(f"Error converting markdown to plain text: {e}")
        return markdown_text


def split_yaml_frontmatter(content: str) -> tuple[str, str] | None:
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
