"""Notion ↔ Markdown bidirectional conversion utilities.

Provides:
- blocks_to_markdown(): Convert Notion blocks → Markdown string
- markdown_to_notion_blocks(): Convert Markdown string → NOTION_ADD_MULTIPLE_PAGE_CONTENT format

Adapted from notion-to-md-py with modifications for Composio integration.
"""

from collections.abc import Callable, Sequence
import re

from app.models.integrations.notion_blocks import (
    NotionAnnotations,
    NotionBlock,
    NotionBlockContent,
    NotionCodeBlock,
    NotionCodeBlockBody,
    NotionContentBlock,
    NotionIcon,
    NotionMarkdownBlock,
    NotionRichText,
    NotionTableBlock,
    NotionTableRow,
    NotionTextContent,
    NotionTextRun,
)

# =============================================================================
# Markdown Formatting Functions
# =============================================================================


def _inline_code(text: str) -> str:
    return f"`{text}`"


def _inline_equation(text: str) -> str:
    return f"${text}$"


def _bold(text: str) -> str:
    return f"**{text}**"


def _italic(text: str) -> str:
    return f"_{text}_"


def _strikethrough(text: str) -> str:
    return f"~~{text}~~"


def _underline(text: str) -> str:
    # HTML fallback since markdown doesn't support underline
    return f"<u>{text}</u>"


def _link(text: str, href: str) -> str:
    return f"[{text}]({href})"


def _code_block(text: str, language: str | None = None) -> str:
    if language == "plain text":
        language = "text"
    return f"```{language or ''}\n{text}\n```"


def _equation(text: str) -> str:
    return f"$$\n{text}\n$$"


def _heading1(text: str) -> str:
    return f"# {text}"


def _heading2(text: str) -> str:
    return f"## {text}"


def _heading3(text: str) -> str:
    return f"### {text}"


def _quote(text: str) -> str:
    no_newline = text.replace("\n", "\n> ")
    return f"> {no_newline}"


def _callout(text: str, icon: NotionIcon | None = None) -> str:
    emoji = icon.emoji if icon and icon.type == "emoji" else ""
    formatted_text = text.replace("\n", "\n> ")
    formatted_emoji = emoji + " " if emoji else ""
    heading_match = re.match(r"^(#{1,6})\s+(.+)", formatted_text)

    if heading_match:
        level, content = heading_match.groups()
        return f"> {'#' * len(level)} {formatted_emoji}{content}"
    return f"> {formatted_emoji}{formatted_text}"


def _bullet(text: str, count: int | None = None) -> str:
    text = text.strip()
    return f"{count}. {text}" if count else f"- {text}"


def _todo(text: str, checked: bool) -> str:
    return f"- [{'x' if checked else ' '}] {text}"


def _image(alt: str, href: str) -> str:
    return f"![{alt}]({href})"


def _add_tab_space(text: str, n: int = 0) -> str:
    if n <= 0:
        return text

    tab = "\t"
    if "\n" in text:
        lines = text.split("\n")
        return "\n".join(f"{tab * n}{line}" for line in lines)
    return f"{tab * n}{text}"


def _divider() -> str:
    return "---"


def _toggle(summary: str | None = None, children: str | None = None) -> str:
    if not summary:
        return children or ""
    return f"<details><summary>{summary}</summary>{children or ''}</details>"


# =============================================================================
# Annotation Application
# =============================================================================


def _apply_annotations(plain_text: str, annotations: NotionAnnotations) -> str:
    """Apply text annotations (bold, italic, etc.) to plain text."""
    if not plain_text.strip():
        return plain_text

    leading_space = plain_text[: len(plain_text) - len(plain_text.lstrip())]
    trailing_space = plain_text[len(plain_text.rstrip()) :]

    plain_text = plain_text.strip()

    if plain_text:
        if annotations.code:
            plain_text = _inline_code(plain_text)
        if annotations.bold:
            plain_text = _bold(plain_text)
        if annotations.italic:
            plain_text = _italic(plain_text)
        if annotations.strikethrough:
            plain_text = _strikethrough(plain_text)
        if annotations.underline:
            plain_text = _underline(plain_text)

    return leading_space + plain_text + trailing_space


# =============================================================================
# Rich Text Conversion
# =============================================================================


def rich_text_to_markdown(rich_text: Sequence[NotionRichText]) -> str:
    """Convert Notion rich_text array to markdown string."""
    result = ""

    for content in rich_text:
        if content.type == "equation":
            result += _inline_equation(content.equation.expression)
            continue

        plain_text = _apply_annotations(content.plain_text, content.annotations)

        # Add link if present
        if content.href:
            plain_text = _link(plain_text, content.href)

        result += plain_text

    return result


# =============================================================================
# Block to Markdown Conversion
# =============================================================================


def _file_link(content: NotionBlockContent) -> str:
    """Return the URL of a file-like block: external or Notion-hosted file."""
    return content.external.url if content.type == "external" else content.file.url


def _plain_caption(content: NotionBlockContent) -> str:
    return "".join(item.plain_text for item in content.caption)


def _block_content(block: NotionBlock) -> NotionBlockContent:
    return block.content or NotionBlockContent()


def _parsed_rich_text(block: NotionBlock) -> str:
    block_content = _block_content(block)
    return rich_text_to_markdown(block_content.rich_text or block_content.text)


def _render_image(block: NotionBlock, _list_number: int | None) -> str:
    block_content = _block_content(block)
    image_title = "image"

    image_caption_plain = _plain_caption(block_content)

    link = _file_link(block_content)

    image_title = image_caption_plain.strip() or link.split("/")[-1] if "/" in link else image_title

    return _image(image_title, link)


def _render_divider(_block: NotionBlock, _list_number: int | None) -> str:
    return _divider()


def _render_equation(block: NotionBlock, _list_number: int | None) -> str:
    return _equation(_block_content(block).expression)


def _render_file_like(block: NotionBlock, _list_number: int | None) -> str:
    """Render a video, file or pdf block."""
    if not block.content:
        return ""
    title = block.type
    caption = _plain_caption(block.content)
    link = _file_link(block.content)
    title = caption.strip() or (link.split("/")[-1] if "/" in link else title)
    return _link(title, link)


def _render_link_like(block: NotionBlock, _list_number: int | None) -> str:
    """Render a bookmark, embed, link_preview or link_to_page block."""
    block_type = block.type
    block_content = _block_content(block)
    if block_type != "link_to_page":
        return _link(block_type, block_content.url)
    if block_content.type == "page_id":
        url = f"https://www.notion.so/{block_content.page_id}"
    elif block_content.type == "database_id":
        url = f"https://www.notion.so/{block_content.database_id}"
    else:
        url = ""
    return _link(block_type, url)


def _render_child_page(block: NotionBlock, _list_number: int | None) -> str:
    return _heading2(_block_content(block).title or "")


def _render_child_database(block: NotionBlock, _list_number: int | None) -> str:
    title = _block_content(block).title
    return _heading2(title if title is not None else "child_database")


def _render_table(_block: NotionBlock, _list_number: int | None) -> str:
    # Tables need special handling with their children (rows processed separately)
    return "[TABLE - see children for rows]"


def _render_table_row(block: NotionBlock, _list_number: int | None) -> str:
    row_content = [rich_text_to_markdown(cell) for cell in _block_content(block).cells]
    return "| " + " | ".join(row_content) + " |"


def _render_code(block: NotionBlock, _list_number: int | None) -> str:
    return _code_block(_parsed_rich_text(block), _block_content(block).language)


def _render_heading1(block: NotionBlock, _list_number: int | None) -> str:
    return _heading1(_parsed_rich_text(block))


def _render_heading2(block: NotionBlock, _list_number: int | None) -> str:
    return _heading2(_parsed_rich_text(block))


def _render_heading3(block: NotionBlock, _list_number: int | None) -> str:
    return _heading3(_parsed_rich_text(block))


def _render_quote(block: NotionBlock, _list_number: int | None) -> str:
    return _quote(_parsed_rich_text(block))


def _render_callout(block: NotionBlock, _list_number: int | None) -> str:
    return _callout(_parsed_rich_text(block), _block_content(block).icon)


def _render_bullet(block: NotionBlock, _list_number: int | None) -> str:
    return _bullet(_parsed_rich_text(block))


def _render_numbered(block: NotionBlock, list_number: int | None) -> str:
    return _bullet(_parsed_rich_text(block), list_number)


def _render_todo(block: NotionBlock, _list_number: int | None) -> str:
    return _todo(_parsed_rich_text(block), _block_content(block).checked)


def _render_toggle(block: NotionBlock, _list_number: int | None) -> str:
    return _toggle(_parsed_rich_text(block))


def _render_rich_text(block: NotionBlock, _list_number: int | None) -> str:
    """paragraph, and the default for any other block type."""
    return _parsed_rich_text(block)


_BLOCK_RENDERERS: dict[str, Callable[[NotionBlock, int | None], str]] = {
    "image": _render_image,
    "divider": _render_divider,
    "equation": _render_equation,
    "video": _render_file_like,
    "file": _render_file_like,
    "pdf": _render_file_like,
    "bookmark": _render_link_like,
    "embed": _render_link_like,
    "link_preview": _render_link_like,
    "link_to_page": _render_link_like,
    "child_page": _render_child_page,
    "child_database": _render_child_database,
    "table": _render_table,
    "table_row": _render_table_row,
    "code": _render_code,
    "heading_1": _render_heading1,
    "heading_2": _render_heading2,
    "heading_3": _render_heading3,
    "quote": _render_quote,
    "callout": _render_callout,
    "bulleted_list_item": _render_bullet,
    "numbered_list_item": _render_numbered,
    "to_do": _render_todo,
    "toggle": _render_toggle,
    "paragraph": _render_rich_text,
}


def block_to_markdown(block: NotionBlock, list_number: int | None = None) -> str:
    """Convert a single Notion block to markdown string.

    list_number is the 1-based position of a numbered_list_item in its run,
    which blocks_to_markdown tracks across siblings.
    """
    if not block.type:
        return ""
    renderer = _BLOCK_RENDERERS.get(block.type, _render_rich_text)
    return renderer(block, list_number)


# =============================================================================
# Block List to Markdown
# =============================================================================


def _rendered_lines(md_content: str, block_id: str | None, nesting_level: int) -> list[str]:
    """Return a rendered block's optional block-id comment then its content, indented for nesting_level."""
    lines: list[str] = []
    # Add block ID comment if requested
    if block_id:
        block_id_comment = f"<!-- block:{block_id} -->"
        lines.append(_add_tab_space(block_id_comment, nesting_level))

    md_content = _add_tab_space(md_content, nesting_level)

    lines.append(md_content)
    return lines


def blocks_to_markdown(
    blocks: Sequence[NotionBlock],
    nesting_level: int = 0,
    include_block_ids: bool = False,
) -> str:
    """Convert a list of Notion blocks to a markdown string.

    include_block_ids prepends block IDs as HTML comments (<!-- block:abc123
    -->) so an LLM can reference them via the after parameter.
    """
    if not blocks:
        return ""

    result_lines: list[str] = []
    numbered_list_index = 0

    for block in blocks:
        block_type = block.type
        block_id = block.id

        # Skip unsupported blocks
        if block_type == "unsupported":
            continue

        # Track numbered list indices
        if block_type == "numbered_list_item":
            numbered_list_index += 1
        else:
            numbered_list_index = 0

        # Convert block to markdown
        md_content = block_to_markdown(block, numbered_list_index or None)

        if md_content:
            result_lines.extend(
                _rendered_lines(md_content, block_id if include_block_ids else None, nesting_level)
            )

        # Handle children recursively if present
        if block.children:
            child_md = blocks_to_markdown(block.children, nesting_level + 1, include_block_ids)
            if child_md:
                result_lines.append(child_md)

    return "\n".join(result_lines)


# =============================================================================
# Markdown → Notion Blocks (for NOTION_ADD_MULTIPLE_PAGE_CONTENT)
# =============================================================================


def _text_run(content: str) -> NotionTextRun:
    return NotionTextRun(text=NotionTextContent(content=content))


# Single-line prefixes, checked in order after the divider test.
# GitHub's alert grammar; any other "> [!" line is an ordinary quote.
_GITHUB_ALERT_RE = re.compile(r"^> \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]")

_PREFIX_BLOCK_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("### ", "heading_3"),
    ("## ", "heading_2"),
    ("# ", "heading_1"),
    ("> ", "quote"),
)


def _parse_code_block(lines: list[str], start: int) -> tuple[NotionCodeBlock, int]:
    """Parse the fenced code block opening at lines[start]; returns it and the next index."""
    language = lines[start].strip()[3:].strip() or "plain text"
    code_lines = []
    i = start + 1
    while i < len(lines) and not lines[i].strip().startswith("```"):
        code_lines.append(lines[i])
        i += 1
    i += 1  # Skip closing ```

    # Code blocks need full Notion format
    block = NotionCodeBlock(
        code=NotionCodeBlockBody(language=language, rich_text=[_text_run("\n".join(code_lines))])
    )
    return block, i


def _parse_table_row(row_line: str) -> list[str]:
    """Cells of a pipe-delimited row."""
    return [cell.strip() for cell in row_line.strip("|").split("|")]


def _is_table_separator(row_line: str) -> bool:
    """Return whether a row is a separator (e.g. |---|---| or |:---|:---:|)."""
    return all(re.match(r"^:?-+:?$", cell.strip()) for cell in row_line.split("|") if cell.strip())


def _parse_table(lines: list[str], start: int) -> tuple[NotionTableBlock | None, int]:
    """Parse consecutive table lines from lines[start].

    Returns the table (None when only separators were found) and the next index.
    """
    table_lines = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        table_lines.append(lines[i].strip())
        i += 1

    data_rows = [r for r in table_lines if not _is_table_separator(r)]
    if not data_rows:
        return None, i

    # First row is header
    header_cells = _parse_table_row(data_rows[0])
    table_width = len(header_cells)

    notion_rows: list[NotionTableRow] = []
    for row_line in data_rows:
        cells = _parse_table_row(row_line)
        # Pad or trim to table_width
        while len(cells) < table_width:  # pragma: no mutate -- the trim below re-imposes the bound
            cells.append("")
        cells = cells[:table_width]
        notion_rows.append(NotionTableRow(cells=[[_text_run(cell)] for cell in cells]))

    table = NotionTableBlock(table_width=table_width, rows=notion_rows)
    return table, i


def _line_block(stripped: str) -> NotionContentBlock:
    """Build the block for one non-empty, non-code, non-table line."""
    # Divider
    if stripped in ["---", "***", "___"]:
        return NotionContentBlock(block_property="paragraph", content="───")

    # Callout (GitHub alert style) — before the "> " quote prefix, which also matches it
    if _GITHUB_ALERT_RE.match(stripped):
        return NotionContentBlock(block_property="callout", content=stripped[2:])

    # Headings, quote
    for prefix, block_property in _PREFIX_BLOCK_PROPERTIES:
        if stripped.startswith(prefix):
            return NotionContentBlock(
                block_property=block_property, content=stripped[len(prefix) :]
            )

    # Todo items
    todo_match = re.match(r"^- \[([ xX])\] (.+)$", stripped)
    if todo_match:
        return NotionContentBlock(block_property="to_do", content=todo_match.group(2))

    # Bulleted list
    if stripped.startswith(("- ", "* ")):
        return NotionContentBlock(block_property="bulleted_list_item", content=stripped[2:])

    # Numbered list
    num_match = re.match(r"^(\d+)\. (.+)$", stripped)
    if num_match:
        return NotionContentBlock(block_property="numbered_list_item", content=num_match.group(2))

    # Default: paragraph
    return NotionContentBlock(block_property="paragraph", content=stripped)


def markdown_to_notion_blocks(markdown: str) -> list[NotionMarkdownBlock]:
    """Convert markdown to NOTION_ADD_MULTIPLE_PAGE_CONTENT format.

    Returns unwrapped content blocks, with code blocks and tables in Notion's
    full form; the Composio tool parses markdown formatting in content itself.
    Supports headings, paragraphs, lists, todos, quotes, code, dividers, tables.
    """
    blocks: list[NotionMarkdownBlock] = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Code block - needs full Notion format
        if stripped.startswith("```"):
            code_block, i = _parse_code_block(lines, i)
            blocks.append(code_block)
            continue

        # Markdown table — detected by a pipe-delimited row
        if stripped.startswith("|") and stripped.endswith("|"):
            table_block, i = _parse_table(lines, i)
            if table_block is not None:
                blocks.append(table_block)
            continue

        blocks.append(_line_block(stripped))
        i += 1

    return blocks
