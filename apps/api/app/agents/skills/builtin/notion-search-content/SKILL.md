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
NOTION_SEARCH_NOTION_PAGE(query="product roadmap", page_size=10)
```

**Filter by type:**
```
# Only pages
NOTION_SEARCH_NOTION_PAGE(query="meeting notes", filter_value="page", page_size=10)

# Only databases
NOTION_SEARCH_NOTION_PAGE(query="tasks", filter_value="database", page_size=10)
```

**Browse all accessible items:**
```
NOTION_FETCH_DATA(fetch_type="all", page_size=100)
```

> **Known limitation:** Notion's search indexing is not immediate. If a specific search returns empty results despite knowing items exist, try an empty query as fallback and filter client-side.

## Step 3: Query Databases

When data is in a database (table, board, gallery):

**Simple query (all rows):**
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
- **Reading Content**: Use `NOTION_FETCH_PAGE_AS_MARKDOWN` for pages or `NOTION_QUERY_DATABASE` for databases to understand their schema and entries.
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

1. **Start specific:** `NOTION_SEARCH_NOTION_PAGE(query="Q1 product roadmap 2025")`
2. **Broaden if empty:** `NOTION_SEARCH_NOTION_PAGE(query="product roadmap")`
3. **Browse if still empty:** `NOTION_FETCH_DATA(fetch_type="all")` → filter client-side
- **Notion**: `NOTION_SEARCH_NOTION_PAGE`, `NOTION_QUERY_DATABASE`, `NOTION_RETRIEVE_PAGE`, `NOTION_GET_PAGE_PROPERTY_ACTION`
- **Analysis**: `SEARCH_ANYTHING` (if broader context is needed)
4. **Check databases:** The info might be a row in a database, not a standalone page

## Anti-Patterns
- Returning raw API response (always synthesize)
- Searching with very long queries (Notion search is basic title matching)

## Using spawn_subagent for Multiple Pages

When you need to read content from multiple Notion pages in parallel:

```
spawn_subagent(task="Read page Q1 Product Roadmap and extract key points", context="Focus on main goals and timeline")
spawn_subagent(task="Read page Sprint 23 Notes and extract key points", context="Focus on blockers and decisions")
spawn_subagent(task="Read page Team Updates and extract key points", context="Focus on recent updates and action items")
```

This allows parallel reading of multiple pages and keeps the main context clean.
