---
name: notion-search-content
description: Smart Notion search — query pages and databases, apply filters, traverse content, synthesize findings
target: notion_agent
---

# Notion: Search & Find Content

## When to Activate
User is looking for information in Notion — pages, databases, specific content, or trying to find something they remember vaguely.

## Step 1: Choose Search Strategy

**Known title/keyword** → Direct search
**Browse workspace** → List all items
**Database query** → Filtered query
**Content inside pages** → Search + read blocks

## Step 2: Search Pages & Databases

**Title search:**
```
NOTION_FETCH_DATA(fetch_type="all", query="product roadmap", page_size=50)
```

**Filter by type:**
```
# Only pages
NOTION_FETCH_DATA(fetch_type="pages", query="meeting notes", page_size=50)

# Only databases
NOTION_FETCH_DATA(fetch_type="databases", query="tasks", page_size=50)
```

**Browse all accessible items:**
```
NOTION_FETCH_DATA(fetch_type="all", page_size=100)
```

> **Known limitation:** Notion's search indexing is not immediate. If a specific search returns empty results despite knowing items exist, try an empty query as fallback and filter client-side.

## Step 3: Query Databases

When data is in a database (table, board, gallery):

**All rows (no filter):**
```
NOTION_QUERY_DATABASE(database_id="<uuid>", page_size=50)
```

**Filtered query:**
```
NOTION_QUERY_DATABASE_WITH_FILTER(
  database_id="<uuid>",
  filter={...},       # Property-based filters
  sorts=[{"property_name": "Due Date", "ascending": true}]
)
```

**Get database structure first:**
```
NOTION_FETCH_DATABASE(database_id="<uuid>") → properties, column types
```

## Step 4: Read Page Content

- **Traversal**: Iterate through promising results.
- **Reading Content**: Use `NOTION_FETCH_PAGE_AS_MARKDOWN` for pages. For databases, fetch schema with `NOTION_FETCH_DATABASE` and query with `NOTION_QUERY_DATABASE` or `NOTION_QUERY_DATABASE_WITH_FILTER`.
- **Synthesis**: Consolidate findings into a structured report with links and key data points.

## Step 5: Synthesize Results

Don't just dump results — organize them:

```
Found 5 results for "product roadmap":

1. "Product Roadmap Q1 2025" (page)
   Last edited: 2 days ago | Parent: Product Team
   
2. "Roadmap Tracker" (database)
   47 entries | Properties: Status, Priority, Owner
   
3. "Roadmap Review Notes" (page)
   Last edited: 1 week ago | Parent: Meetings
```

## Progressive Search Strategy

1. **Start specific:** `NOTION_FETCH_DATA(fetch_type="all", query="Q1 product roadmap 2025")`
2. **Broaden if empty:** `NOTION_FETCH_DATA(fetch_type="all", query="product roadmap")`
3. **Browse if still empty:** `NOTION_FETCH_DATA(fetch_type="all")` → filter client-side
4. **Check databases:** The info might be a row in a database, not a standalone page

## Anti-Patterns
- Returning raw API response (always synthesize)
- Searching with very long queries (Notion search is basic title matching)

## Using spawn_subagent for Multiple Pages

When you need to read content from multiple Notion pages, the **parent agent** drives the loop — it spawns one subagent per page (or per batch of pages) to keep the main context clean. Subagents cannot spawn further subagents.

```
# Parent finds page IDs via search
results = NOTION_FETCH_DATA(fetch_type="pages", query="product roadmap", page_size=50)

# Parent spawns one subagent per page (in parallel where possible)
digest_1 = spawn_subagent(
  task="""
    Fetch and fully process page <page_id_1>:
    NOTION_FETCH_PAGE_AS_MARKDOWN(page_id="<page_id_1>")
    Extract: main goals, timeline, key decisions, action items, open questions.
    Return a structured digest.
  """
)
digest_2 = spawn_subagent(
  task="""
    Fetch and fully process page <page_id_2>:
    NOTION_FETCH_PAGE_AS_MARKDOWN(page_id="<page_id_2>")
    Extract: blockers, decisions, recent updates.
    Return a structured digest.
  """
)

# Parent waits for all digests, then synthesizes
```

This allows parallel reading of multiple pages while keeping the main context clean.
