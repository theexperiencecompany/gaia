"""Templates for Google Docs tool streaming responses."""

GOOGLE_DOCS_CREATE_TEMPLATE = """
📄 **Google Doc Created Successfully**

**Title:** {title}
**Document ID:** {document_id}
**Direct Link:** [Open in Google Docs]({url})

{content}
"""

GOOGLE_DOCS_LIST_TEMPLATE = """
📋 **Google Docs List**

Found **{count}** document{plural}{query_text}:

{docs_list}
"""

GOOGLE_DOCS_GET_TEMPLATE = """
📖 **Document Retrieved**

**Title:** {title}
**Document ID:** {document_id}
**Direct Link:** [Open in Google Docs]({url})

**Content Preview:**
{content_preview}
"""

GOOGLE_DOCS_UPDATE_TEMPLATE = """
✏️ **Document Updated**

**Document ID:** {document_id}
**Action:** Content {action} the document
**Direct Link:** [View Changes]({url})

**Content Preview:**
{content_preview}
"""

GOOGLE_DOCS_FORMAT_TEMPLATE = """
🎨 **Document Formatted**

**Document ID:** {document_id}
**Formatting Applied:** {formatting}
**Range:** {range}
**Direct Link:** [View Changes]({url})
"""

GOOGLE_DOCS_SHARE_TEMPLATE = """
🤝 **Document Shared**

**Shared with:** {email}
**Role:** {role}
**Document ID:** {document_id}
**Notification:** Email sent {notification} notification
**Direct Link:** [Open Document]({url})
"""

GOOGLE_DOCS_SEARCH_TEMPLATE = """
🔍 **Search Results**

**Query:** "{query}"
**Found:** {count} document{plural}

{docs_list}
"""
