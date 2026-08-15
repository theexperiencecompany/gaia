MOVE_PAGE_DOC = """Move a Notion page to a new parent (another page or database).

Use this to organize pages within a workspace:
- Moving a note into a project folder
- Moving a page into a database
- Reorganizing page hierarchy

Args:
    page_id: UUID of the page to move
    parent_type: 'page_id' or 'database_id'
    parent_id: UUID of the new parent

Returns:
    success: True if moved successfully
    page_id: The page ID
    new_parent: The new parent info
    url: Updated page URL
"""

FETCH_PAGE_AS_MARKDOWN_DOC = """Fetch a Notion page and return content as Markdown.

This is the preferred way to read Notion pages - returns clean, readable
markdown instead of raw Notion blocks. Much more token-efficient.

Internally uses NOTION_FETCH_ALL_BLOCK_CONTENTS and converts to markdown.

Block IDs are embedded as HTML comments (<!-- block:id -->) so you can
reference them with INSERT_MARKDOWN's `after` parameter for precise positioning.

Supports: headings, paragraphs, lists, code blocks, quotes, todos,
callouts, images, links, bold, italic, strikethrough, inline code.

Args:
    page_id: UUID of the page to fetch
    recursive: Whether to fetch nested children blocks (default: true)
    include_block_ids: Include block IDs as HTML comments (default: true)

Returns:
    success: True if fetched successfully
    title: Page title
    markdown: Page content as markdown string with block IDs
    block_count: Number of blocks converted
"""

INSERT_MARKDOWN_DOC = """Insert markdown content into a Notion page or block.

Converts markdown to Notion blocks and inserts them. Supports insertion
at a specific position using the `after` parameter.

Internally converts markdown and calls NOTION_ADD_MULTIPLE_PAGE_CONTENT.

Supported markdown:
- # ## ### headings
- Paragraphs
- - bullet lists, * bullet lists
- 1. numbered lists
- - [ ] / - [x] todo items  
- > quotes
- ``` code blocks (with language)
- --- dividers
- **bold**, *italic*, ~~strikethrough~~, `code`, [links](url)

Args:
    parent_block_id: UUID of the parent page or block
    markdown: Markdown content to insert
    after: Optional UUID of block to insert after. If omitted, appends to end.

Returns:
    success: True if inserted successfully
    blocks_added: Number of blocks added
"""

FETCH_DATA_DOC = """Fetch databases or pages from Notion workspace.

Use this to discover available databases and pages in the user's Notion workspace.
This is useful for configuration, selection, or browsing purposes.

Internally uses Notion's /v1/search API endpoint to query resources.

Args:
    fetch_type: Type of data to fetch - 'databases' or 'pages'
    page_size: Maximum number of results to return (default: 100)
    query: Optional search query to filter results by title or content

Returns:
    success: True if fetched successfully
    values: Array of simplified objects with {id, title, type} for each result
"""
