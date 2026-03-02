---
name: notion-update-content
description: Update existing Notion pages safely - discover targets, fetch as markdown, plan changes, insert markdown, and avoid destructive edits.
target: notion_agent
---

# Notion: Update Page Content

## When to Activate

- User asks to update, edit, refactor, or append to an existing Notion page
- User references "that page", "the doc", "the notes", or an existing workspace artifact
- User wants to restructure sections, rewrite content, or add new information

## Core Rules

- Never assume page IDs. Discover first.
- Never write blind. Read current content before editing.
- Prefer markdown workflows:
  - Read: NOTION_FETCH_PAGE_AS_MARKDOWN
  - Write/update: NOTION_INSERT_MARKDOWN
- Avoid destructive edits unless the user explicitly asks (deleting blocks, overwriting large sections, moving/archiving).

If the user wants to change page metadata (e.g., title/properties), use NOTION_UPDATE_PAGE.
If the user wants to move a page, use NOTION_MOVE_PAGE.

## Workflow

### Step 1: Discover the Target

Use discovery tools to locate the correct page:

```
NOTION_FETCH_DATA(fetch_type="pages", page_size=50)
NOTION_FETCH_DATA(fetch_type="pages", query="<keywords>", page_size=50)
```

If multiple plausible pages exist, present the best 2-3 (title + parent + last edited if available) and ask ONE focused question.

### Step 2: Read Current Content as Markdown

```
NOTION_FETCH_PAGE_AS_MARKDOWN(page_id="<uuid>")
```

Identify:
- existing structure (headings)
- where the new content should go
- any constraints (tone, formatting, templates)

### Step 3: Plan the Change

Write a short plan before editing:

- what section you will add/edit
- what you will preserve
- whether you are appending vs refactoring

### Step 4: Apply Update via Markdown Insertion

Use NOTION_INSERT_MARKDOWN to add/replace content.

Guidelines:
- Insert under an appropriate heading
- Use headings and lists to match existing style
- If positioning matters, use INSERT_MARKDOWN's `after` parameter (use block IDs from NOTION_FETCH_PAGE_AS_MARKDOWN)

### Step 5: Verify and Summarize

Re-fetch the page as markdown (or read the affected portion) and summarize:

- what changed
- what stayed the same
- anything that needs user confirmation

## Anti-Patterns

- Creating a new page when the user wanted an edit (unless confirmed)
- Overwriting large content without explicit instruction
- Editing without reading current content
- Dumping raw API output instead of summarizing
