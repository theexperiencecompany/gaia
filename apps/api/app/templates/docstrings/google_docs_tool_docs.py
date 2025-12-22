"""Docstrings for Google Docs custom tools."""

CUSTOM_SHARE_DOC = """
Share a Google Doc with one or more recipients in a single operation.

Use this tool when the user wants to:
- Share a document with multiple people at once
- Collaborate on a document with colleagues
- Grant different access levels to different users
- Share with a team or group of people

Parameters:
- document_id (str): The unique identifier of the document to share
- recipients (list): List of recipients, each containing:
  - email (str): Email address of the person to share with
  - role (str, optional): Permission level - "reader", "writer", or "owner" (default: "writer")
  - send_notification (bool, optional): Whether to send an email notification (default: True)

Returns:
- success: Whether all shares were successful
- document_id: Unique identifier of the shared document
- url: Direct link to the document
- shared: List of successfully shared recipients with permission IDs
- errors: List of any failed shares with error details
- total_shared: Count of successful shares
- total_failed: Count of failed shares

Example usage:
- "Share my project document with john@example.com and jane@example.com as writers"
- "Give read access to this document to the marketing team"
- "Share the meeting notes with alice@company.com as reader and bob@company.com as writer"

Note: This tool supports bulk operations - share with multiple people in a single call for efficiency.
"""

CUSTOM_CREATE_TOC = """
Create a Table of Contents in a Google Doc by analyzing document headings.

This tool scans the document for headings (H1, H2, H3, etc.) and generates
a formatted text-based table of contents which is then inserted at the specified position.

Use this tool when the user wants to:
- Add a table of contents to their document
- Create a document outline/index
- Generate a TOC from existing section headings

Parameters:
- document_id (str): The unique identifier of the document
- insertion_index (int, optional): Position to insert TOC (default: 1 = beginning)
- include_heading_levels (list, optional): Which heading levels to include [1,2,3] = H1, H2, H3
- title (str, optional): Title for the TOC section (default: "Table of Contents")

Returns:
- success: Whether the TOC was created successfully
- document_id: Document identifier
- url: Direct link to the document
- headings_found: Number of headings discovered
- toc_content: The generated TOC text

Example usage:
- "Add a table of contents to my project document"
- "Create a TOC at the beginning of my report"
- "Generate an outline for my document showing only H1 and H2"

Note: This creates a text-based TOC. Unlike the native Google Docs TOC, it won't
auto-update when headings change. Re-run this tool to regenerate the TOC.
"""
