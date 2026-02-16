---
name: find-items
description: Find pages and databases in Notion - search, list, query database contents with filters
target: notion
auto_invoke: true
---

# Notion Discovery Tools

Use this skill to find pages and databases before creating or modifying content.

**Core principle: ALWAYS discover before you act. Never assume or hardcode IDs.**

## When to Use
- User wants to find a specific page or database
- Before creating or modifying any Notion content
- User asks to query database with filters
- Need to verify page/database exists before operations

## Tools

### NOTION_FETCH_DATA
Primary discovery tool for listing pages and databases.
- fetch_type: "pages" | "databases"
- page_size: max results (default: 100)
- query: optional title filter

### NOTION_SEARCH_NOTION_PAGE
Fuzzy search across pages/databases by title or content.

### NOTION_FETCH_DATABASE
Get database schema (properties, types). **Always call before inserting rows.**

### NOTION_QUERY_DATABASE_WITH_FILTER
Query database with property-based filters.

## Workflow

### Finding Pages/Databases
1. NOTION_FETCH_DATA - List pages or databases (default: 100 results)
2. NOTION_SEARCH_NOTION_PAGE - Fuzzy search if FETCH_DATA doesn't find target

### Before Creating Content
1. Find parent page/database ID
2. Use NOTION_FETCH_DATABASE to get schema (required before inserting rows)
3. Create or insert

### Querying Databases
1. Find database ID
2. Use NOTION_QUERY_DATABASE_WITH_FILTER with property filters

## Tips
- Start with FETCH_DATA for overview, then SEARCH for specifics
- Always verify IDs before creating/updating
- Get schema first using NOTION_FETCH_DATABASE before inserting rows
- Handle multiple search results by asking user to clarify
