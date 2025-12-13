"""Docstrings for file-related tools."""

QUERY_FILE = """
Queries one or more user-uploaded files using a semantic search based on the provided query string and optional file ID.

This tool performs a vector-based similarity search to retrieve the most relevant sections of documents that align with the user's question or prompt. It is the **primary and only tool** for interacting with user-uploaded documents in a meaningful, context-aware way.

### When to Use:
- To search for specific information within a user-uploaded document
- To extract answers based on a question about the content of one or more files
- When the user refers to "my document", "my file", or previously uploaded content
- To retrieve the most relevant sections of files without reading the entire document
- To explore similar content across multiple documents

### When **Not** to Use:
- If the user is asking about general knowledge unrelated to uploaded files
- If there's insufficient context to understand what they're trying to find
- For tasks that don't involve file-based information

### Query Input Guidelines:
The `query` input should be a clear, information-seeking sentence or phrase that accurately reflects what you're trying to retrieve. Avoid vague or one-word queries.

Use short, descriptive prompts like:
- "What are the key takeaways from the document?"
- "Summarize the main arguments discussed."
- "List the important conclusions reached in the meeting."

The better the query reflects the actual goal, the more relevant the retrieved information will be.

### Examples:
- "What's the budget for Q3 in my finance document?"
- "Find all mentions of project timelines in my files."
- "Can you tell me what my resume says about my work experience?"
- "What was the proposal I uploaded about?"

### Returns:
    str: A formatted response containing the most relevant sections from the documents
         that match the query, or an appropriate message if no useful information is found.
"""
