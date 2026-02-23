---
name: notion-create-page
description: Intelligently create Notion pages — search for duplicates, find parent, structure content with blocks, offer sharing
target: notion_agent
---

# Notion: Create Page

## When to Activate
User wants to create a new page, document, or wiki entry in Notion.

## Step 1: Search for Duplicates

Before creating, check if a similar page exists:
```
NOTION_SEARCH_NOTION_PAGE(query="<page title>", filter_value="page", page_size=5)
```

If matches found:
- Present matches: "I found a page called 'X'. Should I update it or create a new one?"
- **Drafting Content**: Use `NOTION_INSERT_MARKDOWN` to build the page structure.
- **Verifying Result**: Call `NOTION_FETCH_PAGE_AS_MARKDOWN` to show the final result to the user.

## Step 2: Find the Right Parent

User may specify a parent or you may need to discover one:

```
# Search by name
NOTION_SEARCH_NOTION_PAGE(query="<parent name>", page_size=5)

# If user wants it in a database
NOTION_SEARCH_NOTION_PAGE(query="<db name>", filter_value="database", page_size=5)

# If unsure, list everything accessible
NOTION_FETCH_DATA(fetch_type="all", page_size=20)
```

**Always use UUID format for parent_id** — never pass a plain title string.

## Step 3: Create the Page

```
NOTION_CREATE_NOTION_PAGE(
  title="Meeting Notes — Feb 23",
  parent_id="59833787-2cf9-4fdf-8782-e53db20768a5",  # UUID from search
  icon="note",
  cover="https://example.com/header.jpg"  # optional
)
```

## Step 4: Add Structured Content

After creating the empty page, add content blocks:

**For text-heavy content:**
```
NOTION_APPEND_TEXT_BLOCKS(
  block_id=page_id,
  blocks=[
    {"type": "heading_2", "content": "Attendees"},
    {"type": "paragraph", "content": "Alice, Bob, Charlie"},
    {"type": "heading_2", "content": "Agenda"},
    {"type": "numbered_list", "items": ["Review Q4 results", "Discuss Q1 goals", "Action items"]},
    {"type": "heading_2", "content": "Notes"},
    {"type": "paragraph", "content": "Discussion points go here..."},
    {"type": "heading_2", "content": "Action Items"},
    {"type": "to_do", "items": ["Alice: Send report by Friday", "Bob: Schedule follow-up"]}
  ]
)
```

**For rich content:**
```
NOTION_ADD_MULTIPLE_CONTENT_BLOCKS(
  page_id=page_id,
  children=[...]  # Mix of headings, text, todos, code, callouts
)
```

## Step 5: Confirm & Share

Present what was created:
```
Created: "Meeting Notes — Feb 23"
  Parent: Team Docs
  Sections: Attendees, Agenda, Notes, Action Items
  Link: [Open in Notion](url)
```

## Content Templates

**Meeting notes:** Attendees → Agenda → Discussion → Action Items → Next Steps
**Project brief:** Overview → Goals → Scope → Timeline → Resources → Risks
**Decision doc:** Context → Options → Analysis → Decision → Next Steps
**Wiki article:** Summary → Details → Examples → References

## Anti-Patterns
- Creating pages without searching for duplicates
- Using page title as parent_id (must use UUID)
- Creating empty pages without adding content blocks
- Not offering to share or link the created page
