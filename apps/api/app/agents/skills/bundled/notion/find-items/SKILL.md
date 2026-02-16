---
name: find-items
description: Find pages and databases in Notion - search for pages by title, list databases, query database contents with filters
target: notion
auto_invoke: true
---

# Notion Page and Database Lookup

Use this skill when helping users find information stored in Notion.

## Finding Pages

### Search by Title
Use `NOTION_SEARCH` with:
- `query`: Search terms
- `filter`: Set `value: "page"` to only return pages

### Get Page Content
Once you have a page ID:
- Use `NOTION_GET_PAGE` to get page metadata (title, created time, properties)
- Use `NOTION_GET_BLOCK_CHILDREN` to get the page's content blocks

## Working with Databases

### List Databases
Use `NOTION_SEARCH` with `filter: { value: "database", property: "object" }` to find all databases the user has access to.

### Query a Database
Use `NOTION_DATABASE_QUERY` with:
- `database_id`: The database's Notion ID
- `filter`: Property-based filters (e.g., status = "In Progress")
- `sorts`: Sort by property (e.g., date descending)
- `page_size`: Limit results (default 100)

### Common Query Patterns

**Find by status:**
```json
{
  "property": "Status",
  "status": { "equals": "Done" }
}
```

**Find by person (assignee):**
```json
{
  "property": "Assignee",
  "people": { "contains": "{user_id}" }
}
```

**Date filters:**
```json
{
  "property": "Due Date",
  "date": { "on_or_before": "2024-12-31" }
}
```

**Text search:**
```json
{
  "property": "Name",
  "title": { "contains": "search term" }
}
```

## Getting Database Schema
To understand a database's properties:
1. Get the database with `NOTION_GET_DATABASE`
2. Look at the `properties` field to see all columns and their types

## Creating Items in Notion

### Create a Page
Use `NOTION_CREATE_PAGE`:
- Must provide `parent` (database_id or page_id)
- Provide `properties` matching the database schema

### Update Properties
Use `NOTION_UPDATE_PAGE` to update specific properties on an existing page.

## Tips

- Always verify you have the correct page/database ID
- Check property types before attempting to filter or create
- Use meaningful search queries - Notion search is powerful
- For databases, check what views exist - users often have saved filters
