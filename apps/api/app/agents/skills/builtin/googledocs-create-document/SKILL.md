---
name: googledocs-create-document
description: Create Google Docs intelligently - choose right format, structure professionally, use markdown-first approach, handle templates and sharing.
target: googledocs_agent
---

# Google Docs Create Document

## When to Use
- User asks to "create a document" or "write a doc"
- User wants "meeting notes" or "a report"
- User asks to "draft" something in Docs
- User wants a template or structured document

## Tools

### Discovery
- **GOOGLEDOCS_SEARCH_DOCUMENTS** — Find existing documents
- **GOOGLEDOCS_GET_DOCUMENT_BY_ID** — Read document content

### Creation
- **GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN** — Create with formatted content (PREFERRED)
- **GOOGLEDOCS_CREATE_DOCUMENT** — Create empty or plain text doc

### Modification
- **GOOGLEDOCS_UPDATE_DOCUMENT_MARKDOWN** — Replace entire document content
- **GOOGLEDOCS_UPDATE_DOCUMENT_SECTION_MARKDOWN** — Update specific sections

### Formatting
- **GOOGLEDOCS_CREATE_HEADER** / **GOOGLEDOCS_CREATE_FOOTER** — Professional headers/footers
- **GOOGLEDOCS_INSERT_TABLE_ACTION** — Structured data tables
- **GOOGLEDOCS_INSERT_INLINE_IMAGE** — Visual content
- **GOOGLEDOCS_INSERT_PAGE_BREAK** — Multi-section documents
- **GOOGLEDOCS_UPDATE_DOCUMENT_STYLE** — Margins and page layout
- **GOOGLEDOCS_CUSTOM_CREATE_TOC** — Table of contents

### Sharing
- **GOOGLEDOCS_CUSTOM_SHARE_DOC** — Share with collaborators
- **GOOGLEDOCS_COPY_DOCUMENT** — Create a copy

## Workflow

### Step 1: Check for Existing Documents

Before creating a new document:
```
GOOGLEDOCS_SEARCH_DOCUMENTS(query="project proposal")
```

- If similar document exists: "You already have a 'Project Proposal' doc. Want me to update it instead?"
- Avoid creating duplicates

### Step 2: Choose the Right Tool

**ALWAYS prefer markdown-based tools:**
- **CREATE_DOCUMENT_MARKDOWN** — For any document with formatting (headings, lists, tables)
- **CREATE_DOCUMENT** — Only for truly empty documents

### Step 3: Structure Professionally

Choose structure based on document type:

**Meeting Notes:**
```markdown
# Meeting: [Title]
**Date:** [Date]
**Attendees:** [Names]

## Agenda
1. [Topic 1]
2. [Topic 2]

## Discussion Notes
### [Topic 1]
- [Notes]

## Action Items
- [ ] [Task] — [Owner] — [Due date]

## Next Meeting
[Date/Time]
```

**Report/Proposal:**
```markdown
# [Title]

## Executive Summary
[1-2 paragraph overview]

## Background
[Context]

## Findings / Proposal
### [Section 1]
[Content]

## Recommendations
1. [Recommendation]

## Next Steps
- [Action item]
```

**Weekly Report:**
```markdown
# Weekly Report — [Date Range]

## Summary
[Key highlights]

## Accomplishments
- [Item 1]
- [Item 2]

## In Progress
- [Item 1]

## Blockers
- [Item 1]

## Next Week
- [Planned work]
```

### Step 4: Add Rich Formatting (when appropriate)

- **Headers/Footers:** For formal documents (reports, proposals)
- **Table of Contents:** For long documents (5+ sections)
- **Tables:** For structured data comparisons
- **Page Breaks:** To separate major sections

### Step 5: Share if Collaboration Implied

If the user mentions team members or collaboration:
```
GOOGLEDOCS_CUSTOM_SHARE_DOC(
    document_id="...",
    email="team@company.com",
    role="writer"
)
```

Roles: viewer, commenter, writer

### Step 6: Confirm

Report:
- Document title and URL
- Structure created (sections, tables, etc.)
- Who it's shared with (if applicable)

## Important Rules
1. **Markdown-first** — Always use CREATE_DOCUMENT_MARKDOWN for formatted content
2. **Search before creating** — Avoid duplicates
3. **Professional structure** — Use proper heading hierarchy and formatting
4. **Template awareness** — Use appropriate template for the document type
5. **Offer sharing** — If collaboration is implied, proactively ask to share
