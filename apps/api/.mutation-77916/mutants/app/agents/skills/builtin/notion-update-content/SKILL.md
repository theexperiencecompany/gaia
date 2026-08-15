---
name: notion-manage-content
description: Manage Notion page content — insert, append, update blocks, delete blocks, override/replace content, and create new linked pages. Supports full markdown including tables.
target: notion_agent
---

# Notion: Manage Page Content

## When to Activate

- User asks to update, edit, refactor, append, or insert into an existing Notion page
- User wants to delete specific blocks or override/replace a page's content
- User references "that page", "the doc", "the notes", or an existing workspace artifact
- User wants to restructure sections, rewrite content, or add new information
- Content is large or complex enough to warrant a new dedicated page

## Core Rules

- Never assume page IDs. Discover first.
- Never write blind. Read current content before editing.
- Prefer markdown workflows for text/lists/headings/tables:
  - Read: `NOTION_FETCH_PAGE_AS_MARKDOWN`
  - Write/append: `NOTION_INSERT_MARKDOWN` (supports full markdown including tables)
- Avoid destructive edits unless the user explicitly asks (deleting blocks, overwriting large sections, moving/archiving).
- If the content to add is substantial and self-contained (e.g., a full report, meeting notes, reference doc), **consider creating a new sub-page** and linking it in the parent (see "When to Create a New Page" below).

If the user wants to change page metadata (title/properties), use `NOTION_UPDATE_PAGE`.
If the user wants to move a page, use `NOTION_MOVE_PAGE`.

---

## Workflow

### Step 1: Discover the Target

```
NOTION_FETCH_DATA(fetch_type="pages", page_size=50)
NOTION_FETCH_DATA(fetch_type="pages", query="<keywords>", page_size=50)
```

If multiple plausible pages exist, present the best 2-3 (title + parent + last edited) and ask ONE focused question.

### Step 2: Read Current Content

```
NOTION_FETCH_PAGE_AS_MARKDOWN(page_id="<uuid>")
```

Identify:
- existing structure (headings, block IDs)
- where new content should be inserted
- any tone/formatting constraints

To get block IDs for precise positioning:
```
NOTION_FETCH_BLOCK_CONTENTS(block_id="<page_id>")         # first-level children
NOTION_FETCH_ALL_BLOCK_CONTENTS(block_id="<page_id>")     # full recursive tree
```

### Step 3: Plan the Change

Write a short plan:
- what section to add/edit
- what to preserve
- whether appending, inserting after a block, updating in-place, or replacing

---

## Operations Reference

### Append / Insert Content

**General markdown content (text, headings, lists, checkboxes):**
```
NOTION_INSERT_MARKDOWN(
  parent_block_id="<page_or_block_id>",
  markdown="## Section Title\n- Item one\n- Item two\n- [ ] Task"
)
```

**Insert AFTER a specific block** (use block ID from NOTION_FETCH_BLOCK_CONTENTS):
```
NOTION_INSERT_MARKDOWN(
  parent_block_id="<page_id>",
  after="<block_id_to_insert_after>",
  markdown="New content here"
)
```

**Bulk content (multiple blocks, large inserts):**
```
NOTION_ADD_MULTIPLE_PAGE_CONTENT(
  parent_block_id="<page_id>",
  content_blocks=[
    {"content": "First paragraph", "block_property": "paragraph"},
    {"content": "## New Heading", "block_property": "heading_2"},
    {"content": "List item", "block_property": "bulleted_list_item"}
  ]
)
```

**Specialized block types:**
```
NOTION_APPEND_TEXT_BLOCKS(...)      # paragraphs, headings, lists
NOTION_APPEND_TASK_BLOCKS(...)      # to-do checkboxes, toggles, callouts
NOTION_APPEND_CODE_BLOCKS(...)      # code snippets, quotes, equations
NOTION_APPEND_MEDIA_BLOCKS(...)     # images, videos, audio, embeds, bookmarks
NOTION_APPEND_LAYOUT_BLOCKS(...)    # dividers, TOC, columns
```

---

### Tables

**Use markdown table syntax directly** — `NOTION_INSERT_MARKDOWN` automatically converts it to a proper Notion table via `NOTION_APPEND_TABLE_BLOCKS` under the hood:

```
NOTION_INSERT_MARKDOWN(
  parent_block_id="<page_id>",
  markdown="""
## Task Tracker

| Name | Status | Due |
|------|--------|-----|
| Task A | In Progress | Mar 10 |
| Task B | Done | Mar 5 |
| Task C | Blocked | Mar 15 |
"""
)
```

If you need more control (e.g., inserting a table at a specific position), use `NOTION_APPEND_TABLE_BLOCKS` directly:

```
NOTION_APPEND_TABLE_BLOCKS(
  block_id="<page_id>",
  table_width=3,
  has_column_header=true,
  rows=[
    {"cells": [
      [{"type": "text", "text": {"content": "Name"}}],
      [{"type": "text", "text": {"content": "Status"}}],
      [{"type": "text", "text": {"content": "Due"}}]
    ]},
    {"cells": [
      [{"type": "text", "text": {"content": "Task A"}}],
      [{"type": "text", "text": {"content": "In Progress"}}],
      [{"type": "text", "text": {"content": "Mar 10"}}]
    ]}
  ]
)
```

---

### Update Existing Block

To edit an existing block's text content in-place (must have block ID):

```
NOTION_UPDATE_BLOCK(
  block_id="<block_uuid>",
  content="Updated text content here"
)
```

> Limit: 2000 chars per block. Cannot change block type. Get block IDs via `NOTION_FETCH_BLOCK_CONTENTS`.

---

### Delete Blocks

To delete (archive) specific blocks:

```
NOTION_DELETE_BLOCK(block_id="<block_uuid>")
```

> This archives the block (recoverable from Trash). To delete multiple blocks, call this for each block ID. Get IDs first via `NOTION_FETCH_BLOCK_CONTENTS`.

---

### Override / Replace Page Content

To completely replace a page's content (destructive — confirm with user first):

```
NOTION_REPLACE_PAGE_CONTENT(
  page_id="<page_uuid>",
  new_content=[...],   # Array of block objects
  backup=true          # Optional: backup current content before replacing
)
```

> This deletes all existing children and inserts new ones. Always confirm with user before using. The `backup=true` flag creates a recoverable snapshot.

---

## When to Create a New Page

Create a sub-page instead of inserting inline when:
- Content is long (full report, structured document, reference article)
- Content is self-contained and reusable on its own
- User asks to "create a doc", "write a page about", or "document this"
- Inserting inline would clutter the parent page

**Workflow:**
```
# 1. Create the sub-page under the parent
NOTION_CREATE_NOTION_PAGE(
  title="Q1 Report",
  parent_id="<parent_page_uuid>"
)

# 2. Add content to the new page
NOTION_INSERT_MARKDOWN(
  parent_block_id="<new_page_id>",
  markdown="## Overview\n..."
)

# 3. Link the new page inside the parent page
# Notion auto-links child pages — confirm by mentioning the link to the user
```

After creating, always report:
```
Created: "Q1 Report"
  Parent: Team Workspace > Projects
  Sections: Overview, Results, Next Steps
  Link: [Open in Notion](<url>)
```

---

### Step 4: Verify and Summarize

Re-fetch the affected portion and summarize:
- what changed
- what stayed the same
- anything that needs user confirmation

---

## Anti-Patterns

- Creating a new page when the user wanted an edit (unless confirmed or content warrants it)
- Overwriting large content without explicit instruction
- Editing without reading current content first
- Dumping raw API output instead of summarizing
- Not providing the link to a newly created page
