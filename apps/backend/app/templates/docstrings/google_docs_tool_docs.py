"""Docstrings for Google Docs LangChain tools."""

CREATE_GOOGLE_DOC = """
Creates online Google Docs that can be shared and edited collaboratively in the browser.

TOOL SELECTION: Use this when user says "doc". Use generate_document when user says "file".

Create a new Google Doc with the specified title and optional initial content.

Use this tool when the user wants to:
- Create a new document for writing, note-taking, or collaboration
- Start a new project document, report, or memo
- Create a document with specific initial content

Parameters:
- title (str): The title for the new document
- content (str, optional): Initial content to add to the document

Returns:
- document_id: Unique identifier for the created document
- title: Title of the document
- url: Direct link to edit the document in Google Docs
- content: The initial content added to the document

Example usage:
- "Create a new document called 'Meeting Notes'"
- "Create a document titled 'Project Plan' with initial content about the project overview"
- "Make a new Google Doc for my weekly report"
"""

LIST_GOOGLE_DOCS = """
List the user's Google Docs with optional filtering and search capabilities.

Use this tool when the user wants to:
- See all their Google Docs
- Find documents created recently
- Search for documents by title
- Get an overview of their document collection

Parameters:
- limit (int, optional): Maximum number of documents to return (default: 10)
- query (str, optional): Search query to filter documents by title

Returns:
- List of documents with metadata including:
  - document_id: Unique identifier
  - title: Document title
  - created_time: When the document was created
  - modified_time: When the document was last modified
  - url: Direct link to view/edit the document

Example usage:
- "Show me my recent Google Docs"
- "List all documents with 'meeting' in the title"
- "What Google Docs do I have?"
"""

GET_GOOGLE_DOC = """
Retrieve the content and metadata of a specific Google Doc.

Use this tool when the user wants to:
- Read the content of a specific document
- Get the full text of a document for analysis or reference
- Check the current content before making updates

Parameters:
- document_id (str): The unique identifier of the document to retrieve

Returns:
- document_id: Unique identifier of the document
- title: Title of the document
- content: Full text content of the document
- url: Direct link to edit the document
- revision_id: Current revision identifier

Example usage:
- "Show me the content of document [document_id]"
- "What's in my project plan document?"
- "Read the content of the meeting notes document"
"""

UPDATE_GOOGLE_DOC = """
Update the content of an existing Google Doc by adding new content or replacing existing content.

Use this tool when the user wants to:
- Add new content to an existing document
- Update or replace sections of a document
- Append notes or information to a document

Parameters:
- document_id (str): The unique identifier of the document to update
- content (str): The new content to add or replace
- insert_at_end (bool, optional): Whether to append content at the end (True) or replace all content (False)

Returns:
- document_id: Unique identifier of the updated document
- url: Direct link to edit the document
- updates_applied: Number of update operations performed

Example usage:
- "Add this text to the end of my meeting notes document"
- "Replace all content in document [document_id] with this new content"
- "Update my project plan with the latest information"
"""

FORMAT_GOOGLE_DOC = """
Apply formatting to a specific range of text in a Google Doc.

Use this tool when the user wants to:
- Make text bold, italic, or underlined
- Change font size or color
- Apply professional formatting to documents

Parameters:
- document_id (str): The unique identifier of the document
- start_index (int): Starting position of text to format (character index)
- end_index (int): Ending position of text to format (character index)
- bold (bool, optional): Apply bold formatting
- italic (bool, optional): Apply italic formatting
- underline (bool, optional): Apply underline formatting
- font_size (int, optional): Font size in points
- foreground_color (dict, optional): Text color as RGB values (0-1 range)

Returns:
- document_id: Unique identifier of the document
- url: Direct link to edit the document
- formatting_applied: Number of formatting operations applied

Example usage:
- "Make the title bold in my document"
- "Format the first paragraph as italic"
- "Change the font size of the heading to 18 points"

Note: To find the correct start_index and end_index, you may need to first retrieve the document content using get_google_doc.
"""

SHARE_GOOGLE_DOC = """
Share a Google Doc with another user by granting them specific permissions.

Use this tool when the user wants to:
- Collaborate on a document with colleagues
- Share a document for review or feedback
- Grant access to a document for specific users

Parameters:
- document_id (str): The unique identifier of the document to share
- email (str): Email address of the person to share with
- role (str, optional): Permission level - "reader", "writer", or "owner" (default: "writer")
- send_notification (bool, optional): Whether to send an email notification (default: True)

Returns:
- document_id: Unique identifier of the shared document
- shared_with: Email address of the person granted access
- role: Permission level granted
- permission_id: Unique identifier for the permission
- url: Direct link to the document

Example usage:
- "Share my project document with john@example.com as a writer"
- "Give read access to this document to my team lead"
- "Share the meeting notes with the team"
"""

SEARCH_GOOGLE_DOCS = """
Search through the user's Google Docs by title and content.

Use this tool when the user wants to:
- Find documents containing specific keywords
- Locate documents by partial title or content
- Search through their document collection

Parameters:
- query (str): Search terms to look for in document titles and content
- limit (int, optional): Maximum number of results to return (default: 10)

Returns:
- List of matching documents with metadata including:
  - document_id: Unique identifier
  - title: Document title
  - created_time: When the document was created
  - modified_time: When the document was last modified
  - url: Direct link to view/edit the document

Example usage:
- "Search for documents containing 'budget'"
- "Find all documents with 'quarterly report' in them"
- "Search for documents about the marketing project"
"""
