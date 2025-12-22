"""Notion ↔ Markdown bidirectional conversion utilities.

Provides:
- blocks_to_markdown(): Convert Notion blocks → Markdown string
- markdown_to_notion_blocks(): Convert Markdown string → NOTION_ADD_MULTIPLE_PAGE_CONTENT format

Adapted from notion-to-md-py with modifications for Composio integration.
"""

import re
from typing import Any, Dict, List, Optional

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


def _code_block(text: str, language: Optional[str] = None) -> str:
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


def _callout(text: str, icon: Optional[Dict[str, Any]] = None) -> str:
    emoji = icon.get("emoji", "") if icon and icon.get("type") == "emoji" else ""
    formatted_text = text.replace("\n", "\n> ")
    formatted_emoji = emoji + " " if emoji else ""
    heading_match = re.match(r"^(#{1,6})\s+(.+)", formatted_text)

    if heading_match:
        level, content = heading_match.groups()
        return f"> {'#' * len(level)} {formatted_emoji}{content}"
    return f"> {formatted_emoji}{formatted_text}"


def _bullet(text: str, count: Optional[int] = None) -> str:
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


def _toggle(summary: Optional[str] = None, children: Optional[str] = None) -> str:
    if not summary:
        return children or ""
    return f"<details><summary>{summary}</summary>{children or ''}</details>"


def _table(cells: List[List[str]]) -> str:
    """Convert a table to markdown format."""
    if not cells:
        return ""

    # Build header row
    headers = cells[0] if cells else []
    header_row = "| " + " | ".join(headers) + " |"

    # Build separator
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"

    # Build data rows
    data_rows = []
    for row in cells[1:]:
        # Pad row if needed
        while len(row) < len(headers):
            row.append("")
        data_rows.append("| " + " | ".join(row) + " |")

    return "\n".join([header_row, separator] + data_rows)


# =============================================================================
# Annotation Application
# =============================================================================


def _apply_annotations(plain_text: str, annotations: Dict[str, Any]) -> str:
    """Apply text annotations (bold, italic, etc.) to plain text."""
    if re.match(r"^\s*$", plain_text):
        return plain_text

    leading_space_match = re.match(r"^(\s*)", plain_text)
    trailing_space_match = re.search(r"(\s*)$", plain_text)

    leading_space = leading_space_match.group(0) if leading_space_match else ""
    trailing_space = trailing_space_match.group(0) if trailing_space_match else ""

    plain_text = plain_text.strip()

    if plain_text:
        if annotations.get("code"):
            plain_text = _inline_code(plain_text)
        if annotations.get("bold"):
            plain_text = _bold(plain_text)
        if annotations.get("italic"):
            plain_text = _italic(plain_text)
        if annotations.get("strikethrough"):
            plain_text = _strikethrough(plain_text)
        if annotations.get("underline"):
            plain_text = _underline(plain_text)

    return leading_space + plain_text + trailing_space


# =============================================================================
# Rich Text Conversion
# =============================================================================


def rich_text_to_markdown(rich_text: List[Dict[str, Any]]) -> str:
    """Convert Notion rich_text array to markdown string."""
    result = ""

    for content in rich_text:
        if content.get("type") == "equation":
            expression = content.get("equation", {}).get("expression", "")
            result += _inline_equation(expression)
            continue

        plain_text = content.get("plain_text", "")
        annotations = content.get("annotations", {})

        # Apply annotations
        plain_text = _apply_annotations(plain_text, annotations)

        # Add link if present
        if content.get("href"):
            plain_text = _link(plain_text, content["href"])

        result += plain_text

    return result


# =============================================================================
# Block to Markdown Conversion
# =============================================================================


def block_to_markdown(block: Dict[str, Any]) -> str:
    """Convert a single Notion block to markdown string."""
    if not isinstance(block, dict) or "type" not in block:
        return ""

    block_type = block["type"]

    # Handle image blocks
    if block_type == "image":
        block_content = block.get("image", {})
        image_title = "image"

        image_caption_plain = "".join(
            item.get("plain_text", "") for item in block_content.get("caption", [])
        )

        image_type = block_content.get("type", "")
        if image_type == "external":
            link = block_content.get("external", {}).get("url", "")
        else:
            link = block_content.get("file", {}).get("url", "")

        image_title = (
            image_caption_plain.strip() or link.split("/")[-1]
            if "/" in link
            else image_title
        )

        return _image(image_title, link)

    # Handle divider
    if block_type == "divider":
        return _divider()

    # Handle equation
    if block_type == "equation":
        expression = block.get("equation", {}).get("expression", "")
        return _equation(expression)

    # Handle video, file, pdf
    if block_type in ["video", "file", "pdf"]:
        block_content = block.get(block_type, {})
        title = block_type

        if block_content:
            caption = "".join(
                item.get("plain_text", "") for item in block_content.get("caption", [])
            )

            file_type = block_content.get("type", "")
            if file_type == "external":
                link = block_content.get("external", {}).get("url", "")
            else:
                link = block_content.get("file", {}).get("url", "")

            title = caption.strip() or (link.split("/")[-1] if "/" in link else title)
            return _link(title, link)

        return ""

    # Handle bookmark, embed, link_preview, link_to_page
    if block_type in ["bookmark", "embed", "link_preview", "link_to_page"]:
        if block_type == "link_to_page":
            link_data = block.get("link_to_page", {})
            if link_data.get("type") == "page_id":
                url = f"https://www.notion.so/{link_data.get('page_id', '')}"
            elif link_data.get("type") == "database_id":
                url = f"https://www.notion.so/{link_data.get('database_id', '')}"
            else:
                url = ""
        else:
            block_content = block.get(block_type, {})
            url = block_content.get("url", "")

        return _link(block_type, url)

    # Handle child_page
    if block_type == "child_page":
        page_title = block.get("child_page", {}).get("title", "")
        return _heading2(page_title)

    # Handle child_database
    if block_type == "child_database":
        db_title = block.get("child_database", {}).get("title", "child_database")
        return _heading2(db_title)

    # Handle table (rows processed separately)
    if block_type == "table":
        # Tables need special handling with their children
        return "[TABLE - see children for rows]"

    # Handle table_row
    if block_type == "table_row":
        cells = block.get("table_row", {}).get("cells", [])
        row_content = [rich_text_to_markdown(cell) for cell in cells]
        return "| " + " | ".join(row_content) + " |"

    # Handle standard blocks with rich_text
    block_data = block.get(block_type, {})
    rich_text = block_data.get("rich_text", []) or block_data.get("text", [])
    parsed_data = rich_text_to_markdown(rich_text)

    if block_type == "code":
        language = block.get("code", {}).get("language", "")
        return _code_block(parsed_data, language)

    if block_type == "heading_1":
        return _heading1(parsed_data)

    if block_type == "heading_2":
        return _heading2(parsed_data)

    if block_type == "heading_3":
        return _heading3(parsed_data)

    if block_type == "quote":
        return _quote(parsed_data)

    if block_type == "callout":
        icon = block.get("callout", {}).get("icon")
        return _callout(parsed_data, icon)

    if block_type == "bulleted_list_item":
        return _bullet(parsed_data)

    if block_type == "numbered_list_item":
        number = block.get("numbered_list_item", {}).get("number")
        return _bullet(parsed_data, number)

    if block_type == "to_do":
        checked = block.get("to_do", {}).get("checked", False)
        return _todo(parsed_data, checked)

    if block_type == "toggle":
        return _toggle(parsed_data)

    if block_type == "paragraph":
        return parsed_data

    # Default: return parsed rich text
    return parsed_data


# =============================================================================
# Block List to Markdown
# =============================================================================


def blocks_to_markdown(
    blocks: List[Dict[str, Any]],
    nesting_level: int = 0,
    include_block_ids: bool = False,
) -> str:
    """
    Convert a list of Notion blocks to a markdown string.

    Args:
        blocks: List of Notion block objects
        nesting_level: Current nesting level for indentation
        include_block_ids: If True, prepend block IDs as HTML comments
                          (e.g., <!-- block:abc123 -->) so LLM can reference
                          them for insertion positioning with `after` parameter.

    Returns:
        Markdown formatted string
    """
    if not blocks:
        return ""

    result_lines: List[str] = []
    numbered_list_index = 0

    for block in blocks:
        block_type = block.get("type", "")
        block_id = block.get("id", "")

        # Skip unsupported blocks
        if block_type == "unsupported":
            continue

        # Track numbered list indices
        if block_type == "numbered_list_item":
            numbered_list_index += 1
            block["numbered_list_item"]["number"] = numbered_list_index
        else:
            numbered_list_index = 0

        # Convert block to markdown
        md_content = block_to_markdown(block)

        if md_content:
            # Add block ID comment if requested
            if include_block_ids and block_id:
                block_id_comment = f"<!-- block:{block_id} -->"
                if nesting_level > 0:
                    block_id_comment = _add_tab_space(block_id_comment, nesting_level)
                result_lines.append(block_id_comment)

            # Add indentation for nesting
            if nesting_level > 0:
                md_content = _add_tab_space(md_content, nesting_level)

            result_lines.append(md_content)

        # Handle children recursively if present
        children = block.get("children", [])
        if children:
            child_md = blocks_to_markdown(
                children, nesting_level + 1, include_block_ids
            )
            if child_md:
                result_lines.append(child_md)

    return "\n".join(result_lines)


# =============================================================================
# Simplified Block Extraction (for non-markdown use)
# =============================================================================


def simplify_block(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simplify a Notion block, removing formatting metadata.

    Keeps: id, type, text content, has_children, children
    Removes: colors, annotations, parent info, timestamps, user info
    """
    block_type = block.get("type", "")

    simplified: Dict[str, Any] = {
        "id": block.get("id", ""),
        "type": block_type,
    }

    # Extract text content
    block_data = block.get(block_type, {})
    rich_text = block_data.get("rich_text", []) or block_data.get("text", [])

    if rich_text:
        # Just get plain text, no formatting
        simplified["text"] = "".join(item.get("plain_text", "") for item in rich_text)

    # Handle special block types
    if block_type == "child_page":
        simplified["title"] = block.get("child_page", {}).get("title", "")
    elif block_type == "child_database":
        simplified["title"] = block.get("child_database", {}).get("title", "")
    elif block_type == "to_do":
        simplified["checked"] = block.get("to_do", {}).get("checked", False)
    elif block_type == "code":
        simplified["language"] = block.get("code", {}).get("language", "")
    elif block_type in ["image", "video", "file", "pdf"]:
        content = block.get(block_type, {})
        file_type = content.get("type", "")
        if file_type == "external":
            simplified["url"] = content.get("external", {}).get("url", "")
        else:
            simplified["url"] = content.get("file", {}).get("url", "")
        simplified["caption"] = "".join(
            item.get("plain_text", "") for item in content.get("caption", [])
        )
    elif block_type in ["bookmark", "embed", "link_preview"]:
        simplified["url"] = block.get(block_type, {}).get("url", "")

    # Handle children
    if block.get("has_children"):
        simplified["has_children"] = True
    children = block.get("children", [])
    if children:
        simplified["children"] = [simplify_block(child) for child in children]

    return simplified


def simplify_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Simplify a list of blocks, removing formatting metadata."""
    return [simplify_block(block) for block in blocks]


def extract_plain_text(blocks: List[Dict[str, Any]]) -> str:
    """Extract just the plain text from blocks, no formatting."""
    texts: List[str] = []

    for block in blocks:
        block_type = block.get("type", "")
        block_data = block.get(block_type, {})
        rich_text = block_data.get("rich_text", []) or block_data.get("text", [])

        if rich_text:
            text = "".join(item.get("plain_text", "") for item in rich_text)
            if text:
                texts.append(text)

        # Handle children recursively
        children = block.get("children", [])
        if children:
            child_text = extract_plain_text(children)
            if child_text:
                texts.append(child_text)

    return "\n".join(texts)


# =============================================================================
# Markdown → Notion Blocks (for NOTION_ADD_MULTIPLE_PAGE_CONTENT)
# =============================================================================


def markdown_to_notion_blocks(markdown: str) -> List[Dict[str, Any]]:
    """
    Convert markdown string to NOTION_ADD_MULTIPLE_PAGE_CONTENT format.

    Returns a list of content blocks in the simpler unwrapped format:
    [{"block_property": "paragraph", "content": "text"}, ...]

    The Composio tool automatically parses markdown formatting in content.

    Supported markdown:
    - # ## ### headings
    - Paragraphs
    - - bullet lists
    - 1. numbered lists
    - - [ ] / - [x] todo items
    - > quotes
    - ``` code blocks (with language)
    - --- dividers
    - Inline: **bold**, *italic*, ~~strikethrough~~, `code`, [links](url)
    """
    blocks: List[Dict[str, Any]] = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Code block - needs full Notion format
        if stripped.startswith("```"):
            language = stripped[3:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # Skip closing ```

            # Code blocks need full Notion format
            blocks.append(
                {
                    "type": "code",
                    "code": {
                        "language": language,
                        "rich_text": [
                            {"type": "text", "text": {"content": "\n".join(code_lines)}}
                        ],
                    },
                }
            )
            continue

        # Divider
        if stripped in ["---", "***", "___"]:
            blocks.append({"block_property": "paragraph", "content": "───"})
            i += 1
            continue

        # Headings
        if stripped.startswith("### "):
            blocks.append({"block_property": "heading_3", "content": stripped[4:]})
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append({"block_property": "heading_2", "content": stripped[3:]})
            i += 1
            continue
        if stripped.startswith("# "):
            blocks.append({"block_property": "heading_1", "content": stripped[2:]})
            i += 1
            continue

        # Quote
        if stripped.startswith("> "):
            blocks.append({"block_property": "quote", "content": stripped[2:]})
            i += 1
            continue

        # Todo items
        todo_match = re.match(r"^- \[([ xX])\] (.+)$", stripped)
        if todo_match:
            content = todo_match.group(2)
            blocks.append({"block_property": "to_do", "content": content})
            i += 1
            continue

        # Bulleted list
        if stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(
                {"block_property": "bulleted_list_item", "content": stripped[2:]}
            )
            i += 1
            continue

        # Numbered list
        num_match = re.match(r"^(\d+)\. (.+)$", stripped)
        if num_match:
            content = num_match.group(2)
            blocks.append({"block_property": "numbered_list_item", "content": content})
            i += 1
            continue

        # Callout (GitHub alert style)
        if stripped.startswith("> [!"):
            blocks.append({"block_property": "callout", "content": stripped[2:]})
            i += 1
            continue

        # Default: paragraph
        blocks.append({"block_property": "paragraph", "content": stripped})
        i += 1

    return blocks
